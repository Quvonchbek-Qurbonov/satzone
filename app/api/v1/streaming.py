"""Protected video streaming endpoints.

Lesson playback is **HLS-only**. There is no direct-MP4 endpoint for
lessons because a plain MP4 over HTTP is trivially downloadable — the user
right-clicks "Save As" and walks away with the file. AES-128 encrypted HLS
segments served by this module are useless to anyone who doesn't also hold
a fresh, IP-bound playback token for the per-lesson key endpoint.

Layers in play:

* **HLS + AES-128.** When ffmpeg has finished packaging the uploaded
  source, ``GET /lessons/{id}/playback`` mints a signed playback token
  and returns ``hls_url`` pointing at a manifest endpoint. The manifest
  rewrites every ``EXT-X-KEY`` and segment URI per request to absolute
  paths under our domain; the player can't sidestep us. The 16-byte
  content key is wrapped at rest with a Fernet KEK (``MEDIA_KEK``) and
  only served from ``GET /lessons/{id}/hls/key`` to a holder of a valid
  token.

* **IP-bound, time-bound tokens.** Each playback token bakes the
  requester's IP (``cip`` claim) and expires after
  ``STREAM_TOKEN_TTL_SECONDS`` (default 30 min — long enough for full
  playback, short enough to limit damage from a leaked URL). Every
  manifest, segment and key request re-verifies both.

* **Course preview videos** are deliberately not encrypted — they're
  marketing content meant to be watched by non-enrolled users to
  evaluate the course. Those still go through ``preview-stream`` for
  auth + IP binding, but as a direct MP4 byte-range proxy.

DRM (Widevine / FairPlay / PlayReady) is wired as a separate route in
:mod:`app.api.v1.drm` — it requires a paid license server.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationAppError
from app.db.deps import DbSession
from app.models.course import Course, Lesson
from app.models.enums import HlsStatus
from app.schemas.streaming import (
    DRMInit,
    LessonPlaybackResponse,
    PreviewPlaybackResponse,
)
from app.services import streaming_service
from app.utils.storage import open_range, read_object, stat_object

router = APIRouter(tags=["streaming"])


# ---------- Helpers ----------


_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(header: str | None, size: int) -> tuple[int, int]:
    """Resolve an HTTP ``Range`` header to ``(start, end)`` clamped to the file.

    No header → full file. Suffix range (``bytes=-N``) → last N bytes.
    Returns inclusive bounds suitable for ``Content-Range``.
    """
    if not header:
        return 0, size - 1
    m = _RANGE_RE.match(header.strip())
    if m is None:
        return 0, size - 1
    start_s, end_s = m.group(1), m.group(2)
    if not start_s and not end_s:
        return 0, size - 1
    if not start_s:
        # Suffix
        suffix = int(end_s)
        if suffix <= 0:
            return 0, size - 1
        start = max(size - suffix, 0)
        return start, size - 1
    start = int(start_s)
    end = int(end_s) if end_s else size - 1
    if start >= size:
        # Out of range — fall back to full
        return 0, size - 1
    end = min(end, size - 1)
    return start, end


def _drm_init(lesson_id: uuid.UUID) -> DRMInit | None:
    """Return DRM init data when a provider is configured. Currently a stub —
    the actual license-acquisition URL is the same regardless of provider; the
    client uses it via Encrypted Media Extensions (EME).
    """
    if settings.DRM_PROVIDER == "none":
        return None
    return DRMInit(
        provider=settings.DRM_PROVIDER,
        license_url=f"{settings.API_V1_PREFIX}/lessons/{lesson_id}/drm/license",
    )


def _abs_url(request: Request, path: str) -> str:
    base = settings.API_BASE_URL.rstrip("/")
    if not base:
        return str(request.base_url).rstrip("/") + path
    return f"{base}{path}"


# =============================================================================
# Lesson playback
# =============================================================================


@router.get("/lessons/{lesson_id}/playback", response_model=LessonPlaybackResponse)
async def lesson_playback(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> LessonPlaybackResponse:
    """Issue a signed playback token + ``hls_url`` for a lesson video.

    Plain-MP4 streaming is intentionally not offered: HLS+AES-128 is the
    only way to make ``curl <url>`` return useless bytes. ``hls_url`` is
    populated only once background packaging has set ``hls_status=ready``;
    while it's pending the client should poll this endpoint or display a
    "video processing" state.
    """
    lesson = await streaming_service.authorize_lesson_playback(session, user, lesson_id)
    if not lesson.video_url:
        raise NotFoundError("Lesson has no video", code="lesson_video_missing")
    if lesson.hls_status != HlsStatus.READY:
        # Still packaging — return the status so the client can retry, but
        # don't expose any URL that could be downloaded as plain MP4.
        return LessonPlaybackResponse(
            lesson_id=lesson_id,
            expires_at=streaming_service._now(),
            hls_url=None,
            hls_status=lesson.hls_status,
            drm=None,
        )

    cip = streaming_service.request_client_ip(request)
    token, expires = streaming_service.issue_playback_token(
        user_id=user.id, resource_id=lesson_id, scope="lesson", client_ip=cip
    )
    hls_url = _abs_url(
        request,
        f"{settings.API_V1_PREFIX}/lessons/{lesson_id}/hls/master.m3u8?t={token}",
    )
    return LessonPlaybackResponse(
        lesson_id=lesson_id,
        expires_at=expires,
        hls_url=hls_url,
        hls_status=lesson.hls_status,
        drm=_drm_init(lesson_id),
    )


# =============================================================================
# Course preview playback (the small video on a course detail page)
# =============================================================================


@router.get("/courses/{slug}/preview-playback", response_model=PreviewPlaybackResponse)
async def course_preview_playback(
    slug: str,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> PreviewPlaybackResponse:
    course = (
        await session.execute(select(Course).where(Course.slug == slug))
    ).scalar_one_or_none()
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    await streaming_service.authorize_course_preview(session, user, course.id)
    if not course.preview_video_url:
        raise NotFoundError("Course has no preview video", code="course_preview_missing")

    cip = streaming_service.request_client_ip(request)
    token, expires = streaming_service.issue_playback_token(
        user_id=user.id, resource_id=course.id, scope="course_preview", client_ip=cip
    )
    stream_url = _abs_url(
        request,
        f"{settings.API_V1_PREFIX}/courses/{course.id}/preview-stream?t={token}",
    )
    return PreviewPlaybackResponse(
        course_id=course.id,
        expires_at=expires,
        stream_url=stream_url,
    )


@router.get("/courses/{course_id}/preview-stream")
async def course_preview_stream(
    course_id: uuid.UUID,
    request: Request,
    session: DbSession,
    t: Annotated[str, Query(description="Signed playback token from /preview-playback")],
) -> StreamingResponse:
    streaming_service.verify_playback_token(
        t,
        expected_resource_id=course_id,
        expected_scope="course_preview",
        expected_client_ip=streaming_service.request_client_ip(request),
    )
    course = await session.get(Course, course_id)
    if course is None or not course.preview_video_url:
        raise NotFoundError("Course preview not found", code="course_preview_missing")
    return _stream_object(request, course.preview_video_url)


# =============================================================================
# Shared byte-range streamer
# =============================================================================


def _stream_object(request: Request, key: str) -> StreamingResponse:
    info = stat_object(key)
    if info is None:
        raise NotFoundError("Media not found", code="media_not_found")
    size, content_type = info
    start, end = _parse_range(request.headers.get("range"), size)
    length = end - start + 1
    headers = {
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Cache-Control": "private, no-store",
        # Browsers will still let users save the buffered video; this just
        # keeps middleware caches and proxies from holding a copy.
        "X-Content-Type-Options": "nosniff",
    }
    status_code = 206 if (start, end) != (0, size - 1) else 200
    return StreamingResponse(
        open_range(key, start, end),
        status_code=status_code,
        media_type=content_type,
        headers=headers,
    )


# =============================================================================
# HLS endpoints (Tier 2)
# =============================================================================


@router.get("/lessons/{lesson_id}/hls/master.m3u8")
async def lesson_hls_master(
    lesson_id: uuid.UUID,
    request: Request,
    session: DbSession,
    t: Annotated[str, Query(description="Signed playback token from /playback")],
) -> Response:
    """Return the per-lesson HLS master playlist with rewritten signed URIs.

    The packager writes manifests with relative URIs; we rewrite each
    ``EXT-X-KEY`` and segment line to absolute paths under our domain that
    carry the same ``?t=`` token, so the player can fetch them without
    reaching back into S3 directly.
    """
    streaming_service.verify_playback_token(
        t,
        expected_resource_id=lesson_id,
        expected_scope="lesson",
        expected_client_ip=streaming_service.request_client_ip(request),
    )
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None or not lesson.hls_master_key or lesson.hls_status != HlsStatus.READY:
        raise NotFoundError("HLS not packaged for this lesson", code="hls_not_ready")

    manifest_bytes = read_object(lesson.hls_master_key)
    if manifest_bytes is None:
        raise NotFoundError("HLS manifest missing", code="hls_manifest_missing")
    manifest = manifest_bytes.decode("utf-8")

    base = f"{settings.API_V1_PREFIX}/lessons/{lesson_id}/hls"
    rewritten_lines: list[str] = []
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-KEY"):
            rewritten_lines.append(
                re.sub(
                    r'URI="[^"]+"',
                    f'URI="{_abs_url(request, base + "/key?t=" + t)}"',
                    line,
                )
            )
        elif stripped and not stripped.startswith("#"):
            # Segment line — rewrite the relative segment name to a signed URL.
            rewritten_lines.append(_abs_url(request, f"{base}/seg/{stripped}?t={t}"))
        else:
            rewritten_lines.append(line)
    body = "\n".join(rewritten_lines) + "\n"
    return Response(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/lessons/{lesson_id}/hls/seg/{seg_name}")
async def lesson_hls_segment(
    lesson_id: uuid.UUID,
    seg_name: str,
    request: Request,
    session: DbSession,
    t: Annotated[str, Query()],
) -> StreamingResponse:
    streaming_service.verify_playback_token(
        t,
        expected_resource_id=lesson_id,
        expected_scope="lesson",
        expected_client_ip=streaming_service.request_client_ip(request),
    )
    # Pin to a strict naming pattern to defeat path traversal.
    if not re.fullmatch(r"seg_\d{4,6}\.ts", seg_name):
        raise ValidationAppError("Invalid segment name", code="invalid_segment_name")
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None or lesson.hls_status != HlsStatus.READY:
        raise NotFoundError("HLS not packaged", code="hls_not_ready")
    seg_key = f"lessons/{lesson_id}/hls/{seg_name}"
    return _stream_object(request, seg_key)


@router.get("/lessons/{lesson_id}/hls/key")
async def lesson_hls_key(
    lesson_id: uuid.UUID,
    request: Request,
    session: DbSession,
    t: Annotated[str, Query()],
) -> Response:
    streaming_service.verify_playback_token(
        t,
        expected_resource_id=lesson_id,
        expected_scope="lesson",
        expected_client_ip=streaming_service.request_client_ip(request),
    )
    plain = await streaming_service.get_lesson_key_plaintext(session, lesson_id)
    if plain is None:
        raise NotFoundError("Lesson key not found", code="lesson_key_missing")
    return Response(
        content=plain,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )
