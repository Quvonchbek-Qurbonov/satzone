from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser
from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.schemas.enrollment import WishlistItemRead
from app.services import enrollment_service

router = APIRouter(prefix="/me/wishlist", tags=["my-learnings"])


@router.get("", response_model=Page[WishlistItemRead])
async def list_my_wishlist(
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[WishlistItemRead]:
    items, total = await enrollment_service.list_wishlist(session, user, pagination)
    return to_page([WishlistItemRead.model_validate(i) for i in items], total, pagination)


@router.post("/{course_id}", status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> dict[str, str]:
    await enrollment_service.add_wishlist(session, user, course_id)
    return {"message": "Added"}


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await enrollment_service.remove_wishlist(session, user, course_id)
