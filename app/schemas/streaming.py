from __future__ import annotations

import uuid
from datetime import datetime

from app.models.enums import HlsStatus
from app.schemas.base import ORMModel


class DRMInit(ORMModel):
    provider: str
    license_url: str


class LessonPlaybackResponse(ORMModel):
    lesson_id: uuid.UUID
    expires_at: datetime
    # Only HLS+AES-128 is offered for lessons. ``hls_url`` is null while
    # background packaging is still running — the client should poll until
    # ``hls_status == "ready"``.
    hls_url: str | None = None
    hls_status: HlsStatus | None = None
    # Total HLS segments in the lesson — published so the player can render
    # a static, non-interactive progress bar that matches the server's
    # watermark. Null while packaging is still running.
    total_segments: int | None = None
    # Authoritative segment duration; combine with ``total_segments`` to
    # show total length without trusting ``<video>.duration``.
    segment_seconds: int | None = None
    drm: DRMInit | None = None


class PreviewPlaybackResponse(ORMModel):
    course_id: uuid.UUID
    expires_at: datetime
    stream_url: str
