"""Service layer for instructor-facing course management.

All operations enforce that the acting :class:`User` owns the
:class:`Instructor` row for the targeted course; pure read endpoints are
exposed in :mod:`app.services.course_service` and remain public.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Iterable, Literal

from slugify import slugify
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.pagination import PageParams, paginate
from app.models.catalog import Category, Instructor
from app.models.course import Course, CourseSection, Lesson
from app.models.enrollment import Enrollment
from app.models.enums import LessonType, PublishStatus, UserRole
from app.models.user import User


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _ensure_instructor_role(user: User) -> None:
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise ForbiddenError("Instructor role required", code="instructor_role_required")


# ---------- Profile ----------


async def get_my_instructor(session: AsyncSession, user: User) -> Instructor | None:
    res = await session.execute(select(Instructor).where(Instructor.user_id == user.id))
    return res.scalar_one_or_none()


async def get_or_create_instructor(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    title: str | None = None,
    bio: str | None = None,
    expertise: list[str] | None = None,
    avatar_url: str | None = None,
    linkedin_url: str | None = None,
    twitter_url: str | None = None,
    website_url: str | None = None,
) -> Instructor:
    _ensure_instructor_role(user)
    existing = await get_my_instructor(session, user)
    if existing is not None:
        existing.name = name
        existing.title = title
        existing.bio = bio
        existing.expertise = expertise
        existing.avatar_url = avatar_url or existing.avatar_url
        existing.linkedin_url = linkedin_url
        existing.twitter_url = twitter_url
        existing.website_url = website_url
        await session.commit()
        await session.refresh(existing)
        return existing

    slug = await _unique_instructor_slug(session, name)
    inst = Instructor(
        user_id=user.id,
        slug=slug,
        name=name,
        title=title,
        bio=bio,
        expertise=expertise,
        avatar_url=avatar_url or user.avatar_url,
        linkedin_url=linkedin_url,
        twitter_url=twitter_url,
        website_url=website_url,
    )
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    return inst


async def update_my_instructor(
    session: AsyncSession, user: User, data: dict
) -> Instructor:
    inst = await get_my_instructor(session, user)
    if inst is None:
        raise NotFoundError("Instructor profile not found. Create one first.")
    for k, v in data.items():
        setattr(inst, k, v)
    await session.commit()
    await session.refresh(inst)
    return inst


async def require_my_instructor(session: AsyncSession, user: User) -> Instructor:
    _ensure_instructor_role(user)
    inst = await get_my_instructor(session, user)
    if inst is None:
        raise ForbiddenError(
            "Create your instructor profile before managing courses",
            code="instructor_profile_missing",
        )
    return inst


# ---------- Slug helpers ----------


_BAD_SLUG_RE = re.compile(r"[^a-z0-9-]")


async def _unique_instructor_slug(session: AsyncSession, base: str) -> str:
    candidate = slugify(base)[:140] or uuid.uuid4().hex[:12]
    return await _ensure_unique(session, Instructor, "slug", candidate)


async def _unique_course_slug(session: AsyncSession, base: str) -> str:
    candidate = slugify(base)[:160] or uuid.uuid4().hex[:12]
    return await _ensure_unique(session, Course, "slug", candidate)


async def _ensure_unique(session: AsyncSession, model, field: str, candidate: str) -> str:
    column = getattr(model, field)
    suffix = 0
    value = candidate
    while True:
        existing = (
            await session.execute(select(model.id).where(column == value))
        ).first()
        if existing is None:
            return value
        suffix += 1
        value = f"{candidate}-{suffix}"


# ---------- Courses ----------


async def list_my_courses(
    session: AsyncSession,
    instructor: Instructor,
    page_params: PageParams,
    *,
    status: PublishStatus | None = None,
    search: str | None = None,
) -> tuple[list[Course], int]:
    stmt: Select = select(Course).where(Course.instructor_id == instructor.id)
    if status is not None:
        stmt = stmt.where(Course.status == status)
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(func.lower(Course.title).like(like))
    stmt = stmt.order_by(Course.updated_at.desc())
    return await paginate(session, stmt, page_params)


async def get_my_course(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found")
    if course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this course")
    return course


async def create_course(
    session: AsyncSession,
    instructor: Instructor,
    data: dict,
) -> Course:
    cat = await session.get(Category, data["category_id"])
    if cat is None:
        raise NotFoundError("Category not found")

    slug = await _unique_course_slug(session, data["title"])
    course = Course(
        slug=slug,
        title=data["title"],
        subtitle=data.get("subtitle"),
        description=data.get("description"),
        category_id=data["category_id"],
        instructor_id=instructor.id,
        level=data.get("level"),
        language=data.get("language", "en"),
        price_cents=data.get("price_cents", 0),
        discount_price_cents=data.get("discount_price_cents"),
        currency=data.get("currency", "USD"),
        learning_outcomes=data.get("learning_outcomes"),
        requirements=data.get("requirements"),
        target_audience=data.get("target_audience"),
        tags=data.get("tags"),
        status=PublishStatus.DRAFT,
    )
    session.add(course)
    await session.commit()
    await session.refresh(course)
    return course


async def update_course(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    data: dict,
) -> Course:
    course = await get_my_course(session, instructor, course_id)
    if "category_id" in data and data["category_id"] is not None:
        cat = await session.get(Category, data["category_id"])
        if cat is None:
            raise NotFoundError("Category not found")
    new_price = data.get("price_cents", course.price_cents)
    new_discount = data.get("discount_price_cents", course.discount_price_cents)
    if new_discount is not None and new_price is not None and new_discount > new_price:
        raise ValidationAppError("Discount cannot exceed price", code="invalid_discount")

    for k, v in data.items():
        setattr(course, k, v)
    await session.commit()
    await session.refresh(course)
    return course


async def delete_course(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> None:
    course = await get_my_course(session, instructor, course_id)
    enrolled = (
        await session.execute(
            select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
        )
    ).scalar_one()
    if enrolled:
        raise ConflictError(
            "Course has active enrollments and cannot be deleted; archive it instead",
            code="course_has_enrollments",
        )
    await session.delete(course)
    await session.commit()


async def set_course_status(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    status: PublishStatus,
) -> Course:
    course = await get_my_course(session, instructor, course_id)
    if status == PublishStatus.PUBLISHED:
        # Lightweight publish-readiness validation.
        sections = (
            await session.execute(
                select(func.count(Lesson.id))
                .join(CourseSection, CourseSection.id == Lesson.section_id)
                .where(CourseSection.course_id == course.id)
            )
        ).scalar_one()
        if sections == 0:
            raise ValidationAppError(
                "Course must have at least one lesson before publishing",
                code="course_empty",
            )
        if not course.description:
            raise ValidationAppError(
                "Course description is required to publish",
                code="missing_description",
            )
        if course.published_at is None:
            course.published_at = _now()

    course.status = status
    # Keep instructor's courses_count in sync with published count
    await _recompute_instructor_courses(session, instructor)
    await session.commit()
    await session.refresh(course)
    return course


async def _recompute_instructor_courses(
    session: AsyncSession, instructor: Instructor
) -> None:
    count = (
        await session.execute(
            select(func.count(Course.id)).where(
                Course.instructor_id == instructor.id,
                Course.status == PublishStatus.PUBLISHED,
            )
        )
    ).scalar_one()
    instructor.courses_count = int(count)


# ---------- Sections ----------


async def list_sections(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> list[CourseSection]:
    course = await get_my_course(session, instructor, course_id)
    rows = (
        await session.execute(
            select(CourseSection)
            .where(CourseSection.course_id == course.id)
            .order_by(CourseSection.order)
        )
    ).scalars().all()
    return list(rows)


async def create_section(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    *,
    title: str,
    order: int | None,
) -> CourseSection:
    course = await get_my_course(session, instructor, course_id)
    if order is None:
        next_order = (
            await session.execute(
                select(func.coalesce(func.max(CourseSection.order), -1) + 1).where(
                    CourseSection.course_id == course.id
                )
            )
        ).scalar_one()
        order = int(next_order)
    section = CourseSection(course_id=course.id, title=title, order=order)
    session.add(section)
    await session.commit()
    await session.refresh(section)
    return section


async def get_my_section(
    session: AsyncSession, instructor: Instructor, section_id: uuid.UUID
) -> CourseSection:
    stmt = (
        select(CourseSection)
        .where(CourseSection.id == section_id)
        .options(selectinload(CourseSection.course))
    )
    section = (await session.execute(stmt)).scalar_one_or_none()
    if section is None:
        raise NotFoundError("Section not found")
    if section.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this section")
    return section


async def update_section(
    session: AsyncSession,
    instructor: Instructor,
    section_id: uuid.UUID,
    data: dict,
) -> CourseSection:
    section = await get_my_section(session, instructor, section_id)
    for k, v in data.items():
        setattr(section, k, v)
    await session.commit()
    await session.refresh(section)
    return section


async def delete_section(
    session: AsyncSession, instructor: Instructor, section_id: uuid.UUID
) -> None:
    section = await get_my_section(session, instructor, section_id)
    course_id = section.course_id
    await session.delete(section)
    await session.flush()
    await _recompute_course_aggregates(session, course_id)
    await session.commit()


async def reorder_sections(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    items: Iterable[tuple[uuid.UUID, int]],
) -> list[CourseSection]:
    course = await get_my_course(session, instructor, course_id)
    rows = (
        await session.execute(
            select(CourseSection).where(CourseSection.course_id == course.id)
        )
    ).scalars().all()
    by_id = {s.id: s for s in rows}
    # Stage to large temp values to avoid unique(course_id, order) collisions mid-update.
    for offset, (sid, _) in enumerate(items):
        if sid not in by_id:
            raise ValidationAppError(f"Section {sid} not in course")
        by_id[sid].order = 10_000 + offset
    await session.flush()
    for sid, new_order in items:
        by_id[sid].order = int(new_order)
    await session.commit()
    return sorted(by_id.values(), key=lambda s: s.order)


# ---------- Lessons ----------


async def list_lessons(
    session: AsyncSession, instructor: Instructor, section_id: uuid.UUID
) -> list[Lesson]:
    section = await get_my_section(session, instructor, section_id)
    rows = (
        await session.execute(
            select(Lesson)
            .where(Lesson.section_id == section.id)
            .order_by(Lesson.order)
        )
    ).scalars().all()
    return list(rows)


async def create_lesson(
    session: AsyncSession,
    instructor: Instructor,
    section_id: uuid.UUID,
    data: dict,
) -> Lesson:
    section = await get_my_section(session, instructor, section_id)
    order = data.get("order")
    if order is None:
        order = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(Lesson.order), -1) + 1).where(
                        Lesson.section_id == section.id
                    )
                )
            ).scalar_one()
        )
    lesson = Lesson(
        section_id=section.id,
        title=data["title"],
        description=data.get("description"),
        type=data.get("type", LessonType.VIDEO),
        article_content=data.get("article_content"),
        video_url=data.get("video_url"),
        resource_url=data.get("resource_url"),
        duration_seconds=data.get("duration_seconds", 0),
        order=order,
        is_free_preview=data.get("is_free_preview", False),
    )
    session.add(lesson)
    await session.flush()
    await _recompute_course_aggregates(session, section.course_id)
    await session.commit()
    await session.refresh(lesson)
    return lesson


async def get_my_lesson(
    session: AsyncSession, instructor: Instructor, lesson_id: uuid.UUID
) -> Lesson:
    stmt = (
        select(Lesson)
        .where(Lesson.id == lesson_id)
        .options(selectinload(Lesson.section).selectinload(CourseSection.course))
    )
    lesson = (await session.execute(stmt)).scalar_one_or_none()
    if lesson is None:
        raise NotFoundError("Lesson not found")
    if lesson.section.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this lesson")
    return lesson


async def update_lesson(
    session: AsyncSession,
    instructor: Instructor,
    lesson_id: uuid.UUID,
    data: dict,
) -> Lesson:
    lesson = await get_my_lesson(session, instructor, lesson_id)
    for k, v in data.items():
        setattr(lesson, k, v)
    await session.flush()
    await _recompute_course_aggregates(session, lesson.section.course_id)
    await session.commit()
    await session.refresh(lesson)
    return lesson


async def delete_lesson(
    session: AsyncSession, instructor: Instructor, lesson_id: uuid.UUID
) -> None:
    lesson = await get_my_lesson(session, instructor, lesson_id)
    course_id = lesson.section.course_id
    await session.delete(lesson)
    await session.flush()
    await _recompute_course_aggregates(session, course_id)
    await session.commit()


async def reorder_lessons(
    session: AsyncSession,
    instructor: Instructor,
    section_id: uuid.UUID,
    items: Iterable[tuple[uuid.UUID, int]],
) -> list[Lesson]:
    section = await get_my_section(session, instructor, section_id)
    rows = (
        await session.execute(
            select(Lesson).where(Lesson.section_id == section.id)
        )
    ).scalars().all()
    by_id = {l.id: l for l in rows}
    for offset, (lid, _) in enumerate(items):
        if lid not in by_id:
            raise ValidationAppError(f"Lesson {lid} not in section")
        by_id[lid].order = 10_000 + offset
    await session.flush()
    for lid, new_order in items:
        by_id[lid].order = int(new_order)
    await session.commit()
    return sorted(by_id.values(), key=lambda l: l.order)


async def set_lesson_video(
    session: AsyncSession,
    instructor: Instructor,
    lesson_id: uuid.UUID,
    *,
    url: str,
    duration_seconds: int | None,
) -> Lesson:
    lesson = await get_my_lesson(session, instructor, lesson_id)
    lesson.video_url = url
    if duration_seconds is not None:
        lesson.duration_seconds = duration_seconds
    if lesson.type != LessonType.VIDEO:
        lesson.type = LessonType.VIDEO
    await session.flush()
    await _recompute_course_aggregates(session, lesson.section.course_id)
    await session.commit()
    await session.refresh(lesson)
    return lesson


async def set_lesson_resource(
    session: AsyncSession,
    instructor: Instructor,
    lesson_id: uuid.UUID,
    *,
    url: str,
) -> Lesson:
    lesson = await get_my_lesson(session, instructor, lesson_id)
    lesson.resource_url = url
    await session.commit()
    await session.refresh(lesson)
    return lesson


# ---------- Course aggregates ----------


async def _recompute_course_aggregates(
    session: AsyncSession, course_id: uuid.UUID
) -> None:
    agg = (
        await session.execute(
            select(
                func.count(Lesson.id),
                func.coalesce(func.sum(Lesson.duration_seconds), 0),
            )
            .join(CourseSection, CourseSection.id == Lesson.section_id)
            .where(CourseSection.course_id == course_id)
        )
    ).one()
    course = await session.get(Course, course_id)
    if course is None:
        return
    course.lectures_count = int(agg[0] or 0)
    course.duration_minutes = int((agg[1] or 0) // 60)


# ---------- Students / analytics ----------


async def list_course_students(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    page_params: PageParams,
    *,
    status: Literal["all", "active", "completed"] = "all",
) -> tuple[list[Enrollment], int]:
    course = await get_my_course(session, instructor, course_id)
    stmt = (
        select(Enrollment)
        .where(Enrollment.course_id == course.id)
        .options(selectinload(Enrollment.user))
    )
    if status == "active":
        stmt = stmt.where(Enrollment.completed_at.is_(None))
    elif status == "completed":
        stmt = stmt.where(Enrollment.completed_at.is_not(None))
    stmt = stmt.order_by(Enrollment.enrolled_at.desc())
    return await paginate(session, stmt, page_params)


async def course_analytics(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> dict:
    course = await get_my_course(session, instructor, course_id)
    enrollments_count = (
        await session.execute(
            select(func.count(Enrollment.id)).where(Enrollment.course_id == course.id)
        )
    ).scalar_one()
    completions_count = (
        await session.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.course_id == course.id,
                Enrollment.completed_at.is_not(None),
            )
        )
    ).scalar_one()
    avg_progress = (
        await session.execute(
            select(func.coalesce(func.avg(Enrollment.progress_percent), 0.0)).where(
                Enrollment.course_id == course.id
            )
        )
    ).scalar_one()
    revenue_cents = int((enrollments_count or 0) * course.effective_price_cents)
    return {
        "course_id": course.id,
        "enrollments_count": int(enrollments_count or 0),
        "completions_count": int(completions_count or 0),
        "average_progress_percent": float(avg_progress or 0.0),
        "average_rating": float(course.rating_avg or 0.0),
        "ratings_count": int(course.ratings_count or 0),
        "revenue_cents": revenue_cents,
    }
