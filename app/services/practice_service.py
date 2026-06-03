"""Service layer for the practice (Duolingo-style) quiz feature.

Author-side helpers (pack/quiz/item CRUD) live here next to grading and the
student-facing read paths. The split between ``..._for_instructor`` and
``..._for_student`` reflects two different visibility contracts: instructors
see ``is_correct`` flags and unpublished quizzes; students get a sanitized
payload and the gate against unbought courses.
"""
from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.catalog import Instructor
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.enums import PracticeItemType, PublishStatus
from app.models.practice import (
    PracticeAttempt,
    PracticeItem,
    PracticePack,
    PracticeQuiz,
)
from app.models.user import User
from app.schemas.practice import (
    MAX_ITEMS_PER_QUIZ,
    MatchingDataStudent,
    MatchingDataWrite,
    MCQDataStudent,
    MCQDataWrite,
    PracticeAttemptCreate,
    PracticeItemResult,
    PracticeItemStudentRead,
    PracticeItemWrite,
    PracticePackUpdate,
    PracticeQuizCreate,
    PracticeQuizStudentProgress,
    PracticeQuizUpdate,
)


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------- Ownership ----------


async def _get_owned_course(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found")
    if course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this course")
    return course


async def _get_owned_quiz(
    session: AsyncSession, instructor: Instructor, quiz_id: uuid.UUID
) -> PracticeQuiz:
    stmt = (
        select(PracticeQuiz)
        .where(PracticeQuiz.id == quiz_id)
        .options(
            selectinload(PracticeQuiz.items),
            selectinload(PracticeQuiz.pack).selectinload(PracticePack.course),
        )
    )
    quiz = (await session.execute(stmt)).scalar_one_or_none()
    if quiz is None:
        raise NotFoundError("Practice quiz not found")
    if quiz.pack.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this practice quiz")
    return quiz


async def _get_owned_item(
    session: AsyncSession, instructor: Instructor, item_id: uuid.UUID
) -> PracticeItem:
    stmt = (
        select(PracticeItem)
        .where(PracticeItem.id == item_id)
        .options(
            selectinload(PracticeItem.quiz)
            .selectinload(PracticeQuiz.pack)
            .selectinload(PracticePack.course),
        )
    )
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Practice item not found")
    if item.quiz.pack.course.instructor_id != instructor.id:
        raise ForbiddenError("You do not own this practice item")
    return item


# ---------- Pack lifecycle ----------


async def get_or_create_pack(
    session: AsyncSession, instructor: Instructor, course_id: uuid.UUID
) -> PracticePack:
    course = await _get_owned_course(session, instructor, course_id)
    stmt = (
        select(PracticePack)
        .where(PracticePack.course_id == course.id)
        .options(selectinload(PracticePack.quizzes).selectinload(PracticeQuiz.items))
    )
    pack = (await session.execute(stmt)).scalar_one_or_none()
    if pack is not None:
        return pack
    pack = PracticePack(course_id=course.id)
    session.add(pack)
    await session.commit()
    await session.refresh(pack)
    return pack


async def update_pack(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    payload: PracticePackUpdate,
) -> PracticePack:
    pack = await get_or_create_pack(session, instructor, course_id)
    if payload.title is not None:
        pack.title = payload.title
    if payload.description is not None:
        pack.description = payload.description
    await session.commit()
    await session.refresh(pack)
    return pack


# ---------- Quiz authoring ----------


async def _next_quiz_order(session: AsyncSession, pack_id: uuid.UUID) -> int:
    current = (
        await session.execute(
            select(func.coalesce(func.max(PracticeQuiz.order), -1)).where(
                PracticeQuiz.pack_id == pack_id
            )
        )
    ).scalar_one()
    return int(current) + 1


async def create_quiz(
    session: AsyncSession,
    instructor: Instructor,
    course_id: uuid.UUID,
    payload: PracticeQuizCreate,
) -> PracticeQuiz:
    pack = await get_or_create_pack(session, instructor, course_id)
    order = payload.order if payload.order is not None else await _next_quiz_order(session, pack.id)
    quiz = PracticeQuiz(
        pack_id=pack.id,
        title=payload.title,
        description=payload.description,
        order=order,
        is_published=payload.is_published,
    )
    session.add(quiz)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ConflictError("A quiz with that order already exists in this pack") from exc
    await session.refresh(quiz)
    return quiz


async def update_quiz(
    session: AsyncSession,
    instructor: Instructor,
    quiz_id: uuid.UUID,
    payload: PracticeQuizUpdate,
) -> PracticeQuiz:
    quiz = await _get_owned_quiz(session, instructor, quiz_id)
    if payload.title is not None:
        quiz.title = payload.title
    if payload.description is not None:
        quiz.description = payload.description
    if payload.order is not None:
        quiz.order = payload.order
    if payload.is_published is not None:
        quiz.is_published = payload.is_published
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ConflictError("Reordering collides with another quiz in this pack") from exc
    await session.refresh(quiz)
    return quiz


async def delete_quiz(
    session: AsyncSession, instructor: Instructor, quiz_id: uuid.UUID
) -> None:
    quiz = await _get_owned_quiz(session, instructor, quiz_id)
    await session.delete(quiz)
    await session.commit()


# ---------- Item authoring ----------


async def _next_item_order(session: AsyncSession, quiz_id: uuid.UUID) -> int:
    current = (
        await session.execute(
            select(func.coalesce(func.max(PracticeItem.order), -1)).where(
                PracticeItem.quiz_id == quiz_id
            )
        )
    ).scalar_one()
    return int(current) + 1


async def add_item(
    session: AsyncSession,
    instructor: Instructor,
    quiz_id: uuid.UUID,
    payload: PracticeItemWrite,
) -> PracticeItem:
    quiz = await _get_owned_quiz(session, instructor, quiz_id)
    item_count = (
        await session.execute(
            select(func.count(PracticeItem.id)).where(PracticeItem.quiz_id == quiz.id)
        )
    ).scalar_one()
    if item_count >= MAX_ITEMS_PER_QUIZ:
        raise ValidationAppError(
            f"A practice quiz can hold at most {MAX_ITEMS_PER_QUIZ} items",
            code="quiz_item_limit",
        )
    order = (
        payload.order if payload.order is not None else await _next_item_order(session, quiz.id)
    )
    item = PracticeItem(
        quiz_id=quiz.id,
        type=payload.type,
        order=order,
        points=payload.points,
        data=payload.data.model_dump(mode="json"),
    )
    session.add(item)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ConflictError("An item with that order already exists in this quiz") from exc
    await session.refresh(item)
    return item


async def update_item(
    session: AsyncSession,
    instructor: Instructor,
    item_id: uuid.UUID,
    payload: PracticeItemWrite,
) -> PracticeItem:
    item = await _get_owned_item(session, instructor, item_id)
    item.type = payload.type
    item.points = payload.points
    if payload.order is not None:
        item.order = payload.order
    item.data = payload.data.model_dump(mode="json")
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ConflictError("Reordering collides with another item in this quiz") from exc
    await session.refresh(item)
    return item


async def delete_item(
    session: AsyncSession, instructor: Instructor, item_id: uuid.UUID
) -> None:
    item = await _get_owned_item(session, instructor, item_id)
    await session.delete(item)
    await session.commit()


# ---------- Student reads ----------


async def _require_enrollment(
    session: AsyncSession, user: User, course_id: uuid.UUID
) -> None:
    enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course_id
            )
        )
    ).first()
    if enrolled is None:
        raise ForbiddenError(
            "Enroll in the course to access its practice quizzes",
            code="not_enrolled",
        )


