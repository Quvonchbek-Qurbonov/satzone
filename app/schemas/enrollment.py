from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import ORMModel
from app.schemas.course import CourseSummary, LessonSummary


class EnrollmentRead(ORMModel):
    id: uuid.UUID
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_percent: int
    last_accessed_at: datetime | None = None
    course: CourseSummary
    last_lesson: LessonSummary | None = None


class EnrollRequest(ORMModel):
    course_id: uuid.UUID


class LessonProgressUpdate(ORMModel):
    last_position_seconds: int | None = Field(default=None, ge=0)
    watched_seconds: int | None = Field(default=None, ge=0)
    completed: bool | None = None


class LessonProgressRead(ORMModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    completed_at: datetime | None = None
    watched_seconds: int = 0
    last_position_seconds: int = 0


class WishlistItemRead(ORMModel):
    course: CourseSummary
    created_at: datetime


class CertificateRead(ORMModel):
    id: uuid.UUID
    serial_no: str
    url: str | None = None
    issued_at: datetime
    course_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
