from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.course import CourseSection, Lesson
from app.models.enrollment import Enrollment
from app.models.note import LessonNote
from app.models.user import User


async def _resolve_lesson_course(session: AsyncSession, lesson_id: uuid.UUID) -> uuid.UUID:
    course_id = (
        await session.execute(
            select(CourseSection.course_id)
            .join(Lesson, Lesson.section_id == CourseSection.id)
            .where(Lesson.id == lesson_id)
        )
    ).scalar_one_or_none()
    if course_id is None:
        raise NotFoundError("Lesson not found")
    return course_id


async def _ensure_enrolled(session: AsyncSession, user: User, course_id: uuid.UUID) -> None:
    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course_id
            )
        )
    ).scalar_one_or_none()
    if enrolled is None:
        raise ForbiddenError("Enroll in the course before taking notes", code="not_enrolled")


async def create_note(
    session: AsyncSession,
    user: User,
    *,
    lesson_id: uuid.UUID,
    title: str | None,
    body: str,
    timestamp_seconds: int,
) -> LessonNote:
    course_id = await _resolve_lesson_course(session, lesson_id)
    await _ensure_enrolled(session, user, course_id)
    note = LessonNote(
        user_id=user.id,
        lesson_id=lesson_id,
        course_id=course_id,
        title=title,
        body=body,
        timestamp_seconds=timestamp_seconds,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


async def list_notes(
    session: AsyncSession,
    user: User,
    *,
    lesson_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> list[LessonNote]:
    stmt = select(LessonNote).where(LessonNote.user_id == user.id)
    if lesson_id is not None:
        stmt = stmt.where(LessonNote.lesson_id == lesson_id)
    if course_id is not None:
        stmt = stmt.where(LessonNote.course_id == course_id)
    stmt = stmt.order_by(LessonNote.timestamp_seconds.asc(), LessonNote.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def update_note(
    session: AsyncSession,
    user: User,
    note_id: uuid.UUID,
    *,
    title: str | None,
    body: str | None,
    timestamp_seconds: int | None,
) -> LessonNote:
    note = await _get(session, user, note_id)
    if title is not None:
        note.title = title
    if body is not None:
        note.body = body
    if timestamp_seconds is not None:
        note.timestamp_seconds = timestamp_seconds
    await session.commit()
    await session.refresh(note)
    return note


async def delete_note(session: AsyncSession, user: User, note_id: uuid.UUID) -> None:
    note = await _get(session, user, note_id)
    await session.delete(note)
    await session.commit()


async def _get(session: AsyncSession, user: User, note_id: uuid.UUID) -> LessonNote:
    note = await session.get(LessonNote, note_id)
    if note is None or note.user_id != user.id:
        raise NotFoundError("Note not found")
    return note
