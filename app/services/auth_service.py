from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationAppError
from app.core.logging import email_hash, get_logger
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.auth import PasswordResetToken, PendingRegistration, RefreshToken
from app.models.user import NotificationPreference, User
from app.utils.email import send_email

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _build_token_response(user_id: uuid.UUID, refresh_token: str) -> dict:
    access_token, expire = create_access_token(user_id)
    expires_in = max(0, int((expire - _now()).total_seconds()))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


async def _create_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    request: Request | None = None,
    *,
    replaced_by_id: uuid.UUID | None = None,
) -> tuple[RefreshToken, str]:
    raw = generate_opaque_token()
    rt = RefreshToken(
        user_id=user_id,
        token_hash=hash_opaque_token(raw),
        expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=(request.headers.get("user-agent")[:500] if request else None),
        ip_address=(request.client.host if request and request.client else None),
        replaced_by_id=replaced_by_id,
    )
    session.add(rt)
    await session.flush()
    return rt, raw


async def _find_active_refresh_token(session: AsyncSession, raw_token: str) -> RefreshToken | None:
    th = hash_opaque_token(raw_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == th)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def register(
    session: AsyncSession,
    email: str,
    full_name: str,
    password: str,
) -> None:
    """Create a pending registration and email a verification token.

    No row is written to ``users`` until the token is redeemed via
    :func:`verify_email`. If a pending row already exists for this email,
    it is overwritten — letting the real owner reclaim a squatted email by
    simply re-registering.
    """
    email_norm = email.strip().lower()
    full_name_clean = full_name.strip()

    if (
        await session.execute(select(User.id).where(User.email == email_norm))
    ).scalar_one_or_none() is not None:
        raise ConflictError("An account with this email already exists", code="email_taken")

    raw_verify = generate_opaque_token()
    expires_at = _now() + timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS)

    pending = (
        await session.execute(
            select(PendingRegistration).where(PendingRegistration.email == email_norm)
        )
    ).scalar_one_or_none()
    if pending is None:
        pending = PendingRegistration(
            email=email_norm,
            password_hash=hash_password(password),
            full_name=full_name_clean,
            token_hash=hash_opaque_token(raw_verify),
            expires_at=expires_at,
        )
        session.add(pending)
    else:
        pending.password_hash = hash_password(password)
        pending.full_name = full_name_clean
        pending.token_hash = hash_opaque_token(raw_verify)
        pending.expires_at = expires_at
    await session.commit()

    verify_url = (
        f"{settings.API_BASE_URL.rstrip('/')}{settings.API_V1_PREFIX}"
        f"/auth/verify-email?token={raw_verify}"
    )
    try:
        await send_email(
            to=email_norm,
            subject=f"Verify your {settings.PROJECT_NAME} account",
            body_text=(
                f"Hi {full_name_clean},\n\n"
                f"Please verify your email by visiting:\n{verify_url}\n\n"
                f"This link expires in {settings.EMAIL_VERIFY_EXPIRE_HOURS} hours."
            ),
        )
    except Exception:  # noqa: BLE001
        logger.exception("verification_email_send_failed", email_hash=email_hash(email_norm))


async def issue_tokens(
    session: AsyncSession,
    user: User,
    request: Request | None = None,
) -> dict:
    """Mint an access + refresh pair for an already-authenticated user.

    Used by the email/password ``login`` path and by OAuth callbacks. The
    caller is responsible for any prior identity checks (password match,
    OAuth code exchange, etc.) and for ``user.is_active``.
    """
    user.last_login_at = _now()
    _, raw_refresh = await _create_refresh_token(session, user.id, request)
    await session.commit()
    return _build_token_response(user.id, raw_refresh)


async def login(
    session: AsyncSession,
    email: str,
    password: str,
    request: Request | None = None,
) -> dict:
    email_norm = email.strip().lower()
    stmt = select(User).where(User.email == email_norm)
    user = (await session.execute(stmt)).scalar_one_or_none()
    # Constant-time-ish: always run verify_password against either real hash or a dummy.
    # OAuth-only users have no password_hash — use a dummy so timing reveals nothing,
    # then surface a distinct error so the frontend can route to the Google button.
    candidate_hash = (
        user.password_hash
        if user and user.password_hash
        else hash_password("dummy-disposable-string")
    )
    valid = verify_password(password, candidate_hash)
    if user and user.password_hash is None:
        raise UnauthorizedError(
            "This account uses Google sign-in", code="oauth_only"
        )
    if not user or not valid:
        raise UnauthorizedError("Invalid email or password", code="invalid_credentials")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled", code="account_disabled")
    if not user.is_verified:
        raise UnauthorizedError(
            "Please verify your email before logging in",
            code="email_not_verified",
        )

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = _now()
    _, raw_refresh = await _create_refresh_token(session, user.id, request)
    await session.commit()
    return _build_token_response(user.id, raw_refresh)


