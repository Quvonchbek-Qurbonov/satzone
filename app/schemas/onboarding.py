from __future__ import annotations

import uuid

from pydantic import Field

from app.models.enums import SkillLevel
from app.schemas.base import ORMModel
from app.schemas.category import CategoryRead


class OnboardingProfile(ORMModel):
    headline: str | None = None
    bio: str | None = None
    skill_level: SkillLevel | None = None
    weekly_goal_minutes: int | None = None
    learning_goal: str | None = None
    locale: str | None = None
    timezone: str | None = None


class OnboardingRead(ORMModel):
    profile: OnboardingProfile | None = None
    interests: list[CategoryRead] = []
    onboarding_completed: bool = False


class OnboardingUpdate(ORMModel):
    headline: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=2000)
    skill_level: SkillLevel | None = None
    weekly_goal_minutes: int | None = Field(default=None, ge=0, le=10000)
    learning_goal: str | None = Field(default=None, max_length=2000)
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    interest_category_ids: list[uuid.UUID] | None = None
    mark_completed: bool = False
