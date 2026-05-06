from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models.catalog import Category
from app.models.user import User, UserInterest, UserProfile
from app.schemas.onboarding import OnboardingUpdate


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def get_onboarding(session: AsyncSession, user: User) -> tuple[UserProfile | None, list[Category], bool]:
    profile = (
        await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    ).scalar_one_or_none()
    interests = (
        await session.execute(
            select(Category)
            .join(UserInterest, UserInterest.category_id == Category.id)
            .where(UserInterest.user_id == user.id)
            .order_by(Category.sort_order, Category.name)
        )
    ).scalars().all()
    return profile, list(interests), user.onboarding_completed_at is not None


async def update_onboarding(
    session: AsyncSession, user: User, payload: OnboardingUpdate
) -> tuple[UserProfile, list[Category]]:
    profile = (
        await session.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id)
        session.add(profile)

    profile_fields = {
        "headline",
        "bio",
        "skill_level",
        "weekly_goal_minutes",
        "learning_goal",
        "locale",
        "timezone",
    }
    data = payload.model_dump(exclude_unset=True)
    for field in profile_fields:
        if field in data:
            setattr(profile, field, data[field])

    if payload.interest_category_ids is not None:
        ids = list({cid for cid in payload.interest_category_ids})
        if ids:
            existing = (
                await session.execute(select(Category.id).where(Category.id.in_(ids)))
            ).scalars().all()
            missing = set(ids) - set(existing)
            if missing:
                raise ValidationAppError(
                    f"Unknown category id(s): {sorted(str(m) for m in missing)}",
                    code="invalid_category_ids",
                    details=[str(m) for m in missing],
                )
        await session.execute(delete(UserInterest).where(UserInterest.user_id == user.id))
        for cid in ids:
            session.add(UserInterest(user_id=user.id, category_id=cid))

    if payload.mark_completed and user.onboarding_completed_at is None:
        user.onboarding_completed_at = _now()

    await session.commit()
    await session.refresh(profile)

    interests = (
        await session.execute(
            select(Category)
            .join(UserInterest, UserInterest.category_id == Category.id)
            .where(UserInterest.user_id == user.id)
            .order_by(Category.sort_order, Category.name)
        )
    ).scalars().all()
    return profile, list(interests)
