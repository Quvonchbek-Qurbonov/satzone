"""Admin-only endpoints — full operational control of the platform.

Every route requires ``role=admin`` (enforced via the :data:`AdminUser`
dependency). Sections below are grouped by resource: users, categories,
instructors, courses, programs, enrollments, reviews, certificates.
"""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import EmailStr, Field, model_validator
from slugify import slugify
from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_admin_user
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.pagination import Page, PageParams, page_params, paginate, to_page
from app.db.deps import DbSession
from app.models.catalog import Category, Instructor
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enums import PublishStatus, UserRole
from app.models.program import Program, ProgramCourse
from app.models.review import Review
from app.models.user import NotificationPreference, User
from app.schemas.admin import (
    AdminCertificateRead,
    AdminCourseRead,
    AdminCourseUpdate,
    AdminEnrollmentRead,
    AdminInstructorCreate,
    AdminInstructorRead,
    AdminInstructorUpdate,
    AdminProgramCourseRead,
    AdminProgramRead,
    AdminReviewRead,
    AdminUserRead,
    AdminUserUpdate,
    CategoryCreate,
    CategoryUpdate,
    ProgramCourseAdd,
    ProgramCourseReorder,
    ProgramCourseUpdate,
    ProgramCreate,
    ProgramUpdate,
    UploadResponse,
)
from app.schemas.base import Message, ORMModel
from app.schemas.category import CategoryRead
from app.utils.storage import media_url, save_upload

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_admin_user)])


# =============================================================================
# Helpers
# =============================================================================


_SLUG_INVALID = re.compile(r"[^a-z0-9-]")


async def _ensure_unique_slug(
    session: AsyncSession,
    model,
    base: str,
    *,
    max_len: int = 140,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """Slugify ``base`` and disambiguate against ``model.slug`` collisions."""
    candidate = slugify(base)[:max_len] or uuid.uuid4().hex[:12]
    column = model.slug
    suffix = 0
    value = candidate
    while True:
        stmt = select(model.id).where(column == value)
        if exclude_id is not None:
            stmt = stmt.where(model.id != exclude_id)
        if (await session.execute(stmt)).first() is None:
            return value
        suffix += 1
        value = f"{candidate}-{suffix}"[:max_len]


def _validate_explicit_slug(value: str) -> str:
    slug = value.strip().lower()
    if not slug or _SLUG_INVALID.search(slug):
        raise ValidationAppError(
            "Slug must contain only lowercase letters, digits, and hyphens",
            code="invalid_slug",
        )
    return slug


# =============================================================================
# Users
# =============================================================================


class PromoteInstructorRequest(ORMModel):
    user_id: uuid.UUID | None = None
    email: EmailStr | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _exactly_one(self) -> "PromoteInstructorRequest":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of user_id or email")
        return self


@router.get("/users", response_model=Page[AdminUserRead])
async def list_users(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    role: Annotated[UserRole | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    is_verified: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120, description="search by email or name")] = None,
) -> Page[AdminUserRead]:
    stmt = select(User).order_by(User.created_at.desc())
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if is_verified is not None:
        stmt = stmt.where(User.is_verified == is_verified)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(User.email).like(like) | func.lower(User.full_name).like(like))
    items, total = await paginate(session, stmt, pagination)
    return to_page([AdminUserRead.model_validate(u) for u in items], total, pagination)


@router.get("/users/{user_id}", response_model=AdminUserRead)
async def get_user(user_id: uuid.UUID, session: DbSession) -> AdminUserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    return AdminUserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID, payload: AdminUserUpdate, session: DbSession
) -> AdminUserRead:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    if data.get("is_verified") is True and user.email_verified_at is None:
        from datetime import UTC, datetime

        user.email_verified_at = datetime.now(tz=UTC)
    await session.commit()
    await session.refresh(user)
    return AdminUserRead.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, session: DbSession) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    if user.role == UserRole.ADMIN:
        raise ValidationAppError(
            "Refusing to delete an admin account via the API",
            code="cannot_delete_admin",
        )
    await session.delete(user)
    await session.commit()


