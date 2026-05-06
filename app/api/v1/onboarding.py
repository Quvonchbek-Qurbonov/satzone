from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.db.deps import DbSession
from app.schemas.category import CategoryRead
from app.schemas.onboarding import OnboardingProfile, OnboardingRead, OnboardingUpdate
from app.services import onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("", response_model=OnboardingRead)
async def get_onboarding(user: CurrentUser, session: DbSession) -> OnboardingRead:
    profile, interests, completed = await onboarding_service.get_onboarding(session, user)
    return OnboardingRead(
        profile=OnboardingProfile.model_validate(profile) if profile else None,
        interests=[CategoryRead.model_validate(c) for c in interests],
        onboarding_completed=completed,
    )


@router.put("", response_model=OnboardingRead)
async def update_onboarding(
    payload: OnboardingUpdate, user: CurrentUser, session: DbSession
) -> OnboardingRead:
    profile, interests = await onboarding_service.update_onboarding(session, user, payload)
    return OnboardingRead(
        profile=OnboardingProfile.model_validate(profile) if profile else None,
        interests=[CategoryRead.model_validate(c) for c in interests],
        onboarding_completed=user.onboarding_completed_at is not None,
    )
