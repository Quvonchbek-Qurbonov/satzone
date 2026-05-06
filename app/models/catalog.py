from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.user import User, UserInterest


class Category(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon_url: Mapped[str | None] = mapped_column(String(500))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side="Category.id"
    )
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    courses: Mapped[list["Course"]] = relationship(back_populates="category")
    interested_users: Mapped[list["UserInterest"]] = relationship(back_populates="category")


class Instructor(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "instructors"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    title: Mapped[str | None] = mapped_column(String(150))
    bio: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    expertise: Mapped[list[str] | None] = mapped_column(ARRAY(String(80)))
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0)
    students_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    courses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    twitter_url: Mapped[str | None] = mapped_column(String(500))
    website_url: Mapped[str | None] = mapped_column(String(500))

    user: Mapped["User | None"] = relationship(foreign_keys=[user_id])
    courses: Mapped[list["Course"]] = relationship(back_populates="instructor")