"""Fixtures dùng chung: SQLite in-memory async + httpx AsyncClient gọi app thật."""

import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("REDIS_URL", "")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
