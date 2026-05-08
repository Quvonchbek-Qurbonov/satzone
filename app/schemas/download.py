from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class LessonAttachmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    file_key: str = Field(..., min_length=1, max_length=500)
    file_size_bytes: int | None = Field(default=None, ge=0)
    mime_type: str | None = Field(default=None, max_length=120)


class LessonAttachmentRead(ORMModel):
    id: uuid.UUID
    lesson_id: uuid.UUID
    title: str
    # Resolved to a fresh URL by the ``resource_url``-style media serializer.
    resource_url: str = Field(..., alias="file_key")
    file_size_bytes: int | None = None
    mime_type: str | None = None
    created_at: datetime


class DownloadCreate(BaseModel):
    attachment_id: uuid.UUID


class DownloadRead(ORMModel):
    id: uuid.UUID
    attachment: LessonAttachmentRead
    created_at: datetime
