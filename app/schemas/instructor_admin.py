"""Schemas for instructor-facing course management endpoints.

Distinct from :mod:`app.schemas.course` (public catalog) and
:mod:`app.schemas.instructor` (public profile read) — these include draft
content, status fields, and write payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.models.enums import CourseLevel, LessonType, PublishStatus
from app.schemas.base import ORMModel


# ---- Instructor profile ----


class InstructorProfileUpsert(ORMModel):
    name: str = Field(min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    bio: str | None = None
    expertise: list[str] | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    linkedin_url: str | None = Field(default=None, max_length=500)
    twitter_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)


class InstructorProfileUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    bio: str | None = None
    expertise: list[str] | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    linkedin_url: str | None = Field(default=None, max_length=500)
    twitter_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)


class InstructorProfileRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    slug: str
    name: str
    title: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    expertise: list[str] | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    website_url: str | None = None
    courses_count: int = 0
    students_count: int = 0


# ---- Course management ----


class CourseCreate(ORMModel):
    title: str = Field(min_length=3, max_length=200)
    subtitle: str | None = Field(default=None, max_length=280)
    description: str | None = None
    category_id: uuid.UUID
    level: CourseLevel = CourseLevel.ALL_LEVELS
    language: str = Field(default="en", min_length=2, max_length=10)
    price_cents: int = Field(default=0, ge=0)
    discount_price_cents: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None

    @model_validator(mode="after")
    def _check_discount(self) -> "CourseCreate":
        if (
            self.discount_price_cents is not None
            and self.discount_price_cents > self.price_cents
        ):
            raise ValueError("discount_price_cents cannot exceed price_cents")
        return self


class CourseUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    subtitle: str | None = Field(default=None, max_length=280)
    description: str | None = None
    category_id: uuid.UUID | None = None
    level: CourseLevel | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)
    price_cents: int | None = Field(default=None, ge=0)
    discount_price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None
    thumbnail_url: str | None = Field(default=None, max_length=500)
    preview_video_url: str | None = Field(default=None, max_length=500)


class InstructorCourseRead(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    preview_video_url: str | None = None
    category_id: uuid.UUID
    instructor_id: uuid.UUID
    level: CourseLevel
    language: str
    duration_minutes: int = 0
    lectures_count: int = 0
    price_cents: int = 0
    discount_price_cents: int | None = None
    currency: str = "USD"
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None
    status: PublishStatus
    published_at: datetime | None = None
    enrollments_count: int = 0
    rating_avg: float = 0.0
    ratings_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---- Sections ----


class SectionCreate(ORMModel):
    title: str = Field(min_length=1, max_length=200)
    order: int | None = Field(default=None, ge=0)


class SectionUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    order: int | None = Field(default=None, ge=0)


class SectionAdminRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    order: int


class ReorderItem(ORMModel):
    id: uuid.UUID
    order: int = Field(ge=0)


class ReorderRequest(ORMModel):
    items: list[ReorderItem] = Field(min_length=1)


# ---- Lessons ----


class LessonCreate(ORMModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    type: LessonType = LessonType.VIDEO
    article_content: str | None = None
    video_url: str | None = Field(default=None, max_length=500)
    resource_url: str | None = Field(default=None, max_length=500)
    duration_seconds: int = Field(default=0, ge=0)
    order: int | None = Field(default=None, ge=0)
    is_free_preview: bool = False


class LessonUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    type: LessonType | None = None
    article_content: str | None = None
    video_url: str | None = Field(default=None, max_length=500)
    resource_url: str | None = Field(default=None, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=0)
    order: int | None = Field(default=None, ge=0)
    is_free_preview: bool | None = None


class LessonAdminRead(ORMModel):
    id: uuid.UUID
    section_id: uuid.UUID
    title: str
    description: str | None = None
    type: LessonType
    article_content: str | None = None
    video_url: str | None = None
    resource_url: str | None = None
    duration_seconds: int = 0
    order: int = 0
    is_free_preview: bool = False


# ---- Upload responses ----


class UploadResponse(ORMModel):
    url: str
    size_bytes: int


# ---- Students / analytics ----


class EnrolledStudentRead(ORMModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    avatar_url: str | None = None
    enrolled_at: datetime
    progress_percent: int
    completed_at: datetime | None = None
    last_accessed_at: datetime | None = None


class CourseAnalytics(ORMModel):
    course_id: uuid.UUID
    enrollments_count: int
    completions_count: int
    average_progress_percent: float
    average_rating: float
    ratings_count: int
    revenue_cents: int
