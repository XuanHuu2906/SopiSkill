"""P3.0 Tutor — PostgreSQL race/idempotency (throwaway DB).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p30_tutor_race \
    python -m pytest tests/test_p30_tutor_postgres_concurrency.py -q

Vì sao cần: SQLite in-memory dùng một connection chung nên không mô phỏng được
race thật. Test này chạy nhiều session đồng thời trên PostgreSQL để chứng minh
UNIQUE(course_id, client_message_id, role) + row lock per-user giữ đúng
"1 user message + 1 assistant message" khi client double-click.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models import (
    Course,
    Lesson,
    TutorMessage,
    TutorThread,
    User,
)
from app.schemas.schemas import TutorMessageRequest
from app.services import tutor_service

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL,
    reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests",
)


async def _prepare():
    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(sm) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.models import LessonStatus, Unit

    async with sm() as db:
        user = User(external_id=f"tutor-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(user_id=user.id, topic="Tutor race", client_course_id=uuid.uuid4().hex[:16])
        db.add(course)
        await db.flush()
        unit = Unit(course_id=course.id, order_index=0, title="Unit", blurb="b")
        db.add(unit)
        await db.flush()
        lesson = Lesson(
            unit_id=unit.id,
            course_id=course.id,
            order_index=0,
            title="Bài",
            content=[
                {"type": "teach", "title": "t", "paragraphs": ["p"]},
                {"type": "mc", "question": "q", "options": ["a", "b"], "answerIndex": 0},
            ],
            content_version=1,
            status=LessonStatus.ready,
        )
        db.add(lesson)
        await db.commit()
        return user.id, course.id, lesson.id


def test_concurrent_duplicate_turn_creates_one_pair(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)
            client_message_id = uuid.uuid4().hex[:16]
            request = TutorMessageRequest(
                clientMessageId=client_message_id,
                threadId=None,
                text="Hỏi song song",
                contextRef={"lessonId": f"lsn_{lesson_id}", "blockIndex": 0},
            )

            async def attempt():
                async with sm() as db:
                    course = await db.get(Course, course_id)
                    user = await db.get(User, user_id)
                    return await tutor_service.prepare_turn(db, course, user, request)

            results = await asyncio.gather(
                *[attempt() for _ in range(6)], return_exceptions=True
            )
            ok = [r for r in results if isinstance(r, tutor_service.PreparedTurn)]
            assert ok, results
            # Mọi attempt thành công phải trỏ về cùng một cặp message.
            assert len({r.user_message.id for r in ok}) == 1
            assert len({r.assistant_message.id for r in ok}) == 1

            async with sm() as db:
                messages = (
                    await db.execute(
                        select(TutorMessage).where(
                            TutorMessage.client_message_id == client_message_id
                        )
                    )
                ).scalars().all()
                threads = (
                    await db.execute(
                        select(TutorThread).where(TutorThread.course_id == course_id)
                    )
                ).scalars().all()
            assert len(messages) == 2, f"phải đúng 1 cặp user+assistant, nhận {len(messages)}"
            assert len(threads) == 1, f"không được tạo thread thừa, nhận {len(threads)}"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cross_user_thread_lookup_is_denied(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_a, course_id, lesson_id = await _seed(sm)
            async with sm() as db:
                other = User(external_id=f"o-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
                db.add(other)
                await db.commit()
                other_id = other.id

            request = TutorMessageRequest(
                clientMessageId=uuid.uuid4().hex[:16],
                threadId=None,
                text="Hỏi",
                contextRef={"lessonId": f"lsn_{lesson_id}", "blockIndex": 0},
            )
            async with sm() as db:
                prepared = await tutor_service.prepare_turn(
                    db,
                    await db.get(Course, course_id),
                    await db.get(User, user_a),
                    request,
                )

            async with sm() as db:
                from fastapi import HTTPException

                with pytest.raises(HTTPException) as info:
                    await tutor_service.get_owned_thread(
                        db,
                        await db.get(Course, course_id),
                        other_id,
                        prepared.thread_id(),
                    )
                assert info.value.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
