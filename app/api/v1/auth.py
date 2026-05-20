from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.deps import CurrentUserAny
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import create_oauth_state, verify_oauth_state
from app.db.deps import DbSession
from app.middleware.rate_limit import rate_limit_auth
from app.redis_client import RedisDep
from app.services import google_oauth_service
from app.schemas.auth import (
    EmailVerifyRequest,
    LoginByPhoneRequest,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    PhoneSubmitRequest,
    PhoneVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerifyRequest,
    TokenResponse,
)
from app.schemas.base import Message
from app.schemas.user import UserMe
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit_auth)])


@router.post("/register", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
async def register(payload: RegisterRequest, session: DbSession) -> Message:
    await auth_service.register(
        session=session,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
    )
    return Message(
        message="Check your email to verify the account before logging in"
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: DbSession, request: Request) -> TokenResponse:
    tokens = await auth_service.login(
        session=session,
        email=payload.email,
        password=payload.password,
        request=request,
    )
    return TokenResponse(**tokens)


@router.post("/login/phone", response_model=TokenResponse)
async def login_by_phone(
    payload: LoginByPhoneRequest, session: DbSession, request: Request
) -> TokenResponse:
    tokens = await auth_service.login_by_phone(
        session=session,
        phone_number=payload.phone_number,
        password=payload.password,
        request=request,
    )
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, session: DbSession, request: Request) -> TokenResponse:
    tokens = await auth_service.refresh(
        session=session, raw_token=payload.refresh_token, request=request
    )
    return TokenResponse(**tokens)


@router.post("/logout", response_model=Message)
async def logout(payload: LogoutRequest, session: DbSession) -> Message:
    await auth_service.logout(session=session, raw_token=payload.refresh_token)
    return Message(message="Logged out")


@router.post("/verify-email", response_model=Message)
async def verify_email(payload: EmailVerifyRequest, session: DbSession) -> Message:
    await auth_service.verify_email(session=session, raw_token=payload.token)
    return Message(message="Email verified")


@router.get("/verify-email", response_class=HTMLResponse, include_in_schema=False)
async def verify_email_via_link(
    session: DbSession,
    token: str = Query(..., min_length=10, max_length=200),
) -> HTMLResponse:
    """Click-target for the verification email link — renders a tiny success/error page."""
    try:
        await auth_service.verify_email(session=session, raw_token=token)
    except AppError as exc:
        return HTMLResponse(
            f"<!doctype html><meta charset='utf-8'><title>Verification failed</title>"
            f"<body style='font-family:system-ui;max-width:480px;margin:4rem auto;text-align:center'>"
            f"<h1>Verification failed</h1><p>{exc.message}</p>"
            f"<p>Request a new link from the app or via <code>POST /auth/resend-verification</code>.</p>"
            f"</body>",
            status_code=exc.status_code,
        )
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Email verified</title>"
        "<body style='font-family:system-ui;max-width:480px;margin:4rem auto;text-align:center'>"
        "<h1>Email verified</h1><p>You can now log in.</p>"
        "</body>"
    )


@router.post("/resend-verification", response_model=Message)
async def resend_verification(payload: ResendVerifyRequest, session: DbSession) -> Message:
    await auth_service.resend_verification(session=session, email=payload.email)
    return Message(message="If the account exists and is unverified, a new verification email was sent")


@router.post("/phone", response_model=Message)
async def submit_phone(
    payload: PhoneSubmitRequest,
    user: CurrentUserAny,
    session: DbSession,
    redis: RedisDep,
) -> Message:
    """Stash a phone number + freshly-minted code in Redis and email it.

    Re-callable until the phone is verified, so the user can correct a typo.
    Once ``is_phone_verified`` is true the endpoint refuses with
    ``phone_already_verified``. The phone is **not** persisted to ``users``
    until ``/auth/verify-phone`` succeeds.
    """
    await auth_service.set_phone_number(
        session=session,
        redis=redis,
        user=user,
        phone_number=payload.phone_number,
    )
    return Message(message="Verification code sent")


@router.post("/verify-phone", response_model=Message)
async def verify_phone(
    payload: PhoneVerifyRequest,
    user: CurrentUserAny,
    session: DbSession,
    redis: RedisDep,
) -> Message:
    await auth_service.verify_phone(
        session=session, redis=redis, user=user, code=payload.code
    )
    return Message(message="Phone number verified")


@router.post("/resend-phone-code", response_model=Message)
async def resend_phone_code(
    user: CurrentUserAny, session: DbSession, redis: RedisDep
) -> Message:
    await auth_service.resend_phone_code(session=session, redis=redis, user=user)
    return Message(message="Verification code sent")


@router.post("/password/forgot", response_model=Message)
async def forgot_password(payload: PasswordResetRequest, session: DbSession) -> Message:
    await auth_service.request_password_reset(session=session, email=payload.email)
    return Message(message="If the email is registered, a reset link has been sent")


@router.post("/password/reset", response_model=Message)
async def reset_password(payload: PasswordResetConfirm, session: DbSession) -> Message:
    await auth_service.reset_password(
        session=session, raw_token=payload.token, new_password=payload.new_password
    )
    return Message(message="Password updated")


@router.get("/me", response_model=UserMe)
async def me(user: CurrentUserAny) -> UserMe:
    """Current user — accessible even before phone is verified so the
    frontend can read ``is_phone_verified`` and route into the verify-phone
    screen."""
    return UserMe.model_validate(user)


# ---------- Google OAuth ----------


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    """Start the Google OAuth dance: redirects the browser to Google's consent screen."""
    google_oauth_service.ensure_configured()
    state = create_oauth_state()
    return RedirectResponse(
        url=google_oauth_service.build_authorization_url(state),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    session: DbSession,
    request: Request,
    code: str = Query(..., min_length=1, max_length=2048),
    state: str = Query(..., min_length=1, max_length=2048),
) -> RedirectResponse:
    """Google redirects the browser here after consent. We exchange the code,
    find-or-create the user, and 303-redirect to ``FRONTEND_URL/auth/google/callback``
    with the tokens (or an error) in the URL fragment. The fragment never
    reaches the server, so the SPA can read it from ``window.location.hash``
    without leaking tokens to access logs or referers."""
    frontend_cb = f"{settings.FRONTEND_URL.rstrip('/')}/auth/google/callback"
    try:
        verify_oauth_state(state)
        user = await google_oauth_service.complete_oauth_flow(session, code)
    except AppError as exc:
        return RedirectResponse(
            url=f"{frontend_cb}#error={exc.code}&error_description={quote(exc.message)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    from app.services import auth_service

    tokens = await auth_service.issue_tokens(session, user, request)
    handoff = (
        f"{frontend_cb}"
        f"#access_token={tokens['access_token']}"
        f"&refresh_token={tokens['refresh_token']}"
        f"&expires_in={tokens['expires_in']}"
    )
    return RedirectResponse(url=handoff, status_code=status.HTTP_303_SEE_OTHER)