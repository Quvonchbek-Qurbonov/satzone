from __future__ import annotations

import html
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from redis.asyncio import Redis
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
from app.models.auth import (
    PasswordResetToken,
    PendingRegistration,
    RefreshToken,
)
from app.models.user import NotificationPreference, User
from app.utils.email import send_email

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _render_verification_email(full_name: str, verify_url: str) -> tuple[str, str]:
    """Return (text, html) bodies for the verify-email message.

    The HTML uses inline styles only — Gmail/Outlook strip <style> blocks and
    most external CSS, so anything not inlined silently disappears. The button
    uses a VML <v:roundrect> fallback inside an MSO conditional so it renders
    with rounded corners and the brand color in classic Outlook, which ignores
    CSS border-radius and most background colors on <a> tags.
    """
    expire_hours = settings.EMAIL_VERIFY_EXPIRE_HOURS
    project = settings.PROJECT_NAME

    text_body = (
        f"Hi {full_name},\n\n"
        f"Welcome to {project}! Please verify your email by visiting:\n{verify_url}\n\n"
        f"This link expires in {expire_hours} hours. If you didn't create an account, "
        f"you can safely ignore this email."
    )

    name_esc = html.escape(full_name)
    url_esc = html.escape(verify_url, quote=True)
    project_esc = html.escape(project)
    initial_esc = html.escape(project[:1].upper() or "S")
    preheader = f"Confirm your email to activate your {project} account."
    preheader_esc = html.escape(preheader)

    html_body = f"""\
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="color-scheme" content="light dark" />
    <meta name="supported-color-schemes" content="light dark" />
    <title>Verify your {project_esc} account</title>
    <!--[if mso]>
    <style type="text/css">
      body, table, td, a {{ font-family: 'Segoe UI', Arial, sans-serif !important; }}
    </style>
    <![endif]-->
  </head>
  <body style="margin:0;padding:0;background-color:#eef2ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;-webkit-font-smoothing:antialiased;">
    <div style="display:none;font-size:1px;color:#eef2ff;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
      {preheader_esc}
    </div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#eef2ff;">
      <tr>
        <td align="center" style="padding:40px 16px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:520px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 10px 30px rgba(15,23,42,0.08);">
            <tr>
              <td style="background-color:#4f46e5;background-image:linear-gradient(135deg,#6366f1 0%,#4f46e5 50%,#7c3aed 100%);padding:36px 32px;text-align:center;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto 12px auto;">
                  <tr>
                    <td align="center" valign="middle" width="56" height="56" style="width:56px;height:56px;background-color:rgba(255,255,255,0.18);border-radius:50%;color:#ffffff;font-size:24px;font-weight:700;line-height:56px;text-align:center;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                      {initial_esc}
                    </td>
                  </tr>
                </table>
                <div style="color:#ffffff;font-size:13px;letter-spacing:2px;text-transform:uppercase;font-weight:600;opacity:0.85;">{project_esc}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:40px 40px 16px 40px;text-align:center;">
                <h1 style="margin:0 0 12px 0;font-size:24px;line-height:1.3;font-weight:700;color:#0f172a;letter-spacing:-0.01em;">Confirm your email</h1>
                <p style="margin:0 0 8px 0;font-size:15px;line-height:1.6;color:#475569;">Hi {name_esc},</p>
                <p style="margin:0 0 32px 0;font-size:15px;line-height:1.6;color:#475569;">Thanks for signing up. Tap the button below to verify your email address and finish setting up your account.</p>
                <!--[if mso]>
                <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{url_esc}" style="height:48px;v-text-anchor:middle;width:220px;" arcsize="17%" stroke="f" fillcolor="#4f46e5">
                  <w:anchorlock/>
                  <center style="color:#ffffff;font-family:'Segoe UI',Arial,sans-serif;font-size:15px;font-weight:600;">Verify my email</center>
                </v:roundrect>
                <![endif]-->
                <!--[if !mso]><!-- -->
                <a href="{url_esc}" style="display:inline-block;padding:14px 36px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;background-color:#4f46e5;background-image:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%);border-radius:10px;box-shadow:0 4px 12px rgba(79,70,229,0.35);letter-spacing:0.01em;">Verify my email</a>
                <!--<![endif]-->
              </td>
            </tr>
            <tr>
              <td style="padding:24px 40px 8px 40px;">
                <div style="border-top:1px solid #e2e8f0;"></div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 40px 32px 40px;">
                <p style="margin:0 0 8px 0;font-size:13px;line-height:1.5;color:#64748b;">Button not working? Paste this link into your browser:</p>
                <p style="margin:0 0 20px 0;font-size:13px;line-height:1.5;word-break:break-all;"><a href="{url_esc}" style="color:#4f46e5;text-decoration:none;">{url_esc}</a></p>
                <p style="margin:0;font-size:12px;line-height:1.6;color:#94a3b8;">This link expires in <strong style="color:#475569;">{expire_hours} hours</strong>. If you didn't create a {project_esc} account, you can safely ignore this email — no further action is needed.</p>
              </td>
            </tr>
          </table>
          <p style="margin:24px 0 0 0;font-size:12px;line-height:1.5;color:#94a3b8;text-align:center;">&copy; {project_esc}. All rights reserved.</p>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    return text_body, html_body


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
    text_body, html_body = _render_verification_email(full_name_clean, verify_url)
    try:
        await send_email(
            to=email_norm,
            subject=f"Verify your {settings.PROJECT_NAME} account",
            body_text=text_body,
            body_html=html_body,
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


async def login_by_phone(
    session: AsyncSession,
    phone_number: str,
    password: str,
    request: Request | None = None,
) -> dict:
    """Same shape as :func:`login`, but identifies the user by a verified phone.

    Only matches when ``is_phone_verified`` is true — an unverified phone
    sitting on the row is just a typed-in string, not proof of identity.
    Google-only users (no ``password_hash``) get the same ``oauth_only``
    redirect as on email login.
    """
    stmt = select(User).where(
        User.phone_number == phone_number, User.is_phone_verified.is_(True)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
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
        raise UnauthorizedError(
            "Invalid phone number or password", code="invalid_credentials"
        )
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


def _generate_phone_code() -> str:
    length = max(4, min(10, settings.PHONE_CODE_LENGTH))
    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def _otp_key(otp: str) -> str:
    return f"phone_verify:otp:{otp}"


def _phone_pending_key(phone: str) -> str:
    return f"phone_verify:phone:{phone}"


async def issue_phone_otp(
    session: AsyncSession, redis: Redis, phone_number: str
) -> tuple[str, int]:
    """Mint an OTP for ``phone_number`` and stash the OTP↔phone pair in Redis.

    Called by the Telegram bot via ``POST /internal/phone/issue-otp``. The
    OTP is returned in the HTTP response so the bot can show it to the user
    in chat — the backend itself does not deliver it anywhere.

    Side effects:
      * If another verified user already owns ``phone_number`` we 409 with
        ``phone_taken`` so the bot can prompt the user to use a different
        number (or log in to that account instead).
      * Any prior pending OTP for the same phone is wiped first, so a single
        phone never has two live codes — re-issuing always supersedes.

    Returns ``(otp, ttl_seconds)``.
    """
    taken = (
        await session.execute(
            select(User.id).where(User.phone_number == phone_number)
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise ConflictError(
            "An account with this phone number already exists",
            code="phone_taken",
        )

    ttl_seconds = settings.PHONE_VERIFY_EXPIRE_MINUTES * 60
    phone_key = _phone_pending_key(phone_number)

    # Invalidate any prior OTP for this same number so the bot's last-write
    # wins. The mapping is one-OTP-per-phone at any given time.
    old_otp = await redis.get(phone_key)
    if old_otp:
        await redis.delete(_otp_key(old_otp))

    # Random OTPs can — astronomically rarely — collide with a live one
    # bound to a different phone. Re-roll a few times instead of clobbering.
    for _ in range(5):
        otp = _generate_phone_code()
        otp_key = _otp_key(otp)
        if await redis.set(otp_key, phone_number, ex=ttl_seconds, nx=True):
            break
    else:
        raise RuntimeError("Could not allocate a unique phone OTP after 5 attempts")

    await redis.set(phone_key, otp, ex=ttl_seconds)
    return otp, ttl_seconds


async def verify_phone(
    session: AsyncSession, redis: Redis, user: User, otp: str
) -> User:
    """Consume an OTP minted by the bot flow and bind its phone to ``user``.

    The OTP is the only thing the frontend submits — the phone is read out
    of Redis. We re-check uniqueness right before commit so a race between
    two users typing the same OTP (or claiming the same number through a
    different code) becomes a clean 409 instead of an IntegrityError.
    """
    if user.is_phone_verified:
        raise ConflictError("Phone is already verified", code="phone_already_verified")

    otp_key = _otp_key(otp)
    phone = await redis.get(otp_key)
    if not phone:
        raise ValidationAppError(
            "Invalid or expired verification code", code="invalid_phone_code"
        )

    taken = (
        await session.execute(
            select(User.id).where(User.phone_number == phone, User.id != user.id)
        )
    ).scalar_one_or_none()
    if taken is not None:
        await redis.delete(otp_key, _phone_pending_key(phone))
        raise ConflictError(
            "An account with this phone number already exists",
            code="phone_taken",
        )

    now = _now()
    user.phone_number = phone
    user.is_phone_verified = True
    user.phone_verified_at = now
    await session.commit()
    await redis.delete(otp_key, _phone_pending_key(phone))
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
    text_body, html_body = _render_verification_email(pending.full_name, verify_url)
    try:
        await send_email(
            to=pending.email,
            subject=f"Verify your {settings.PROJECT_NAME} account",
            body_text=text_body,
            body_html=html_body,
        )
    except Exception:  # noqa: BLE001
        logger.exception("resend_verify_failed", email_hash=email_hash(email_norm))