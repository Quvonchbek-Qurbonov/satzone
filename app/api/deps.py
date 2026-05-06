from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.deps import DbSession
from app.models.enums import UserRole
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Authentication required", code="missing_token")
    payload = decode_access_token(credentials.credentials)
    sub = payload.get("sub")
    try:
        user_id = uuid.UUID(sub)
    except (TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid token subject", code="invalid_token") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or disabled", code="invalid_user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_verified_user(user: CurrentUser) -> User:
    if not user.is_verified:
        raise ForbiddenError("Email verification required", code="email_not_verified")
    return user


VerifiedUser = Annotated[User, Depends(get_verified_user)]


async def get_admin_user(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Admin role required")
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]