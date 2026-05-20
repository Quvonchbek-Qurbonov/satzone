from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.pagination import PageParams, paginate
from app.models.assessment import Assessment, Question
from app.models.catalog import Category, Instructor
from app.models.course import Course, CourseSection, Lesson
from app.models.enums import AssessmentStatus, CourseLevel, PublishStatus
from app.models.review import Review

SortOption = Literal["popular", "newest", "rating", "price_asc", "price_desc"]


def _base_published_query() -> Select:
    return (
        select(Course)
        .where(Course.status == PublishStatus.PUBLISHED)
        .options(
            selectinload(Course.instructor),
            selectinload(Course.category),
        )
    )


def _apply_sort(stmt: Select, sort: SortOption) -> Select:
    if sort == "popular":
        return stmt.order_by(Course.enrollments_count.desc(), Course.rating_avg.desc())
    if sort == "newest":
        return stmt.order_by(Course.published_at.desc().nulls_last(), Course.created_at.desc())
    if sort == "rating":
        return stmt.order_by(Course.rating_avg.desc(), Course.ratings_count.desc())
    if sort == "price_asc":
        return stmt.order_by(
            func.coalesce(Course.discount_price_cents, Course.price_cents).asc(),
            Course.title.asc(),
        )
    if sort == "price_desc":
        return stmt.order_by(
            func.coalesce(Course.discount_price_cents, Course.price_cents).desc(),
            Course.title.asc(),
        )
    return stmt.order_by(Course.created_at.desc())


async def list_courses(
    session: AsyncSession,
    *,
    page_params: PageParams,
    search: str | None = None,
    category_id: uuid.UUID | None = None,
    category_slug: str | None = None,
    instructor_id: uuid.UUID | None = None,
    level: CourseLevel | None = None,
    is_free: bool | None = None,
    min_rating: float | None = None,
    min_duration_minutes: int | None = None,
    max_duration_minutes: int | None = None,
    tags: list[str] | None = None,
    sort: SortOption = "popular",
) -> tuple[list[Course], int]:
    stmt = _base_published_query()

    if category_id is not None:
        stmt = stmt.where(Course.category_id == category_id)
    if category_slug is not None:
        stmt = stmt.where(
            Course.category_id.in_(select(Category.id).where(Category.slug == category_slug))
        )
    if instructor_id is not None:
        stmt = stmt.where(Course.instructor_id == instructor_id)
    if level is not None:
        stmt = stmt.where(Course.level == level)
    if is_free is True:
        stmt = stmt.where(
            or_(
                Course.price_cents == 0,
                Course.discount_price_cents == 0,
            )
        )
    elif is_free is False:
        stmt = stmt.where(
            func.coalesce(Course.discount_price_cents, Course.price_cents) > 0
        )
    if min_rating is not None:
        stmt = stmt.where(Course.rating_avg >= min_rating)
    if min_duration_minutes is not None:
        stmt = stmt.where(Course.duration_minutes >= min_duration_minutes)
    if max_duration_minutes is not None:
        stmt = stmt.where(Course.duration_minutes <= max_duration_minutes)
    if tags:
        stmt = stmt.where(Course.tags.op("&&")(tags))
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Course.title).like(like),
                func.lower(Course.subtitle).like(like),
            )
        )

    stmt = _apply_sort(stmt, sort)
    items, total = await paginate(session, stmt, page_params)
    return items, total


async def get_course_by_slug(session: AsyncSession, slug: str) -> Course:
    stmt = (
        select(Course)
        .where(Course.slug == slug, Course.status == PublishStatus.PUBLISHED)
        .options(
            selectinload(Course.instructor),
            selectinload(Course.category),
        )
    )
    course = (await session.execute(stmt)).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found")
    return course


async def get_curriculum(session: AsyncSession, course_id: uuid.UUID) -> tuple[list[CourseSection], int, int]:
    sections = (
        await session.execute(
            select(CourseSection)
            .where(CourseSection.course_id == course_id)
            .options(selectinload(CourseSection.lessons))
            .order_by(CourseSection.order)
        )
    ).scalars().all()

    total_duration = 0
    total_lessons = 0
    for s in sections:
        for l in s.lessons:
            total_duration += l.duration_seconds or 0
            total_lessons += 1

    return list(sections), total_duration, total_lessons


async def list_course_assessments_for_student(
    session: AsyncSession, course_id: uuid.UUID
) -> list[tuple[Assessment, int]]:
    """Return every non-archived assessment in ``course_id`` along with its
    question count. Caller is responsible for verifying course publish state
    — typically reached via ``get_course_by_slug`` which already filters to
    PUBLISHED courses.
    """
    rows = (
        await session.execute(
            select(Assessment, func.count(Question.id))
            .outerjoin(Question, Question.assessment_id == Assessment.id)
            .where(
                Assessment.course_id == course_id,
                Assessment.status != AssessmentStatus.ARCHIVED,
            )
            .group_by(Assessment.id)
            .order_by(Assessment.created_at.asc())
        )
    ).all()
    return [(a, int(c or 0)) for a, c in rows]


async def get_related_courses(
    session: AsyncSession, course: Course, limit: int = 6
) -> list[Course]:
    stmt = (
        _base_published_query()
        .where(Course.id != course.id)
        .where(Course.category_id == course.category_id)
        .order_by(Course.rating_avg.desc(), Course.enrollments_count.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_reviews(
    session: AsyncSession,
    course_id: uuid.UUID,
    page_params: PageParams,
) -> tuple[list[Review], int]:
    stmt = (
        select(Review)
        .where(Review.course_id == course_id)
        .options(selectinload(Review.user))
        .order_by(Review.created_at.desc())
    )
    return await paginate(session, stmt, page_params)


async def list_categories(session: AsyncSession) -> list[Category]:
    stmt = select(Category).order_by(Category.sort_order, Category.name)
    return list((await session.execute(stmt)).scalars().all())


async def list_instructors(
    session: AsyncSession, page_params: PageParams, search: str | None = None
) -> tuple[list[Instructor], int]:
    stmt = select(Instructor)
    if search:
        like = f"%{search.strip().lower()}%"
        stmt = stmt.where(func.lower(Instructor.name).like(like))
    stmt = stmt.order_by(Instructor.rating_avg.desc(), Instructor.students_count.desc())
    return await paginate(session, stmt, page_params)


async def get_instructor_by_slug(session: AsyncSession, slug: str) -> Instructor:
    stmt = select(Instructor).where(Instructor.slug == slug)
    inst = (await session.execute(stmt)).scalar_one_or_none()
    if inst is None:
        raise NotFoundError("Instructor not found")
    return inst
