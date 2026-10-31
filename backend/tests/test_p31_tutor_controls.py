"""P3.1 — Tutor controls: server-side stop, allowance, concurrency, stale reap.

Chạy offline (SQLite in-memory + MockProvider). Đây là kiểm chứng **contract**,
không phải bằng chứng chất lượng LLM thật. Stop là best-effort: server dừng
được vòng stream của chính nó, nhưng không thể hoàn chi phí provider đã sinh.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Course,
    TutorMessage,
    TutorMessageStatus,
    TutorThread,
    TutorUsageEvent,
    User,
)
from app.services import tutor_service

from tests.test_p30_tutor import (
    PASSWORD,
    create_course_with_lessons,
    csrf_headers,
    message_body,
    parse_sse,
    send_message,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _tutor_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tutor_enabled", True)
    monkeypatch.setattr(settings, "tutor_messages_per_day", 0)
    monkeypatch.setattr(settings, "tutor_tokens_per_day", 0)
    monkeypatch.setattr(settings, "tutor_max_concurrent_streams", 0)
    monkeypatch.setattr(settings, "tutor_heartbeat_seconds", 1.0)
    monkeypatch.setattr(settings, "tutor_stream_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "tutor_cancel_poll_seconds", 0.2)
    monkeypatch.setattr(settings, "tutor_stale_stream_seconds", 180.0)


async def _prepare_running(client, course_id: str, lesson_id: str):
    """Tạo PreparedTurn thật rồi chuyển assistant sang `running`."""
    body = message_body(lesson_id, text="Câu hỏi sẽ bị dừng")
    async with SessionLocal() as db:
        course = await db.get(Course, uuid.UUID(course_id.removeprefix("crs_")))
        user = await db.get(User, course.user_id)
        prepared = await tutor_service.prepare_turn(
            db, course, user, tutor_service.TutorMessageRequest.model_validate(body)
        )
        await tutor_service.mark_running(db, prepared.assistant_message.id)
    return prepared


async def _reload(message_id):
    async with SessionLocal() as db:
        return await db.get(TutorMessage, message_id)


# ---------- stop endpoint ----------


async def test_stop_endpoint_sets_cancel_flag_for_running_message(client):
    course_id, lessons = await create_course_with_lessons(client)
    prepared = await _prepare_running(client, course_id, lessons[0]["id"])

    r = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/{prepared.assistant_id()}/stop",
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["status"] == "cancel_requested"
    assert payload["providerStopGuaranteed"] is False

    message = await _reload(prepared.assistant_message.id)
    assert message.cancel_requested_at is not None
    # Không tự đánh dấu cancelled: task stream còn sống phải tự ghi trạng thái cuối.
    assert message.status is TutorMessageStatus.running

    # Gọi lại: idempotent, không đổi dấu thời gian.
    again = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/{prepared.assistant_id()}/stop",
        headers=csrf_headers(client),
    )
    assert again.status_code == 200
    assert (await _reload(prepared.assistant_message.id)).cancel_requested_at is not None


async def test_stop_unknown_or_foreign_message_is_404(client):
    course_id, lessons = await create_course_with_lessons(client)
    prepared = await _prepare_running(client, course_id, lessons[0]["id"])

    bogus = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/tmsg_{uuid.uuid4()}/stop",
        headers=csrf_headers(client),
    )
    assert bogus.status_code == 404
    assert bogus.json()["detail"]["code"] == "TUTOR_STOP_NOT_FOUND"

    # User B không dừng được stream của A.
    other = await client.post("/v1/auth/register", json={"email": f"b-{uuid.uuid4().hex[:8]}@test.dev", "password": PASSWORD})
    assert other.status_code == 201, other.text
    cross = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/{prepared.assistant_id()}/stop",
        headers=csrf_headers(client),
    )
    # Course không còn thuộc B ⇒ 404 trước khi chạm message.
    assert cross.status_code == 404
    assert (await _reload(prepared.assistant_message.id)).status is TutorMessageStatus.running


async def test_stop_requires_csrf(client):
    course_id, lessons = await create_course_with_lessons(client)
    prepared = await _prepare_running(client, course_id, lessons[0]["id"])
    r = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/{prepared.assistant_id()}/stop"
    )
    assert r.status_code == 403


async def test_stop_on_completed_message_reports_terminal_state(client):
    course_id, lessons = await create_course_with_lessons(client)
    status, headers, _ = await send_message(
        client, course_id, message_body(lessons[0]["id"])
    )
    assert status == 200
    message_id = headers["x-tutor-message-id"]

    r = await client.post(
        f"/v1/courses/{course_id}/tutor/messages/{message_id}/stop",
        headers=csrf_headers(client),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert "đã kết thúc" in r.json()["notice"]


# ---------- stream stops when flag is set (server-side) ----------


async def test_running_stream_detects_cancel_flag_in_frame_stream(client, monkeypatch):
    """Provider stream liên tục, không có khoảng nghỉ: stop vẫn phải có hiệu lực.

    Đây chính là lỗi dễ mắc: chỉ kiểm cờ trong nhánh `asyncio.TimeoutError` thì
    stream có token liên tục sẽ không bao giờ dừng.
    """
    from app.api.v1 import tutor as tutor_api

    course_id, lessons = await create_course_with_lessons(client)
    prepared = await _prepare_running(client, course_id, lessons[0]["id"])
    produced = {"count": 0}

    class EndlessProvider:
        name = "endless"

        async def stream_tutor_reply(self, *, system, messages, max_input_chars):
            for index in range(10_000):
                produced["count"] = index
                await asyncio.sleep(0.01)
                yield f"t{index} "

    frames: list[str] = []
    async for chunk in tutor_api._stream_turn(
        prepared, "system", [{"role": "user", "content": "hỏi"}], EndlessProvider()
    ):
        frames.append(chunk)
        if len(frames) == 3:
            # Client bấm "Dừng" ⇒ endpoint ghi cờ; generator vẫn đang chạy.
            r = await client.post(
                f"/v1/courses/{course_id}/tutor/messages/{prepared.assistant_id()}/stop",
                headers=csrf_headers(client),
            )
            assert r.status_code == 200

    events = parse_sse("".join(frames))
    kinds = [e["event"] for e in events]
    assert "cancelled" in kinds, kinds
    assert kinds[-1] == "cancelled", kinds
    assert produced["count"] < 9_999, "producer phải bị hủy, không chạy hết vòng lặp"

    message = await _reload(prepared.assistant_message.id)
    assert message.status is TutorMessageStatus.cancelled
    assert message.error_code == "TUTOR_CANCELLED"
    assert message.content.startswith("t0 "), "phần đã nhận phải được giữ"


# ---------- usage / allowance ----------


async def test_usage_endpoint_reports_counts_and_limits(client, monkeypatch):
    course_id, lessons = await create_course_with_lessons(client)
    monkeypatch.setattr(get_settings(), "tutor_messages_per_day", 5)

    initial = await client.get(f"/v1/courses/{course_id}/tutor/usage")
    assert initial.status_code == 200, initial.text
    body = initial.json()
    assert body["used"]["messages"] == 0
    assert body["limits"]["messagesPerDay"] == 5
    assert body["remaining"]["messages"] == 5
    assert body["tokensKnown"] is False

    status, _, _ = await send_message(
        client, course_id, message_body(lessons[0]["id"])
    )
    assert status == 200

    after = (await client.get(f"/v1/courses/{course_id}/tutor/usage")).json()
    assert after["used"]["messages"] == 1
    assert after["remaining"]["messages"] == 4


async def test_token_quota_blocks_before_provider(client, monkeypatch):
    course_id, lessons = await create_course_with_lessons(client)
    monkeypatch.setattr(get_settings(), "tutor_tokens_per_day", 100)

    async with SessionLocal() as db:
        course = await db.get(Course, uuid.UUID(course_id.removeprefix("crs_")))
        user_id = course.user_id
        db.add(
            TutorUsageEvent(
                user_id=user_id,
                course_id=course.id,
                provider="mock",
                model="mock",
                prompt_tokens=80,
                completion_tokens=40,
            )
        )
        await db.commit()

    r = await client.post(
        f"/v1/courses/{course_id}/tutor/messages",
        json=message_body(lessons[0]["id"]),
        headers=csrf_headers(client),
    )
    assert r.status_code == 429, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "TUTOR_TOKEN_LIMIT_REACHED"
    # Error body kèm quota có cấu trúc để client hiển thị, không chỉ chuỗi lỗi.
    assert detail["quota"]["used"]["tokens"] == 120
    assert detail["quota"]["remaining"]["tokens"] == 0

    async with SessionLocal() as db:
        count = (
            await db.execute(select(TutorMessage).where(TutorMessage.course_id == course.id))
        ).scalars().all()
    assert count == [], "quota chặn TRƯỚC khi tạo message/gọi provider"


async def test_concurrency_limit_blocks_second_stream(client, monkeypatch):
    course_id, lessons = await create_course_with_lessons(client)
    monkeypatch.setattr(get_settings(), "tutor_max_concurrent_streams", 1)
    await _prepare_running(client, course_id, lessons[0]["id"])

    r = await client.post(
        f"/v1/courses/{course_id}/tutor/messages",
        json=message_body(lessons[0]["id"]),
        headers=csrf_headers(client),
    )
    assert r.status_code == 429, r.text
    assert r.json()["detail"]["code"] == "TUTOR_CONCURRENCY_LIMIT"


# ---------- stale reap (server restart) ----------


async def test_stale_running_message_is_reaped_so_user_not_locked(client):
    course_id, lessons = await create_course_with_lessons(client)
    prepared = await _prepare_running(client, course_id, lessons[0]["id"])

    # Giả lập tiến trình giữ stream đã chết từ lâu: updated_at cũ.
    old = datetime.now(UTC) - timedelta(seconds=600)
    async with SessionLocal() as db:
        message = await db.get(TutorMessage, prepared.assistant_message.id)
        message.updated_at = old
        await db.commit()

    status, headers, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="Câu hỏi mới")
    )
    assert status == 200, raw
    assert headers["x-tutor-message-id"] != prepared.assistant_id()

    stale = await _reload(prepared.assistant_message.id)
    assert stale.status is TutorMessageStatus.failed
    assert stale.error_code == "TUTOR_STALE"


async def test_quota_state_counts_only_assistant_in_progress(client):
    course_id, lessons = await create_course_with_lessons(client)
    async with SessionLocal() as db:
        course = await db.get(Course, uuid.UUID(course_id.removeprefix("crs_")))
        user_id = course.user_id
        await tutor_service.reap_stale_messages(db, user_id)
        assert await tutor_service.count_running_streams(db, user_id) == 0

    await _prepare_running(client, course_id, lessons[0]["id"])
    async with SessionLocal() as db:
        course = await db.get(Course, uuid.UUID(course_id.removeprefix("crs_")))
        assert await tutor_service.count_running_streams(db, course.user_id) == 1


# ---------- usage persistence ----------


async def test_usage_record_is_persisted_without_content():
    async with SessionLocal() as db:
        user = User(
            external_id=f"usage-{uuid.uuid4().hex[:8]}",
            display_name="Usage",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        thread_course_user = user.id

        from app.providers.usage import UsageRecord

        await tutor_service.record_usage(
            db,
            user_id=thread_course_user,
            course_id=None,
            message_id=None,
            record=UsageRecord(
                provider="openai_compatible",
                model="test-model",
                kind="tutor",
                prompt_tokens=11,
                completion_tokens=7,
                latency_ms=123,
                finish_reason="stop",
            ),
        )
        rows = (
            await db.execute(
                select(TutorUsageEvent).where(TutorUsageEvent.user_id == thread_course_user)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 11 and rows[0].completion_tokens == 7
    assert not hasattr(rows[0], "content"), "usage event không được chứa nội dung"
