"""P2.SR PostgreSQL concurrency — idempotency dưới race thật.

SQLite không mô phỏng được UNIQUE/transaction concurrency đủ tốt cho yêu cầu này.
Chạy trên DB throwaway:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p2sr_race_check \
    python -m pytest tests/test_p2sr_postgres_concurrency.py -q
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models import Course, SourceResearchRun, User
from app.services import source_research_service

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests"
)


async def _prepare():
    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed_course(sm) -> uuid.UUID:
    async with sm() as db:
        user = User(external_id=f"p2sr-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(user_id=user.id, topic="Python cho người mới", client_course_id=uuid.uuid4().hex[:16])
        db.add(course)
        await db.commit()
        return course.id


def test_concurrent_research_requests_create_one_run():
    async def run():
        settings = get_settings()
        original_enabled = settings.source_research_enabled
        original_provider = settings.source_research_provider
        settings.source_research_enabled = True
        settings.source_research_provider = "mock"
        engine, sm = await _prepare()
        try:
            course_id = await _seed_course(sm)

            async def call():
                async with sm() as db:
                    course = (
                        await db.execute(select(Course).where(Course.id == course_id))
                    ).scalar_one()
                    row, created = await source_research_service.run_research(db, course, max_sources=3)
                    return row.id, created

            results = await asyncio.gather(*[call() for _ in range(6)])
            ids = {run_id for run_id, _ in results}
            assert len(ids) == 1, f"phải chỉ có 1 research run, nhận {len(ids)}"
            assert sum(1 for _, created in results if created) == 1

            async with sm() as db:
                rows = (await db.execute(select(SourceResearchRun))).scalars().all()
            assert len(rows) == 1
            assert rows[0].is_mock is True
            assert rows[0].sources
        finally:
            await engine.dispose()
            settings.source_research_enabled = original_enabled
            settings.source_research_provider = original_provider

    asyncio.run(run())
