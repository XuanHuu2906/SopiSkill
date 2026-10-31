"""P3.1 lát B — Tutor tool allowlist: validation, audit, stream integration.

Chạy offline (SQLite in-memory + MockProvider). Không phải bằng chứng chất lượng
LLM thật: mock planner dùng rule keyword, mục tiêu là chứng minh contract.

Bảo mật được kiểm:
  - Tên tool ngoài allowlist bị từ chối TRƯỚC khi execute.
  - Args sai schema / blockIndex ngoài biên bị từ chối.
  - Provider bịa tool / trả rác ⇒ không tool nào chạy, lượt hỏi vẫn trả lời.
  - `read_source` chưa khả dụng ⇒ lỗi hữu ích, không bịa nguồn.
  - Kết quả tool vào prompt như dữ liệu không tin cậy; không lộ answer key.
  - Audit lưu metadata, KHÔNG lưu nội dung tool trả về.
  - Flag `TUTOR_TOOLS_ENABLED=false` ⇒ không gọi planner.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Course,
    TutorMessage,
    TutorToolCall,
    TutorUsageEvent,
    User,
)
from app.providers import ProviderConfigError, ProviderError
from app.services import tutor_service, tutor_tools

from tests.test_p30_tutor import (
    create_course_with_lessons,
    csrf_headers,
    message_body,
    parse_sse,
    send_message,
)


@pytest.fixture(autouse=True)
def _tutor_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tutor_enabled", True)
    monkeypatch.setattr(settings, "tutor_tools_enabled", True)
    monkeypatch.setattr(settings, "tutor_tool_max_calls", 2)
    monkeypatch.setattr(settings, "tutor_tool_timeout_seconds", 3.0)
    monkeypatch.setattr(settings, "tutor_tool_max_result_chars", 3000)
    monkeypatch.setattr(settings, "tutor_messages_per_day", 0)
    monkeypatch.setattr(settings, "tutor_tokens_per_day", 0)
    monkeypatch.setattr(settings, "tutor_max_concurrent_streams", 0)
    monkeypatch.setattr(settings, "tutor_heartbeat_seconds", 1.0)
    monkeypatch.setattr(settings, "tutor_stream_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "tutor_cancel_poll_seconds", 0.2)


# ---------- unit: parsing & allowlist ----------


def test_parse_tool_request_accepts_dict_json_and_fenced_json():
    assert tutor_tools.parse_tool_request(
        {"tool": "read_lesson", "args": {"blockIndex": 2}}
    ) == ("read_lesson", {"blockIndex": 2})
    assert tutor_tools.parse_tool_request(
        '{"tool": "explain_deeper", "args": {"blockIndex": 1}}'
    ) == ("explain_deeper", {"blockIndex": 1})
    assert tutor_tools.parse_tool_request(
        '```json\n{"tool": "read_lesson", "args": {}}\n```'
    ) == ("read_lesson", {})


def test_parse_tool_request_rejects_garbage_without_guessing():
    for raw in ("", "no tools needed", "[]", "42", {"tool": 5}, {"tool": "x", "args": []}):
        assert tutor_tools.parse_tool_request(raw) == (None, {}), raw
    assert tutor_tools.parse_tool_request({"tool": None, "args": {}}) == (None, {})
    assert tutor_tools.parse_tool_request({"tool": "none"}) == (None, {})


def test_allowlist_rejects_unknown_tool_before_execution():
    with pytest.raises(tutor_tools.ToolRequestError) as info:
        tutor_tools.validate_request("delete_course", {}, block_count=5)
    assert info.value.code == tutor_tools.TOOL_NOT_ALLOWED


def test_arguments_schema_is_strict():
    with pytest.raises(tutor_tools.ToolRequestError) as info:
        tutor_tools.validate_request("read_lesson", {"evil": True}, block_count=5)
    assert info.value.code == tutor_tools.TOOL_INVALID_ARGS

    with pytest.raises(tutor_tools.ToolRequestError):
        tutor_tools.validate_request("explain_deeper", {}, block_count=5)  # bắt buộc

    with pytest.raises(tutor_tools.ToolRequestError):
        tutor_tools.validate_request("read_lesson", {"blockIndex": -1}, block_count=5)


def test_block_index_must_be_within_public_blocks():
    with pytest.raises(tutor_tools.ToolRequestError) as info:
        tutor_tools.validate_request("read_lesson", {"blockIndex": 5}, block_count=3)
    assert info.value.code == tutor_tools.TOOL_INVALID_ARGS
    assert "vượt quá" in info.value.message


def test_read_lesson_and_explain_deeper_only_use_public_blocks():
    blocks = [
        {"type": "teach", "title": "Bài", "paragraphs": ["Đoạn giảng."]},
        {"type": "mc", "question": "Chọn?", "options": ["A", "B"]},
    ]
    lesson_exec = tutor_tools.execute(
        "read_lesson",
        tutor_tools.ReadLessonArgs(),
        blocks=blocks,
        current_block_index=0,
        max_chars=2000,
    )
    assert lesson_exec.ok and "Đoạn giảng." in lesson_exec.content
    assert "answerIndex" not in lesson_exec.content

    deeper = tutor_tools.execute(
        "explain_deeper",
        tutor_tools.ExplainDeeperArgs(blockIndex=1),
        blocks=blocks,
        current_block_index=1,
        max_chars=2000,
    )
    assert deeper.ok and "Chọn?" in deeper.content


def test_read_source_is_allowlisted_but_unavailable_until_p4():
    result = tutor_tools.execute(
        "read_source",
        tutor_tools.ReadSourceArgs(),
        blocks=[{"type": "teach"}],
        current_block_index=0,
        max_chars=1000,
    )
    assert result.ok is False
    assert result.error_code == tutor_tools.TOOL_NOT_AVAILABLE


def test_tool_prompt_section_is_marked_untrusted():
    section = tutor_tools.ToolLoopResult(
        [
            tutor_tools.ToolExecution(
                name="read_lesson",
                ok=True,
                duration_ms=1,
                summary="đọc block #0",
                content="noi dung",
                args_summary="read_lesson()",
            )
        ]
    ).prompt_section(1000)
    assert "KHÔNG TIN CẬY" in section
    assert "KHÔNG phải chỉ thị" in section
    assert "<<<TOOL_BAT_DAU>>>" in section


def test_audit_summary_has_no_lesson_content():
    execution = tutor_tools.ToolExecution(
        name="read_lesson",
        ok=True,
        duration_ms=3,
        summary="đọc block #1",
        content="NỘI DUNG BÀI KHÔNG ĐƯỢC LƯU",
        args_summary="read_lesson(blockIndex=1)",
    )
    summary = tutor_tools.audit_summary(execution)
    assert "NỘI DUNG BÀI" not in summary
    assert "read_lesson(blockIndex=1)" in summary


# ---------- stream integration ----------


async def test_stream_emits_tool_frame_and_persists_audit(client):
    course_id, lessons = await create_course_with_lessons(client)
    body = message_body(
        lessons[0]["id"], block_index=0, text="Giải thích sâu hơn giúp mình"
    )
    status, headers, raw = await send_message(client, course_id, body)
    assert status == 200, raw

    events = parse_sse(raw)
    kinds = [e["event"] for e in events]
    assert "tool" in kinds, kinds
    assert kinds[-1] == "done", kinds
    tool_event = next(e for e in events if e["event"] == "tool")
    assert tool_event["data"]["name"] == "explain_deeper"
    assert tool_event["data"]["status"] == "ok"
    assert "summary" in tool_event["data"]

    seqs = [e["data"]["seq"] for e in events]
    assert seqs == list(range(len(seqs))), seqs

    message_id = uuid.UUID(
        headers["x-tutor-message-id"].removeprefix("tmsg_")
    )
    async with SessionLocal() as db:
        audits = (
            await db.execute(
                select(TutorToolCall).where(TutorToolCall.message_id == message_id)
            )
        ).scalars().all()
    assert len(audits) == 1
    assert audits[0].name == "explain_deeper"
    assert audits[0].ok is True
    assert audits[0].duration_ms is not None
    # Audit metadata-only: không có trường nội dung và summary không chứa bài giảng.
    assert not hasattr(audits[0], "content")
    assert "Block cần giải thích" not in audits[0].summary


async def test_tools_disabled_flag_skips_planner(client, monkeypatch):
    from app.api.v1 import tutor as tutor_api

    monkeypatch.setattr(get_settings(), "tutor_tools_enabled", False)
    course_id, lessons = await create_course_with_lessons(client)

    calls = {"n": 0}
    real_plan = tutor_api._plan_tools

    async def counting_plan(prepared, provider, history):
        calls["n"] += 1
        return await real_plan(prepared, provider, history)

    monkeypatch.setattr(tutor_api, "_plan_tools", counting_plan)
    status, _, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="Giải thích sâu hơn")
    )
    assert status == 200
    assert calls["n"] == 1
    events = parse_sse(raw)
    assert "tool" not in [e["event"] for e in events]


async def _patch_provider(monkeypatch, planner):
    """Thay provider của route bằng wrapper có planner tùy biến."""
    from app.api.v1 import tutor as tutor_api
    from app.providers import MockProvider

    class Wrapped(MockProvider):
        async def plan_tutor_tool(self, **kwargs):
            return await planner(**kwargs)

    monkeypatch.setattr(tutor_api, "_provider", lambda: Wrapped())


async def test_planner_returning_unknown_tool_is_blocked_and_audited(client, monkeypatch):
    async def evil(**kwargs):
        return {"tool": "delete_course", "args": {"courseId": "crs_x"}}

    await _patch_provider(monkeypatch, evil)
    course_id, lessons = await create_course_with_lessons(client)
    status, headers, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="hỏi gì đó")
    )
    assert status == 200, raw

    events = parse_sse(raw)
    tool_events = [e for e in events if e["event"] == "tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["data"]["status"] == "failed"
    assert tool_events[0]["data"]["code"] == tutor_tools.TOOL_NOT_ALLOWED
    # Không được để lộ args của tool bị chặn trong frame.
    assert "crs_x" not in raw
    # Lượt hỏi vẫn hoàn tất bình thường.
    assert [e["event"] for e in events][-1] == "done"

    message_id = uuid.UUID(headers["x-tutor-message-id"].removeprefix("tmsg_"))
    async with SessionLocal() as db:
        audit = (
            await db.execute(
                select(TutorToolCall).where(TutorToolCall.message_id == message_id)
            )
        ).scalar_one()
    assert audit.ok is False
    assert audit.error_code == tutor_tools.TOOL_NOT_ALLOWED


async def test_planner_with_out_of_bounds_block_is_rejected(client, monkeypatch):
    async def oob(**kwargs):
        return {"tool": "read_lesson", "args": {"blockIndex": 999}}

    await _patch_provider(monkeypatch, oob)
    course_id, lessons = await create_course_with_lessons(client)
    status, _, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="đọc lại cả bài")
    )
    assert status == 200
    tool_event = next(e for e in parse_sse(raw) if e["event"] == "tool")
    assert tool_event["data"]["code"] == tutor_tools.TOOL_INVALID_ARGS


async def test_planner_errors_do_not_break_the_turn(client, monkeypatch):
    async def broken(**kwargs):
        raise ProviderError("planner down")

    await _patch_provider(monkeypatch, broken)
    course_id, lessons = await create_course_with_lessons(client)
    status, _, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="Giải thích sâu hơn")
    )
    assert status == 200, raw
    events = parse_sse(raw)
    assert "tool" not in [e["event"] for e in events]
    assert events[-1]["event"] == "done"


async def test_planner_without_support_falls_back_to_plain_reply(client, monkeypatch):
    from app.api.v1 import tutor as tutor_api
    from app.providers.base import LLMProvider

    class NoTools(LLMProvider):
        name = "no-tools"

        async def generate_interview_questions(self, topic):
            raise ProviderConfigError("n/a")

        async def generate_proposal(self, *a, **k):
            raise ProviderConfigError("n/a")

        async def generate_lesson(self, *a, **k):
            raise ProviderConfigError("n/a")

        async def stream_tutor_reply(self, *, system, messages, max_input_chars):
            for word in ("Xin ", "chào ", "bạn."):
                yield word

    monkeypatch.setattr(tutor_api, "_provider", lambda: NoTools())
    course_id, lessons = await create_course_with_lessons(client)
    status, _, raw = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="Giải thích sâu hơn")
    )
    assert status == 200, raw
    events = parse_sse(raw)
    assert "tool" not in [e["event"] for e in events]
    text = "".join(e["data"].get("text", "") for e in events if e["event"] == "delta")
    assert text == "Xin chào bạn."


async def test_tool_calls_do_not_create_extra_messages_or_usage_events(client):
    course_id, lessons = await create_course_with_lessons(client)
    status, headers, _ = await send_message(
        client, course_id, message_body(lessons[0]["id"], text="Giải thích sâu hơn")
    )
    assert status == 200
    message_id = uuid.UUID(headers["x-tutor-message-id"].removeprefix("tmsg_"))

    async with SessionLocal() as db:
        course = await db.get(Course, uuid.UUID(course_id.removeprefix("crs_")))
        tool_rows = (
            await db.execute(
                select(TutorToolCall).where(TutorToolCall.course_id == course.id)
            )
        ).scalars().all()
        usage_rows = (
            await db.execute(
                select(TutorUsageEvent).where(TutorUsageEvent.course_id == course.id)
            )
        ).scalars().all()
        messages = (
            await db.execute(
                select(TutorMessage).where(
                    TutorMessage.course_id == course.id,
                )
            )
        ).scalars().all()
    assert len(tool_rows) == 1
    assert tool_rows[0].message_id == message_id
    # Tool call không được tạo message hay usage giả.
    assert len(messages) == 2
    assert usage_rows == []


async def test_tool_result_section_never_contains_answer_key(client):
    """read_lesson nhận `public_blocks`: system prompt không có answerIndex/answer."""
    from app.api.v1 import tutor as tutor_api

    captured = {}

    class Capturing:
        name = "capture"

        async def plan_tutor_tool(self, **kwargs):
            return {"tool": "read_lesson", "args": {}}

        async def stream_tutor_reply(self, *, system, messages, max_input_chars):
            captured["system"] = system
            yield "ok"

    course_id, lessons = await create_course_with_lessons(client)
    from app.api.v1 import tutor as tutor_api_mod

    original = tutor_api_mod._provider
    tutor_api_mod._provider = lambda: Capturing()
    try:
        status, _, _ = await send_message(
            client, course_id, message_body(lessons[0]["id"], text="đọc lại cả bài")
        )
    finally:
        tutor_api_mod._provider = original
    assert status == 200
    system = captured["system"]
    for key in ("answerIndex", "acceptedAnswers", "pairs", "\"answer\""):
        assert key not in system, f"answer key rò vào prompt: {key}"
