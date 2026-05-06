from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Category
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enums import PublishStatus
from app.models.program import Program
from app.models.user import User, UserInterest


async def fetch_continue_learning(session: AsyncSession, user: User, limit: int = 6) -> list[Enrollment]:
    stmt = (
        select(Enrollment)
        .where(Enrollment.user_id == user.id, Enrollment.completed_at.is_(None))
        .options(
            selectinload(Enrollment.course).selectinload(Course.instructor),
            selectinload(Enrollment.course).selectinload(Course.category),
            selectinload(Enrollment.last_lesson),
        )
        .order_by(Enrollment.last_accessed_at.desc().nulls_last(), Enrollment.enrolled_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_recommended(session: AsyncSession, user: User | None, limit: int = 8) -> list[Course]:
    base = (
        select(Course)
        .where(Course.status == PublishStatus.PUBLISHED)
        .options(selectinload(Course.instructor), selectinload(Course.category))
    )
    if user is not None:
        interest_subq = select(UserInterest.category_id).where(UserInterest.user_id == user.id)
        # Try interest-based first
        stmt = (
            base.where(Course.category_id.in_(interest_subq))
            .order_by(Course.rating_avg.desc(), Course.enrollments_count.desc())
            .limit(limit)
        )
        results = list((await session.execute(stmt)).scalars().all())
        if results:
            return results
    # Fallback: top-rated overall
    fallback = base.order_by(Course.rating_avg.desc(), Course.enrollments_count.desc()).limit(limit)
    return list((await session.execute(fallback)).scalars().all())


async def fetch_featured(session: AsyncSession, limit: int = 6) -> list[Course]:
    stmt = (
        select(Course)
        .where(Course.status == PublishStatus.PUBLISHED, Course.is_featured.is_(True))
        .options(selectinload(Course.instructor), selectinload(Course.category))
        .order_by(Course.rating_avg.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_popular(session: AsyncSession, limit: int = 8) -> list[Course]:
    stmt = (
        select(Course)
        .where(Course.status == PublishStatus.PUBLISHED)
        .options(selectinload(Course.instructor), selectinload(Course.category))
        .order_by(Course.enrollments_count.desc(), Course.rating_avg.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_new(session: AsyncSession, limit: int = 8) -> list[Course]:
    stmt = (
        select(Course)
        .where(Course.status == PublishStatus.PUBLISHED)
        .options(selectinload(Course.instructor), selectinload(Course.category))
        .order_by(Course.published_at.desc().nulls_last(), Course.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_top_categories(session: AsyncSession, limit: int = 12) -> list[Category]:
    stmt = (
        select(Category)
        .where(Category.parent_id.is_(None))
        .order_by(Category.sort_order, Category.name)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def fetch_programs(session: AsyncSession, limit: int = 4) -> list[Program]:
    stmt = (
        select(Program)
        .where(Program.status == PublishStatus.PUBLISHED)
        .order_by(Program.published_at.desc().nulls_last(), Program.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
