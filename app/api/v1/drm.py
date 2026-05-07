"""DRM license proxy.

The player sends a binary license challenge in the request body; we forward
it to the configured provider (see :mod:`app.utils.drm`) along with the
authenticated user + lesson identity, and stream the binary license back.

Endpoint is auth-gated like every other lesson resource — DRM doesn't
remove the need to verify enrollment, it just makes the bytes useless to a
client that hasn't gone through the license dance.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.services import streaming_service
from app.utils.drm import get_provider

router = APIRouter(tags=["drm"])


@router.post("/lessons/{lesson_id}/drm/license")
async def issue_drm_license(
    lesson_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> Response:
    await streaming_service.authorize_lesson_playback(session, user, lesson_id)
    challenge = await request.body()
    provider = get_provider()
    license_bytes = await provider.issue_license(
        lesson_id=lesson_id, user_id=user.id, license_request=challenge
    )
    return Response(
        content=license_bytes,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )
