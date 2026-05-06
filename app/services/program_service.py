from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.core.pagination import PageParams, paginate
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enums import PublishStatus
from app.models.program import Program, ProgramCourse, ProgramEnrollment
from app.models.user import User


async def list_programs(
    session: AsyncSession, page_params: PageParams
) -> tuple[list[Program], int]:
    stmt = (
        select(Program)
        .where(Program.status == PublishStatus.PUBLISHED)
        .order_by(Program.published_at.desc().nulls_last(), Program.created_at.desc())
    )
    return await paginate(session, stmt, page_params)


async def get_program_by_slug(session: AsyncSession, slug: str) -> Program:
    stmt = (
        select(Program)
        .where(Program.slug == slug, Program.status == PublishStatus.PUBLISHED)
        .options(
            selectinload(Program.courses)
            .selectinload(ProgramCourse.course)
            .selectinload(Course.instructor),
            selectinload(Program.courses)
            .selectinload(ProgramCourse.course)
            .selectinload(Course.category),
        )
    )
    program = (await session.execute(stmt)).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")
    return program


async def enroll_in_program(
    session: AsyncSession, user: User, program_id: uuid.UUID
) -> ProgramEnrollment:
    program = (
        await session.execute(
            select(Program).where(Program.id == program_id, Program.status == PublishStatus.PUBLISHED)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    existing = (
        await session.execute(
            select(ProgramEnrollment).where(
                ProgramEnrollment.user_id == user.id, ProgramEnrollment.program_id == program_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    enrollment = ProgramEnrollment(user_id=user.id, program_id=program_id)
    session.add(enrollment)

    # Auto-enroll user in all required courses of the program
    course_ids = (
        await session.execute(
            select(ProgramCourse.course_id).where(
                ProgramCourse.program_id == program_id, ProgramCourse.is_required.is_(True)
            )
        )
    ).scalars().all()
    if course_ids:
        existing_enrollments = (
            await session.execute(
                select(Enrollment.course_id).where(
                    Enrollment.user_id == user.id, Enrollment.course_id.in_(course_ids)
                )
            )
        ).scalars().all()
        existing_set = set(existing_enrollments)
        for cid in course_ids:
            if cid not in existing_set:
                session.add(Enrollment(user_id=user.id, course_id=cid))
                await session.execute(
                    update(Course)
                    .where(Course.id == cid)
                    .values(enrollments_count=Course.enrollments_count + 1)
                )

    await session.commit()
    await session.refresh(enrollment, attribute_names=["program"])
    return enrollment


async def list_my_program_enrollments(
    session: AsyncSession, user: User, page_params: PageParams
) -> tuple[list[ProgramEnrollment], int]:
    stmt = (
        select(ProgramEnrollment)
        .where(ProgramEnrollment.user_id == user.id)
        .options(selectinload(ProgramEnrollment.program))
        .order_by(ProgramEnrollment.enrolled_at.desc())
    )
    items, total = await paginate(session, stmt, page_params)
    # Refresh aggregate progress on the fly so the response is current.
    for pe in items:
        await _recompute_program_progress(session, pe)
    await session.commit()
    return items, total


async def _recompute_program_progress(
    session: AsyncSession, pe: ProgramEnrollment
) -> None:
    course_ids = (
        await session.execute(
            select(ProgramCourse.course_id).where(ProgramCourse.program_id == pe.program_id)
        )
    ).scalars().all()
    if not course_ids:
        pe.progress_percent = 0
        return
    completed = (
        await session.execute(
            select(func.count(Enrollment.id)).where(
                Enrollment.user_id == pe.user_id,
                Enrollment.course_id.in_(course_ids),
                Enrollment.completed_at.is_not(None),
            )
        )
    ).scalar_one()
    pe.progress_percent = int(round((completed / len(course_ids)) * 100))
    if completed >= len(course_ids) and pe.completed_at is None:
        from datetime import UTC, datetime

        pe.completed_at = datetime.now(tz=UTC)
