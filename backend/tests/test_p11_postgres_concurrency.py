"""P1.1 gate — race/idempotency thật trên PostgreSQL.

SQLite in-memory dùng StaticPool + một connection nên **không** mô phỏng được
concurrency. Test này chạy khi có biến môi trường:

    POSTGRES_TEST_URL=postgresql+asyncpg://user:pass@host:port/dbname

Điều kiện: DB rỗng/throwaway. Test tự drop/create schema trên DB đó — **không**
dùng DB `ailp` chính. Viết dạng sync + `asyncio.run` để toàn bộ engine/connection
nằm trong đúng một event loop (tránh cross-loop của asyncpg).

Chạy ví dụ (Windows, stack compose đang chạy):

    docker compose exec -T db psql -U ailp -d postgres -c "CREATE DATABASE p11_race_check;"
    POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p11_race_check \
      python -m pytest tests/test_p11_postgres_concurrency.py -q
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Course, CourseStatus, Lesson, LessonAttempt, Unit, User, XpEvent
from app.schemas.schemas import AttemptRequest
from app.services import lesson_service
from app.services.lesson_content import public_block

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests"
)

BLOCKS = [
    {"type": "teach", "title": "t", "paragraphs": ["p"]},
    {"type": "mc", "question": "q", "options": ["a", "b", "c"], "answerIndex": 1},
    {"type": "blank", "sentence": "s", "answer": "python"},
    {"type": "order", "prompt": "p", "items": ["một", "hai", "ba"]},
    {"type": "match", "prompt": "p", "pairs": [["A", "1"], ["B", "2"]]},
    {"type": "short", "question": "q", "acceptedAnswers": ["python"]},
]


def _answers(lesson_id: uuid.UUID) -> list[dict]:
    version = 1
    out = [
        {"index": 1, "answer": 1},
        {"index": 2, "answer": "python"},
        {"index": 5, "answer": "python"},
    ]
    order_pub = public_block(lesson_id, version, 3, BLOCKS[3])
    text_to_id = {i["text"]: i["id"] for i in order_pub["items"]}
    out.append({"index": 3, "answer": [text_to_id[t] for t in BLOCKS[3]["items"]]})

    match_pub = public_block(lesson_id, version, 4, BLOCKS[4])
    left = {i["text"]: i["id"] for i in match_pub["lefts"]}
    right = {i["text"]: i["id"] for i in match_pub["rights"]}
    out.append({"index": 4, "answer": {left[a]: right[b] for a, b in BLOCKS[4]["pairs"]}})
    return out


async def _prepare():
    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(sessionmaker) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessionmaker() as db:
        user = User(external_id=f"pg-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(
            user_id=user.id, topic="race", client_course_id=uuid.uuid4().hex, status=CourseStatus.ready
        )
        db.add(course)
        await db.flush()
        unit = Unit(course_id=course.id, order_index=0, title="u", blurb="")
        db.add(unit)
        await db.flush()
        lesson = Lesson(
            unit_id=unit.id,
            course_id=course.id,
            order_index=0,
            title="l",
            content=BLOCKS,
            content_version=1,
        )
        db.add(lesson)
        await db.commit()
        return user.id, lesson.id


async def _submit_many(sessionmaker, user_id, lesson_id, attempt_id_fn, count=20):
    payload = _answers(lesson_id)

    async def one(_):
        async with sessionmaker() as db:
            user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
            lesson = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one()
            request = AttemptRequest(
                clientAttemptId=attempt_id_fn(), contentVersion=1, answers=payload
            )
            attempt, _dup = await lesson_service.submit_attempt(db, lesson, user, request)
            return attempt.id

    return await asyncio.gather(*[one(i) for i in range(count)], return_exceptions=True)


async def _totals(sessionmaker, user_id):
    async with sessionmaker() as db:
        xp_total = (
            await db.execute(
                select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
                    XpEvent.user_id == user_id
                )
            )
        ).scalar_one()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    return int(xp_total), user.xp


class _Runner:
    def __init__(self):
        self.engine = None
        self.sessionmaker = None


def _run(coro_fn):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


def test_20_concurrent_same_client_attempt_id_awards_xp_once():
    async def scenario():
        engine, sm = await _prepare()
        try:
            user_id, lesson_id = await _seed(sm)
            cid = uuid.uuid4().hex
            results = await _submit_many(sm, user_id, lesson_id, lambda: cid)
            failures = [r for r in results if isinstance(r, Exception)]
            assert not failures, f"submit lỗi: {failures[:3]}"
            assert len(set(results)) == 1, "20 request cùng clientAttemptId phải trả cùng 1 attempt"

            async with sm() as db:
                attempts = (
                    await db.execute(
                        select(LessonAttempt).where(LessonAttempt.client_attempt_id == cid)
                    )
                ).scalars().all()
            assert len(attempts) == 1
            assert attempts[0].score_correct == attempts[0].score_total == 5

            xp_total, user_xp = await _totals(sm, user_id)
            assert xp_total == attempts[0].xp_awarded == 5 * 10 + 20
            assert user_xp == 70
        finally:
            await engine.dispose()

    _run(scenario)


def test_20_concurrent_distinct_attempt_ids_do_not_farm_xp():
    async def scenario():
        engine, sm = await _prepare()
        try:
            user_id, lesson_id = await _seed(sm)
            results = await _submit_many(sm, user_id, lesson_id, lambda: uuid.uuid4().hex)
            failures = [r for r in results if isinstance(r, Exception)]
            assert not failures, f"submit lỗi: {failures[:3]}"
            assert len(set(results)) == 20

            xp_total, user_xp = await _totals(sm, user_id)
            assert xp_total == 70, f"XP bị farm: {xp_total}"
            assert user_xp == 70
        finally:
            await engine.dispose()

    _run(scenario)
