from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

# Ensure required env vars are set BEFORE importing the app
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("POSTGRES_HOST", os.environ.get("POSTGRES_HOST", "localhost"))
os.environ.setdefault("POSTGRES_PORT", os.environ.get("POSTGRES_PORT", "5432"))
os.environ.setdefault("POSTGRES_USER", os.environ.get("POSTGRES_USER", "satzone"))
os.environ.setdefault("POSTGRES_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "satzone"))
os.environ.setdefault("POSTGRES_DB", os.environ.get("POSTGRES_DB", "satzone_test"))
os.environ.setdefault("REDIS_HOST", os.environ.get("REDIS_HOST", "localhost"))
os.environ.setdefault("REDIS_PORT", os.environ.get("REDIS_PORT", "6379"))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")


@pytest_asyncio.fixture
async def app():
    from app.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
