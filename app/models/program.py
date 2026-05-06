from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import CourseLevel, PublishStatus

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User


# Reuse the enum types defined in course.py — create_type=False ensures Alembic only creates them once.
program_level_enum = PgEnum(CourseLevel, name="course_level", create_type=False, values_callable=lambda x: [e.value for e in x])
program_status_enum = PgEnum(PublishStatus, name="publish_status", create_type=False, values_callable=lambda x: [e.value for e in x])


class Program(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="program_price_non_negative"),
    )

    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(280))
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    level: Mapped[CourseLevel] = mapped_column(
        program_level_enum, nullable=False, default=CourseLevel.ALL_LEVELS
    )
    duration_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[PublishStatus] = mapped_column(
        program_status_enum, nullable=False, default=PublishStatus.DRAFT, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    courses: Mapped[list["ProgramCourse"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="ProgramCourse.order",
    )
    enrollments: Mapped[list["ProgramEnrollment"]] = relationship(back_populates="program")


class ProgramCourse(Base):
    __tablename__ = "program_courses"
    __table_args__ = (
        UniqueConstraint("program_id", "order", name="uq_program_course_order"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="RESTRICT"), primary_key=True
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    milestone_title: Mapped[str | None] = mapped_column(String(200))
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    program: Mapped[Program] = relationship(back_populates="courses")
    course: Mapped["Course"] = relationship(back_populates="program_links")


class ProgramEnrollment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "program_enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "program_id", name="uq_program_enrollment_user_program"),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="program_progress_pct_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship(back_populates="program_enrollments")
    program: Mapped[Program] = relationship(back_populates="enrollments")