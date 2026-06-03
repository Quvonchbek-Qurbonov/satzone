"""Standalone practice quizzes (Duolingo-style drills).

Two routers live here:

* ``student_router`` — read + attempt endpoints under ``/courses`` and
  ``/practice``, gated by enrollment. The pack is only visible when the parent
  course is published; individual quizzes additionally require
  ``is_published=True``.
* ``instructor_router`` — authoring endpoints under ``/instructor/...``. Every
  write re-validates that the caller's instructor profile owns the parent
  course, mirroring the assessments-authoring pattern.

This feature is intentionally separate from the ``assessments`` API: no
pass/fail, no time limit, no attempt cap, no lesson gating.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.deps import DbSession
from app.models.enums import UserRole
from app.schemas.practice import (
    PracticeAttemptCreate,
    PracticeAttemptResult,
    PracticeItemInstructorRead,
    PracticeItemWrite,
    PracticePackInstructorRead,
    PracticePackStudentRead,
    PracticePackUpdate,
    PracticeQuizCreate,
    PracticeQuizInstructorRead,
    PracticeQuizStudentRead,
    PracticeQuizStudentSummary,
    PracticeQuizSummary,
    PracticeQuizUpdate,
)
from app.services import instructor_service, practice_service

student_router = APIRouter(tags=["practice"])
instructor_router = APIRouter(prefix="/instructor", tags=["practice"])


async def _require_instructor_role(user: CurrentUser) -> None:
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise ForbiddenError(
            "Instructor role required", code="instructor_role_required"
        )


def _quiz_summary(quiz, item_count: int) -> PracticeQuizSummary:
    return PracticeQuizSummary(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        order=quiz.order,
        is_published=quiz.is_published,
        item_count=item_count,
    )


# ---------- Student ----------


@student_router.get(
    "/courses/{course_id}/practice",
    response_model=PracticePackStudentRead | None,
    summary="Get a course's practice pack with my progress",
    description=(
        "Returns the published practice pack for an enrolled course along with "
        "the caller's progress on every published quiz. Returns ``null`` when "
        "the course has no pack yet."
    ),
)
async def get_course_practice(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> PracticePackStudentRead | None:
    pack, progress_map = await practice_service.get_pack_for_student(
        session, user, course_id
    )
    if pack is None:
        return None
    quiz_summaries = []
    for quiz in pack.quizzes:
        if not quiz.is_published:
            continue
        summary = PracticeQuizStudentSummary(
            id=quiz.id,
            title=quiz.title,
            description=quiz.description,
            order=quiz.order,
            is_published=quiz.is_published,
            item_count=len(quiz.items),
        )
        prog = progress_map.get(quiz.id)
        if prog is not None:
            summary.progress = prog
        quiz_summaries.append(summary)
    quiz_summaries.sort(key=lambda q: q.order)
    return PracticePackStudentRead(
        id=pack.id,
        course_id=pack.course_id,
        title=pack.title,
        description=pack.description,
        quizzes=quiz_summaries,
    )


@student_router.get(
    "/practice/quizzes/{quiz_id}",
    response_model=PracticeQuizStudentRead,
    summary="Get a practice quiz with shuffled items",
    description=(
        "Returns the published quiz with its items in the canonical order. "
        "Matching items have ``lefts`` and ``rights`` shuffled server-side so "
        "the order of options doesn't leak the answer."
    ),
)
async def get_practice_quiz(
    quiz_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> PracticeQuizStudentRead:
    quiz, progress = await practice_service.get_quiz_for_student(
        session, user, quiz_id
    )
    items = [practice_service.sanitize_item_for_student(it) for it in quiz.items]
    return PracticeQuizStudentRead(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        order=quiz.order,
        is_published=quiz.is_published,
        item_count=len(items),
        progress=progress,
        items=items,
    )


@student_router.post(
    "/practice/quizzes/{quiz_id}/attempts",
    response_model=PracticeAttemptResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit answers for a practice quiz",
    description=(
        "Grades a single attempt and returns the per-item result list along "
        "with the aggregate score. Unlimited attempts; the best score across "
        "attempts is what shows in progress views."
    ),
)
async def submit_practice_attempt(
    quiz_id: uuid.UUID,
    payload: PracticeAttemptCreate,
    user: CurrentUser,
    session: DbSession,
) -> PracticeAttemptResult:
    attempt, results = await practice_service.submit_attempt(
        session, user, quiz_id, payload
    )
    return PracticeAttemptResult(
        id=attempt.id,
        quiz_id=attempt.quiz_id,
        score_percent=attempt.score_percent,
        correct_count=attempt.correct_count,
        total_count=attempt.total_count,
        completed_at=attempt.completed_at,
        results=results,
    )


# ---------- Instructor ----------


@instructor_router.get(
    "/courses/{course_id}/practice",
    response_model=PracticePackInstructorRead,
    summary="Get the practice pack for a course I own",
)
async def get_my_practice_pack(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> PracticePackInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    pack = await practice_service.get_or_create_pack(session, inst, course_id)
    summaries = sorted(
        (_quiz_summary(q, len(q.items)) for q in pack.quizzes),
        key=lambda q: q.order,
    )
    return PracticePackInstructorRead(
        id=pack.id,
        course_id=pack.course_id,
        title=pack.title,
        description=pack.description,
        quizzes=summaries,
    )


@instructor_router.patch(
    "/courses/{course_id}/practice",
    response_model=PracticePackInstructorRead,
    summary="Update pack title / description",
)
async def update_my_practice_pack(
    course_id: uuid.UUID,
    payload: PracticePackUpdate,
    user: CurrentUser,
    session: DbSession,
) -> PracticePackInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    pack = await practice_service.update_pack(session, inst, course_id, payload)
    summaries = sorted(
        (_quiz_summary(q, len(q.items)) for q in pack.quizzes),
        key=lambda q: q.order,
    )
    return PracticePackInstructorRead(
        id=pack.id,
        course_id=pack.course_id,
        title=pack.title,
        description=pack.description,
        quizzes=summaries,
    )


@instructor_router.post(
    "/courses/{course_id}/practice/quizzes",
    response_model=PracticeQuizInstructorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new practice quiz",
)
async def create_practice_quiz(
    course_id: uuid.UUID,
    payload: PracticeQuizCreate,
    user: CurrentUser,
    session: DbSession,
) -> PracticeQuizInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    quiz = await practice_service.create_quiz(session, inst, course_id, payload)
    return PracticeQuizInstructorRead(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        order=quiz.order,
        is_published=quiz.is_published,
        item_count=0,
        items=[],
    )


@instructor_router.get(
    "/practice/quizzes/{quiz_id}",
    response_model=PracticeQuizInstructorRead,
    summary="Get a quiz with full answer key",
)
async def get_my_practice_quiz(
    quiz_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> PracticeQuizInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    quiz = await practice_service._get_owned_quiz(session, inst, quiz_id)
    items = [
        PracticeItemInstructorRead(
            id=it.id, type=it.type, order=it.order, points=it.points, data=it.data
        )
        for it in quiz.items
    ]
    return PracticeQuizInstructorRead(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        order=quiz.order,
        is_published=quiz.is_published,
        item_count=len(items),
        items=items,
    )


@instructor_router.patch(
    "/practice/quizzes/{quiz_id}",
    response_model=PracticeQuizInstructorRead,
    summary="Update a practice quiz",
)
async def update_practice_quiz(
    quiz_id: uuid.UUID,
    payload: PracticeQuizUpdate,
    user: CurrentUser,
    session: DbSession,
) -> PracticeQuizInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    quiz = await practice_service.update_quiz(session, inst, quiz_id, payload)
    items = [
        PracticeItemInstructorRead(
            id=it.id, type=it.type, order=it.order, points=it.points, data=it.data
        )
        for it in quiz.items
    ]
    return PracticeQuizInstructorRead(
        id=quiz.id,
        title=quiz.title,
        description=quiz.description,
        order=quiz.order,
        is_published=quiz.is_published,
        item_count=len(items),
        items=items,
    )


@instructor_router.delete(
    "/practice/quizzes/{quiz_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a practice quiz",
)
async def delete_practice_quiz(
    quiz_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await practice_service.delete_quiz(session, inst, quiz_id)


@instructor_router.post(
    "/practice/quizzes/{quiz_id}/items",
    response_model=PracticeItemInstructorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an item (MCQ or matching) to a quiz",
    description=(
        "Each quiz holds up to 50 items. The ``data`` payload is discriminated "
        "on ``type``: MCQ supplies ``options`` with exactly one ``is_correct`` "
        "flag; MATCHING supplies ``pairs`` whose ``id`` is the join key the "
        "student's answer references."
    ),
)
async def add_practice_item(
    quiz_id: uuid.UUID,
    payload: PracticeItemWrite,
    user: CurrentUser,
    session: DbSession,
) -> PracticeItemInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    item = await practice_service.add_item(session, inst, quiz_id, payload)
    return PracticeItemInstructorRead(
        id=item.id, type=item.type, order=item.order, points=item.points, data=item.data
    )


@instructor_router.put(
    "/practice/items/{item_id}",
    response_model=PracticeItemInstructorRead,
    summary="Replace an item's payload",
)
async def update_practice_item(
    item_id: uuid.UUID,
    payload: PracticeItemWrite,
    user: CurrentUser,
    session: DbSession,
) -> PracticeItemInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    item = await practice_service.update_item(session, inst, item_id, payload)
    return PracticeItemInstructorRead(
        id=item.id, type=item.type, order=item.order, points=item.points, data=item.data
    )


@instructor_router.delete(
    "/practice/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an item",
)
async def delete_practice_item(
    item_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await practice_service.delete_item(session, inst, item_id)
