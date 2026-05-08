from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.download import DownloadCreate, DownloadRead, LessonAttachmentRead
from app.services import download_service

attachments_router = APIRouter(prefix="/lessons", tags=["my-learnings"])
downloads_router = APIRouter(prefix="/me/downloads", tags=["my-learnings"])


@attachments_router.get(
    "/{lesson_id}/attachments", response_model=list[LessonAttachmentRead]
)
async def list_lesson_attachments(
    lesson_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[LessonAttachmentRead]:
    rows = await download_service.list_attachments_for_lesson(session, lesson_id)
    return [LessonAttachmentRead.model_validate(r) for r in rows]


@downloads_router.get("", response_model=list[DownloadRead])
async def list_my_downloads(
    user: CurrentUser, session: DbSession
) -> list[DownloadRead]:
    rows = await download_service.list_my_downloads(session, user)
    return [
        DownloadRead.model_validate(
            {
                "id": record.id,
                "created_at": record.created_at,
                "attachment": attachment,
            }
        )
        for record, attachment in rows
    ]


@downloads_router.post("", response_model=DownloadRead, status_code=status.HTTP_201_CREATED)
async def save_download(
    payload: DownloadCreate, user: CurrentUser, session: DbSession
) -> DownloadRead:
    record = await download_service.save_download(session, user, payload.attachment_id)
    # Fetch the attachment for the response.
    rows = await download_service.list_my_downloads(session, user)
    for r, attachment in rows:
        if r.id == record.id:
            return DownloadRead.model_validate(
                {"id": r.id, "created_at": r.created_at, "attachment": attachment}
            )
    # Fallback (should not happen).
    raise RuntimeError("download record disappeared after insert")  # pragma: no cover


@downloads_router.delete("/{download_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_download(
    download_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await download_service.delete_download(session, user, download_id)
