from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import CourseLevel, LessonType, PublishStatus

if TYPE_CHECKING:
    from app.models.catalog import Category, Instructor
    from app.models.enrollment import Enrollment
    from app.models.program import ProgramCourse
    from app.models.review import Review


course_level_enum = PgEnum(CourseLevel, name="course_level", create_type=False, values_callable=lambda x: [e.value for e in x])
publish_status_enum = PgEnum(PublishStatus, name="publish_status", create_type=False, values_callable=lambda x: [e.value for e in x])
lesson_type_enum = PgEnum(LessonType, name="lesson_type", create_type=False, values_callable=lambda x: [e.value for e in x])


class Course(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint("price_cents >= 0", name="price_non_negative"),
        CheckConstraint(
            "discount_price_cents IS NULL OR discount_price_cents >= 0",
            name="discount_non_negative",
        ),
        CheckConstraint(
            "discount_price_cents IS NULL OR discount_price_cents <= price_cents",
            name="discount_le_price",
        ),
    )

    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(280))
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    preview_video_url: Mapped[str | None] = mapped_column(String(500))

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    instructor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instructors.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    level: Mapped[CourseLevel] = mapped_column(
        course_level_enum, nullable=False, default=CourseLevel.ALL_LEVELS
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lectures_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discount_price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0)
    ratings_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enrollments_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    learning_outcomes: Mapped[list[str] | None] = mapped_column(ARRAY(String(280)))
    requirements: Mapped[list[str] | None] = mapped_column(ARRAY(String(280)))
    target_audience: Mapped[list[str] | None] = mapped_column(ARRAY(String(280)))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)), index=True)

    status: Mapped[PublishStatus] = mapped_column(
        publish_status_enum, nullable=False, default=PublishStatus.DRAFT, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    category: Mapped["Category"] = relationship(back_populates="courses")
    instructor: Mapped["Instructor"] = relationship(back_populates="courses")
    sections: Mapped[list["CourseSection"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseSection.order",
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="course")
    reviews: Mapped[list["Review"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    program_links: Mapped[list["ProgramCourse"]] = relationship(back_populates="course")

    @property
    def is_free(self) -> bool:
        return (self.discount_price_cents or self.price_cents) == 0

    @property
    def effective_price_cents(self) -> int:
        return self.discount_price_cents if self.discount_price_cents is not None else self.price_cents


class CourseSection(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "course_sections"
    __table_args__ = (UniqueConstraint("course_id", "order", name="uq_course_section_order"),)

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    course: Mapped[Course] = relationship(back_populates="sections")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        order_by="Lesson.order",
    )


class Lesson(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("section_id", "order", name="uq_lesson_section_order"),)

    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    video_url: Mapped[str | None] = mapped_column(String(500))
    article_content: Mapped[str | None] = mapped_column(Text)
    resource_url: Mapped[str | None] = mapped_column(String(500))
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[LessonType] = mapped_column(
        lesson_type_enum, nullable=False, default=LessonType.VIDEO
    )
    is_free_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    section: Mapped[CourseSection] = relationship(back_populates="lessons")