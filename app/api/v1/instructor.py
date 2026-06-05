"""Instructor-facing endpoints: course/section/lesson management, video and
resource uploads, assessments, and student/analytics views.

All routes require the caller to have the ``instructor`` (or ``admin``) role.
A persisted :class:`Instructor` profile is auto-required for write operations
beyond ``/me/profile``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.exceptions import ForbiddenError
from app.core.pagination import Page, PageParams, page_params, to_page
from app.db.deps import DbSession
from app.models.enums import PublishStatus, UserRole
from app.schemas.download import LessonAttachmentRead
from app.schemas.assessment import (
    AssessmentCreate,
    AssessmentInstructorRead,
    AssessmentSubmissionRead,
    AssessmentSummary,
    AssessmentUpdate,
    QuestionCreate,
    QuestionInstructorRead,
    QuestionUpdate,
)
from app.schemas.instructor_admin import (
    CourseAnalytics,
    CourseCreate,
    CourseUpdate,
    EnrolledStudentRead,
    InstructorCourseRead,
    InstructorProfileRead,
    InstructorProfileUpdate,
    InstructorProfileUpsert,
    LessonAdminRead,
    LessonCreate,
    LessonUpdate,
    ReorderRequest,
    SectionAdminRead,
    SectionCreate,
    SectionUpdate,
    UploadResponse,
)
from app.schemas.promocode import PromocodeCreate, PromocodeRead
from app.services import assessment_service, instructor_service, promocode_service
from app.utils.hls import package_lesson_hls
from app.utils.storage import media_url, save_upload

router = APIRouter(prefix="/instructor", tags=["instructor"])


async def _require_instructor_role(user: CurrentUser):
    if user.role not in (UserRole.INSTRUCTOR, UserRole.ADMIN):
        raise ForbiddenError("Instructor role required", code="instructor_role_required")
    return user


# ---------- Profile ----------


@router.get("/me/profile", response_model=InstructorProfileRead)
async def get_my_profile(
    user: CurrentUser, session: DbSession
) -> InstructorProfileRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    return InstructorProfileRead.model_validate(inst)


@router.put("/me/profile", response_model=InstructorProfileRead)
async def upsert_my_profile(
    payload: InstructorProfileUpsert, user: CurrentUser, session: DbSession
) -> InstructorProfileRead:
    await _require_instructor_role(user)
    inst = await instructor_service.get_or_create_instructor(
        session,
        user,
        name=payload.name,
        title=payload.title,
        bio=payload.bio,
        expertise=payload.expertise,
        avatar_url=payload.avatar_url,
        linkedin_url=payload.linkedin_url,
        twitter_url=payload.twitter_url,
        website_url=payload.website_url,
    )
    return InstructorProfileRead.model_validate(inst)


@router.patch("/me/profile", response_model=InstructorProfileRead)
async def update_my_profile(
    payload: InstructorProfileUpdate, user: CurrentUser, session: DbSession
) -> InstructorProfileRead:
    await _require_instructor_role(user)
    inst = await instructor_service.update_my_instructor(
        session, user, payload.model_dump(exclude_unset=True)
    )
    return InstructorProfileRead.model_validate(inst)


@router.post("/me/profile/avatar", response_model=UploadResponse)
async def upload_my_avatar(
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    key, size = await save_upload(file, kind="image", subdir=f"instructors/{inst.id}/avatars")
    inst.avatar_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


# ---------- Courses ----------


@router.get("/courses", response_model=Page[InstructorCourseRead])
async def list_my_courses(
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[PublishStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[InstructorCourseRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items, total = await instructor_service.list_my_courses(
        session, inst, pagination, status=status_filter, search=search
    )
    return to_page(
        [InstructorCourseRead.model_validate(c) for c in items], total, pagination
    )


@router.post(
    "/courses", response_model=InstructorCourseRead, status_code=status.HTTP_201_CREATED
)
async def create_course(
    payload: CourseCreate, user: CurrentUser, session: DbSession
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.create_course(
        session, inst, payload.model_dump(exclude_unset=True)
    )
    return InstructorCourseRead.model_validate(course)


@router.get("/courses/{course_id}", response_model=InstructorCourseRead)
async def get_course(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.get_my_course(session, inst, course_id)
    return InstructorCourseRead.model_validate(course)


@router.patch("/courses/{course_id}", response_model=InstructorCourseRead)
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdate,
    user: CurrentUser,
    session: DbSession,
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.update_course(
        session, inst, course_id, payload.model_dump(exclude_unset=True)
    )
    return InstructorCourseRead.model_validate(course)


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await instructor_service.delete_course(session, inst, course_id)


@router.post("/courses/{course_id}/publish", response_model=InstructorCourseRead)
async def publish_course(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.set_course_status(
        session, inst, course_id, PublishStatus.PUBLISHED
    )
    return InstructorCourseRead.model_validate(course)


@router.post("/courses/{course_id}/unpublish", response_model=InstructorCourseRead)
async def unpublish_course(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.set_course_status(
        session, inst, course_id, PublishStatus.DRAFT
    )
    return InstructorCourseRead.model_validate(course)


@router.post("/courses/{course_id}/archive", response_model=InstructorCourseRead)
async def archive_course(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> InstructorCourseRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.set_course_status(
        session, inst, course_id, PublishStatus.ARCHIVED
    )
    return InstructorCourseRead.model_validate(course)


@router.post("/courses/{course_id}/thumbnail", response_model=UploadResponse)
async def upload_course_thumbnail(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.get_my_course(session, inst, course_id)
    key, size = await save_upload(file, kind="image", subdir=f"courses/{course.id}/thumbnails")
    course.thumbnail_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


@router.post("/courses/{course_id}/preview-video", response_model=UploadResponse)
async def upload_course_preview_video(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    course = await instructor_service.get_my_course(session, inst, course_id)
    key, size = await save_upload(file, kind="video", subdir=f"courses/{course.id}/preview")
    course.preview_video_url = key
    await session.commit()
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


# ---------- Sections ----------


@router.get("/courses/{course_id}/sections", response_model=list[SectionAdminRead])
async def list_sections(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[SectionAdminRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    sections = await instructor_service.list_sections(session, inst, course_id)
    return [SectionAdminRead.model_validate(s) for s in sections]


@router.post(
    "/courses/{course_id}/sections",
    response_model=SectionAdminRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    course_id: uuid.UUID,
    payload: SectionCreate,
    user: CurrentUser,
    session: DbSession,
) -> SectionAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    section = await instructor_service.create_section(
        session, inst, course_id, title=payload.title, order=payload.order
    )
    return SectionAdminRead.model_validate(section)


@router.post("/courses/{course_id}/sections/reorder", response_model=list[SectionAdminRead])
async def reorder_sections(
    course_id: uuid.UUID,
    payload: ReorderRequest,
    user: CurrentUser,
    session: DbSession,
) -> list[SectionAdminRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items = [(i.id, i.order) for i in payload.items]
    sections = await instructor_service.reorder_sections(session, inst, course_id, items)
    return [SectionAdminRead.model_validate(s) for s in sections]


@router.patch("/sections/{section_id}", response_model=SectionAdminRead)
async def update_section(
    section_id: uuid.UUID,
    payload: SectionUpdate,
    user: CurrentUser,
    session: DbSession,
) -> SectionAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    section = await instructor_service.update_section(
        session, inst, section_id, payload.model_dump(exclude_unset=True)
    )
    return SectionAdminRead.model_validate(section)


@router.delete("/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(
    section_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await instructor_service.delete_section(session, inst, section_id)


# ---------- Lessons ----------


@router.get("/sections/{section_id}/lessons", response_model=list[LessonAdminRead])
async def list_lessons(
    section_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[LessonAdminRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lessons = await instructor_service.list_lessons(session, inst, section_id)
    return [LessonAdminRead.model_validate(l) for l in lessons]


@router.post(
    "/sections/{section_id}/lessons",
    response_model=LessonAdminRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_lesson(
    section_id: uuid.UUID,
    payload: LessonCreate,
    user: CurrentUser,
    session: DbSession,
) -> LessonAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lesson = await instructor_service.create_lesson(
        session, inst, section_id, payload.model_dump(exclude_unset=True)
    )
    return LessonAdminRead.model_validate(lesson)


@router.post("/sections/{section_id}/lessons/reorder", response_model=list[LessonAdminRead])
async def reorder_lessons(
    section_id: uuid.UUID,
    payload: ReorderRequest,
    user: CurrentUser,
    session: DbSession,
) -> list[LessonAdminRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items = [(i.id, i.order) for i in payload.items]
    lessons = await instructor_service.reorder_lessons(session, inst, section_id, items)
    return [LessonAdminRead.model_validate(l) for l in lessons]


@router.patch("/lessons/{lesson_id}", response_model=LessonAdminRead)
async def update_lesson(
    lesson_id: uuid.UUID,
    payload: LessonUpdate,
    user: CurrentUser,
    session: DbSession,
) -> LessonAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lesson = await instructor_service.update_lesson(
        session, inst, lesson_id, payload.model_dump(exclude_unset=True)
    )
    return LessonAdminRead.model_validate(lesson)


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await instructor_service.delete_lesson(session, inst, lesson_id)


@router.post("/lessons/{lesson_id}/video", response_model=LessonAdminRead)
async def upload_lesson_video(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    duration_seconds: Annotated[int | None, Form(ge=0)] = None,
) -> LessonAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lesson = await instructor_service.get_my_lesson(session, inst, lesson_id)
    key, _ = await save_upload(
        file,
        kind="video",
        subdir=f"courses/{lesson.section.course_id}/lessons/{lesson.id}",
    )
    lesson = await instructor_service.set_lesson_video(
        session, inst, lesson_id, url=key, duration_seconds=duration_seconds
    )
    if settings.HLS_AUTO_PACKAGE:
        # Schedule HLS+AES-128 packaging — runs after the response is sent.
        background.add_task(package_lesson_hls, lesson_id)
    return LessonAdminRead.model_validate(lesson)


@router.post("/lessons/{lesson_id}/resource", response_model=LessonAdminRead)
async def upload_lesson_resource(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> LessonAdminRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lesson = await instructor_service.get_my_lesson(session, inst, lesson_id)
    key, _ = await save_upload(
        file,
        kind="document",
        subdir=f"courses/{lesson.section.course_id}/lessons/{lesson.id}/resources",
    )
    lesson = await instructor_service.set_lesson_resource(
        session, inst, lesson_id, url=key
    )
    return LessonAdminRead.model_validate(lesson)


@router.post(
    "/lessons/{lesson_id}/attachments",
    response_model=LessonAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_lesson_attachment(
    lesson_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form(min_length=1, max_length=200)],
) -> LessonAttachmentRead:
    """Add a downloadable attachment (PDF, slides, code zip, …) to a lesson.

    Multi-file companion to ``/lessons/{id}/resource`` — that route
    overwrites a single ``Lesson.resource_url`` column, this one creates a
    ``LessonAttachment`` row so a lesson can carry many files. Listed by
    ``GET /lessons/{id}/attachments`` and surfaced in the My Learning →
    Download screen.
    """
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    lesson = await instructor_service.get_my_lesson(session, inst, lesson_id)
    key, size = await save_upload(
        file,
        kind="document",
        subdir=f"courses/{lesson.section.course_id}/lessons/{lesson.id}/attachments",
    )
    attachment = await instructor_service.create_lesson_attachment(
        session,
        inst,
        lesson_id,
        title=title,
        file_key=key,
        file_size_bytes=size,
        mime_type=file.content_type,
    )
    return LessonAttachmentRead.model_validate(attachment)


@router.delete(
    "/lessons/{lesson_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lesson_attachment(
    lesson_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await instructor_service.delete_lesson_attachment(
        session, inst, lesson_id, attachment_id
    )


# ---------- Students / analytics ----------


@router.get("/courses/{course_id}/students", response_model=Page[EnrolledStudentRead])
async def list_course_students(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
    status_filter: Annotated[Literal["all", "active", "completed"], Query(alias="status")] = "all",
) -> Page[EnrolledStudentRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items, total = await instructor_service.list_course_students(
        session, inst, course_id, pagination, status=status_filter
    )
    rows = [
        EnrolledStudentRead(
            user_id=e.user.id,
            full_name=e.user.full_name,
            email=e.user.email,
            avatar_url=e.user.avatar_url,
            enrolled_at=e.enrolled_at,
            progress_percent=e.progress_percent,
            completed_at=e.completed_at,
            last_accessed_at=e.last_accessed_at,
        )
        for e in items
    ]
    return to_page(rows, total, pagination)


@router.get("/courses/{course_id}/analytics", response_model=CourseAnalytics)
async def course_analytics(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> CourseAnalytics:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    data = await instructor_service.course_analytics(session, inst, course_id)
    return CourseAnalytics.model_validate(data)


# ---------- Promocodes ----------


@router.get(
    "/courses/{course_id}/promocodes", response_model=list[PromocodeRead]
)
async def list_course_promocodes(
    course_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> list[PromocodeRead]:
    """List every promocode the instructor has issued for ``course_id``.

    Ordered newest-first. Includes revoked / exhausted codes so the
    instructor can audit usage; ``is_active`` and ``uses_count`` tell the
    UI which ones are still redeemable.
    """
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    rows = await promocode_service.list_course_promocodes(session, inst, course_id)
    return [PromocodeRead.model_validate(r) for r in rows]


@router.post(
    "/courses/{course_id}/promocodes",
    response_model=PromocodeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_course_promocode(
    course_id: uuid.UUID,
    payload: PromocodeCreate,
    user: CurrentUser,
    session: DbSession,
) -> PromocodeRead:
    """Issue a single-use promocode for one of the instructor's courses.

    Fails with ``promocode_code_taken`` (409) if the chosen code is
    already in use anywhere in the system, ``course_is_free`` (422) if
    the course costs nothing, ``discount_exceeds_price`` /
    ``discount_makes_free`` (422) if the discount would zero out the
    price.
    """
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    promo = await promocode_service.create_promocode(
        session,
        inst,
        course_id,
        code=payload.code,
        discount_kind=payload.discount_kind,
        discount_value=payload.discount_value,
        expires_at=payload.expires_at,
    )
    return PromocodeRead.model_validate(promo)


@router.delete(
    "/promocodes/{promocode_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_promocode(
    promocode_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    """Revoke an instructor-owned promocode.

    If the code has never been used the row is deleted outright. If it
    has been redeemed (``uses_count > 0``), it is soft-revoked
    (``is_active=false``) so the order's FK remains valid; the code
    cannot be redeemed again either way.
    """
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await promocode_service.revoke_promocode(session, inst, promocode_id)


# ---------- Assessments ----------


@router.get("/courses/{course_id}/assessments", response_model=Page[AssessmentSummary])
async def list_course_assessments(
    course_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[AssessmentSummary]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items, total = await assessment_service.list_assessments(
        session, inst, course_id, pagination
    )
    summaries = [
        AssessmentSummary(
            id=a.id,
            course_id=a.course_id,
            section_id=a.section_id,
            title=a.title,
            description=a.description,
            pass_percent=a.pass_percent,
            time_limit_minutes=a.time_limit_minutes,
            max_attempts=a.max_attempts,
            status=a.status,
            is_section_quiz=a.is_section_quiz,
            questions_count=len(a.questions) if a.questions is not None else 0,
            created_at=a.created_at,
        )
        for a in items
    ]
    return to_page(summaries, total, pagination)


@router.post(
    "/courses/{course_id}/assessments",
    response_model=AssessmentInstructorRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_course_assessment(
    course_id: uuid.UUID,
    payload: AssessmentCreate,
    user: CurrentUser,
    session: DbSession,
) -> AssessmentInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    assessment = await assessment_service.create_assessment(
        session, inst, course_id, payload.model_dump(exclude_unset=True)
    )
    return AssessmentInstructorRead.model_validate(assessment)


@router.get("/assessments/{assessment_id}", response_model=AssessmentInstructorRead)
async def get_assessment(
    assessment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AssessmentInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    assessment = await assessment_service.get_owned_assessment(session, inst, assessment_id)
    return AssessmentInstructorRead.model_validate(assessment)


@router.patch("/assessments/{assessment_id}", response_model=AssessmentInstructorRead)
async def update_assessment(
    assessment_id: uuid.UUID,
    payload: AssessmentUpdate,
    user: CurrentUser,
    session: DbSession,
) -> AssessmentInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    assessment = await assessment_service.update_assessment(
        session, inst, assessment_id, payload.model_dump(exclude_unset=True)
    )
    return AssessmentInstructorRead.model_validate(assessment)


@router.delete("/assessments/{assessment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assessment(
    assessment_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await assessment_service.delete_assessment(session, inst, assessment_id)


@router.post(
    "/assessments/{assessment_id}/questions",
    response_model=QuestionInstructorRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_assessment_question(
    assessment_id: uuid.UUID,
    payload: QuestionCreate,
    user: CurrentUser,
    session: DbSession,
) -> QuestionInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    question = await assessment_service.add_question(
        session, inst, assessment_id, payload.model_dump(exclude_unset=True)
    )
    return QuestionInstructorRead.model_validate(question)


@router.patch("/questions/{question_id}", response_model=QuestionInstructorRead)
async def update_assessment_question(
    question_id: uuid.UUID,
    payload: QuestionUpdate,
    user: CurrentUser,
    session: DbSession,
) -> QuestionInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    question = await assessment_service.update_question(
        session, inst, question_id, payload.model_dump(exclude_unset=True)
    )
    return QuestionInstructorRead.model_validate(question)


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assessment_question(
    question_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await assessment_service.delete_question(session, inst, question_id)


@router.post("/questions/{question_id}/image", response_model=QuestionInstructorRead)
async def upload_question_image(
    question_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> QuestionInstructorRead:
    """Attach an image (diagram, photo, …) to a quiz question."""
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    key, _ = await save_upload(
        file, kind="image", subdir=f"assessments/questions/{question_id}"
    )
    question = await assessment_service.set_question_image(
        session, inst, question_id, key
    )
    return QuestionInstructorRead.model_validate(question)


@router.delete(
    "/questions/{question_id}/image", response_model=QuestionInstructorRead
)
async def clear_question_image(
    question_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> QuestionInstructorRead:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    question = await assessment_service.set_question_image(
        session, inst, question_id, None
    )
    return QuestionInstructorRead.model_validate(question)


@router.post("/options/{option_id}/image", response_model=UploadResponse)
async def upload_option_image(
    option_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File(...)],
) -> UploadResponse:
    """Attach an image to a single answer option (e.g. picture-multiple-
    choice). Returns the resolved URL plus uploaded size.
    """
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    key, size = await save_upload(
        file, kind="image", subdir=f"assessments/options/{option_id}"
    )
    await assessment_service.set_option_image(session, inst, option_id, key)
    return UploadResponse(url=media_url(key) or "", size_bytes=size)


@router.delete("/options/{option_id}/image", status_code=status.HTTP_204_NO_CONTENT)
async def clear_option_image(
    option_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> None:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    await assessment_service.set_option_image(session, inst, option_id, None)


@router.get(
    "/assessments/{assessment_id}/submissions",
    response_model=Page[AssessmentSubmissionRead],
)
async def list_assessment_submissions(
    assessment_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    pagination: Annotated[PageParams, Depends(page_params)],
) -> Page[AssessmentSubmissionRead]:
    await _require_instructor_role(user)
    inst = await instructor_service.require_my_instructor(session, user)
    items, total = await assessment_service.list_assessment_submissions_for_instructor(
        session, inst, assessment_id, pagination
    )
    return to_page(
        [AssessmentSubmissionRead.model_validate(s) for s in items], total, pagination
    )
