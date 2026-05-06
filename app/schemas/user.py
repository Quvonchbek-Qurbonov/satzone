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
    avatar_url: str | None = None
    role: UserRole
    is_active: bool
    is_verified: bool
    email_verified_at: datetime | None = None
    onboarding_completed_at: datetime | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class UserUpdate(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    avatar_url: str | None = Field(default=None, max_length=500)


class PasswordChange(ORMModel):
    current_password: str = Field(min_length=8, max_length=128)
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