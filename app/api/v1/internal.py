from __future__ import annotations

import hmac
import re
import uuid

from fastapi import APIRouter, Header, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.db.deps import DbSession
from app.models.user import User
from app.schemas.base import ORMModel

router = APIRouter(prefix="/internal", tags=["internal"])

_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def _normalize(value: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not _PHONE_RE.match(cleaned):
        raise ValueError("phone_number must be E.164")
    return cleaned if cleaned.startswith("+") else "+" + cleaned


class PhoneLookupRequest(BaseModel):
    phone_number: str = Field(min_length=4, max_length=32)

    @field_validator("phone_number")
    @classmethod
    def _v(cls, v: str) -> str:
        return _normalize(v)


class PhoneLookupResponse(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_phone_verified: bool


def _require_api_key(provided: str | None) -> None:
    expected = getattr(settings, "INTERNAL_API_KEY", "")
    if not expected:
        raise UnauthorizedError(
            "Internal API not configured", code="internal_not_configured"
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise UnauthorizedError("Invalid internal API key", code="invalid_api_key")


@router.post(
    "/users/lookup-by-phone",
    response_model=PhoneLookupResponse,
    status_code=status.HTTP_200_OK,
)
async def lookup_user_by_phone(
    payload: PhoneLookupRequest,
    session: DbSession,
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-API-Key"),
) -> PhoneLookupResponse:
    _require_api_key(x_internal_api_key)
    stmt = select(User).where(User.phone_number == payload.phone_number)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    return PhoneLookupResponse.model_validate(user)
