"""Service layer for assessments — instructor-side authoring and student-side
attempts. Authoring helpers re-validate ownership through the course.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.core.pagination import PageParams, paginate
from app.models.assessment import (
    Assessment,
    AssessmentSubmission,
    Question,
    QuestionOption,
    SubmissionAnswer,
)
from app.models.catalog import Instructor
from app.models.course import Course, CourseSection
from app.models.enrollment import Enrollment
from app.models.enums import AssessmentStatus, PublishStatus, QuestionType
from app.models.user import User


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------- Ownership helpers ----------


async def _get_owned_course(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found")
    if course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this course")
    return course


async def get_owned_assessment(
    session: AsyncSession, instructor: Instructor, assessment_id: uuid.UUID
) -> Assessment:
    stmt = (
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(
            selectinload(Assessment.questions).selectinload(Question.options),
            selectinload(Assessment.course),
        )
    )
    assessment = (await session.execute(stmt)).scalar_one_or_none()
    if assessment is None:
        raise NotFoundError("Assessment not found")
    if assessment.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this assessment")
    return assessment


async def _reload_assessment(
    session: AsyncSession, assessment_id: uuid.UUID
) -> Assessment:
    stmt = (
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(
            selectinload(Assessment.questions).selectinload(Question.options),
        )
    )
    return (await session.execute(stmt)).scalar_one()


async def _reload_question(
    session: AsyncSession, question_id: uuid.UUID
) -> Question:
    stmt = (
        select(Question)
        .where(Question.id == question_id)
        .options(selectinload(Question.options))
    )
    return (await session.execute(stmt)).scalar_one()


async def _get_owned_question(
    session: AsyncSession, instructor: Instructor, question_id: uuid.UUID
) -> Question:
    stmt = (
        select(Question)
        .where(Question.id == question_id)
        .options(
            selectinload(Question.options),
            selectinload(Question.assessment).selectinload(Assessment.course),
        )
    )
    question = (await session.execute(stmt)).scalar_one_or_none()
    if question is None:
        raise NotFoundError("Question not found")
    if question.assessment.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this question")
    return question


# ---------- Authoring ----------


async def list_assessments(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    page_params: PageParams,
) -> tuple[list[Assessment], int]:
    course = await _get_owned_course(session, instructor, course_id)
    stmt: Select = (
        select(Assessment)
        .where(Assessment.course_id == course.id)
        .options(selectinload(Assessment.questions))
        .order_by(Assessment.created_at.desc())
    )
    return await paginate(session, stmt, page_params)


async def create_assessment(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    data: dict,
) -> Assessment:
    course = await _get_owned_course(session, instructor, course_id)
    section_id = data.get("section_id")
    if section_id is not None:
        section = await session.get(CourseSection, section_id)
        if section is None or section.course_id != course.id:
            raise ValidationAppError("Section does not belong to this course")
    assessment = Assessment(
        course_id=course.id,
        section_id=section_id,
        title=data["title"],
        description=data.get("description"),
        instructions=data.get("instructions"),
        time_limit_minutes=data.get("time_limit_minutes"),
        pass_percent=data.get("pass_percent", 70),
        max_attempts=data.get("max_attempts"),
        shuffle_questions=data.get("shuffle_questions", False),
        show_correct_answers=data.get("show_correct_answers", True),
        status=AssessmentStatus.DRAFT,
    )
    session.add(assessment)
    await session.commit()
    return await _reload_assessment(session, assessment.id)


async def update_assessment(
    session: AsyncSession,
    instructor: Instructor,
    assessment_id: uuid.UUID,
    data: dict,
) -> Assessment:
    assessment = await get_owned_assessment(session, instructor, assessment_id)
    if "section_id" in data and data["section_id"] is not None:
        section = await session.get(CourseSection, data["section_id"])
        if section is None or section.course_id != assessment.course_id:
            raise ValidationAppError("Section does not belong to this course")
    for k, v in data.items():
        setattr(assessment, k, v)
    await session.commit()
    return await _reload_assessment(session, assessment.id)


async def delete_assessment(
    session: AsyncSession, instructor: Instructor, assessment_id: uuid.UUID
) -> None:
    assessment = await get_owned_assessment(session, instructor, assessment_id)
    await session.delete(assessment)
    await session.commit()


async def add_question(
    session: AsyncSession,
    instructor: Instructor,
    assessment_id: uuid.UUID,
    data: dict,
) -> Question:
    assessment = await get_owned_assessment(session, instructor, assessment_id)
    order = data.get("order")
    if order is None:
        order = int(
            (
                await session.execute(
                    select(func.coalesce(func.max(Question.order), -1) + 1).where(
                        Question.assessment_id == assessment.id
                    )
                )
            ).scalar_one()
        )

    question = Question(
        assessment_id=assessment.id,
        type=data["type"],
        prompt=data["prompt"],
        explanation=data.get("explanation"),
        points=data.get("points", 1),
        order=order,
        expected_answers=[a.lower() for a in (data.get("expected_answers") or [])] or None,
    )
    session.add(question)
    await session.flush()

    options = data.get("options") or []
    for idx, opt in enumerate(options):
        session.add(
            QuestionOption(
                question_id=question.id,
                text=opt["text"],
                is_correct=bool(opt.get("is_correct", False)),
                order=opt.get("order") if opt.get("order") is not None else idx,
            )
        )
    await session.commit()
    return await _reload_question(session, question.id)


async def update_question(
    session: AsyncSession,
    instructor: Instructor,
    question_id: uuid.UUID,
    data: dict,
) -> Question:
    question = await _get_owned_question(session, instructor, question_id)
    if "prompt" in data and data["prompt"] is not None:
        question.prompt = data["prompt"]
    if "explanation" in data:
        question.explanation = data["explanation"]
    if "points" in data and data["points"] is not None:
        question.points = data["points"]
    if "order" in data and data["order"] is not None:
        question.order = data["order"]
    if "expected_answers" in data and data["expected_answers"] is not None:
        question.expected_answers = [a.lower() for a in data["expected_answers"]]

    if "options" in data and data["options"] is not None:
        # Replace options wholesale.
        for o in list(question.options):
            await session.delete(o)
        await session.flush()
        for idx, opt in enumerate(data["options"]):
            session.add(
                QuestionOption(
                    question_id=question.id,
                    text=opt["text"],
                    is_correct=bool(opt.get("is_correct", False)),
                    order=opt.get("order") if opt.get("order") is not None else idx,
                )
            )
    await session.commit()
    return await _reload_question(session, question.id)


async def delete_question(
    session: AsyncSession, instructor: Instructor, question_id: uuid.UUID
) -> None:
    question = await _get_owned_question(session, instructor, question_id)
    await session.delete(question)
    await session.commit()


# ---------- Student side ----------


async def get_assessment_for_student(
    session: AsyncSession, user: User, assessment_id: uuid.UUID
) -> Assessment:
    stmt = (
        select(Assessment)
        .where(
            Assessment.id == assessment_id,
            Assessment.status == AssessmentStatus.PUBLISHED,
        )
        .options(
            selectinload(Assessment.questions).selectinload(Question.options),
        )
    )
    assessment = (await session.execute(stmt)).scalar_one_or_none()
    if assessment is None:
        raise NotFoundError("Assessment not found")
    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id,
                Enrollment.course_id == assessment.course_id,
            )
        )
    ).first()
    if enrolled is None:
        raise ForbiddenError("Enroll in the course to take this assessment")
    return assessment


async def submit_assessment(
    session: AsyncSession,
    user: User,
    assessment_id: uuid.UUID,
    answers: list[dict],
) -> AssessmentSubmission:
    assessment = await get_assessment_for_student(session, user, assessment_id)

    prior_count = (
        await session.execute(
            select(func.count(AssessmentSubmission.id)).where(
                AssessmentSubmission.assessment_id == assessment.id,
                AssessmentSubmission.user_id == user.id,
            )
        )
    ).scalar_one()
    if assessment.max_attempts is not None and prior_count >= assessment.max_attempts:
        raise ConflictError(
            "Maximum attempts reached for this assessment",
            code="max_attempts_reached",
        )

    submission = AssessmentSubmission(
        assessment_id=assessment.id,
        user_id=user.id,
        attempt_number=int(prior_count) + 1,
        started_at=_now(),
        submitted_at=_now(),
    )
    session.add(submission)
    await session.flush()

    questions_by_id = {q.id: q for q in assessment.questions}
    total_points = sum(q.points for q in assessment.questions) or 1
    awarded_total = 0

    for ans in answers:
        qid = ans["question_id"]
        question = questions_by_id.get(qid)
        if question is None:
            raise ValidationAppError(f"Question {qid} not in assessment")

        is_correct, awarded = _grade_answer(question, ans)
        awarded_total += awarded
        session.add(
            SubmissionAnswer(
                submission_id=submission.id,
                question_id=qid,
                response={
                    "selected_option_ids": [str(o) for o in (ans.get("selected_option_ids") or [])],
                    "text": ans.get("text"),
                },
                is_correct=is_correct,
                awarded_points=awarded,
            )
        )

    score_percent = int(round((awarded_total / total_points) * 100))
    submission.score_percent = score_percent
    submission.passed = score_percent >= assessment.pass_percent

    await session.commit()
    await session.refresh(submission, attribute_names=["answers"])
    return submission


def _grade_answer(question: Question, ans: dict) -> tuple[bool, int]:
    if question.type in (QuestionType.SINGLE_CHOICE, QuestionType.MULTI_CHOICE, QuestionType.TRUE_FALSE):
        selected = set(ans.get("selected_option_ids") or [])
        correct_ids = {o.id for o in question.options if o.is_correct}
        chosen_ids = {uuid.UUID(str(s)) for s in selected}
        is_correct = chosen_ids == correct_ids and len(correct_ids) > 0
        return is_correct, question.points if is_correct else 0
    if question.type == QuestionType.SHORT_ANSWER:
        text = (ans.get("text") or "").strip().lower()
        expected = [e.lower() for e in (question.expected_answers or [])]
        is_correct = bool(text) and text in expected
        return is_correct, question.points if is_correct else 0
    return False, 0


async def list_my_submissions(
    session: AsyncSession,
    user: User,
    assessment_id: uuid.UUID,
) -> list[AssessmentSubmission]:
    stmt = (
        select(AssessmentSubmission)
        .where(
            AssessmentSubmission.assessment_id == assessment_id,
            AssessmentSubmission.user_id == user.id,
        )
        .options(selectinload(AssessmentSubmission.answers))
        .order_by(AssessmentSubmission.attempt_number.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def list_assessment_submissions_for_instructor(
    session: AsyncSession,
    instructor: Instructor,
    assessment_id: uuid.UUID,
    page_params: PageParams,
) -> tuple[list[AssessmentSubmission], int]:
    await get_owned_assessment(session, instructor, assessment_id)
    stmt = (
        select(AssessmentSubmission)
        .where(AssessmentSubmission.assessment_id == assessment_id)
        .options(
            selectinload(AssessmentSubmission.user),
            selectinload(AssessmentSubmission.answers),
        )
        .order_by(AssessmentSubmission.submitted_at.desc().nulls_last())
    )
    return await paginate(session, stmt, page_params)
