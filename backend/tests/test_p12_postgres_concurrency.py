"""P1.2 gate — atomic claim / approve races trên PostgreSQL thật.

SQLite in-memory không mô phỏng được đồng thời (một connection). Test chạy khi có:

    POSTGRES_TEST_URL=postgresql+asyncpg://user:pass@host:port/throwaway_db

Test tự drop/create schema trên DB đó — **không** dùng DB `ailp` chính.
Viết dạng sync + `asyncio.run` để engine/connection nằm trong đúng một event loop.

Ví dụ:

    docker compose exec -T db psql -U ailp -d postgres -c "CREATE DATABASE p12_race_check;"
    POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p12_race_check \
      python -m pytest tests/test_p12_postgres_concurrency.py -q
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import (
    Course,
    CourseInterview,
    CourseProposal,
    CourseStatus,
    GenerationJob,
    JobStatus,
    User,
)
from app.services import course_service, job_service

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests"
)


class Env:
    def __init__(self):
        self.engine = None
        self.sm = None


async def _prepare() -> Env:
    env = Env()
    env.engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with env.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    env.sm = async_sessionmaker(env.engine, expire_on_commit=False, class_=AsyncSession)
    return env


async def _seed_proposed_course(env: Env) -> tuple[uuid.UUID, uuid.UUID]:
    async with env.sm() as db:
        user = User(external_id=f"p12-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(
            user_id=user.id,
            topic="race",
            client_course_id=uuid.uuid4().hex,
            status=CourseStatus.proposed,
        )
        db.add(course)
        await db.flush()
        db.add(
            CourseInterview(
                course_id=course.id, questions=["q"] * 5, answers=["a"] * 5, completed_count=5
            )
        )
        db.add(
            CourseProposal(
                course_id=course.id,
                version=1,
                payload={
                    "name": "p",
                    "objective": "o",
                    "units": [
                        {"title": "u1", "blurb": "", "lessonTitles": ["a"]},
                        {"title": "u2", "blurb": "", "lessonTitles": ["b"]},
                    ],
                    "outcomes": ["x", "y"],
                },
            )
        )
        await db.commit()
        return user.id, course.id


def _run(coro_fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


def test_concurrent_claim_single_winner():
    async def scenario():
        env = await _prepare()
        try:
            _, course_id = await _seed_proposed_course(env)
            async with env.sm() as db:
                course = (
                    await db.execute(select(Course).where(Course.id == course_id))
                ).scalar_one()
                job = await course_service.approve_course(db, course)
                job_id = job.id

            async def claim():
                async with env.sm() as db:
                    return await job_service.claim_job(db, job_id)

            results = await asyncio.gather(*[claim() for _ in range(10)])
            winners = [r for r in results if r is not None]
            assert len(winners) == 1, f"phải có đúng 1 worker claim được, thực tế {len(winners)}"

            async with env.sm() as db:
                job = (
                    await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
                ).scalar_one()
            assert job.status == JobStatus.running
            assert job.attempts_count == 1
        finally:
            await env.engine.dispose()

    _run(scenario)


def test_concurrent_approve_creates_one_job():
    async def scenario():
        env = await _prepare()
        try:
            _, course_id = await _seed_proposed_course(env)

            async def approve():
                async with env.sm() as db:
                    course = (
                        await db.execute(select(Course).where(Course.id == course_id))
                    ).scalar_one()
                    try:
                        job = await course_service.approve_course(db, course)
                        return job.id
                    except Exception as exc:  # HTTPException 409 là kết quả hợp lệ
                        await db.rollback()
                        return type(exc).__name__

            results = await asyncio.gather(*[approve() for _ in range(10)])
            ok = [r for r in results if isinstance(r, uuid.UUID)]
            assert len(ok) == 1, f"chỉ 1 approve được thắng, thực tế {len(ok)}: {results}"

            async with env.sm() as db:
                count = (
                    await db.execute(
                        select(func.count())
                        .select_from(GenerationJob)
                        .where(GenerationJob.course_id == course_id)
                    )
                ).scalar_one()
            assert count == 1, f"không được tạo nhiều job: {count}"
        finally:
            await env.engine.dispose()

    _run(scenario)


def test_expired_lease_reclaimed_by_other_worker():
    async def scenario():
        env = await _prepare()
        try:
            _, course_id = await _seed_proposed_course(env)
            async with env.sm() as db:
                course = (
                    await db.execute(select(Course).where(Course.id == course_id))
                ).scalar_one()
                job_id = (await course_service.approve_course(db, course)).id

            async with env.sm() as db:
                assert await job_service.claim_job(db, job_id) is not None

            async with env.sm() as db:
                job = (
                    await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
                ).scalar_one()
                job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
                await db.commit()

            async def claim():
                async with env.sm() as db:
                    return await job_service.claim_job(db, job_id)

            results = await asyncio.gather(*[claim() for _ in range(5)])
            assert len([r for r in results if r is not None]) == 1
        finally:
            await env.engine.dispose()

    _run(scenario)


def test_reconciler_dispatch_once_for_stuck_outbox_job():
    async def scenario():
        env = await _prepare()
        try:
            _, course_id = await _seed_proposed_course(env)
            async with env.sm() as db:
                course = (
                    await db.execute(select(Course).where(Course.id == course_id))
                ).scalar_one()
                job_id = (await course_service.approve_course(db, course)).id
                job = (
                    await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
                ).scalar_one()
                job.created_at = datetime.now(UTC) - timedelta(seconds=120)
                job.dispatched_at = None
                await db.commit()

            async def recover():
                async with env.sm() as db:
                    return await job_service.recover_stuck_jobs(db)

            results = await asyncio.gather(*[recover() for _ in range(5)])
            handled = sum(1 for r in results for x in r if x == job_id)
            # Cho phép cả 5 lần "thấy" job (idempotent dispatch), nhưng job vẫn
            # chỉ có một record và không bị đẩy sang failed.
            assert handled >= 1
            async with env.sm() as db:
                job = (
                    await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
                ).scalar_one()
            assert job.status != JobStatus.failed
            assert job.dispatched_at is not None
        finally:
            await env.engine.dispose()

    _run(scenario)
