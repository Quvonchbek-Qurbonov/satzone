from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser
from app.core.exceptions import ConflictError, NotFoundError
from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.models.enums import CourseLevel
from app.models.review import Review
from app.schemas.course import CourseDetail, CourseSummary, CurriculumRead, LessonSummary, SectionRead
from app.schemas.review import ReviewCreate, ReviewRead, ReviewUpdate
from app.services import course_service
from sqlalchemy import select

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=Page[CourseSummary])
async def list_courses(
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=100)] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    category_slug: Annotated[str | None, Query(max_length=120)] = None,
    instructor_id: Annotated[uuid.UUID | None, Query()] = None,
    level: Annotated[CourseLevel | None, Query()] = None,
    is_free: Annotated[bool | None, Query()] = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    min_duration_minutes: Annotated[int | None, Query(ge=0)] = None,
    max_duration_minutes: Annotated[int | None, Query(ge=0)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    sort: Annotated[
        Literal["popular", "newest", "rating", "price_asc", "price_desc"], Query()
    ] = "popular",
) -> Page[CourseSummary]:
    items, total = await course_service.list_courses(
        session,
        page_params=pagination,
        search=search,
        category_id=category_id,
        category_slug=category_slug,
        instructor_id=instructor_id,
        level=level,
        is_free=is_free,
        min_rating=min_rating,
        min_duration_minutes=min_duration_minutes,
        max_duration_minutes=max_duration_minutes,
        tags=tags,
        sort=sort,
    )
    return to_page([CourseSummary.model_validate(c) for c in items], total, pagination)


@router.get("/{slug}", response_model=CourseDetail)
async def course_detail(slug: str, session: DbSession) -> CourseDetail:
    course = await course_service.get_course_by_slug(session, slug)
    return CourseDetail.model_validate(course)


@router.get("/{slug}/curriculum", response_model=CurriculumRead)
async def course_curriculum(slug: str, session: DbSession) -> CurriculumRead:
    course = await course_service.get_course_by_slug(session, slug)
    sections, total_duration, total_lessons = await course_service.get_curriculum(session, course.id)
    return CurriculumRead(
        sections=[
            SectionRead(
                id=s.id,
                title=s.title,
                order=s.order,
                lessons=[LessonSummary.model_validate(l) for l in s.lessons],
            )
            for s in sections
        ],
        total_duration_seconds=total_duration,
        total_lessons=total_lessons,
    )


@router.get("/{slug}/related", response_model=list[CourseSummary])
async def course_related(slug: str, session: DbSession) -> list[CourseSummary]:
    course = await course_service.get_course_by_slug(session, slug)
    related = await course_service.get_related_courses(session, course)
    return [CourseSummary.model_validate(c) for c in related]


@router.get("/{slug}/reviews", response_model=Page[ReviewRead])
async def course_reviews(
    slug: str,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[ReviewRead]:
    course = await course_service.get_course_by_slug(session, slug)
    items, total = await course_service.list_reviews(session, course.id, pagination)
    return to_page([ReviewRead.model_validate(r) for r in items], total, pagination)


@router.post("/{slug}/reviews", response_model=ReviewRead, status_code=201)
async def create_review(
    slug: str,
    payload: ReviewCreate,
    user: CurrentUser,
    session: DbSession,
) -> ReviewRead:
    course = await course_service.get_course_by_slug(session, slug)
    # Must be enrolled in the course to review.
    from app.models.enrollment import Enrollment

    is_enrolled = (
        await session.execute(
            select(Enrollment.id).where(
                Enrollment.user_id == user.id, Enrollment.course_id == course.id
            )
        )
    ).first()
    if is_enrolled is None:
        raise ConflictError("You must be enrolled to review this course", code="not_enrolled")

    existing = (
        await session.execute(
            select(Review).where(Review.course_id == course.id, Review.user_id == user.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("You have already reviewed this course", code="review_exists")

    review = Review(
        course_id=course.id,
        user_id=user.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    session.add(review)
    # Recompute course rating aggregate
    await session.flush()
    await _recompute_course_rating(session, course.id)
    await session.commit()
    await session.refresh(review, attribute_names=["user"])
    return ReviewRead.model_validate(review)


@router.put("/{slug}/reviews/me", response_model=ReviewRead)
async def update_my_review(
    slug: str,
    payload: ReviewUpdate,
    user: CurrentUser,
    session: DbSession,
) -> ReviewRead:
    course = await course_service.get_course_by_slug(session, slug)
    review = (
        await session.execute(
            select(Review).where(Review.course_id == course.id, Review.user_id == user.id)
        )
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("Review not found")
    if payload.rating is not None:
        review.rating = payload.rating
    if payload.comment is not None:
        review.comment = payload.comment
    await session.flush()
    await _recompute_course_rating(session, course.id)
    await session.commit()
    await session.refresh(review, attribute_names=["user"])
    return ReviewRead.model_validate(review)


@router.delete("/{slug}/reviews/me", status_code=204)
async def delete_my_review(slug: str, user: CurrentUser, session: DbSession) -> None:
    course = await course_service.get_course_by_slug(session, slug)
    review = (
        await session.execute(
            select(Review).where(Review.course_id == course.id, Review.user_id == user.id)
        )
    ).scalar_one_or_none()
    if review is None:
        raise NotFoundError("Review not found")
    await session.delete(review)
    await session.flush()
    await _recompute_course_rating(session, course.id)
    await session.commit()


async def _recompute_course_rating(session, course_id: uuid.UUID) -> None:
    from sqlalchemy import func, update
    from app.models.course import Course

    agg = (
        await session.execute(
            select(func.avg(Review.rating), func.count(Review.id)).where(Review.course_id == course_id)
        )
    ).one()
    avg = float(agg[0]) if agg[0] is not None else 0.0
    count = int(agg[1] or 0)
    await session.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(rating_avg=round(avg, 2), ratings_count=count)
    )
