from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser
from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.schemas.program import ProgramDetail, ProgramEnrollmentRead, ProgramSummary
from app.services import program_service

router = APIRouter(prefix="/programs", tags=["programs"])
me_router = APIRouter(prefix="/me/programs", tags=["my-learnings"])


@router.get("", response_model=Page[ProgramSummary])
async def list_programs(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[ProgramSummary]:
    items, total = await program_service.list_programs(session, pagination)
    return to_page([ProgramSummary.model_validate(p) for p in items], total, pagination)


@router.get("/{slug}", response_model=ProgramDetail)
async def program_detail(slug: str, session: DbSession) -> ProgramDetail:
    program = await program_service.get_program_by_slug(session, slug)
    return ProgramDetail.model_validate(program)


@router.post(
    "/{program_id}/enroll",
    response_model=ProgramEnrollmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_in_program(
    program_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> ProgramEnrollmentRead:
    enrollment = await program_service.enroll_in_program(session, user, program_id)
    return ProgramEnrollmentRead.model_validate(enrollment)


@me_router.get("", response_model=Page[ProgramEnrollmentRead])
async def my_programs(
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[ProgramEnrollmentRead]:
    items, total = await program_service.list_my_program_enrollments(session, user, pagination)
    return to_page([ProgramEnrollmentRead.model_validate(p) for p in items], total, pagination)
