from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import SkillLevel, UserRole

if TYPE_CHECKING:
    from app.models.catalog import Category
    from app.models.course import Course
    from app.models.enrollment import Enrollment, Wishlist
    from app.models.program import ProgramEnrollment


user_role_enum = PgEnum(UserRole, name="user_role", create_type=False, values_callable=lambda x: [e.value for e in x])
skill_level_enum = PgEnum(SkillLevel, name="skill_level", create_type=False, values_callable=lambda x: [e.value for e in x])


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False, default=UserRole.USER)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    notification_pref: Mapped["NotificationPreference | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    interests: Mapped[list["UserInterest"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    wishlist_items: Mapped[list["Wishlist"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    program_enrollments: Mapped[list["ProgramEnrollment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    headline: Mapped[str | None] = mapped_column(String(255))
    bio: Mapped[str | None] = mapped_column(Text)
    skill_level: Mapped[SkillLevel | None] = mapped_column(skill_level_enum)
    weekly_goal_minutes: Mapped[int | None] = mapped_column(Integer)
    learning_goal: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str | None] = mapped_column(String(10), default="en")
    timezone: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship(back_populates="profile")


class UserInterest(Base):
    __tablename__ = "user_interests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="interests")
    category: Mapped["Category"] = relationship(back_populates="interested_users")


class NotificationPreference(TimestampMixin, Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email_marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_announcements: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_course_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship(back_populates="notification_pref")