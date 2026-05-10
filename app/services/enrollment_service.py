from __future__ import annotations

import uuid
from datetime import UTC, datetime
from secrets import token_hex
from typing import Literal

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, paginate
from app.models.certificate import Certificate
from app.models.course import Course, CourseSection, Lesson
from app.models.enrollment import Enrollment, LessonProgress, Wishlist
from app.models.enums import PublishStatus
from app.models.user import User
from app.services import activity_service


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def enroll(session: AsyncSession, user: User, course_id: uuid.UUID) -> Enrollment:
    course = (
        await session.execute(
            select(Course).where(Course.id == course_id, Course.status == PublishStatus.PUBLISHED)
        )
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found")

    existing = (
        await session.execute(
            select(Enrollment).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    enrollment = Enrollment(user_id=user.id, course_id=course_id)
    session.add(enrollment)
    await session.execute(
        update(Course).where(Course.id == course_id).values(enrollments_count=Course.enrollments_count + 1)
    )
    await session.commit()
    return await _reload_enrollment(session, enrollment.id)


async def _reload_enrollment(session: AsyncSession, enrollment_id: uuid.UUID) -> Enrollment:
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.course).selectinload(Course.instructor),
            selectinload(Enrollment.course).selectinload(Course.category),
            selectinload(Enrollment.last_lesson),
        )
    )
    return (await session.execute(stmt)).scalar_one()


async def list_my_enrollments(
    session: AsyncSession,
    user: User,
    page_params: PageParams,
    *,
    status: Literal["all", "active", "completed"] = "all",
) -> tuple[list[Enrollment], int]:
    stmt: Select = (
        select(Enrollment)
        .where(Enrollment.user_id == user.id)
        .options(
            selectinload(Enrollment.course).selectinload(Course.instructor),
            selectinload(Enrollment.course).selectinload(Course.category),
            selectinload(Enrollment.last_lesson),
        )
    )
    if status == "active":
        stmt = stmt.where(Enrollment.completed_at.is_(None))
    elif status == "completed":
        stmt = stmt.where(Enrollment.completed_at.is_not(None))
    stmt = stmt.order_by(Enrollment.last_accessed_at.desc().nulls_last(), Enrollment.enrolled_at.desc())
    return await paginate(session, stmt, page_params)


async def get_enrollment_for_user(
    session: AsyncSession, user: User, enrollment_id: uuid.UUID
) -> Enrollment:
    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.course).selectinload(Course.instructor),
            selectinload(Enrollment.course).selectinload(Course.category),
            selectinload(Enrollment.last_lesson),
        )
    )
    enrollment = (await session.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise NotFoundError("Enrollment not found")
    if enrollment.user_id != user.id:
        raise ForbiddenError("You do not have access to this enrollment")
    return enrollment


async def update_lesson_progress(
    session: AsyncSession,
    user: User,
    enrollment_id: uuid.UUID,
    lesson_id: uuid.UUID,
    *,
    last_position_seconds: int | None = None,
    watched_seconds: int | None = None,
    completed: bool | None = None,
) -> LessonProgress:
    enrollment = await get_enrollment_for_user(session, user, enrollment_id)

    # Validate lesson belongs to the enrollment's course; surface its section
    # so we can run the section-quiz gate below.
    lesson_row = (
        await session.execute(
            select(Lesson.id, Lesson.section_id)
            .join(CourseSection, CourseSection.id == Lesson.section_id)
            .where(Lesson.id == lesson_id, CourseSection.course_id == enrollment.course_id)
        )
    ).first()
    if lesson_row is None:
        raise NotFoundError("Lesson not found in this course")

    # Imported lazily to avoid a circular import (assessment_service →
    # enrollment indirectly via shared ORM relationships).
    from app.services import assessment_service

    await assessment_service.assert_prior_section_quizzes_passed(
        session,
        user,
        course_id=enrollment.course_id,
        target_section_id=lesson_row[1],
    )

    progress = (
        await session.execute(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.lesson_id == lesson_id,
            )
        )
    ).scalar_one_or_none()
    if progress is None:
        # Set Python-side defaults explicitly — ``mapped_column(default=...)``
        # only fires at INSERT, leaving the attribute as ``None`` between
        # ``__init__`` and ``flush``; the arithmetic below would blow up.
        progress = LessonProgress(
            enrollment_id=enrollment.id,
            lesson_id=lesson_id,
            watched_seconds=0,
            last_position_seconds=0,
            max_segment_index=-1,
            play_credit_seconds=0,
        )
        session.add(progress)

    prev_watched = progress.watched_seconds
    if last_position_seconds is not None:
        progress.last_position_seconds = last_position_seconds
    if watched_seconds is not None:
        progress.watched_seconds = max(progress.watched_seconds, watched_seconds)
    just_completed = False
    if completed is True and progress.completed_at is None:
        progress.completed_at = _now()
        just_completed = True
    elif completed is False:
        progress.completed_at = None

    enrollment.last_lesson_id = lesson_id
    enrollment.last_accessed_at = _now()

    minutes_delta = max(0, (progress.watched_seconds - prev_watched)) // 60
    if minutes_delta > 0 or just_completed:
        await activity_service.record_minutes(
            session,
            user.id,
            minutes=minutes_delta,
            completed_lesson=just_completed,
        )

    await session.flush()
    await _recompute_progress(session, enrollment)
    await session.commit()
    await session.refresh(progress)
    return progress


