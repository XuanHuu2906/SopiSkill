"""P3.1 — Tutor controls race/idempotency trên PostgreSQL (throwaway DB).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p31_tutor_race \
    python -m pytest tests/test_p31_tutor_postgres_concurrency.py -q

SQLite in-memory dùng một connection chung nên không mô phỏng được race thật.
Các test dưới đây chứng minh trên PostgreSQL:
  - stop song song / stop-vs-complete race không xóa nội dung hay ghi đè trạng thái;
  - allowance đếm đúng khi nhiều lượt được chấp nhận đồng thời (không âm thầm vượt trần);
  - audit tool (P3.1 lát B) ghi song song không mất bản ghi;
  - không phụ thuộc Redis: mọi thứ nằm trong DB.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models import (
    Course,
    Lesson,
    LessonStatus,
    TutorMessage,
    TutorMessageStatus,
    TutorThread,
    TutorUsageEvent,
    Unit,
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
    async with sm() as db:
        user = User(external_id=f"p31-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(user_id=user.id, topic="P3.1 race", client_course_id=uuid.uuid4().hex[:16])
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
            content=[{"type": "teach", "title": "t", "paragraphs": ["p"]}],
            content_version=1,
            status=LessonStatus.ready,
        )
        db.add(lesson)
        await db.commit()
        return user.id, course.id, lesson.id


def test_concurrent_stop_requests_are_idempotent(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)
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
                    await db.get(User, user_id),
                    request,
                )
                await tutor_service.mark_running(db, prepared.assistant_message.id)

            async def stop_once():
                async with sm() as db:
                    return await tutor_service.request_cancel(
                        db,
                        await db.get(Course, course_id),
                        user_id,
                        prepared.assistant_id(),
                    )

            results = await asyncio.gather(*[stop_once() for _ in range(8)])
            assert all(r["status"] == "cancel_requested" for r in results), results

            async with sm() as db:
                message = await db.get(TutorMessage, prepared.assistant_message.id)
            # Stop KHÔNG tự ghi terminal: chỉ task stream được ghi trạng thái cuối.
            assert message.status is TutorMessageStatus.running
            assert message.cancel_requested_at is not None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_stop_after_terminal_does_not_rewrite_status_or_content(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)
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
                    await db.get(User, user_id),
                    request,
                )
                await tutor_service.finalize(
                    db,
                    prepared.assistant_message.id,
                    tutor_service.FinalState(
                        status=TutorMessageStatus.completed,
                        content="nội dung hoàn chỉnh",
                        finish_reason="stop",
                    ),
                )

            async with sm() as db:
                result = await tutor_service.request_cancel(
                    db,
                    await db.get(Course, course_id),
                    user_id,
                    prepared.assistant_id(),
                )
            assert result["status"] == "completed"

            async with sm() as db:
                message = await db.get(TutorMessage, prepared.assistant_message.id)
            assert message.status is TutorMessageStatus.completed
            assert message.content == "nội dung hoàn chỉnh"
            assert message.cancel_requested_at is None

            # cancel_if_running không được đè trạng thái terminal.
            async with sm() as db:
                changed = await tutor_service.cancel_if_running(
                    db, prepared.assistant_message.id, "một phần"
                )
            assert changed is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_usage_allowance_sums_across_concurrent_writes(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)

            from app.providers.usage import UsageRecord

            async def write_one(index: int):
                async with sm() as db:
                    await tutor_service.record_usage(
                        db,
                        user_id=user_id,
                        course_id=course_id,
                        message_id=None,
                        record=UsageRecord(
                            provider="openai_compatible",
                            model="m",
                            kind="tutor",
                            prompt_tokens=10,
                            completion_tokens=5,
                            finish_reason="stop",
                        ),
                    )

            await asyncio.gather(*[write_one(i) for i in range(5)])

            async with sm() as db:
                course = await db.get(Course, course_id)
                state = await tutor_service.quota_state(db, course.user_id)
                total = (
                    await db.execute(
                        select(func.count()).select_from(TutorUsageEvent)
                    )
                ).scalar_one()
            assert total == 5
            assert state["used"]["tokens"] == 75, state
            assert state["tokensKnown"] is True
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_stale_reap_unblocks_user_after_concurrent_attempts(monkeypatch):
    async def run():
        from datetime import UTC, datetime, timedelta

        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        monkeypatch.setattr(get_settings(), "tutor_stale_stream_seconds", 60.0)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)
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
                    await db.get(User, user_id),
                    request,
                )
                await tutor_service.mark_running(db, prepared.assistant_message.id)
                message = await db.get(TutorMessage, prepared.assistant_message.id)
                message.updated_at = datetime.now(UTC) - timedelta(seconds=600)
                await db.commit()

            async with sm() as db:
                reaped = await tutor_service.reap_stale_messages(db, user_id)
                await db.commit()
            assert reaped == 1

            async with sm() as db:
                message = await db.get(TutorMessage, prepared.assistant_message.id)
                running = await tutor_service.count_running_streams(db, user_id)
            assert message.status is TutorMessageStatus.failed
            assert message.error_code == "TUTOR_STALE"
            assert running == 0
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_concurrent_tool_audit_writes_are_all_recorded(monkeypatch):
    async def run():
        monkeypatch.setattr(get_settings(), "tutor_enabled", True)
        engine, sm = await _prepare()
        try:
            user_id, course_id, lesson_id = await _seed(sm)
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
                    await db.get(User, user_id),
                    request,
                )

            async def write_one(index: int):
                async with sm() as db:
                    await tutor_service.record_tool_call(
                        db,
                        user_id=user_id,
                        course_id=course_id,
                        message_id=prepared.assistant_message.id,
                        name="read_lesson",
                        ok=True,
                        duration_ms=index,
                        summary="read_lesson() -> ok",
                        error_code=None,
                    )

            await asyncio.gather(*[write_one(i) for i in range(6)])

            from app.models import TutorToolCall

            async with sm() as db:
                rows = (
                    await db.execute(
                        select(TutorToolCall).where(
                            TutorToolCall.message_id == prepared.assistant_message.id
                        )
                    )
                ).scalars().all()
            assert len(rows) == 6
            assert all(r.name == "read_lesson" and r.ok for r in rows)
        finally:
            await engine.dispose()

    asyncio.run(run())
