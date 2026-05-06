from __future__ import annotations

import time

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import RateLimitedError
from app.core.logging import get_logger
from app.redis_client import get_redis

logger = get_logger(__name__)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def _check_limit(redis: Redis, bucket: str, limit: int, window_s: int = 60) -> None:
    """Sliding-window rate limit using a sorted set per (bucket, identifier).

    Fails open: if Redis is unreachable, the request is allowed through and the
    failure is logged. Rate limiting is a best-effort defense, not a correctness
    boundary, so a Redis outage must not take the API down.
    """
    now = time.time()
    try:
        pipe = redis.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - window_s)
        pipe.zadd(bucket, {f"{now}:{int(now * 1_000_000) % 1_000_000}": now})
        pipe.zcard(bucket)
        pipe.expire(bucket, window_s + 1)
        _, _, count, _ = await pipe.execute()
    except RedisError as exc:
        logger.warning("rate_limit_redis_unavailable", bucket=bucket, error=str(exc))
        return

    if int(count) > limit:
        raise RateLimitedError(
            f"Rate limit exceeded: {limit} requests per {window_s} seconds",
            details={"limit": limit, "window_seconds": window_s},
        )


async def rate_limit_default(request: Request) -> None:
    redis = get_redis()
    key = f"rl:default:{_client_key(request)}"
    await _check_limit(redis, key, settings.RATE_LIMIT_DEFAULT_PER_MINUTE)


async def rate_limit_auth(request: Request) -> None:
    redis = get_redis()
    key = f"rl:auth:{_client_key(request)}:{request.url.path}"
    await _check_limit(redis, key, settings.RATE_LIMIT_AUTH_PER_MINUTE)