"""Protected video streaming — token issuance, access checks, and KEK helpers.

The streaming endpoints (``/lessons/{id}/stream``, the HLS manifest, segments
and AES-128 key URL) accept a short-lived signed token in a ``?t=`` query
parameter. We use the query string rather than the ``Authorization`` header
so that HTML5 ``<video>`` and HLS players — which can't easily attach custom
headers to byte-range or segment fetches — can still play protected content.

The signing path:

* ``issue_playback_token`` returns a JWT scoped to a single ``(user_id,
  lesson_id, scope)`` tuple with a TTL pulled from settings.
* ``verify_playback_token`` re-authenticates that token on each segment /
  range / key request. The returned context lets the route enforce that the
  caller is requesting *their* token for *this* lesson — substituting another
  user's token or another lesson's token fails verification.

Per-lesson AES-128 keys are wrapped at rest with a Fernet master key
(``settings.MEDIA_KEK``). Plaintext content keys exist only for the duration
of an authorized key-fetch request.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.models.course import Course, CourseSection, Lesson
from app.models.enrollment import Enrollment, LessonProgress
from app.models.enums import PublishStatus, UserRole
from app.models.media import MediaKey
from app.models.user import User

PlaybackScope = Literal["lesson", "course_preview"]


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------- Token issue / verify ----------


def request_client_ip(request) -> str:
    """Best-effort client IP. Honours ``X-Forwarded-For`` so the API works
    behind a reverse proxy; in dev it falls back to the socket peer.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def issue_playback_token(
    *,
    user_id: uuid.UUID,
    resource_id: uuid.UUID,
    scope: PlaybackScope,
    client_ip: str,
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    expire = _now() + timedelta(seconds=ttl_seconds or settings.STREAM_TOKEN_TTL_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "rid": str(resource_id),
        "scope": scope,
        "cip": client_ip,
        "type": "playback",
        "iat": int(_now().timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def verify_playback_token(
    token: str,
    *,
    expected_resource_id: uuid.UUID,
    expected_scope: PlaybackScope,
    expected_client_ip: str,
) -> uuid.UUID:
    """Validate ``token`` and return the user id baked into it.

    Raises :class:`UnauthorizedError` if the token is missing/expired/forged,
    doesn't match the requested resource/scope, or was minted for a different
    client IP. Tokens are non-transferable across networks.
    """
    # Lazy import — keeps streaming_service usable from scripts that don't
    # boot the FastAPI app (and thus don't register the Prometheus collectors).
    from app.core.metrics import playback_token_rejections_total

    def _reject(reason: str, message: str) -> UnauthorizedError:
        playback_token_rejections_total.labels(reason=reason).inc()
        return UnauthorizedError(message, code=reason)

    if not token:
        raise _reject("missing_playback_token", "Missing playback token")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise _reject("playback_token_expired", "Playback token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise _reject("invalid_playback_token", "Invalid playback token") from exc
    if payload.get("type") != "playback":
        raise _reject("invalid_playback_token", "Wrong token type")
    if payload.get("scope") != expected_scope:
        raise _reject("playback_scope_mismatch", "Token scope mismatch")
    if payload.get("rid") != str(expected_resource_id):
        raise _reject("playback_resource_mismatch", "Token resource mismatch")
    if payload.get("cip") != expected_client_ip:
        raise _reject("playback_ip_mismatch", "Token bound to a different IP")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _reject("invalid_playback_token", "Invalid token subject") from exc


# ---------- Access checks ----------


async def authorize_lesson_playback(
    session: AsyncSession,
    user: User,
    lesson_id: uuid.UUID,
) -> Lesson:
    """Return ``lesson`` if ``user`` is allowed to play it.

    Allowed when any of:

    * the lesson is marked ``is_free_preview`` and the parent course is
      published,
    * the user is enrolled in the course,
    * the user owns the course (instructor) or is an admin.
    """
    stmt = (
        select(Lesson, CourseSection, Course)
        .join(CourseSection, CourseSection.id == Lesson.section_id)
        .join(Course, Course.id == CourseSection.course_id)
        .where(Lesson.id == lesson_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFoundError("Lesson not found", code="lesson_not_found")
    lesson, _section, course = row

    if user.role == UserRole.ADMIN:
        return lesson

    from app.models.catalog import Instructor

    owner_user_id = (
        await session.execute(
            select(Instructor.user_id).where(Instructor.id == course.instructor_id)
        )
    ).scalar_one_or_none()
    if owner_user_id is not None and owner_user_id == user.id:
        return lesson

    if lesson.is_free_preview and course.status == PublishStatus.PUBLISHED:
        return lesson

    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course.id
            )
        )
    ).first()
    if enrolled is None:
        raise ForbiddenError(
            "Enroll in this course to watch the lesson",
            code="not_enrolled",
        )
    return lesson


async def lookup_enforced_enrollment(
    session: AsyncSession, user: User, lesson: Lesson
) -> Enrollment | None:
    """Return the enrollment whose anti-seek state we should drive — or
    ``None`` if the caller is exempt (admin, course owner, or a non-enrolled
    user watching a free preview).

    Exempt callers see the full HLS manifest and no segment is gated.
    """
    if user.role == UserRole.ADMIN:
        return None
    course_id = (
        await session.execute(
            select(CourseSection.course_id).where(CourseSection.id == lesson.section_id)
        )
    ).scalar_one()
    from app.models.catalog import Instructor

    course = await session.get(Course, course_id)
    if course is not None:
        owner_user_id = (
            await session.execute(
                select(Instructor.user_id).where(Instructor.id == course.instructor_id)
            )
        ).scalar_one_or_none()
        if owner_user_id is not None and owner_user_id == user.id:
            return None

    enrollment = (
        await session.execute(
            select(Enrollment).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course_id
            )
        )
    ).scalar_one_or_none()
    return enrollment


# ---------- Anti-seek / max-2x gating ----------


class SegmentSkipBlocked(ForbiddenError):
    """Raised when a segment fetch would skip past the allowed window."""

    code = "segment_skip_blocked"
    message = "Skipping ahead is not allowed for this lesson"


class SegmentRateExceeded(ForbiddenError):
    """Raised when a segment fetch would exceed the max playback rate."""

    code = "segment_rate_exceeded"
    message = "Playback rate limit exceeded"
    status_code = 429


async def _get_or_create_progress(
    session: AsyncSession, enrollment: Enrollment, lesson_id: uuid.UUID
) -> LessonProgress:
    progress = (
        await session.execute(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == enrollment.id,
                LessonProgress.lesson_id == lesson_id,
            )
        )
    ).scalar_one_or_none()
    if progress is None:
        # See note in enrollment_service: column defaults are insert-time, so
        # we set the int counters here so subsequent arithmetic is safe even
        # if a caller reads attributes before the next flush.
        progress = LessonProgress(
            enrollment_id=enrollment.id,
            lesson_id=lesson_id,
            watched_seconds=0,
            last_position_seconds=0,
            max_segment_index=-1,
            play_credit_seconds=0,
        )
        session.add(progress)
        await session.flush()
    return progress


def visible_segment_ceiling(max_segment_index: int) -> int:
    """Highest segment index the manifest may currently expose to the user.

    The sliding window is `[0, max_segment_index + LOOKAHEAD]`. Segments past
    that simply don't appear in the served manifest, which is what makes
    naive HLS players physically unable to seek beyond it.
    """
    return max_segment_index + settings.STREAM_LOOKAHEAD_SEGMENTS


async def gate_segment_fetch(
    session: AsyncSession,
    enrollment: Enrollment,
    lesson: Lesson,
    seg_index: int,
) -> tuple[LessonProgress, bool]:
    """Authorize a single HLS segment fetch and advance the watermark.

    The two enforcement rules:

    1. **Anti-skip** — ``seg_index`` may not be more than ``LOOKAHEAD``
       segments ahead of the user's current watermark. Re-fetching segments
       at or below the watermark is always allowed (rewatch, re-buffer).
    2. **Anti-fast-forward** — the wall-clock time the user has actually
       spent in the player (``play_credit_seconds``, with each gap clamped
       at one segment duration so pauses/backgrounded tabs don't bank
       credit) must be at least
       ``(post_watermark + 1 - LOOKAHEAD) * seg_dur / MAX_RATE``.

    On success, persists the new ``max_segment_index``,
    ``play_credit_seconds`` and ``last_segment_at``, and marks the lesson
    complete the moment the watermark reaches the final segment. Returns
    ``(progress, just_completed)`` so callers can fan out completion side
    effects (enrollment recompute, daily-activity rollup) only on the
    transition.
    """
    progress = await _get_or_create_progress(session, enrollment, lesson.id)

    seg_dur = settings.HLS_SEGMENT_SECONDS
    lookahead = settings.STREAM_LOOKAHEAD_SEGMENTS
    max_rate = settings.STREAM_MAX_RATE_MULTIPLIER
    now = _now()

    # Rule 1 — anti-skip. Re-fetching ≤ watermark is fine; this only blocks
    # leaping past the look-ahead window.
    if seg_index > progress.max_segment_index + lookahead:
        raise SegmentSkipBlocked()

    # Build the candidate updated state. We commit it only after the rate
    # check passes.
    if progress.last_segment_at is None:
        gap = 0
    else:
        gap = max(0, int((now - progress.last_segment_at).total_seconds()))
    credit = progress.play_credit_seconds + min(gap, seg_dur)
    new_max = max(progress.max_segment_index, seg_index)

    # Rule 2 — anti-fast-forward. The first ``lookahead`` segments are free
    # so initial buffering works; everything past that is rate-limited
    # against accumulated play credit.
    required_credit = max(0, (new_max + 1 - lookahead) * seg_dur / max_rate)
    if credit < required_credit:
        # Don't persist; let the player retry once enough time has elapsed.
        raise SegmentRateExceeded()

    progress.max_segment_index = new_max
    progress.play_credit_seconds = credit
    progress.last_segment_at = now

    just_completed = False
    total = lesson.hls_segments_count
    if total is not None and new_max >= total - 1 and progress.completed_at is None:
        progress.completed_at = now
        just_completed = True

    await session.flush()
    return progress, just_completed


async def authorize_course_preview(
    session: AsyncSession, user: User | None, course_id: uuid.UUID
) -> Course:
    """Course preview videos are openable by any authenticated user when the
    course is published; admins/owners can preview unpublished drafts.
    """
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found", code="course_not_found")
    if course.status == PublishStatus.PUBLISHED:
        return course
    if user is None:
        raise ForbiddenError("Course preview not available", code="course_not_published")
    if user.role == UserRole.ADMIN:
        return course
    from app.models.catalog import Instructor

    owner_user_id = (
        await session.execute(
            select(Instructor.user_id).where(Instructor.id == course.instructor_id)
        )
    ).scalar_one_or_none()
    if owner_user_id == user.id:
        return course
    raise ForbiddenError("Course preview not available", code="course_not_published")


# ---------- KEK (Fernet) helpers ----------


def _fernet() -> Fernet:
    if not settings.MEDIA_KEK:
        raise RuntimeError(
            "MEDIA_KEK is not configured — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and set it in .env"
        )
    return Fernet(settings.MEDIA_KEK.encode("utf-8"))


def wrap_content_key(plain: bytes) -> bytes:
    return _fernet().encrypt(plain)


def unwrap_content_key(wrapped: bytes) -> bytes:
    try:
        return _fernet().decrypt(wrapped)
    except InvalidToken as exc:
        raise RuntimeError("Failed to unwrap content key — KEK rotated or wrong?") from exc


def generate_content_key() -> bytes:
    """Fresh 16-byte AES-128 content key."""
    return os.urandom(16)


async def get_or_create_lesson_key(
    session: AsyncSession, lesson_id: uuid.UUID
) -> tuple[MediaKey, bytes]:
    """Return ``(record, plaintext_key)``; mints + persists if absent."""
    existing = (
        await session.execute(select(MediaKey).where(MediaKey.lesson_id == lesson_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, unwrap_content_key(existing.encrypted_key)
    plain = generate_content_key()
    record = MediaKey(lesson_id=lesson_id, encrypted_key=wrap_content_key(plain))
    session.add(record)
    await session.flush()
    return record, plain


async def get_lesson_key_plaintext(
    session: AsyncSession, lesson_id: uuid.UUID
) -> bytes | None:
    record = (
        await session.execute(select(MediaKey).where(MediaKey.lesson_id == lesson_id))
    ).scalar_one_or_none()
    if record is None:
        return None
    return unwrap_content_key(record.encrypted_key)
