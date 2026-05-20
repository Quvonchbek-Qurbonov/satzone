from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, computed_field, model_validator

from app.core.config import settings
from app.models.enums import AssessmentStatus, CourseLevel, HlsStatus, LessonType, PublishStatus
from app.schemas.base import ORMModel
from app.schemas.category import CategoryRead
from app.schemas.instructor import InstructorSummary


class CourseSummary(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    thumbnail_url: str | None = None
    level: CourseLevel
    language: str
    duration_minutes: int = 0
    lectures_count: int = 0
    price_cents: int = 0
    discount_price_cents: int | None = None
    currency: str = "USD"
    rating_avg: Decimal = Decimal("0")
    ratings_count: int = 0
    enrollments_count: int = 0
    is_featured: bool = False
    instructor: InstructorSummary | None = None
    category: CategoryRead | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_free(self) -> bool:
        effective = self.discount_price_cents if self.discount_price_cents is not None else self.price_cents
        return effective == 0


class CourseDetail(CourseSummary):
    description: str | None = None
    has_preview_video: bool = False
    preview_playback_url: str | None = None
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None
    status: PublishStatus
    published_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_preview_playback(cls, data):
        # ``data`` is a SQLAlchemy Course instance (when called via
        # ``model_validate``) or a dict in tests. We expose only whether a
        # preview video exists and a path to the auth-gated playback endpoint.
        if isinstance(data, dict):
            return data
        has_preview = bool(getattr(data, "preview_video_url", None))
        slug = getattr(data, "slug", None)
        playback_url = (
            f"{settings.API_V1_PREFIX}/courses/{slug}/preview-playback"
            if has_preview and slug
            else None
        )
        return {
            "id": data.id,
            "slug": data.slug,
            "title": data.title,
            "subtitle": data.subtitle,
            "thumbnail_url": data.thumbnail_url,
            "level": data.level,
            "language": data.language,
            "duration_minutes": data.duration_minutes,
            "lectures_count": data.lectures_count,
            "price_cents": data.price_cents,
            "discount_price_cents": data.discount_price_cents,
            "currency": data.currency,
            "rating_avg": data.rating_avg,
            "ratings_count": data.ratings_count,
            "enrollments_count": data.enrollments_count,
            "is_featured": data.is_featured,
            "instructor": data.instructor,
            "category": data.category,
            "description": data.description,
            "has_preview_video": has_preview,
            "preview_playback_url": playback_url,
            "learning_outcomes": data.learning_outcomes,
            "requirements": data.requirements,
            "target_audience": data.target_audience,
            "tags": data.tags,
            "status": data.status,
            "published_at": data.published_at,
        }


class LessonSummary(ORMModel):
    id: uuid.UUID
    title: str
    type: LessonType
    duration_seconds: int = 0
    order: int = 0
    is_free_preview: bool = False


class LessonRead(LessonSummary):
    description: str | None = None
    has_video: bool = False
    playback_url: str | None = None
    hls_status: HlsStatus | None = None
    article_content: str | None = None
    resource_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_lesson_playback(cls, data):
        if isinstance(data, dict):
            return data
        has_video = bool(getattr(data, "video_url", None))
        lesson_id = getattr(data, "id", None)
        playback_url = (
            f"{settings.API_V1_PREFIX}/lessons/{lesson_id}/playback"
            if has_video and lesson_id
            else None
        )
        return {
            "id": data.id,
            "title": data.title,
            "type": data.type,
            "duration_seconds": data.duration_seconds,
            "order": data.order,
            "is_free_preview": data.is_free_preview,
            "description": data.description,
            "has_video": has_video,
            "playback_url": playback_url,
            "hls_status": getattr(data, "hls_status", None),
            "article_content": data.article_content,
            "resource_url": data.resource_url,
        }


class AssessmentBrief(ORMModel):
    id: uuid.UUID
    section_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    pass_percent: int
    time_limit_minutes: int | None = None
    max_attempts: int | None = None
    is_section_quiz: bool = False
    status: AssessmentStatus
    questions_count: int = 0


class SectionRead(ORMModel):
    id: uuid.UUID
    title: str
    order: int
    lessons: list[LessonSummary] = Field(default_factory=list)
    assessments: list[AssessmentBrief] = Field(default_factory=list)


class CurriculumRead(ORMModel):
    sections: list[SectionRead]
    total_duration_seconds: int = 0
    total_lessons: int = 0
    # Course-level assessments (no ``section_id``) — e.g. a final assignment
    # that spans the whole course. Section-scoped assessments live inside
    # ``sections[].assessments``.
    course_assessments: list[AssessmentBrief] = Field(default_factory=list)
