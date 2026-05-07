from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine
from app.middleware.request_id import RequestContextMiddleware
from app.redis_client import close_redis, get_redis

# Importing the module is enough — counters are registered as a side effect.
import app.core.metrics  # noqa: F401

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "app_startup",
        env=settings.ENV,
        debug=settings.DEBUG,
        project=settings.PROJECT_NAME,
    )
    # Warm up Redis connection
    redis = get_redis()
    try:
        await redis.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unreachable_at_startup", error=str(exc))
    try:
        yield
    finally:
        logger.info("app_shutdown")
        await close_redis()
        await dispose_engine()


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="1.0.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    media_root = Path(settings.MEDIA_ROOT)
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount(settings.MEDIA_URL, StaticFiles(directory=media_root), name="media")

    # Prometheus /metrics — labels routes by their template (so all lessons
    # collapse onto a single ``/lessons/{lesson_id}/hls/seg/{seg_name}``
    # series instead of one series per UUID, which would explode cardinality).
    Instrumentator(
        excluded_handlers=["/metrics", "/docs", "/redoc", "/openapi.json"],
        should_group_status_codes=False,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()