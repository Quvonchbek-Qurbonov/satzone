from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import ORMModel
from app.schemas.user import UserPublic


class ReviewRead(ORMModel):
    id: uuid.UUID
    rating: int
    comment: str | None = None
    created_at: datetime
    user: UserPublic | None = None


class ReviewCreate(ORMModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)


class ReviewUpdate(ORMModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)