async def recompute_enrollment_progress(
    session: AsyncSession, enrollment: Enrollment
) -> None:
    """Public wrapper around the progress recomputation used both by the
    progress-update endpoint and by the streaming layer when a segment fetch
    crosses a lesson into the completed state.
    """
    await _recompute_progress(session, enrollment)


async def _recompute_progress(session: AsyncSession, enrollment: Enrollment) -> None:
    total = (
        await session.execute(
            select(func.count(Lesson.id))
            .join(CourseSection, CourseSection.id == Lesson.section_id)
            .where(CourseSection.course_id == enrollment.course_id)
        )
    ).scalar_one()
    completed = (
        await session.execute(
            select(func.count(LessonProgress.id)).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.completed_at.is_not(None),
            )
        )
    ).scalar_one()
    pct = int(round((completed / total) * 100)) if total else 0
    enrollment.progress_percent = pct
    if total and completed >= total and enrollment.completed_at is None:
        enrollment.completed_at = _now()
        await _ensure_certificate(session, enrollment)
    elif (not total or completed < total) and enrollment.completed_at is not None:
        enrollment.completed_at = None


async def _ensure_certificate(session: AsyncSession, enrollment: Enrollment) -> Certificate:
    existing = (
        await session.execute(
            select(Certificate).where(
                Certificate.user_id == enrollment.user_id,
                Certificate.course_id == enrollment.course_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    cert = Certificate(
        user_id=enrollment.user_id,
        course_id=enrollment.course_id,
        serial_no=f"CRT-{token_hex(8).upper()}",
    )
    session.add(cert)
    await session.flush()
    return cert


async def get_certificate_for_course(
    session: AsyncSession, user: User, course_id: uuid.UUID
) -> Certificate:
    cert = (
        await session.execute(
            select(Certificate).where(
                Certificate.user_id == user.id, Certificate.course_id == course_id
            )
        )
    ).scalar_one_or_none()
    if cert is None:
        raise NotFoundError("Certificate not yet issued for this course")
    return cert


async def list_certificates(session: AsyncSession, user: User) -> list[Certificate]:
    stmt = (
        select(Certificate).where(Certificate.user_id == user.id).order_by(Certificate.issued_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------- Wishlist ----------


async def add_wishlist(session: AsyncSession, user: User, course_id: uuid.UUID) -> Wishlist:
    course = (
        await session.execute(
            select(Course.id).where(Course.id == course_id, Course.status == PublishStatus.PUBLISHED)
        )
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found")
    existing = (
        await session.execute(
            select(Wishlist).where(Wishlist.user_id == user.id, Wishlist.course_id == course_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    item = Wishlist(user_id=user.id, course_id=course_id)
    session.add(item)
    await session.commit()
    return item


async def remove_wishlist(session: AsyncSession, user: User, course_id: uuid.UUID) -> None:
    item = (
        await session.execute(
            select(Wishlist).where(Wishlist.user_id == user.id, Wishlist.course_id == course_id)
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Wishlist item not found")
    await session.delete(item)
    await session.commit()


async def list_wishlist(
    session: AsyncSession, user: User, page_params: PageParams
) -> tuple[list[Wishlist], int]:
    stmt = (
        select(Wishlist)
        .where(Wishlist.user_id == user.id)
        .options(
            selectinload(Wishlist.course).selectinload(Course.instructor),
            selectinload(Wishlist.course).selectinload(Course.category),
        )
        .order_by(Wishlist.created_at.desc())
    )
    return await paginate(session, stmt, page_params)
