from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.activity import WeeklyActivityRead, WeeklyGoalUpdate
from app.services import activity_service

router = APIRouter(prefix="/me/activity", tags=["account"])


@router.get("/weekly", response_model=WeeklyActivityRead)
async def get_weekly_activity(
    user: CurrentUser, session: DbSession
) -> WeeklyActivityRead:
    data = await activity_service.get_weekly(session, user)
    return WeeklyActivityRead.model_validate(data)


@router.put("/weekly-goal", response_model=WeeklyActivityRead)
async def set_weekly_goal(
    payload: WeeklyGoalUpdate, user: CurrentUser, session: DbSession
) -> WeeklyActivityRead:
    await activity_service.set_weekly_goal(session, user, payload.weekly_goal_minutes)
    data = await activity_service.get_weekly(session, user)
    return WeeklyActivityRead.model_validate(data)
