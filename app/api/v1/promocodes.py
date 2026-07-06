"""User-facing promocode surfaces.

Two groups:

- ``/promocodes/preview`` — discounted total a buyer would pay for
  ``course_id`` using ``code``, without reserving it. The reservation
  happens at order creation (``POST /orders`` with ``promocode``).
- ``/me/promocodes`` — the profile "Discounts" wallet: save a code, list
  the wallet (optionally filtered to a course, with the price math), and
  drop a code. Saving is a bookmark, not a reservation.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.core.exceptions import ValidationAppError
from app.models.course import Course
from app.schemas.promocode import (
    PromocodePreviewRequest,
    PromocodePreviewResponse,
    SavedPromocodeApplicable,
    SavedPromocodeRead,
    SavePromocodeRequest,
)
from app.services import promocode_service
from app.services.payment_service import get_published_course

router = APIRouter(prefix="/promocodes", tags=["promocodes"])
me_router = APIRouter(prefix="/me/promocodes", tags=["promocodes"])


@router.post(
    "/preview",
    response_model=PromocodePreviewResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_promocode(
    payload: PromocodePreviewRequest,
    _: CurrentUser,
    session: DbSession,
) -> PromocodePreviewResponse:
    course = await get_published_course(session, payload.course_id)
    original_amount = course.effective_price_cents
    if original_amount == 0:
        raise ValidationAppError(
            "Course is free; promocodes do not apply",
            code="course_is_free",
        )
    promo = await promocode_service.find_active_promocode_for_course(
        session, code=payload.code, course_id=payload.course_id
    )
    discount = promocode_service.compute_discount_cents(
        kind=promo.discount_kind,
        value=promo.discount_value,
        base_amount_cents=original_amount,
    )
    final = original_amount - discount
    if final <= 0:
        raise ValidationAppError(
            "Promocode would make the order free; use free enrollment instead",
            code="promocode_makes_free",
        )
    return PromocodePreviewResponse(
        course_id=course.id,
        code=promo.code,
        discount_kind=promo.discount_kind,
        discount_value=promo.discount_value,
        original_amount_cents=original_amount,
        discount_cents=discount,
        final_amount_cents=final,
        currency=course.currency,
    )


# ---------- Discount wallet (profile "Discounts" section) ----------


def _to_read(sp, promo, course) -> SavedPromocodeRead:
    return SavedPromocodeRead(
        id=sp.id,
        promocode_id=promo.id,
        code=promo.code,
        course_id=course.id,
        course_title=course.title,
        course_slug=course.slug,
        discount_kind=promo.discount_kind,
        discount_value=promo.discount_value,
        expires_at=promo.expires_at,
        status=promocode_service.saved_status(promo),
        is_valid=promocode_service.saved_status(promo) == "usable",
        saved_at=sp.created_at,
    )


def _to_applicable(sp, promo, course) -> SavedPromocodeApplicable:
    base = course.effective_price_cents
    is_valid = promocode_service.saved_status(promo) == "usable"
    discount = final = None
    if is_valid and base > 0:
        discount = promocode_service.compute_discount_cents(
            kind=promo.discount_kind,
            value=promo.discount_value,
            base_amount_cents=base,
        )
        final = base - discount
    return SavedPromocodeApplicable(
        **_to_read(sp, promo, course).model_dump(),
        original_amount_cents=base,
        discount_cents=discount,
        final_amount_cents=final,
        currency=course.currency,
    )


@me_router.get("", response_model=list[SavedPromocodeRead])
async def list_wallet(
    user: CurrentUser,
    session: DbSession,
    course_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[SavedPromocodeRead]:
    """List the user's saved promocodes.

    Without ``course_id`` this is the full wallet (profile screen). With
    ``course_id`` it returns only the codes that apply to that course,
    each enriched with the price math (buy screen) — the response items
    are then :class:`SavedPromocodeApplicable`.
    """
    rows = await promocode_service.list_saved_promocodes(
        session, user, course_id=course_id
    )
    if course_id is not None:
        return [_to_applicable(sp, promo, course) for sp, promo, course in rows]
    return [_to_read(sp, promo, course) for sp, promo, course in rows]


@me_router.post("", response_model=SavedPromocodeRead, status_code=status.HTTP_201_CREATED)
async def save_to_wallet(
    payload: SavePromocodeRequest, user: CurrentUser, session: DbSession
) -> SavedPromocodeRead:
    saved, promo = await promocode_service.save_promocode(
        session, user, code=payload.code
    )
    course = await session.get(Course, promo.course_id)
    return _to_read(saved, promo, course)


@me_router.delete("/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_from_wallet(
    saved_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await promocode_service.delete_saved_promocode(session, user, saved_id)
