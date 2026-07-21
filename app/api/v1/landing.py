"""Public landing-page statistics.

A self-contained space, deliberately kept apart from the rest of the API:

* ``GET /landing/stats`` — public, no auth. Anyone can read the figures shown
  on the marketing landing page.
* ``PUT /landing/stats`` — admin only. The figures are hand-curated marketing
  numbers, not derived from live data, so an admin sets them directly.

Storage is a single always-present row (:data:`~app.models.landing.SINGLETON_ID`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_admin_user
from app.db.deps import DbSession
from app.models.landing import SINGLETON_ID, LandingStats
from app.schemas.landing import LandingStatsRead, LandingStatsUpdate

router = APIRouter(prefix="/landing", tags=["landing"])


async def _get_or_create(session: DbSession) -> LandingStats:
    stats = await session.get(LandingStats, SINGLETON_ID)
    if stats is None:
        stats = LandingStats(id=SINGLETON_ID)
        session.add(stats)
        await session.commit()
        await session.refresh(stats)
    return stats


@router.get("/stats", response_model=LandingStatsRead)
async def get_landing_stats(session: DbSession) -> LandingStatsRead:
    """Public — the landing page reads this without signing up."""
    stats = await _get_or_create(session)
    return LandingStatsRead.model_validate(stats)


@router.put(
    "/stats",
    response_model=LandingStatsRead,
    dependencies=[Depends(get_admin_user)],
)
async def update_landing_stats(
    payload: LandingStatsUpdate, session: DbSession
) -> LandingStatsRead:
    """Admin only — set any subset of the landing-page figures."""
    stats = await _get_or_create(session)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(stats, key, value)
    await session.commit()
    await session.refresh(stats)
    return LandingStatsRead.model_validate(stats)
