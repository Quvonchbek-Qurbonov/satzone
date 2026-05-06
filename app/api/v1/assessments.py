"""Student-facing assessment endpoints. Instructor authoring lives in
:mod:`app.api.v1.instructor`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.assessment import (
    AssessmentSubmissionCreate,
    AssessmentSubmissionRead,
    QuestionStudentRead,
)
from app.schemas.base import ORMModel
from app.services import assessment_service

router = APIRouter(prefix="/assessments", tags=["assessments"])


class AssessmentStudentRead(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    section_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    instructions: str | None = None
    time_limit_minutes: int | None = None
    pass_percent: int
    max_attempts: int | None = None
    questions: list[QuestionStudentRead]


@router.get("/{assessment_id}", response_model=AssessmentStudentRead)
async def get_assessment(
    assessment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AssessmentStudentRead:
    a = await assessment_service.get_assessment_for_student(session, user, assessment_id)
    return AssessmentStudentRead(
        id=a.id,
        course_id=a.course_id,
        section_id=a.section_id,
        title=a.title,
        description=a.description,
        instructions=a.instructions,
        time_limit_minutes=a.time_limit_minutes,
        pass_percent=a.pass_percent,
        max_attempts=a.max_attempts,
        questions=[QuestionStudentRead.model_validate(q) for q in a.questions],
    )


@router.post(
    "/{assessment_id}/submissions",
    response_model=AssessmentSubmissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_assessment(
    assessment_id: uuid.UUID,
    payload: AssessmentSubmissionCreate,
    user: CurrentUser,
    session: DbSession,
) -> AssessmentSubmissionRead:
    submission = await assessment_service.submit_assessment(
        session,
        user,
        assessment_id,
        [a.model_dump() for a in payload.answers],
    )
    return AssessmentSubmissionRead.model_validate(submission)


@router.get(
    "/{assessment_id}/submissions/me",
    response_model=list[AssessmentSubmissionRead],
)
async def list_my_submissions(
    assessment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[AssessmentSubmissionRead]:
    submissions = await assessment_service.list_my_submissions(
        session, user, assessment_id
    )
    return [AssessmentSubmissionRead.model_validate(s) for s in submissions]
