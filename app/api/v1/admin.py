from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter
from pydantic import EmailStr, Field, model_validator
from sqlalchemy import select

from app.api.deps import AdminUser
from app.core.exceptions import NotFoundError, ValidationAppError
from app.db.deps import DbSession
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.base import ORMModel
from app.schemas.user import UserMe

router = APIRouter(prefix="/admin", tags=["admin"])


class PromoteInstructorRequest(ORMModel):
    user_id: uuid.UUID | None = None
    email: EmailStr | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _exactly_one(self) -> "PromoteInstructorRequest":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of user_id or email")
        return self


@router.post("/users/promote-instructor", response_model=UserMe)
async def promote_user_to_instructor(
    payload: PromoteInstructorRequest,
    _admin: AdminUser,
    session: DbSession,
) -> UserMe:
    if payload.user_id is not None:
        user = await session.get(User, payload.user_id)
    else:
        user = (
            await session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()

    if user is None:
        raise NotFoundError("User not found", code="user_not_found")
    if not user.is_active:
        raise ValidationAppError("Cannot promote a disabled user", code="user_disabled")

    if user.role == UserRole.ADMIN:
        return UserMe.model_validate(user)
    if user.role != UserRole.INSTRUCTOR:
        user.role = UserRole.INSTRUCTOR
        await session.commit()
        await session.refresh(user)

    return UserMe.model_validate(user)
