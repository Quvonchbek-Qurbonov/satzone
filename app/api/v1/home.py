from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import bearer_scheme, get_current_user
from app.db.deps import DbSession
from app.models.user import User
from app.schemas.category import CategoryRead
from app.schemas.course import CourseSummary
from app.schemas.enrollment import EnrollmentRead
from app.schemas.home import HomeFeed
from app.schemas.program import ProgramSummary
from app.services import home_service

router = APIRouter(prefix="/home", tags=["home"])


async def _maybe_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    if credentials is None:
        return None
    try:
        return await get_current_user(session=session, credentials=credentials)
    except Exception:  # noqa: BLE001
        return None


@router.get("", response_model=HomeFeed)
async def home_feed(
    session: DbSession,
    user: Annotated[User | None, Depends(_maybe_user)],
) -> HomeFeed:
    continue_learning = (
        await home_service.fetch_continue_learning(session, user) if user else []
    )
    recommended = await home_service.fetch_recommended(session, user)
    featured = await home_service.fetch_featured(session)
    popular = await home_service.fetch_popular(session)
    new_courses = await home_service.fetch_new(session)
    categories = await home_service.fetch_top_categories(session)
    programs = await home_service.fetch_programs(session)

    return HomeFeed(
        continue_learning=[EnrollmentRead.model_validate(e) for e in continue_learning],
        recommended=[CourseSummary.model_validate(c) for c in recommended],
        featured=[CourseSummary.model_validate(c) for c in featured],
        popular=[CourseSummary.model_validate(c) for c in popular],
        new_courses=[CourseSummary.model_validate(c) for c in new_courses],
        categories=[CategoryRead.model_validate(c) for c in categories],
        programs=[ProgramSummary.model_validate(p) for p in programs],
    )
