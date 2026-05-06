from __future__ import annotations

import uuid
from datetime import datetime

from app.models.enums import CourseLevel, PublishStatus
from app.schemas.base import ORMModel
from app.schemas.course import CourseSummary


class ProgramSummary(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    thumbnail_url: str | None = None
    level: CourseLevel
    duration_weeks: int = 0
    price_cents: int = 0
    currency: str = "USD"
    status: PublishStatus
    published_at: datetime | None = None


class ProgramCourseRead(ORMModel):
    order: int
    milestone_title: str | None = None
    is_required: bool = True
    course: CourseSummary


class ProgramDetail(ProgramSummary):
    description: str | None = None
    courses: list[ProgramCourseRead] = []


class ProgramEnrollmentRead(ORMModel):
    id: uuid.UUID
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_percent: int
    program: ProgramSummary
