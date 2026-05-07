"""Schemas for instructor-facing course management endpoints.

Distinct from :mod:`app.schemas.course` (public catalog) and
:mod:`app.schemas.instructor` (public profile read) — these include draft
content, status fields, and write payloads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.core.config import settings
from app.models.enums import CourseLevel, HlsStatus, LessonType, PublishStatus
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
    has_preview_video: bool = False
    preview_playback_url: str | None = None
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

    @model_validator(mode="before")
    @classmethod
    def _derive_instructor_course_playback(cls, data):
        if isinstance(data, dict):
            return data
        has_preview = bool(getattr(data, "preview_video_url", None))
        slug = getattr(data, "slug", None)
        return {
            "id": data.id,
            "slug": data.slug,
            "title": data.title,
            "subtitle": data.subtitle,
            "description": data.description,
            "thumbnail_url": data.thumbnail_url,
            "has_preview_video": has_preview,
            "preview_playback_url": (
                f"{settings.API_V1_PREFIX}/courses/{slug}/preview-playback"
                if has_preview and slug
                else None
            ),
            "category_id": data.category_id,
            "instructor_id": data.instructor_id,
            "level": data.level,
            "language": data.language,
            "duration_minutes": data.duration_minutes,
            "lectures_count": data.lectures_count,
            "price_cents": data.price_cents,
            "discount_price_cents": data.discount_price_cents,
            "currency": data.currency,
            "learning_outcomes": data.learning_outcomes,
            "requirements": data.requirements,
            "target_audience": data.target_audience,
            "tags": data.tags,
            "status": data.status,
            "published_at": data.published_at,
            "enrollments_count": data.enrollments_count,
            "rating_avg": data.rating_avg,
            "ratings_count": data.ratings_count,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


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
    has_video: bool = False
    playback_url: str | None = None
    hls_status: HlsStatus | None = None
    resource_url: str | None = None
    duration_seconds: int = 0
    order: int = 0
    is_free_preview: bool = False

    @model_validator(mode="before")
    @classmethod
    def _derive_admin_lesson_playback(cls, data):
        if isinstance(data, dict):
            return data
        has_video = bool(getattr(data, "video_url", None))
        lesson_id = getattr(data, "id", None)
        return {
            "id": data.id,
            "section_id": data.section_id,
            "title": data.title,
            "description": data.description,
            "type": data.type,
            "article_content": data.article_content,
            "has_video": has_video,
            "playback_url": (
                f"{settings.API_V1_PREFIX}/lessons/{lesson_id}/playback"
                if has_video and lesson_id
                else None
            ),
            "hls_status": getattr(data, "hls_status", None),
            "resource_url": data.resource_url,
            "duration_seconds": data.duration_seconds,
            "order": data.order,
            "is_free_preview": data.is_free_preview,
        }


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
