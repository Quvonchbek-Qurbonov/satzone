from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.schemas.instructor import InstructorRead, InstructorSummary
from app.services import course_service

router = APIRouter(prefix="/instructors", tags=["instructors"])


@router.get("", response_model=Page[InstructorSummary])
async def list_instructors(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[InstructorSummary]:
    items, total = await course_service.list_instructors(session, pagination, search)
    return to_page([InstructorSummary.model_validate(i) for i in items], total, pagination)


@router.get("/{slug}", response_model=InstructorRead)
async def get_instructor(slug: str, session: DbSession) -> InstructorRead:
    instructor = await course_service.get_instructor_by_slug(session, slug)
    return InstructorRead.model_validate(instructor)
