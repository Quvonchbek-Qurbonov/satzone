"""Admin-only request/response schemas.

All write payloads use ``exclude_unset=True`` style at the call site so PATCH
endpoints only touch fields the caller explicitly set.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import EmailStr, Field

from app.models.enums import CourseLevel, PublishStatus, UserRole
from app.schemas.base import ORMModel
from app.schemas.category import CategoryRead
from app.schemas.course import CourseSummary
from app.schemas.instructor import InstructorSummary


# ---------- Users ----------


class AdminUserUpdate(ORMModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    avatar_url: str | None = Field(default=None, max_length=500)
    role: UserRole | None = None
    is_active: bool | None = None
    is_verified: bool | None = None


class AdminUserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    avatar_url: str | None = None
    role: UserRole
    is_active: bool
    is_verified: bool
    email_verified_at: datetime | None = None
    last_login_at: datetime | None = None
    onboarding_completed_at: datetime | None = None
    google_sub: str | None = None
    created_at: datetime


# ---------- Categories ----------


class CategoryCreate(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class CategoryUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None


# ---------- Instructors (admin overlay over the public InstructorRead) ----------


class AdminInstructorCreate(ORMModel):
    name: str = Field(min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    bio: str | None = None
    expertise: list[str] | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    linkedin_url: str | None = Field(default=None, max_length=500)
    twitter_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)
    user_id: uuid.UUID | None = None  # optional link to an existing User


class AdminInstructorUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    title: str | None = Field(default=None, max_length=150)
    bio: str | None = None
    expertise: list[str] | None = None
    avatar_url: str | None = Field(default=None, max_length=500)
    linkedin_url: str | None = Field(default=None, max_length=500)
    twitter_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)
    user_id: uuid.UUID | None = None


class AdminInstructorRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    slug: str
    name: str
    title: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    expertise: list[str] | None = None
    linkedin_url: str | None = None
    twitter_url: str | None = None
    website_url: str | None = None
    rating_avg: Decimal = Decimal("0")
    students_count: int = 0
    courses_count: int = 0
    created_at: datetime


# ---------- Courses (admin) ----------


class AdminCourseUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    subtitle: str | None = Field(default=None, max_length=280)
    description: str | None = None
    category_id: uuid.UUID | None = None
    instructor_id: uuid.UUID | None = None
    level: CourseLevel | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)
    price_cents: int | None = Field(default=None, ge=0)
    discount_price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    learning_outcomes: list[str] | None = None
    requirements: list[str] | None = None
    target_audience: list[str] | None = None
    tags: list[str] | None = None
    is_featured: bool | None = None


class AdminCourseRead(CourseSummary):
    description: str | None = None
    status: PublishStatus
    published_at: datetime | None = None
    created_at: datetime


# ---------- Programs ----------


class ProgramCreate(ORMModel):
    title: str = Field(min_length=3, max_length=200)
    slug: str | None = Field(default=None, min_length=3, max_length=180)
    subtitle: str | None = Field(default=None, max_length=280)
    description: str | None = None
    level: CourseLevel = CourseLevel.ALL_LEVELS
    duration_weeks: int = Field(default=0, ge=0)
    price_cents: int = Field(default=0, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ProgramUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, min_length=3, max_length=180)
    subtitle: str | None = Field(default=None, max_length=280)
    description: str | None = None
    level: CourseLevel | None = None
    duration_weeks: int | None = Field(default=None, ge=0)
    price_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class AdminProgramRead(ORMModel):
    id: uuid.UUID
    slug: str
    title: str
    subtitle: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    level: CourseLevel
    duration_weeks: int = 0
    price_cents: int = 0
    currency: str = "USD"
    status: PublishStatus
    published_at: datetime | None = None
    created_at: datetime


class ProgramCourseAdd(ORMModel):
    course_id: uuid.UUID
    order: int = 0
    milestone_title: str | None = Field(default=None, max_length=200)
    is_required: bool = True


class ProgramCourseUpdate(ORMModel):
    order: int | None = None
    milestone_title: str | None = Field(default=None, max_length=200)
    is_required: bool | None = None


class ProgramCourseReorderItem(ORMModel):
    course_id: uuid.UUID
    order: int


class ProgramCourseReorder(ORMModel):
    items: Annotated[list[ProgramCourseReorderItem], Field(min_length=1)]


class AdminProgramCourseRead(ORMModel):
    course_id: uuid.UUID
    order: int
    milestone_title: str | None = None
    is_required: bool = True
    course: CourseSummary


# ---------- Moderation reads ----------


class AdminReviewRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    user_id: uuid.UUID
    rating: int
    comment: str | None = None
    created_at: datetime
    course: CourseSummary | None = None


class AdminEnrollmentRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID
    enrolled_at: datetime
    completed_at: datetime | None = None
    progress_percent: int = 0
    last_accessed_at: datetime | None = None
    course: CourseSummary | None = None


class AdminCertificateRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    course_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    serial_no: str
    url: str | None = None
    issued_at: datetime


# ---------- Misc ----------


class UploadResponse(ORMModel):
    url: str
    size_bytes: int


__all__ = [
    "AdminCertificateRead",
    "AdminCourseRead",
    "AdminCourseUpdate",
    "AdminEnrollmentRead",
    "AdminInstructorCreate",
    "AdminInstructorRead",
    "AdminInstructorUpdate",
    "AdminProgramCourseRead",
    "AdminProgramRead",
    "AdminReviewRead",
    "AdminUserRead",
    "AdminUserUpdate",
    "CategoryCreate",
    "CategoryUpdate",
    "ProgramCourseAdd",
    "ProgramCourseReorder",
    "ProgramCourseReorderItem",
    "ProgramCourseUpdate",
    "ProgramCreate",
    "ProgramUpdate",
    "UploadResponse",
]