async def _aggregate_progress(
    session: AsyncSession, user: User, quiz_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, PracticeQuizStudentProgress]:
    quiz_ids = list(quiz_ids)
    if not quiz_ids:
        return {}
    stmt = (
        select(
            PracticeAttempt.quiz_id,
            func.max(PracticeAttempt.score_percent).label("best"),
            func.count(PracticeAttempt.id).label("attempts"),
            func.max(PracticeAttempt.completed_at).label("last"),
        )
        .where(
            PracticeAttempt.user_id == user.id,
            PracticeAttempt.quiz_id.in_(quiz_ids),
        )
        .group_by(PracticeAttempt.quiz_id)
    )
    rows = (await session.execute(stmt)).all()
    out: dict[uuid.UUID, PracticeQuizStudentProgress] = {}
    for row in rows:
        out[row.quiz_id] = PracticeQuizStudentProgress(
            completed=row.attempts > 0,
            best_score_percent=int(row.best or 0),
            attempts_count=int(row.attempts),
            last_attempted_at=row.last,
        )
    return out


async def get_pack_for_student(
    session: AsyncSession, user: User, course_id: uuid.UUID
) -> tuple[PracticePack | None, dict[uuid.UUID, PracticeQuizStudentProgress]]:
    course = await session.get(Course, course_id)
    if course is None:
        raise NotFoundError("Course not found")
    if course.status != PublishStatus.PUBLISHED:
        raise NotFoundError("Course not found")
    await _require_enrollment(session, user, course.id)
    stmt = (
        select(PracticePack)
        .where(PracticePack.course_id == course.id)
        .options(selectinload(PracticePack.quizzes).selectinload(PracticeQuiz.items))
    )
    pack = (await session.execute(stmt)).scalar_one_or_none()
    if pack is None:
        return None, {}
    published_ids = [q.id for q in pack.quizzes if q.is_published]
    progress = await _aggregate_progress(session, user, published_ids)
    return pack, progress


