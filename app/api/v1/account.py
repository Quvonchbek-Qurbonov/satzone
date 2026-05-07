from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy import select, update

from app.api.deps import CurrentUser
from app.core.exceptions import NotFoundError
from app.db.deps import DbSession
from app.models.auth import RefreshToken
from app.models.user import NotificationPreference
from app.schemas.base import Message
from app.schemas.user import (
    AvatarUploadResponse,
    NotificationPreferenceSchema,
    NotificationPreferenceUpdate,
    PasswordChange,
    UserMe,
    UserUpdate,
)
from app.services import auth_service
from app.utils.storage import media_url, save_upload

router = APIRouter(prefix="/me", tags=["account"])


@router.get("", response_model=UserMe)
async def get_me(user: CurrentUser) -> UserMe:
    return UserMe.model_validate(user)


@router.patch("", response_model=UserMe)
async def update_me(payload: UserUpdate, user: CurrentUser, session: DbSession) -> UserMe:
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    await session.commit()
    await session.refresh(user)
    return UserMe.model_validate(user)


@router.put("/password", response_model=Message)
async def change_password(
    payload: PasswordChange, user: CurrentUser, session: DbSession
) -> Message:
    await auth_service.change_password(
        session=session,
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return Message(message="Password changed")


@router.post("/avatar", response_model=AvatarUploadResponse)
async def upload_my_avatar(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> AvatarUploadResponse:
    key, size = await save_upload(file, kind="image", subdir=f"users/{user.id}/avatars")
    user.avatar_url = key
    await session.commit()
    return AvatarUploadResponse(avatar_url=media_url(key), size_bytes=size)


@router.delete("/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_avatar(user: CurrentUser, session: DbSession) -> None:
    user.avatar_url = None
    await session.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, session: DbSession) -> None:
    # Soft delete: deactivate + scrub PII; cascades happen via FK ondelete on related tables
    # only if a hard delete is later issued. This preserves analytics + course aggregates.
    user.is_active = False
    user.email = f"deleted-{user.id}@deleted.local"
    user.full_name = "Deleted user"
    user.avatar_url = None
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(tz=UTC))
    )
    await session.commit()


# ---- Notification preferences ----

prefs_router = APIRouter(prefix="/preferences/notifications", tags=["account"])


async def _get_or_create_pref(
    session, user_id: uuid.UUID
) -> NotificationPreference:
    pref = (
        await session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        session.add(pref)
        await session.flush()
    return pref


@prefs_router.get("", response_model=NotificationPreferenceSchema)
async def get_notification_prefs(
    user: CurrentUser, session: DbSession
) -> NotificationPreferenceSchema:
    pref = await _get_or_create_pref(session, user.id)
    await session.commit()
    return NotificationPreferenceSchema.model_validate(pref)


@prefs_router.patch("", response_model=NotificationPreferenceSchema)
async def update_notification_prefs(
    payload: NotificationPreferenceUpdate, user: CurrentUser, session: DbSession
) -> NotificationPreferenceSchema:
    pref = await _get_or_create_pref(session, user.id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(pref, k, v)
    await session.commit()
    await session.refresh(pref)
    return NotificationPreferenceSchema.model_validate(pref)


router.include_router(prefs_router)


# ---- Sessions (refresh token devices) ----

sessions_router = APIRouter(prefix="/sessions", tags=["account"])


@sessions_router.get("", response_model=list[dict])
async def list_sessions(user: CurrentUser, session: DbSession) -> list[dict]:
    rows = (
        await session.execute(
            select(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .order_by(RefreshToken.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "user_agent": r.user_agent,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
            "expires_at": r.expires_at.isoformat(),
        }
        for r in rows
    ]


@sessions_router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    rt = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.id == session_id, RefreshToken.user_id == user.id)
        )
    ).scalar_one_or_none()
    if rt is None:
        raise NotFoundError("Session not found")
    if rt.revoked_at is None:
        rt.revoked_at = datetime.now(tz=UTC)
        await session.commit()


@sessions_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(user: CurrentUser, session: DbSession) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(tz=UTC))
    )
    await session.commit()


router.include_router(sessions_router)
