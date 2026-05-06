from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser
from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.schemas.enrollment import (
    CertificateRead,
    EnrollmentRead,
    EnrollRequest,
    LessonProgressRead,
    LessonProgressUpdate,
)
from app.services import enrollment_service

router = APIRouter(prefix="/me/enrollments", tags=["my-learnings"])
certificate_router = APIRouter(prefix="/me/certificates", tags=["my-learnings"])


@router.post("", response_model=EnrollmentRead, status_code=status.HTTP_201_CREATED)
async def enroll(payload: EnrollRequest, user: CurrentUser, session: DbSession) -> EnrollmentRead:
    enrollment = await enrollment_service.enroll(session, user, payload.course_id)
    return EnrollmentRead.model_validate(enrollment)


@router.get("", response_model=Page[EnrollmentRead])
async def list_my_enrollments(
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[Literal["all", "active", "completed"], Query(alias="status")] = "all",
) -> Page[EnrollmentRead]:
    items, total = await enrollment_service.list_my_enrollments(
        session, user, pagination, status=status_filter
    )
    return to_page([EnrollmentRead.model_validate(e) for e in items], total, pagination)


@router.get("/{enrollment_id}", response_model=EnrollmentRead)
async def get_my_enrollment(
    enrollment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> EnrollmentRead:
    enrollment = await enrollment_service.get_enrollment_for_user(session, user, enrollment_id)
    return EnrollmentRead.model_validate(enrollment)


@router.put("/{enrollment_id}/lessons/{lesson_id}/progress", response_model=LessonProgressRead)
async def update_progress(
    enrollment_id: uuid.UUID,
    lesson_id: uuid.UUID,
    payload: LessonProgressUpdate,
    user: CurrentUser,
    session: DbSession,
) -> LessonProgressRead:
    progress = await enrollment_service.update_lesson_progress(
        session,
        user,
        enrollment_id,
        lesson_id,
        last_position_seconds=payload.last_position_seconds,
        watched_seconds=payload.watched_seconds,
        completed=payload.completed,
    )
    return LessonProgressRead.model_validate(progress)


@certificate_router.get("", response_model=list[CertificateRead])
async def list_my_certificates(user: CurrentUser, session: DbSession) -> list[CertificateRead]:
    certs = await enrollment_service.list_certificates(session, user)
    return [CertificateRead.model_validate(c) for c in certs]


@certificate_router.get("/courses/{course_id}", response_model=CertificateRead)
async def get_course_certificate(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> CertificateRead:
    cert = await enrollment_service.get_certificate_for_course(session, user, course_id)
    return CertificateRead.model_validate(cert)