async def get_quiz_for_student(
    session: AsyncSession, user: User, quiz_id: uuid.UUID
) -> tuple[PracticeQuiz, PracticeQuizStudentProgress]:
    stmt = (
        select(PracticeQuiz)
        .where(PracticeQuiz.id == quiz_id)
        .options(
            selectinload(PracticeQuiz.items),
            selectinload(PracticeQuiz.pack).selectinload(PracticePack.course),
        )
    )
    quiz = (await session.execute(stmt)).scalar_one_or_none()
    if quiz is None or not quiz.is_published:
        raise NotFoundError("Practice quiz not found")
    course = quiz.pack.course
    if course.status != PublishStatus.PUBLISHED:
        raise NotFoundError("Practice quiz not found")
    await _require_enrollment(session, user, course.id)
    progress_map = await _aggregate_progress(session, user, [quiz.id])
    return quiz, progress_map.get(quiz.id, PracticeQuizStudentProgress())


def sanitize_item_for_student(item: PracticeItem) -> PracticeItemStudentRead:
    """Strip the answer key out of an item's JSONB payload before serving.

    For matching items, sides are also shuffled so the student can't infer
    pairs from positional order.
    """
    data = item.data or {}
    if item.type == PracticeItemType.MCQ:
        options = [
            {"id": o["id"], "text": o["text"], "image_url": o.get("image_url")}
            for o in data.get("options", [])
        ]
        payload = MCQDataStudent(
            type=PracticeItemType.MCQ,
            prompt=data.get("prompt", ""),
            image_url=data.get("image_url"),
            options=options,
        )
    elif item.type == PracticeItemType.MATCHING:
        pairs = data.get("pairs", [])
        lefts = [{"id": p["id"], "text": p["left"]} for p in pairs]
        rights = [{"id": p["id"], "text": p["right"]} for p in pairs]
        random.shuffle(lefts)
        random.shuffle(rights)
        payload = MatchingDataStudent(
            type=PracticeItemType.MATCHING,
            prompt=data.get("prompt", ""),
            lefts=lefts,
            rights=rights,
        )
    else:
        raise ValidationAppError(f"Unknown practice item type: {item.type}")
    return PracticeItemStudentRead(
        id=item.id,
        type=item.type,
        order=item.order,
        points=item.points,
        data=payload,
    )


# ---------- Grading & attempts ----------


def _grade_mcq(item: PracticeItem, response: dict) -> bool:
    correct_id = next(
        (o["id"] for o in item.data.get("options", []) if o.get("is_correct")),
        None,
    )
    return response.get("option_id") == correct_id


def _grade_matching(item: PracticeItem, response: dict) -> bool:
    # Each canonical pair has id P, and the left/right values are both labelled
    # with that id at author time. A correct submission pairs left_id == right_id
    # for every pair in the item, with nothing missing or extra.
    expected_ids = {p["id"] for p in item.data.get("pairs", [])}
    submitted = response.get("pairs") or []
    if len(submitted) != len(expected_ids):
        return False
    seen_left: set[str] = set()
    seen_right: set[str] = set()
    for pair in submitted:
        left = pair.get("left_id")
        right = pair.get("right_id")
        if left != right:
            return False
        if left not in expected_ids or left in seen_left or right in seen_right:
            return False
        seen_left.add(left)
        seen_right.add(right)
    return True


async def submit_attempt(
    session: AsyncSession,
    user: User,
    quiz_id: uuid.UUID,
    payload: PracticeAttemptCreate,
) -> tuple[PracticeAttempt, list[PracticeItemResult]]:
    quiz, _ = await get_quiz_for_student(session, user, quiz_id)
    items_by_id: dict[uuid.UUID, PracticeItem] = {it.id: it for it in quiz.items}
    if not items_by_id:
        raise ValidationAppError(
            "Cannot attempt an empty quiz", code="quiz_has_no_items"
        )

    answered: set[uuid.UUID] = set()
    persisted_answers: list[dict] = []
    results: list[PracticeItemResult] = []
    awarded = 0
    correct_count = 0

    for answer in payload.answers:
        item_id = answer.item_id
        if item_id in answered:
            raise ValidationAppError(
                "Duplicate answer for the same item", code="duplicate_answer"
            )
        item = items_by_id.get(item_id)
        if item is None:
            raise ValidationAppError(
                "Answer references an unknown item", code="unknown_item"
            )
        answered.add(item_id)
        response = answer.model_dump(mode="json", exclude={"item_id"})
        if item.type == PracticeItemType.MCQ:
            is_correct = _grade_mcq(item, response)
        elif item.type == PracticeItemType.MATCHING:
            is_correct = _grade_matching(item, response)
        else:
            is_correct = False
        points = item.points if is_correct else 0
        if is_correct:
            correct_count += 1
            awarded += points
        persisted_answers.append(
            {
                "item_id": str(item_id),
                "response": response,
                "is_correct": is_correct,
                "awarded_points": points,
            }
        )
        results.append(
            PracticeItemResult(item_id=item_id, is_correct=is_correct, awarded_points=points)
        )

    total_points = sum(item.points for item in items_by_id.values()) or 1
    score_percent = round((awarded / total_points) * 100)

    attempt = PracticeAttempt(
        quiz_id=quiz.id,
        user_id=user.id,
        started_at=payload.started_at,
        completed_at=_now(),
        score_percent=score_percent,
        correct_count=correct_count,
        total_count=len(items_by_id),
        answers=persisted_answers,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt, results
