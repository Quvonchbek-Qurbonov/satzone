from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.course import CourseSection, Lesson
from app.models.download import LessonAttachment, UserResourceDownload
from app.models.enrollment import Enrollment
from app.models.user import User


# --- Attachments (instructor / admin would create these) -------------------


async def list_attachments_for_lesson(
    session: AsyncSession, lesson_id: uuid.UUID
) -> list[LessonAttachment]:
    stmt = (
        select(LessonAttachment)
        .where(LessonAttachment.lesson_id == lesson_id)
        .order_by(LessonAttachment.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# --- "Saved for offline" tracking ------------------------------------------


async def save_download(
    session: AsyncSession, user: User, attachment_id: uuid.UUID
) -> UserResourceDownload:
    attachment = await session.get(LessonAttachment, attachment_id)
    if attachment is None:
        raise NotFoundError("Attachment not found")

    course_id = (
        await session.execute(
            select(CourseSection.course_id)
            .join(Lesson, Lesson.section_id == CourseSection.id)
            .where(Lesson.id == attachment.lesson_id)
        )
    ).scalar_one_or_none()
    if course_id is None:
        raise NotFoundError("Lesson not found")

    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course_id
            )
        )
    ).scalar_one_or_none()
    if enrolled is None:
        raise ForbiddenError("Enroll in the course before downloading", code="not_enrolled")

    existing = (
        await session.execute(
            select(UserResourceDownload).where(
                UserResourceDownload.user_id == user.id,
                UserResourceDownload.attachment_id == attachment_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    record = UserResourceDownload(user_id=user.id, attachment_id=attachment_id)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def list_my_downloads(
    session: AsyncSession, user: User
) -> list[tuple[UserResourceDownload, LessonAttachment]]:
    stmt = (
        select(UserResourceDownload, LessonAttachment)
        .join(LessonAttachment, LessonAttachment.id == UserResourceDownload.attachment_id)
        .where(UserResourceDownload.user_id == user.id)
        .order_by(UserResourceDownload.created_at.desc())
    )
    return list((await session.execute(stmt)).all())


async def delete_download(
    session: AsyncSession, user: User, download_id: uuid.UUID
) -> None:
    record = await session.get(UserResourceDownload, download_id)
    if record is None or record.user_id != user.id:
        raise NotFoundError("Download not found")
    await session.delete(record)
    await session.commit()
