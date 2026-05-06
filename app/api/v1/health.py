from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.db.deps import DbSession
from app.redis_client import RedisDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: DbSession, redis: RedisDep) -> dict[str, object]:
    db_ok = False
    redis_ok = False
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        pass
    try:
        pong = await redis.ping()
        redis_ok = bool(pong)
    except Exception:  # noqa: BLE001
        pass
    return {"status": "ready" if (db_ok and redis_ok) else "degraded", "db": db_ok, "redis": redis_ok}