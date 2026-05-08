from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin


class LessonNote(UUIDPKMixin, TimestampMixin, Base):
    """A single user-authored note pinned to a (course, lesson) timestamp."""

    __tablename__ = "lesson_notes"
    __table_args__ = (
        Index("ix_lesson_notes_user_lesson", "user_id", "lesson_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Optional course pointer for cheap "all my notes for this course" listings;
    # could be derived via a join but denormalized for read speed.
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Position in the lesson video the note was taken at (0 if N/A).
    timestamp_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
