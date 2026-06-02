"""Google OAuth 2.0 flow.

Backend-led: GET /auth/google/login redirects to Google with a signed state
token; Google redirects back to GET /auth/google/callback?code=...&state=...,
which we exchange for an access token and the user's profile, then either
link to an existing user (matched by google_sub or email) or create a new
verified user. The endpoint then issues an access + refresh JWT pair.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AppError, UnauthorizedError
from app.core.logging import get_logger
from app.models.user import NotificationPreference, User

logger = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPES = ["openid", "email", "profile"]


def _redirect_uri() -> str:
    if settings.GOOGLE_REDIRECT_URI:
        return settings.GOOGLE_REDIRECT_URI
    return (
        f"{settings.API_BASE_URL.rstrip('/')}{settings.API_V1_PREFIX}"
        f"/auth/google/callback"
    )


def ensure_configured() -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise AppError(
            "Google OAuth is not configured on this server",
            code="oauth_not_configured",
        )


def build_authorization_url(state: str) -> str:
    ensure_configured()
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def _exchange_code(code: str) -> dict[str, Any]:
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _redirect_uri(),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data=data)
    if resp.status_code >= 400:
        logger.error(
            "google_token_exchange_failed", status=resp.status_code, body=resp.text
        )
        raise UnauthorizedError(
            "Failed to exchange authorization code with Google",
            code="oauth_token_exchange_failed",
        )
    return resp.json()


async def _fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        logger.error(
            "google_userinfo_failed", status=resp.status_code, body=resp.text
        )
        raise UnauthorizedError(
            "Failed to fetch Google user info", code="oauth_userinfo_failed"
        )
    return resp.json()


async def _lookup_user(
    session: AsyncSession, sub: str, email: str
) -> User | None:
    user = (
        await session.execute(select(User).where(User.google_sub == sub))
    ).scalar_one_or_none()
    if user is not None:
        return user
    return (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()


async def find_or_create_user(
    session: AsyncSession, userinfo: dict[str, Any]
) -> User:
    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    if not sub or not email:
        raise UnauthorizedError(
            "Google did not return a verified email", code="oauth_missing_email"
        )
    if userinfo.get("email_verified") is False:
        raise UnauthorizedError(
            "Google email is not verified", code="oauth_email_not_verified"
        )

    user = await _lookup_user(session, sub, email)

    # 2) link by email — same person who registered with email/password earlier.
    # Wrapped in a savepoint so a concurrent Google login for the same row that
    # already won the link race doesn't 500 us with IntegrityError on google_sub.
    if user is not None and user.google_sub is None:
        try:
            async with session.begin_nested():
                user.google_sub = sub
        except IntegrityError:
            user = await _lookup_user(session, sub, email)

    # 3) net-new user — savepoint + re-query covers the case where two
    # concurrent first-time logins for the same Google account both miss the
    # SELECT above and race on the unique(google_sub) / unique(email) inserts.
    if user is None:
        try:
            async with session.begin_nested():
                user = User(
                    email=email,
                    password_hash=None,
                    full_name=userinfo.get("name") or email.split("@")[0],
                    avatar_url=userinfo.get("picture"),
                    google_sub=sub,
                    is_verified=True,
                    email_verified_at=datetime.now(tz=UTC),
                )
                session.add(user)
                await session.flush()
                session.add(NotificationPreference(user_id=user.id))
        except IntegrityError:
            user = await _lookup_user(session, sub, email)
            if user is None:
                raise UnauthorizedError(
                    "Failed to provision Google user",
                    code="oauth_user_provision_failed",
                )

    if not user.is_verified:
        # email matched an unverified pre-existing account; Google has verified it.
        user.is_verified = True
        user.email_verified_at = datetime.now(tz=UTC)
    if not user.is_active:
        raise UnauthorizedError("Account is disabled", code="account_disabled")

    user.last_login_at = datetime.now(tz=UTC)
    return user


async def complete_oauth_flow(
    session: AsyncSession, code: str
) -> User:
    ensure_configured()
    token_resp = await _exchange_code(code)
    access_token = token_resp.get("access_token")
    if not access_token:
        raise UnauthorizedError(
            "Google did not return an access token",
            code="oauth_token_exchange_failed",
        )
    userinfo = await _fetch_userinfo(access_token)
    return await find_or_create_user(session, userinfo)
