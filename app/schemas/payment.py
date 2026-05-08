from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    CardBrand,
    OrderItemKind,
    OrderStatus,
    PaymentProvider,
    TransactionState,
)
from app.schemas.base import ORMModel


# --- Payment methods (saved cards) ---


class PaymentMethodCreate(BaseModel):
    """Save a new card.

    The PAN never persists — we forward it to Payme ``cards.create``, store
    the returned token + last 4. After this call the verification flow is:
    ``POST /me/payment-methods/{id}/verify/start`` → ``.../verify/confirm``.
    """

    card_number: str = Field(..., min_length=12, max_length=23)
    expires_month: int = Field(..., ge=1, le=12)
    expires_year: int = Field(..., ge=2025, le=2099)
    cardholder_name: str | None = Field(default=None, max_length=120)
    set_default: bool = False

    @field_validator("card_number")
    @classmethod
    def _strip_spaces(cls, v: str) -> str:
        v = re.sub(r"\s+", "", v)
        if not v.isdigit():
            raise ValueError("card_number must be digits only (spaces allowed)")
        return v


class PaymentMethodVerifyStart(BaseModel):
    """No body — server kicks off Payme ``cards.get_verify_code``."""


class PaymentMethodVerifyConfirm(BaseModel):
    code: str = Field(..., min_length=3, max_length=12)


class PaymentMethodRead(ORMModel):
    id: uuid.UUID
    provider: PaymentProvider
    brand: CardBrand
    last4: str
    expires_month: int
    expires_year: int
    cardholder_name: str | None = None
    is_default: bool
    is_verified: bool
    created_at: datetime


# --- Orders ---


class OrderCreate(BaseModel):
    item_kind: OrderItemKind
    course_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None

    @field_validator("program_id")
    @classmethod
    def _exactly_one(cls, v, info):
        kind = info.data.get("item_kind")
        course = info.data.get("course_id")
        if kind == OrderItemKind.COURSE and (course is None or v is not None):
            raise ValueError("course_id required when item_kind=course")
        if kind == OrderItemKind.PROGRAM and (v is None or course is not None):
            raise ValueError("program_id required when item_kind=program")
        return v


class OrderRead(ORMModel):
    id: uuid.UUID
    item_kind: OrderItemKind
    course_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    amount_cents: int
    currency: str
    status: OrderStatus
    provider: PaymentProvider | None = None
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime


# --- Pay actions ---


class PayWithCard(BaseModel):
    payment_method_id: uuid.UUID


class PayWithPayme(BaseModel):
    """Returns a Payme checkout URL for the frontend to redirect to."""

    return_url: str | None = Field(
        default=None,
        description="Optional URL Payme redirects the user back to after payment.",
    )


class PayResponse(BaseModel):
    order_id: uuid.UUID
    status: OrderStatus
    # Set when the flow requires the frontend to redirect to a hosted page.
    checkout_url: str | None = None
    # Set on synchronous card-on-file payments.
    transaction_id: uuid.UUID | None = None


class TransactionRead(ORMModel):
    id: uuid.UUID
    order_id: uuid.UUID
    provider: PaymentProvider
    provider_txn_id: str
    state: TransactionState
    amount_cents: int
    perform_time: datetime | None = None
    cancel_time: datetime | None = None
    cancel_reason: int | None = None
    created_at: datetime


# --- Payme JSON-RPC merchant callback envelope ---
#
# We intentionally keep the request schema permissive (Any) — Payme's spec
# uses different ``params`` shapes per method and we dispatch on ``method``
# in the service. The response schema is fixed.


class PaymeRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class PaymeRpcError(BaseModel):
    code: int
    message: dict[str, str] | str


class PaymeRpcResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = None
    result: dict[str, Any] | None = None
    error: PaymeRpcError | None = None
