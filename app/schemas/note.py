from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class LessonNoteCreate(BaseModel):
    lesson_id: uuid.UUID
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(..., min_length=1, max_length=10_000)
    timestamp_seconds: int = Field(default=0, ge=0)


class LessonNoteUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=10_000)
    timestamp_seconds: int | None = Field(default=None, ge=0)


class LessonNoteRead(ORMModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    course_id: uuid.UUID
    title: str | None = None
    body: str
    timestamp_seconds: int
    created_at: datetime
    updated_at: datetime
