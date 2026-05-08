from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.note import LessonNoteCreate, LessonNoteRead, LessonNoteUpdate
from app.services import note_service

router = APIRouter(prefix="/me/notes", tags=["my-learnings"])


@router.post("", response_model=LessonNoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: LessonNoteCreate, user: CurrentUser, session: DbSession
) -> LessonNoteRead:
    note = await note_service.create_note(
        session,
        user,
        lesson_id=payload.lesson_id,
        title=payload.title,
        body=payload.body,
        timestamp_seconds=payload.timestamp_seconds,
    )
    return LessonNoteRead.model_validate(note)


@router.get("", response_model=list[LessonNoteRead])
async def list_notes(
    user: CurrentUser,
    session: DbSession,
    lesson_id: uuid.UUID | None = Query(default=None),
    course_id: uuid.UUID | None = Query(default=None),
) -> list[LessonNoteRead]:
    rows = await note_service.list_notes(
        session, user, lesson_id=lesson_id, course_id=course_id
    )
    return [LessonNoteRead.model_validate(r) for r in rows]


@router.patch("/{note_id}", response_model=LessonNoteRead)
async def update_note(
    note_id: uuid.UUID,
    payload: LessonNoteUpdate,
    user: CurrentUser,
    session: DbSession,
) -> LessonNoteRead:
    note = await note_service.update_note(
        session,
        user,
        note_id,
        title=payload.title,
        body=payload.body,
        timestamp_seconds=payload.timestamp_seconds,
    )
    return LessonNoteRead.model_validate(note)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, user: CurrentUser, session: DbSession) -> None:
    await note_service.delete_note(session, user, note_id)
