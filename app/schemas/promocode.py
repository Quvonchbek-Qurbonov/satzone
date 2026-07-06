from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import PromocodeDiscountKind
from app.schemas.base import ORMModel

# Live status of a saved code, recomputed against the underlying promocode
# at read time (a code can expire / be revoked / be used up after saving).
SavedPromocodeStatus = Literal["usable", "expired", "used", "revoked"]

# Letters, digits, dashes and underscores. Codes are stored upper-case so
# matching is case-insensitive without needing a functional index.
_CODE_RE = re.compile(r"^[A-Z0-9_-]{4,40}$")


class PromocodeCreate(BaseModel):
    """Instructor creates a single-use promocode for one of their courses.

    ``code`` is auto-normalized to upper-case so users may enter it in any
    case. ``discount_value`` is the percent (1-100) when
    ``discount_kind="percent"`` or the amount in minor units (tiyin /
    cents) when ``discount_kind="fixed"``.
    """

    code: str = Field(..., min_length=4, max_length=40)
    discount_kind: PromocodeDiscountKind
    discount_value: int = Field(..., gt=0)
    expires_at: datetime | None = None

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _CODE_RE.match(v):
            raise ValueError(
                "code must be 4-40 chars, letters/digits/'-'/'_' only"
            )
        return v

    @model_validator(mode="after")
    def _discount_range(self) -> "PromocodeCreate":
        if self.discount_kind is PromocodeDiscountKind.PERCENT and not (1 <= self.discount_value <= 100):
            raise ValueError("percent discount must be between 1 and 100")
        return self


class PromocodeRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    code: str
    discount_kind: PromocodeDiscountKind
    discount_value: int
    max_uses: int
    uses_count: int
    expires_at: datetime | None = None
    is_active: bool
    created_at: datetime


class PromocodePreviewRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    course_id: uuid.UUID

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class PromocodePreviewResponse(BaseModel):
    """Server-side preview of how much a code shaves off a course price.

    Mirrors what ``POST /orders`` will charge — the frontend can render
    the discounted total before the user confirms checkout.
    """

    course_id: uuid.UUID
    code: str
    discount_kind: PromocodeDiscountKind
    discount_value: int
    original_amount_cents: int
    discount_cents: int
    final_amount_cents: int
    currency: str


# --- User discount wallet (profile "Discounts" section) ---


class SavePromocodeRequest(BaseModel):
    """Stash a promocode in the user's profile wallet by its code.

    Only the code is needed — the server resolves the course/instructor/
    discount from it. Saving does not reserve the code; that still happens
    at checkout.
    """

    code: str = Field(..., min_length=1, max_length=40)

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class SavedPromocodeRead(BaseModel):
    """One entry in the user's discount wallet.

    ``status`` is derived live from the underlying code so the UI can grey
    out a code that expired / was revoked / got used up after it was saved.
    ``is_valid`` is the convenience boolean (``status == "usable"``).
    """

    id: uuid.UUID  # saved-promocode (wallet entry) id
    promocode_id: uuid.UUID
    code: str
    course_id: uuid.UUID
    course_title: str | None = None
    course_slug: str | None = None
    discount_kind: PromocodeDiscountKind
    discount_value: int
    expires_at: datetime | None = None
    status: SavedPromocodeStatus
    is_valid: bool
    saved_at: datetime


class SavedPromocodeApplicable(SavedPromocodeRead):
    """A wallet entry filtered to one course, enriched with the price math.

    Returned by ``GET /me/promocodes?course_id=…`` so the buy screen can
    show each saved code alongside exactly what the buyer would pay. The
    discount fields are populated only when ``is_valid`` — an unusable code
    leaves them ``None``.
    """

    original_amount_cents: int
    discount_cents: int | None = None
    final_amount_cents: int | None = None
    currency: str
