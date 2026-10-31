"""P3.0 PostgreSQL race/idempotency + migration smoke (throwaway DB).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p30_race_check \
    python -m pytest tests/test_p30_postgres_concurrency.py -q
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Course, CourseSource, Source, SourceVerificationStatus, User
from app.schemas.schemas import SourceCreateRequest
from app.services import source_service

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


async def _seed_user(sm) -> uuid.UUID:
    async with sm() as db:
        user = User(external_id=f"p30-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.commit()
        return user.id


def _body(title: str = "Race Source") -> SourceCreateRequest:
    return SourceCreateRequest(
        sourceType="official_documentation",
        title=title,
        canonicalUrl="https://race.example.com/doc",
        publisher="Race Org",
        version="1",
        visibility="private",
    )


def test_concurrent_source_creation_creates_one_row():
    async def run():
        engine, sm = await _prepare()
        try:
            user_id = await _seed_user(sm)

            async def create():
                async with sm() as db:
                    source, created = await source_service.create_source(db, user_id, _body())
                    return source.id, created

            results = await asyncio.gather(*[create() for _ in range(8)])
            ids = {source_id for source_id, _ in results}
            assert len(ids) == 1, f"phải chỉ có 1 nguồn, nhận {len(ids)}"
            assert sum(1 for _, created in results if created) == 1

            async with sm() as db:
                rows = (await db.execute(select(Source))).scalars().all()
            assert len(rows) == 1
            assert rows[0].verification_status is SourceVerificationStatus.unverified
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_concurrent_course_source_links_are_idempotent():
    async def run():
        engine, sm = await _prepare()
        try:
            user_id = await _seed_user(sm)
            async with sm() as db:
                source, _ = await source_service.create_source(db, user_id, _body("Link Source"))
            async with sm() as db:
                course = Course(user_id=user_id, topic="t", client_course_id=uuid.uuid4().hex[:16])
                db.add(course)
                await db.commit()

            async def link():
                async with sm() as db:
                    fresh_course = (
                        await db.execute(select(Course).where(Course.id == course.id))
                    ).scalar_one()
                    return await source_service.link_source_to_course(
                        db, fresh_course, user_id, f"src_{source.id}"
                    )

            results = await asyncio.gather(*[link() for _ in range(6)])
            assert len({r[0].id for r in results}) == 1

            async with sm() as db:
                rows = (await db.execute(select(CourseSource))).scalars().all()
            assert len(rows) == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_source_private_not_accessible_to_other_user():
    async def run():
        engine, sm = await _prepare()
        try:
            owner = await _seed_user(sm)
            other = await _seed_user(sm)
            async with sm() as db:
                source, _ = await source_service.create_source(db, owner, _body("Private A"))

            async with sm() as db:
                with pytest.raises(source_service.SourceAccessError):
                    await source_service.get_accessible_source(db, f"src_{source.id}", other)
            async with sm() as db:
                found = await source_service.get_accessible_source(
                    db, f"src_{source.id}", owner
                )
                assert found.id == source.id
        finally:
            await engine.dispose()

    asyncio.run(run())
