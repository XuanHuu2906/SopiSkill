"""Fixtures dùng chung: SQLite in-memory async + httpx AsyncClient gọi app thật."""

import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-not-production")
# P6.1 — seed shuffle quiz phải tất định trong test (không dùng khoá dev mặc định).
os.environ.setdefault("LESSON_SHUFFLE_SECRET", "test-shuffle-secret-for-pytest-only")
os.environ.setdefault("ALLOW_DEMO_HEADER", "false")
# Chạy generation đồng bộ trong test: SQLite :memory: dùng chung một connection,
# task nền fire-and-forget sẽ chồng transaction với session của request.
os.environ.setdefault("GENERATION_INLINE_BLOCKING", "true")
# P4.0 — ingest chạy đồng bộ + storage in-memory (không cần MinIO/network trong test).
os.environ.setdefault("SOURCE_STORAGE_BACKEND", "memory")
os.environ.setdefault("SOURCE_STORAGE_BUCKET", "test-sources")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.limits import clear_rate_limits
from app.db.session import create_all, engine
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_db():
    await create_all()
    yield


@pytest_asyncio.fixture
async def client():
    clear_rate_limits()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    clear_rate_limits()