async def refresh(
    session: AsyncSession,
    raw_token: str,
    request: Request | None = None,
) -> dict:
    rt = await _find_active_refresh_token(session, raw_token)
    if rt is None:
        raise UnauthorizedError("Invalid refresh token", code="invalid_refresh_token")

    if rt.revoked_at is not None:
        # Reuse detected — revoke all tokens belonging to this user for safety.
        logger.warning("refresh_token_reuse_detected", user_id=str(rt.user_id))
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == rt.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        await session.commit()
        raise UnauthorizedError("Refresh token reuse detected; all sessions revoked", code="token_reuse")

    if rt.expires_at <= _now():
        raise UnauthorizedError("Refresh token expired", code="refresh_expired")

    # Rotate
    new_rt, raw_new = await _create_refresh_token(session, rt.user_id, request)
    rt.revoked_at = _now()
    rt.replaced_by_id = new_rt.id
    await session.commit()
    return _build_token_response(rt.user_id, raw_new)


async def logout(session: AsyncSession, raw_token: str) -> None:
    rt = await _find_active_refresh_token(session, raw_token)
    if rt is None or rt.revoked_at is not None:
        return  # idempotent
    rt.revoked_at = _now()
    await session.commit()


async def verify_email(session: AsyncSession, raw_token: str) -> User:
    """Redeem a verification token: promote a pending registration into a real user."""
    th = hash_opaque_token(raw_token)
    pending = (
        await session.execute(
            select(PendingRegistration).where(PendingRegistration.token_hash == th)
        )
    ).scalar_one_or_none()
    if pending is None or pending.expires_at <= _now():
        raise ValidationAppError(
            "Invalid or expired verification token", code="invalid_verify_token"
        )

    # Defensive: another flow may have created a real user with this email between
    # registration and verification. Surface that as a clean conflict.
    if (
        await session.execute(select(User.id).where(User.email == pending.email))
    ).scalar_one_or_none() is not None:
        raise ConflictError(
            "An account with this email already exists", code="email_taken"
        )

    now = _now()
    user = User(
        email=pending.email,
        password_hash=pending.password_hash,
        full_name=pending.full_name,
        is_verified=True,
        email_verified_at=now,
    )
    session.add(user)
    await session.flush()
    session.add(NotificationPreference(user_id=user.id))
    await session.delete(pending)
    await session.commit()
    return user


async def request_password_reset(session: AsyncSession, email: str) -> None:
    email_norm = email.strip().lower()
    stmt = select(User).where(User.email == email_norm)
    user = (await session.execute(stmt)).scalar_one_or_none()
    # Always return success to avoid email enumeration; only send mail if user exists.
    if user is None:
        logger.info("password_reset_unknown_email", email_hash=email_hash(email_norm))
        return

    raw = generate_opaque_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_opaque_token(raw),
            expires_at=_now() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
    )
    await session.commit()

    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw}"
    try:
        await send_email(
            to=user.email,
            subject=f"Reset your {settings.PROJECT_NAME} password",
            body_text=(
                f"Hi {user.full_name},\n\n"
                f"Reset your password by visiting:\n{reset_url}\n\n"
                f"This link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes."
            ),
        )
    except Exception:  # noqa: BLE001
        logger.exception("password_reset_email_send_failed", user_id=str(user.id))


async def reset_password(session: AsyncSession, raw_token: str, new_password: str) -> None:
    th = hash_opaque_token(raw_token)
    stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == th)
    tok = (await session.execute(stmt)).scalar_one_or_none()
    if tok is None or tok.consumed_at is not None or tok.expires_at <= _now():
        raise ValidationAppError("Invalid or expired reset token", code="invalid_reset_token")
    user = await session.get(User, tok.user_id)
    if user is None:
        raise NotFoundError("User not found")
    user.password_hash = hash_password(new_password)
    tok.consumed_at = _now()
    # Best practice: revoke all existing refresh tokens after password reset.
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await session.commit()


async def change_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise UnauthorizedError("Current password is incorrect", code="invalid_credentials")
    if current_password == new_password:
        raise ValidationAppError("New password must differ from the current one", code="password_unchanged")
    user.password_hash = hash_password(new_password)
    await session.commit()


async def resend_verification(session: AsyncSession, email: str) -> None:
    """Re-issue a verification token for a pending registration. Silent on miss."""
    email_norm = email.strip().lower()
    pending = (
        await session.execute(
            select(PendingRegistration).where(PendingRegistration.email == email_norm)
        )
    ).scalar_one_or_none()
    if pending is None:
        return  # silent — no enumeration

    raw = generate_opaque_token()
    pending.token_hash = hash_opaque_token(raw)
    pending.expires_at = _now() + timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS)
    await session.commit()

    verify_url = (
        f"{settings.API_BASE_URL.rstrip('/')}{settings.API_V1_PREFIX}"
        f"/auth/verify-email?token={raw}"
    )
    try:
        await send_email(
            to=pending.email,
            subject=f"Verify your {settings.PROJECT_NAME} account",
            body_text=f"Hi {pending.full_name},\n\nVerify your email: {verify_url}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("resend_verify_failed", email_hash=email_hash(email_norm))