from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field

from app.models.enums import UserRole
from app.schemas.base import ORMModel


class UserPublic(ORMModel):
    id: uuid.UUID
    full_name: str
    avatar_url: str | None = None


class UserMe(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    phone_number: str | None = None
    avatar_url: str | None = None
    role: UserRole
    is_active: bool
    is_verified: bool
    is_phone_verified: bool
    email_verified_at: datetime | None = None
    phone_verified_at: datetime | None = None
    onboarding_completed_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    # Which sign-in methods are wired up, so Settings can render the right
    # form: "Set password" when has_password is false (Google-only), else
    # "Change password". has_google flags whether a Google identity is linked.
    has_password: bool
    has_google: bool


class UserUpdate(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)


class AvatarUploadResponse(ORMModel):
    avatar_url: str | None = None
    size_bytes: int


class PasswordChange(ORMModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordSet(ORMModel):
    """Set an initial password on a Google-only account (no current password)."""

    new_password: str = Field(min_length=8, max_length=128)


class NotificationPreferenceSchema(ORMModel):
    email_marketing: bool
    email_announcements: bool
    email_course_updates: bool
    push_enabled: bool


class NotificationPreferenceUpdate(ORMModel):
    email_marketing: bool | None = None
    email_announcements: bool | None = None
    email_course_updates: bool | None = None
    push_enabled: bool | None = None