from __future__ import annotations

import uuid
from decimal import Decimal

from app.schemas.base import ORMModel


class InstructorSummary(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    title: str | None = None
    avatar_url: str | None = None
    rating_avg: Decimal = Decimal("0")
    students_count: int = 0
    courses_count: int = 0


class InstructorRead(InstructorSummary):
    bio: str | None = None
    expertise: list[str] | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    website_url: str | None = None
