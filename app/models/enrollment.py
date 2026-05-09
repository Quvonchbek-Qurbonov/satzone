from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.course import Course, Lesson
from app.models.user import User


class Enrollment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="progress_pct_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL")
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship(back_populates="enrollments")
    last_lesson: Mapped[Lesson | None] = relationship()
    lesson_progress: Mapped[list["LessonProgress"]] = relationship(
        back_populates="enrollment", cascade="all, delete-orphan"
    )


class LessonProgress(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress_enroll_lesson"),
    )

    enrollment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("enrollments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), index=True, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watched_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_position_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Anti-seek / max-2x playback state. Driven by HLS segment fetches —
    # ``max_segment_index`` is the highest segment index ever delivered to
    # this user for this lesson; ``play_credit_seconds`` accumulates effective
    # playback time (with each gap clamped at one segment duration so a long
    # pause cannot bank credit); ``last_segment_at`` is the wall clock of the
    # previous fetch and seeds the next gap calculation.
    max_segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    play_credit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_segment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enrollment: Mapped[Enrollment] = relationship(back_populates="lesson_progress")
    lesson: Mapped[Lesson] = relationship()


class Wishlist(Base):
    __tablename__ = "wishlists"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="wishlist_items")
    course: Mapped[Course] = relationship()