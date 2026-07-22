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
    # Authoritative *nominal* segment duration. Kept for backwards
    # compatibility and as the value to use when ``segment_durations`` is null.
    segment_seconds: int | None = None
    # Real per-segment durations (seconds), positionally aligned with segment
    # indices. Populated for lessons packaged with the non-uniform stream-copy
    # path; null for uniform (transcode) lessons and older packages, where
    # every segment is ``segment_seconds`` long. Lets the player render an
    # accurate progress bar without trusting ``<video>.duration``.
    segment_durations: list[float] | None = None
    drm: DRMInit | None = None


class PreviewPlaybackResponse(ORMModel):
    course_id: uuid.UUID
    expires_at: datetime
    stream_url: str
