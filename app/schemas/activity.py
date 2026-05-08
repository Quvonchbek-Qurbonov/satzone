from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.schemas.base import ORMModel


class WeeklyGoalUpdate(BaseModel):
    weekly_goal_minutes: int = Field(..., ge=0, le=10_080)  # cap at minutes/week


class DailyActivityRead(ORMModel):
    activity_date: date
    minutes_learned: int
    lessons_completed: int


class WeeklyActivityRead(BaseModel):
    """Last 7 days, oldest-first. Missing days show as zero rows."""

    weekly_goal_minutes: int | None = None
    minutes_learned_total: int
    days: list[DailyActivityRead]
