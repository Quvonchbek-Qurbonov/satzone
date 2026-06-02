from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

# E.164-ish: optional leading "+", 8-15 digits, no leading zero on the country
# code. Tolerates spaces / dashes / parens by stripping them before validating.
_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def _normalize_phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not _PHONE_RE.match(cleaned):
        raise ValueError(
            "phone_number must be E.164 format (e.g. +14155552671) — 8 to 15 digits, optional leading '+'"
        )
    return cleaned


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class LoginByPhoneRequest(BaseModel):
    phone_number: str = Field(min_length=8, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("phone_number")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        return _normalize_phone(v)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expiry


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class EmailVerifyRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class ResendVerifyRequest(BaseModel):
    email: EmailStr


class PhoneVerifyRequest(BaseModel):
    # OTP minted by /internal/phone/issue-otp when the Telegram bot forwards
    # the user's shared contact. Looking it up in Redis yields the phone
    # number; no phone field is accepted here (the bot is the only sender).
    otp: str = Field(min_length=4, max_length=10)
