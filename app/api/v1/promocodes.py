"""User-facing promocode preview.

Returns the discounted total a buyer would pay for ``course_id`` using
``code``, without reserving the code. The actual reservation happens at
order creation (``POST /orders`` with ``promocode``).
"""
from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.core.exceptions import ValidationAppError
from app.schemas.promocode import PromocodePreviewRequest, PromocodePreviewResponse
from app.services import promocode_service
from app.services.payment_service import get_published_course

router = APIRouter(prefix="/promocodes", tags=["promocodes"])


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
