from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.middleware.rate_limit import rate_limit_auth
from app.schemas.auth import (
    EmailVerifyRequest,
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    ResendVerifyRequest,
    TokenResponse,
)
from app.schemas.base import Message
from app.schemas.user import UserMe
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit_auth)])


@router.post("/register", response_model=UserMe, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: DbSession) -> UserMe:
    user = await auth_service.register(
        session=session,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
    )
    return UserMe.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: DbSession, request: Request) -> TokenResponse:
    tokens = await auth_service.login(
        session=session,
        email=payload.email,
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


@router.post("/resend-verification", response_model=Message)
async def resend_verification(payload: ResendVerifyRequest, session: DbSession) -> Message:
    await auth_service.resend_verification(session=session, email=payload.email)
    return Message(message="If the account exists and is unverified, a new verification email was sent")


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
async def me(user: CurrentUser) -> UserMe:
    return UserMe.model_validate(user)