"""Payments + Payme integration.

Three router groups in one file:

- ``/me/payment-methods`` — user-owned saved cards (Payments & Billing screen).
- ``/orders`` — purchase intents for a course or program; user-facing pay
  endpoints (card-on-file or Payme hosted checkout).
- ``/payments/payme/callback`` — Payme Merchant API JSON-RPC endpoint, called
  *by* Payme; auth via HTTP Basic ``Paycom:<merchant_key>``.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Header, Request, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.base import Message
from app.schemas.payment import (
    OrderCreate,
    OrderRead,
    PayResponse,
    PaymentMethodCreate,
    PaymentMethodRead,
    PaymentMethodVerifyConfirm,
    PayWithCard,
    PayWithPayme,
    TransactionRead,
)
from app.services import payment_service

methods_router = APIRouter(prefix="/me/payment-methods", tags=["payments"])
orders_router = APIRouter(prefix="/orders", tags=["payments"])
me_orders_router = APIRouter(prefix="/me/orders", tags=["payments"])
payme_router = APIRouter(prefix="/payments/payme", tags=["payments"])


# ---------- Saved cards ----------


@methods_router.get("", response_model=list[PaymentMethodRead])
async def list_methods(user: CurrentUser, session: DbSession) -> list[PaymentMethodRead]:
    rows = await payment_service.list_payment_methods(session, user)
    return [PaymentMethodRead.model_validate(r) for r in rows]


@methods_router.post("", response_model=PaymentMethodRead, status_code=status.HTTP_201_CREATED)
async def create_method(
    payload: PaymentMethodCreate, user: CurrentUser, session: DbSession
) -> PaymentMethodRead:
    pm = await payment_service.create_payment_method(
        session,
        user,
        card_number=payload.card_number,
        expires_month=payload.expires_month,
        expires_year=payload.expires_year,
        cardholder_name=payload.cardholder_name,
        set_default=payload.set_default,
    )
    return PaymentMethodRead.model_validate(pm)


@methods_router.post("/{pm_id}/verify/start", response_model=Message)
async def start_verify(pm_id: uuid.UUID, user: CurrentUser, session: DbSession) -> Message:
    await payment_service.start_card_verification(session, user, pm_id)
    return Message(message="Verification code sent")


@methods_router.post("/{pm_id}/verify/confirm", response_model=PaymentMethodRead)
async def confirm_verify(
    pm_id: uuid.UUID,
    payload: PaymentMethodVerifyConfirm,
    user: CurrentUser,
    session: DbSession,
) -> PaymentMethodRead:
    pm = await payment_service.confirm_card_verification(session, user, pm_id, payload.code)
    return PaymentMethodRead.model_validate(pm)


@methods_router.delete("/{pm_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_method(pm_id: uuid.UUID, user: CurrentUser, session: DbSession) -> None:
    await payment_service.delete_payment_method(session, user, pm_id)


# ---------- Orders ----------


@orders_router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate, user: CurrentUser, session: DbSession
) -> OrderRead:
    order = await payment_service.create_order(
        session,
        user,
        item_kind=payload.item_kind,
        course_id=payload.course_id,
        program_id=payload.program_id,
        promocode=payload.promocode,
    )
    return OrderRead.model_validate(order)


@orders_router.get("/{order_id}", response_model=OrderRead)
async def get_order(
    order_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> OrderRead:
    order = await payment_service.get_order(session, user, order_id)
    return OrderRead.model_validate(order)


@orders_router.delete("/{order_id}", response_model=OrderRead)
async def cancel_order(
    order_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> OrderRead:
    order = await payment_service.cancel_order(session, user, order_id)
    return OrderRead.model_validate(order)


@orders_router.post("/{order_id}/pay/card", response_model=PayResponse)
async def pay_card(
    order_id: uuid.UUID,
    payload: PayWithCard,
    user: CurrentUser,
    session: DbSession,
) -> PayResponse:
    order, txn = await payment_service.pay_with_card(
        session, user, order_id, payload.payment_method_id
    )
    return PayResponse(order_id=order.id, status=order.status, transaction_id=txn.id)


@orders_router.post("/{order_id}/pay/payme", response_model=PayResponse)
async def pay_payme(
    order_id: uuid.UUID,
    payload: PayWithPayme,
    user: CurrentUser,
    session: DbSession,
) -> PayResponse:
    order, url = await payment_service.pay_with_payme(
        session, user, order_id, payload.return_url
    )
    return PayResponse(order_id=order.id, status=order.status, checkout_url=url)


@me_orders_router.get("", response_model=list[OrderRead])
async def list_my_orders(user: CurrentUser, session: DbSession) -> list[OrderRead]:
    rows = await payment_service.list_orders(session, user)
    return [OrderRead.model_validate(r) for r in rows]


# ---------- Payme merchant JSON-RPC callback ----------


@payme_router.post("/callback")
async def payme_callback(
    request: Request,
    session: DbSession,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    body: dict[str, Any] = await request.json()
    return await payment_service.handle_merchant_rpc(session, authorization, body)
