from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, computed_field

from app.models.enums import CourseLevel, LessonType, PublishStatus
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
    preview_video_url: str | None = None
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None
    status: PublishStatus
    published_at: datetime | None = None


class LessonSummary(ORMModel):
    id: uuid.UUID
    title: str
    type: LessonType
    duration_seconds: int = 0
    order: int = 0
    is_free_preview: bool = False


class LessonRead(LessonSummary):
    description: str | None = None
    video_url: str | None = None
    article_content: str | None = None
    resource_url: str | None = None


class SectionRead(ORMModel):
    id: uuid.UUID
    title: str
    order: int
    lessons: list[LessonSummary] = Field(default_factory=list)


class CurriculumRead(ORMModel):
    sections: list[SectionRead]
    total_duration_seconds: int = 0
    total_lessons: int = 0
