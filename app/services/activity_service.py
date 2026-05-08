"""Daily activity rollups + weekly goal accessors.

``record_minutes`` is the upsert called from ``enrollment_service`` whenever
a lesson progress write moves ``watched_seconds`` forward. Day key is the
user's *server-local* date (UTC) — close enough for the home chart, and
avoids storing a per-user timezone read-side.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.activity import DailyActivity
from app.models.user import User, UserProfile


def _today_utc() -> date:
    return datetime.now(tz=UTC).date()


async def record_minutes(
    session: AsyncSession,
    user_id,
    *,
    minutes: int,
    completed_lesson: bool = False,
    on_date: date | None = None,
) -> None:
    if minutes <= 0 and not completed_lesson:
        return
    day = on_date or _today_utc()
    stmt = pg_insert(DailyActivity).values(
        user_id=user_id,
        activity_date=day,
        minutes_learned=max(0, minutes),
        lessons_completed=1 if completed_lesson else 0,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyActivity.user_id, DailyActivity.activity_date],
        set_={
            "minutes_learned": DailyActivity.minutes_learned + max(0, minutes),
            "lessons_completed": DailyActivity.lessons_completed + (1 if completed_lesson else 0),
        },
    )
    await session.execute(stmt)


async def get_weekly(session: AsyncSession, user: User) -> dict:
    today = _today_utc()
    start = today - timedelta(days=6)
    rows = list(
        (
            await session.execute(
                select(DailyActivity)
                .where(
                    DailyActivity.user_id == user.id,
                    DailyActivity.activity_date >= start,
                    DailyActivity.activity_date <= today,
                )
                .order_by(DailyActivity.activity_date.asc())
            )
        ).scalars().all()
    )
    by_day = {r.activity_date: r for r in rows}
    days = []
    total = 0
    for offset in range(7):
        d = start + timedelta(days=offset)
        existing = by_day.get(d)
        days.append(
            {
                "activity_date": d,
                "minutes_learned": existing.minutes_learned if existing else 0,
                "lessons_completed": existing.lessons_completed if existing else 0,
            }
        )
        if existing:
            total += existing.minutes_learned

    profile = (
        await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    ).scalar_one_or_none()
    return {
        "weekly_goal_minutes": getattr(profile, "weekly_goal_minutes", None),
        "minutes_learned_total": total,
        "days": days,
    }


async def set_weekly_goal(
    session: AsyncSession, user: User, weekly_goal_minutes: int
) -> int:
    profile = (
        await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None:
        # Lazy-create a profile row if onboarding never ran.
        profile = UserProfile(user_id=user.id)
        session.add(profile)
    profile.weekly_goal_minutes = weekly_goal_minutes
    await session.commit()
    return weekly_goal_minutes


async def total_minutes_learned(session: AsyncSession, user: User) -> int:
    total = (
        await session.execute(
            select(func.coalesce(func.sum(DailyActivity.minutes_learned), 0)).where(
                DailyActivity.user_id == user.id
            )
        )
    ).scalar_one()
    return int(total or 0)
