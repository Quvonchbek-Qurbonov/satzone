"""Promocode lifecycle.

Two callers:

1. **Instructors** — create, list, and revoke codes for their own
   courses. A code may be revoked only while it has zero recorded uses;
   once it has been redeemed (an order paid with it) the row is frozen so
   the order's audit trail keeps a valid FK.
2. **Checkout** — at order creation time we compute the discount, then
   atomically *reserve* one of the code's remaining uses. The reservation
   is held by the order's lifecycle: paid → permanent, cancelled →
   released. The reservation update is a single SQL ``UPDATE ... WHERE
   uses_count < max_uses RETURNING`` so two simultaneous buyers can
   never both consume the last use.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.models.catalog import Instructor
from app.models.course import Course
from app.models.enums import PromocodeDiscountKind
from app.models.promocode import Promocode, SavedPromocode
from app.models.user import User


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _normalize_code(code: str) -> str:
    return code.strip().upper()


# ---------- Discount math ----------


def compute_discount_cents(
    *,
    kind: PromocodeDiscountKind,
    value: int,
    base_amount_cents: int,
) -> int:
    """Return how much should be shaved off ``base_amount_cents``.

    Result is always clipped to ``[0, base_amount_cents]`` so we never
    refund more than the user is paying and never produce a negative
    discount.
    """
    if base_amount_cents <= 0:
        return 0
    if kind is PromocodeDiscountKind.PERCENT:
        raw = (base_amount_cents * value) // 100
    else:
        raw = value
    return max(0, min(raw, base_amount_cents))


# ---------- Instructor CRUD ----------


async def _owned_course(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found")
    if course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this course")
    return course


async def create_promocode(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    *,
    code: str,
    discount_kind: PromocodeDiscountKind,
    discount_value: int,
    expires_at: datetime | None,
) -> Promocode:
    course = await _owned_course(session, instructor, course_id)
    base_price = course.effective_price_cents
    if base_price <= 0:
        raise ValidationAppError(
            "Course is free; promocodes cannot be applied",
            code="course_is_free",
        )

    if discount_kind is PromocodeDiscountKind.FIXED and discount_value >= base_price:
        raise ValidationAppError(
            "Fixed discount must be less than the course price",
            code="discount_exceeds_price",
        )
    if discount_kind is PromocodeDiscountKind.PERCENT and discount_value >= 100:
        # 100% would result in a zero-price order which violates the
        # ``amount_positive`` CHECK on ``orders``.
        raise ValidationAppError(
            "Percent discount must be less than 100",
            code="discount_makes_free",
        )
    if expires_at is not None and expires_at <= _now():
        raise ValidationAppError(
            "expires_at must be in the future", code="expires_in_past"
        )

    promo = Promocode(
        course_id=course.id,
        instructor_id=instructor.id,
        code=_normalize_code(code),
        discount_kind=discount_kind,
        discount_value=discount_value,
        max_uses=1,
        uses_count=0,
        expires_at=expires_at,
        is_active=True,
    )
    session.add(promo)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "Promocode already exists", code="promocode_code_taken"
        ) from exc
    await session.refresh(promo)
    return promo


async def list_course_promocodes(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> list[Promocode]:
    await _owned_course(session, instructor, course_id)
    rows = (
        await session.execute(
            select(Promocode)
            .where(Promocode.course_id == course_id)
            .order_by(Promocode.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def get_my_promocode(
    session: AsyncSession, instructor: Instructor, promocode_id: uuid.UUID
) -> Promocode:
    promo = await session.get(Promocode, promocode_id)
    if promo is None:
        raise NotFoundError("Promocode not found")
    if promo.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this promocode")
    return promo


async def revoke_promocode(
    session: AsyncSession, instructor: Instructor, promocode_id: uuid.UUID
) -> None:
    """Hard-delete an unused promocode owned by ``instructor``.

    A code that has any recorded uses (``uses_count > 0``) cannot be
    deleted — pending or completed orders depend on it. Instead, we
    deactivate it so it can't be redeemed any further but the order's FK
    stays valid.
    """
    promo = await get_my_promocode(session, instructor, promocode_id)
    if promo.uses_count > 0:
        promo.is_active = False
        await session.commit()
        return
    await session.delete(promo)
    await session.commit()


# ---------- Checkout helpers ----------


async def find_active_promocode_for_course(
    session: AsyncSession, *, code: str, course_id: uuid.UUID
) -> Promocode:
    """Look up a code that's valid for ``course_id`` *right now*.

    Raises 422 with a stable error code per failure reason so the
    frontend can render a precise message instead of a generic
    ``not_found``.
    """
    normalized = _normalize_code(code)
    promo = (
        await session.execute(
            select(Promocode).where(Promocode.code == normalized)
        )
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promocode not found", code="promocode_not_found")
    if promo.course_id != course_id:
        raise ValidationAppError(
            "Promocode is not valid for this course",
            code="promocode_wrong_course",
        )
    if not promo.is_active:
        raise ValidationAppError(
            "Promocode has been revoked", code="promocode_inactive"
        )
    if promo.expires_at is not None and promo.expires_at <= _now():
        raise ValidationAppError(
            "Promocode has expired", code="promocode_expired"
        )
    if promo.uses_count >= promo.max_uses:
        raise ConflictError(
            "Promocode has already been used", code="promocode_exhausted"
        )
    return promo


async def try_reserve(session: AsyncSession, promo: Promocode) -> bool:
    """Atomically claim one use of ``promo``.

    Returns ``True`` iff the row was updated. Caller must commit/rollback
    the surrounding session. Race-safe: two concurrent buyers send the
    same UPDATE, exactly one row will satisfy ``uses_count < max_uses``
    after the other writes through.
    """
    now = _now()
    stmt = (
        update(Promocode)
        .where(
            Promocode.id == promo.id,
            Promocode.is_active.is_(True),
            Promocode.uses_count < Promocode.max_uses,
            or_(
                Promocode.expires_at.is_(None),
                Promocode.expires_at > now,
            ),
        )
        .values(uses_count=Promocode.uses_count + 1, updated_at=now)
        .returning(Promocode.id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def release(session: AsyncSession, promocode_id: uuid.UUID) -> None:
    """Decrement ``uses_count`` for a cancelled reservation.

    Safe to call multiple times: the ``uses_count > 0`` guard prevents
    underflow and skips no-op releases. The caller is responsible for
    committing.
    """
    await session.execute(
        update(Promocode)
        .where(and_(Promocode.id == promocode_id, Promocode.uses_count > 0))
        .values(uses_count=Promocode.uses_count - 1, updated_at=_now())
    )


# ---------- User discount wallet ----------


def saved_status(promo: Promocode, *, now: datetime | None = None) -> str:
    """Live status of a saved code: usable / expired / used / revoked.

    Precedence is revoked → expired → used → usable: a revoked code reads
    as revoked even if it also happens to be expired, because that's the
    reason the buyer can no longer redeem it.
    """
    now = now or _now()
    if not promo.is_active:
        return "revoked"
    if promo.expires_at is not None and promo.expires_at <= now:
        return "expired"
    if promo.uses_count >= promo.max_uses:
        return "used"
    return "usable"


async def save_promocode(
    session: AsyncSession, user: User, *, code: str
) -> tuple[SavedPromocode, Promocode]:
    """Bookmark a valid promocode into ``user``'s discount wallet.

    Validates the code the same way checkout does (minus the course match):
    it must exist, be active, unexpired, and have a remaining use. Saving a
    dead code would only mislead the buyer, so we reject it up front with a
    precise error code. Returns the wallet entry plus the resolved code.
    """
    normalized = _normalize_code(code)
    promo = (
        await session.execute(
            select(Promocode).where(Promocode.code == normalized)
        )
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promocode not found", code="promocode_not_found")
    if not promo.is_active:
        raise ValidationAppError(
            "Promocode has been revoked", code="promocode_inactive"
        )
    if promo.expires_at is not None and promo.expires_at <= _now():
        raise ValidationAppError(
            "Promocode has expired", code="promocode_expired"
        )
    if promo.uses_count >= promo.max_uses:
        raise ConflictError(
            "Promocode has already been used", code="promocode_exhausted"
        )

    saved = SavedPromocode(user_id=user.id, promocode_id=promo.id)
    session.add(saved)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "Promocode is already in your wallet",
            code="promocode_already_saved",
        ) from exc
    await session.refresh(saved)
    return saved, promo


async def list_saved_promocodes(
    session: AsyncSession, user: User, *, course_id: uuid.UUID | None = None
) -> list[tuple[SavedPromocode, Promocode, Course]]:
    """Return the user's wallet, newest first.

    When ``course_id`` is given the wallet is filtered to codes for that
    course — the "which of my saved discounts apply to what I'm buying"
    view the checkout screen renders.
    """
    stmt = (
        select(SavedPromocode, Promocode, Course)
        .join(Promocode, SavedPromocode.promocode_id == Promocode.id)
        .join(Course, Promocode.course_id == Course.id)
        .where(SavedPromocode.user_id == user.id)
        .order_by(SavedPromocode.created_at.desc())
    )
    if course_id is not None:
        stmt = stmt.where(Promocode.course_id == course_id)
    rows = (await session.execute(stmt)).all()
    return [(sp, promo, course) for sp, promo, course in rows]


async def delete_saved_promocode(
    session: AsyncSession, user: User, saved_id: uuid.UUID
) -> None:
    """Remove one entry from the user's wallet. Idempotent-ish: a missing
    or foreign entry raises 404 rather than silently no-op'ing."""
    saved = await session.get(SavedPromocode, saved_id)
    if saved is None or saved.user_id != user.id:
        raise NotFoundError("Saved promocode not found")
    await session.delete(saved)
    await session.commit()
