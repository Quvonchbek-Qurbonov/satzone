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
    SectionQuizStatus,
)
from app.schemas.base import ORMModel
from app.services import assessment_service

router = APIRouter(prefix="/assessments", tags=["assessments"])
section_quiz_router = APIRouter(prefix="/sections", tags=["assessments"])


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
    is_section_quiz: bool = False
    questions: list[QuestionStudentRead]


def _to_student_read(a) -> AssessmentStudentRead:
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
        is_section_quiz=a.is_section_quiz,
        questions=[QuestionStudentRead.model_validate(q) for q in a.questions],
    )


@router.get("/{assessment_id}", response_model=AssessmentStudentRead)
async def get_assessment(
    assessment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AssessmentStudentRead:
    a = await assessment_service.get_assessment_for_student(session, user, assessment_id)
    return _to_student_read(a)


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


# ---------- Section quiz (gating-aware shortcuts) ----------


@section_quiz_router.get(
    "/{section_id}/quiz",
    response_model=AssessmentStudentRead,
    summary="Get the section quiz",
    description=(
        "Returns the published end-of-section quiz the learner must pass to "
        "advance. 404 with ``section_quiz_not_found`` if the instructor "
        "hasn't published one for this section."
    ),
)
async def get_section_quiz(
    section_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AssessmentStudentRead:
    a = await assessment_service.get_section_quiz_for_student(
        session, user, section_id
    )
    return _to_student_read(a)


@section_quiz_router.get(
    "/{section_id}/quiz/status",
    response_model=SectionQuizStatus,
    summary="Section quiz pass/attempts status",
    description=(
        "Lightweight progress check. The UI calls this to decide whether to "
        "unlock the next section. ``required=false`` means no gating quiz "
        "exists for the section."
    ),
)
async def get_section_quiz_status(
    section_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> SectionQuizStatus:
    data = await assessment_service.get_section_quiz_status(
        session, user, section_id
    )
    return SectionQuizStatus.model_validate(data)