@router.post("/users/promote-instructor", response_model=AdminUserRead)
async def promote_user_to_instructor(
    payload: PromoteInstructorRequest, session: DbSession
) -> AdminUserRead:
    if payload.user_id is not None:
        user = await session.get(User, payload.user_id)
    else:
        user = (
            await session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    if not user.is_active:
        raise ValidationAppError("Cannot promote a disabled user", code="user_disabled")
    if user.role == UserRole.ADMIN:
        return AdminUserRead.model_validate(user)
    if user.role != UserRole.INSTRUCTOR:
        user.role = UserRole.INSTRUCTOR
        await session.commit()
        await session.refresh(user)
    return AdminUserRead.model_validate(user)


# =============================================================================
# Categories
# =============================================================================


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(session: DbSession) -> list[CategoryRead]:
    cats = (
        await session.execute(
            select(Category).order_by(Category.sort_order, Category.name)
        )
    ).scalars().all()
    return [CategoryRead.model_validate(c) for c in cats]


@router.post("/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryCreate, session: DbSession) -> CategoryRead:
    if payload.parent_id is not None:
        parent = await session.get(Category, payload.parent_id)
        if parent is None:
            raise NotFoundError("Parent category not found", code="parent_not_found")
    base_slug = _validate_explicit_slug(payload.slug) if payload.slug else payload.name
    slug = await _ensure_unique_slug(session, Category, base_slug, max_len=120)
    cat = Category(
        slug=slug,
        name=payload.name.strip(),
        description=payload.description,
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return CategoryRead.model_validate(cat)


@router.get("/categories/{category_id}", response_model=CategoryRead)
async def get_category(category_id: uuid.UUID, session: DbSession) -> CategoryRead:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise NotFoundError("Category not found", code="category_not_found")
    return CategoryRead.model_validate(cat)


@router.patch("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, session: DbSession
) -> CategoryRead:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise NotFoundError("Category not found", code="category_not_found")
    data = payload.model_dump(exclude_unset=True)

    if "parent_id" in data and data["parent_id"] is not None:
        if data["parent_id"] == category_id:
            raise ValidationAppError(
                "A category cannot be its own parent", code="self_parent"
            )
        parent = await session.get(Category, data["parent_id"])
        if parent is None:
            raise NotFoundError("Parent category not found", code="parent_not_found")

    if "slug" in data and data["slug"]:
        new_base = _validate_explicit_slug(data["slug"])
        cat.slug = await _ensure_unique_slug(
            session, Category, new_base, max_len=120, exclude_id=cat.id
        )
        del data["slug"]

    for k, v in data.items():
        setattr(cat, k, v)
    await session.commit()
    await session.refresh(cat)
    return CategoryRead.model_validate(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, session: DbSession) -> None:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise NotFoundError("Category not found", code="category_not_found")
    course_count = (
        await session.execute(select(func.count()).where(Course.category_id == cat.id))
    ).scalar_one()
    if course_count:
        raise ConflictError(
            f"Cannot delete: {course_count} course(s) still use this category",
            code="category_in_use",
        )
    await session.delete(cat)
    await session.commit()


@router.post("/categories/{category_id}/icon", response_model=UploadResponse)
async def upload_category_icon(
    category_id: uuid.UUID,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    cat = await session.get(Category, category_id)
    if cat is None:
        raise NotFoundError("Category not found", code="category_not_found")
    key, size = await save_upload(file, kind="image", subdir=f"categories/{cat.id}/icons")
    cat.icon_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


# =============================================================================
# Instructors
# =============================================================================


@router.get("/instructors", response_model=Page[AdminInstructorRead])
async def list_instructors(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[AdminInstructorRead]:
    stmt = select(Instructor).order_by(Instructor.created_at.desc())
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Instructor.name).like(like))
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminInstructorRead.model_validate(i) for i in items], total, pagination
    )


@router.post(
    "/instructors", response_model=AdminInstructorRead, status_code=status.HTTP_201_CREATED
)
async def create_instructor(
    payload: AdminInstructorCreate, session: DbSession
) -> AdminInstructorRead:
    if payload.user_id is not None:
        target = await session.get(User, payload.user_id)
        if target is None:
            raise NotFoundError("User not found", code="user_not_found")
        existing = (
            await session.execute(
                select(Instructor.id).where(Instructor.user_id == payload.user_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                "This user already has an instructor profile",
                code="instructor_exists",
            )
    slug = await _ensure_unique_slug(session, Instructor, payload.name, max_len=150)
    inst = Instructor(
        slug=slug,
        name=payload.name.strip(),
        title=payload.title,
        bio=payload.bio,
        expertise=payload.expertise,
        avatar_url=payload.avatar_url,
        linkedin_url=payload.linkedin_url,
        twitter_url=payload.twitter_url,
        website_url=payload.website_url,
        user_id=payload.user_id,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    return AdminInstructorRead.model_validate(inst)


@router.get("/instructors/{instructor_id}", response_model=AdminInstructorRead)
async def get_instructor(
    instructor_id: uuid.UUID, session: DbSession
) -> AdminInstructorRead:
    inst = await session.get(Instructor, instructor_id)
    if inst is None:
        raise NotFoundError("Instructor not found", code="instructor_not_found")
    return AdminInstructorRead.model_validate(inst)


@router.patch("/instructors/{instructor_id}", response_model=AdminInstructorRead)
async def update_instructor(
    instructor_id: uuid.UUID, payload: AdminInstructorUpdate, session: DbSession
) -> AdminInstructorRead:
    inst = await session.get(Instructor, instructor_id)
    if inst is None:
        raise NotFoundError("Instructor not found", code="instructor_not_found")
    data = payload.model_dump(exclude_unset=True)
    if "user_id" in data and data["user_id"] is not None:
        target = await session.get(User, data["user_id"])
        if target is None:
            raise NotFoundError("User not found", code="user_not_found")
        clash = (
            await session.execute(
                select(Instructor.id).where(
                    Instructor.user_id == data["user_id"], Instructor.id != inst.id
                )
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise ConflictError(
                "Another instructor profile already links to this user",
                code="instructor_user_taken",
            )
    for k, v in data.items():
        setattr(inst, k, v)
    await session.commit()
    await session.refresh(inst)
    return AdminInstructorRead.model_validate(inst)


@router.delete("/instructors/{instructor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instructor(instructor_id: uuid.UUID, session: DbSession) -> None:
    inst = await session.get(Instructor, instructor_id)
    if inst is None:
        raise NotFoundError("Instructor not found", code="instructor_not_found")
    course_count = (
        await session.execute(select(func.count()).where(Course.instructor_id == inst.id))
    ).scalar_one()
    if course_count:
        raise ConflictError(
            f"Cannot delete: {course_count} course(s) still belong to this instructor",
            code="instructor_in_use",
        )
    await session.delete(inst)
    await session.commit()


@router.post("/instructors/{instructor_id}/avatar", response_model=UploadResponse)
async def upload_instructor_avatar(
    instructor_id: uuid.UUID,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    inst = await session.get(Instructor, instructor_id)
    if inst is None:
        raise NotFoundError("Instructor not found", code="instructor_not_found")
    key, size = await save_upload(file, kind="image", subdir=f"instructors/{inst.id}/avatars")
    inst.avatar_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


# =============================================================================
# Courses (admin moderation — instructor-self CRUD lives in /instructor/*)
# =============================================================================


def _course_select() -> Select:
    return select(Course).options(
        selectinload(Course.category),
        selectinload(Course.instructor),
    )


@router.get("/courses", response_model=Page[AdminCourseRead])
async def list_courses(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[PublishStatus | None, Query(alias="status")] = None,
    instructor_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[AdminCourseRead]:
    stmt = _course_select().order_by(Course.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Course.status == status_filter)
    if instructor_id is not None:
        stmt = stmt.where(Course.instructor_id == instructor_id)
    if category_id is not None:
        stmt = stmt.where(Course.category_id == category_id)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Course.title).like(like))
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminCourseRead.model_validate(c) for c in items], total, pagination
    )


@router.get("/courses/{course_id}", response_model=AdminCourseRead)
async def get_course(course_id: uuid.UUID, session: DbSession) -> AdminCourseRead:
    course = (
        await session.execute(_course_select().where(Course.id == course_id))
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    return AdminCourseRead.model_validate(course)


@router.patch("/courses/{course_id}", response_model=AdminCourseRead)
async def update_course(
    course_id: uuid.UUID, payload: AdminCourseUpdate, session: DbSession
) -> AdminCourseRead:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    data = payload.model_dump(exclude_unset=True)
    if "category_id" in data:
        if (await session.get(Category, data["category_id"])) is None:
            raise NotFoundError("Category not found", code="category_not_found")
    if "instructor_id" in data:
        if (await session.get(Instructor, data["instructor_id"])) is None:
            raise NotFoundError("Instructor not found", code="instructor_not_found")
    for k, v in data.items():
        setattr(course, k, v)
    await session.commit()
    course = (
        await session.execute(_course_select().where(Course.id == course.id))
    ).scalar_one()
    return AdminCourseRead.model_validate(course)


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(course_id: uuid.UUID, session: DbSession) -> None:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    enroll_count = (
        await session.execute(select(func.count()).where(Enrollment.course_id == course.id))
    ).scalar_one()
    if enroll_count:
        raise ConflictError(
            f"Cannot delete: {enroll_count} active enrollment(s). Archive instead.",
            code="course_has_enrollments",
        )
    await session.delete(course)
    await session.commit()


async def _set_course_status(
    session: AsyncSession, course_id: uuid.UUID, new_status: PublishStatus
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    course.status = new_status
    if new_status == PublishStatus.PUBLISHED and course.published_at is None:
        from datetime import UTC, datetime

        course.published_at = datetime.now(tz=UTC)
    await session.commit()
    return (
        await session.execute(_course_select().where(Course.id == course_id))
    ).scalar_one()


@router.post("/courses/{course_id}/publish", response_model=AdminCourseRead)
async def publish_course(course_id: uuid.UUID, session: DbSession) -> AdminCourseRead:
    course = await _set_course_status(session, course_id, PublishStatus.PUBLISHED)
    return AdminCourseRead.model_validate(course)


@router.post("/courses/{course_id}/unpublish", response_model=AdminCourseRead)
async def unpublish_course(
    course_id: uuid.UUID, session: DbSession
) -> AdminCourseRead:
    course = await _set_course_status(session, course_id, PublishStatus.DRAFT)
    return AdminCourseRead.model_validate(course)


@router.post("/courses/{course_id}/archive", response_model=AdminCourseRead)
async def archive_course(course_id: uuid.UUID, session: DbSession) -> AdminCourseRead:
    course = await _set_course_status(session, course_id, PublishStatus.ARCHIVED)
    return AdminCourseRead.model_validate(course)


@router.post("/courses/{course_id}/feature", response_model=AdminCourseRead)
async def feature_course(course_id: uuid.UUID, session: DbSession) -> AdminCourseRead:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    course.is_featured = True
    await session.commit()
    course = (
        await session.execute(_course_select().where(Course.id == course_id))
    ).scalar_one()
    return AdminCourseRead.model_validate(course)


@router.post("/courses/{course_id}/unfeature", response_model=AdminCourseRead)
async def unfeature_course(
    course_id: uuid.UUID, session: DbSession
) -> AdminCourseRead:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    course.is_featured = False
    await session.commit()
    course = (
        await session.execute(_course_select().where(Course.id == course_id))
    ).scalar_one()
    return AdminCourseRead.model_validate(course)


# =============================================================================
# Programs
# =============================================================================


@router.get("/programs", response_model=Page[AdminProgramRead])
async def list_programs(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[PublishStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[AdminProgramRead]:
    stmt = select(Program).order_by(Program.created_at.desc())
    if status_filter is not None:
        stmt = stmt.where(Program.status == status_filter)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Program.title).like(like))
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminProgramRead.model_validate(p) for p in items], total, pagination
    )


@router.post(
    "/programs", response_model=AdminProgramRead, status_code=status.HTTP_201_CREATED
)
async def create_program(payload: ProgramCreate, session: DbSession) -> AdminProgramRead:
    base_slug = _validate_explicit_slug(payload.slug) if payload.slug else payload.title
    slug = await _ensure_unique_slug(session, Program, base_slug, max_len=180)
    prog = Program(
        slug=slug,
        title=payload.title.strip(),
        subtitle=payload.subtitle,
        description=payload.description,
        level=payload.level,
        duration_weeks=payload.duration_weeks,
        price_cents=payload.price_cents,
        currency=payload.currency,
    )
    session.add(prog)
    await session.commit()
    await session.refresh(prog)
    return AdminProgramRead.model_validate(prog)


@router.get("/programs/{program_id}", response_model=AdminProgramRead)
async def get_program(program_id: uuid.UUID, session: DbSession) -> AdminProgramRead:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    return AdminProgramRead.model_validate(prog)


@router.patch("/programs/{program_id}", response_model=AdminProgramRead)
async def update_program(
    program_id: uuid.UUID, payload: ProgramUpdate, session: DbSession
) -> AdminProgramRead:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    data = payload.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"]:
        new_base = _validate_explicit_slug(data["slug"])
        prog.slug = await _ensure_unique_slug(
            session, Program, new_base, max_len=180, exclude_id=prog.id
        )
        del data["slug"]
    for k, v in data.items():
        setattr(prog, k, v)
    await session.commit()
    await session.refresh(prog)
    return AdminProgramRead.model_validate(prog)


@router.delete("/programs/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_program(program_id: uuid.UUID, session: DbSession) -> None:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    await session.delete(prog)
    await session.commit()


async def _set_program_status(
    session: AsyncSession, program_id: uuid.UUID, new_status: PublishStatus
) -> Program:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    prog.status = new_status
    if new_status == PublishStatus.PUBLISHED and prog.published_at is None:
        from datetime import UTC, datetime

        prog.published_at = datetime.now(tz=UTC)
    await session.commit()
    await session.refresh(prog)
    return prog


@router.post("/programs/{program_id}/publish", response_model=AdminProgramRead)
async def publish_program(
    program_id: uuid.UUID, session: DbSession
) -> AdminProgramRead:
    prog = await _set_program_status(session, program_id, PublishStatus.PUBLISHED)
    return AdminProgramRead.model_validate(prog)


@router.post("/programs/{program_id}/unpublish", response_model=AdminProgramRead)
async def unpublish_program(
    program_id: uuid.UUID, session: DbSession
) -> AdminProgramRead:
    prog = await _set_program_status(session, program_id, PublishStatus.DRAFT)
    return AdminProgramRead.model_validate(prog)


@router.post("/programs/{program_id}/archive", response_model=AdminProgramRead)
async def archive_program(
    program_id: uuid.UUID, session: DbSession
) -> AdminProgramRead:
    prog = await _set_program_status(session, program_id, PublishStatus.ARCHIVED)
    return AdminProgramRead.model_validate(prog)


@router.post("/programs/{program_id}/thumbnail", response_model=UploadResponse)
async def upload_program_thumbnail(
    program_id: uuid.UUID,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    key, size = await save_upload(file, kind="image", subdir=f"programs/{prog.id}/thumbnails")
    prog.thumbnail_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


# ----- Program ↔ Course linking -----


@router.get(
    "/programs/{program_id}/courses",
    response_model=list[AdminProgramCourseRead],
)
async def list_program_courses(
    program_id: uuid.UUID, session: DbSession
) -> list[AdminProgramCourseRead]:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    rows = (
        await session.execute(
            select(ProgramCourse)
            .options(
                selectinload(ProgramCourse.course).selectinload(Course.category),
                selectinload(ProgramCourse.course).selectinload(Course.instructor),
            )
            .where(ProgramCourse.program_id == program_id)
            .order_by(ProgramCourse.order)
        )
    ).scalars().all()
    return [AdminProgramCourseRead.model_validate(r) for r in rows]


@router.post(
    "/programs/{program_id}/courses",
    response_model=AdminProgramCourseRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_course_to_program(
    program_id: uuid.UUID, payload: ProgramCourseAdd, session: DbSession
) -> AdminProgramCourseRead:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    course = await session.get(Course, payload.course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    existing = await session.get(ProgramCourse, (program_id, payload.course_id))
    if existing is not None:
        raise ConflictError(
            "Course is already part of this program", code="course_in_program"
        )
    link = ProgramCourse(
        program_id=program_id,
        course_id=payload.course_id,
        order=payload.order,
        milestone_title=payload.milestone_title,
        is_required=payload.is_required,
    )
    session.add(link)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "Order index is already taken in this program; pick a different one",
            code="program_order_conflict",
        ) from exc
    link = (
        await session.execute(
            select(ProgramCourse)
            .options(
                selectinload(ProgramCourse.course).selectinload(Course.category),
                selectinload(ProgramCourse.course).selectinload(Course.instructor),
            )
            .where(
                and_(
                    ProgramCourse.program_id == program_id,
                    ProgramCourse.course_id == payload.course_id,
                )
            )
        )
    ).scalar_one()
    return AdminProgramCourseRead.model_validate(link)


@router.patch(
    "/programs/{program_id}/courses/{course_id}",
    response_model=AdminProgramCourseRead,
)
async def update_program_course(
    program_id: uuid.UUID,
    course_id: uuid.UUID,
    payload: ProgramCourseUpdate,
    session: DbSession,
) -> AdminProgramCourseRead:
    link = await session.get(ProgramCourse, (program_id, course_id))
    if link is None:
        raise NotFoundError("Program-course link not found", code="link_not_found")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(link, k, v)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "Order index is already taken in this program",
            code="program_order_conflict",
        ) from exc
    link = (
        await session.execute(
            select(ProgramCourse)
            .options(
                selectinload(ProgramCourse.course).selectinload(Course.category),
                selectinload(ProgramCourse.course).selectinload(Course.instructor),
            )
            .where(
                and_(
                    ProgramCourse.program_id == program_id,
                    ProgramCourse.course_id == course_id,
                )
            )
        )
    ).scalar_one()
    return AdminProgramCourseRead.model_validate(link)


@router.delete(
    "/programs/{program_id}/courses/{course_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_course_from_program(
    program_id: uuid.UUID, course_id: uuid.UUID, session: DbSession
) -> None:
    link = await session.get(ProgramCourse, (program_id, course_id))
    if link is None:
        raise NotFoundError("Program-course link not found", code="link_not_found")
    await session.delete(link)
    await session.commit()


@router.post(
    "/programs/{program_id}/courses/reorder",
    response_model=list[AdminProgramCourseRead],
)
async def reorder_program_courses(
    program_id: uuid.UUID, payload: ProgramCourseReorder, session: DbSession
) -> list[AdminProgramCourseRead]:
    prog = await session.get(Program, program_id)
    if prog is None:
        raise NotFoundError("Program not found", code="program_not_found")
    # Drop conflicts upfront by parking everyone at -1, then setting the new order.
    await session.execute(
        ProgramCourse.__table__.update()
        .where(ProgramCourse.program_id == program_id)
        .values(order=-1)
    )
    for item in payload.items:
        result = await session.execute(
            ProgramCourse.__table__.update()
            .where(
                and_(
                    ProgramCourse.program_id == program_id,
                    ProgramCourse.course_id == item.course_id,
                )
            )
            .values(order=item.order)
        )
        if result.rowcount == 0:
            await session.rollback()
            raise NotFoundError(
                f"Course {item.course_id} is not part of this program",
                code="course_not_in_program",
            )
    await session.commit()
    rows = (
        await session.execute(
            select(ProgramCourse)
            .options(
                selectinload(ProgramCourse.course).selectinload(Course.category),
                selectinload(ProgramCourse.course).selectinload(Course.instructor),
            )
            .where(ProgramCourse.program_id == program_id)
            .order_by(ProgramCourse.order)
        )
    ).scalars().all()
    return [AdminProgramCourseRead.model_validate(r) for r in rows]


# =============================================================================
# Reviews (moderation)
# =============================================================================


@router.get("/reviews", response_model=Page[AdminReviewRead])
async def list_reviews(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
) -> Page[AdminReviewRead]:
    stmt = (
        select(Review)
        .options(
            selectinload(Review.course).selectinload(Course.category),
            selectinload(Review.course).selectinload(Course.instructor),
        )
        .order_by(Review.created_at.desc())
    )
    if course_id is not None:
        stmt = stmt.where(Review.course_id == course_id)
    if user_id is not None:
        stmt = stmt.where(Review.user_id == user_id)
    if rating is not None:
        stmt = stmt.where(Review.rating == rating)
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminReviewRead.model_validate(r) for r in items], total, pagination
    )


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(review_id: uuid.UUID, session: DbSession) -> None:
    review = await session.get(Review, review_id)
    if review is None:
        raise NotFoundError("Review not found", code="review_not_found")
    await session.delete(review)
    await session.commit()


# =============================================================================
# Enrollments (support)
# =============================================================================


@router.get("/enrollments", response_model=Page[AdminEnrollmentRead])
async def list_enrollments(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[
        Literal["all", "active", "completed"], Query(alias="status")
    ] = "all",
) -> Page[AdminEnrollmentRead]:
    stmt = (
        select(Enrollment)
        .options(
            selectinload(Enrollment.course).selectinload(Course.category),
            selectinload(Enrollment.course).selectinload(Course.instructor),
        )
        .order_by(Enrollment.enrolled_at.desc())
    )
    if course_id is not None:
        stmt = stmt.where(Enrollment.course_id == course_id)
    if user_id is not None:
        stmt = stmt.where(Enrollment.user_id == user_id)
    if status_filter == "active":
        stmt = stmt.where(Enrollment.completed_at.is_(None))
    elif status_filter == "completed":
        stmt = stmt.where(Enrollment.completed_at.is_not(None))
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminEnrollmentRead.model_validate(e) for e in items], total, pagination
    )


@router.delete(
    "/enrollments/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_enrollment(
    enrollment_id: uuid.UUID, session: DbSession
) -> None:
    enroll = await session.get(Enrollment, enrollment_id)
    if enroll is None:
        raise NotFoundError("Enrollment not found", code="enrollment_not_found")
    await session.delete(enroll)
    await session.commit()


# =============================================================================
# Certificates (support)
# =============================================================================


@router.get("/certificates", response_model=Page[AdminCertificateRead])
async def list_certificates(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
    program_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AdminCertificateRead]:
    stmt = select(Certificate).order_by(Certificate.issued_at.desc())
    if user_id is not None:
        stmt = stmt.where(Certificate.user_id == user_id)
    if course_id is not None:
        stmt = stmt.where(Certificate.course_id == course_id)
    if program_id is not None:
        stmt = stmt.where(Certificate.program_id == program_id)
    items, total = await paginate(session, stmt, pagination)
    return to_page(
        [AdminCertificateRead.model_validate(c) for c in items], total, pagination
    )


@router.delete(
    "/certificates/{certificate_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_certificate(
    certificate_id: uuid.UUID, session: DbSession
) -> None:
    cert = await session.get(Certificate, certificate_id)
    if cert is None:
        raise NotFoundError("Certificate not found", code="certificate_not_found")
    await session.delete(cert)
    await session.commit()


