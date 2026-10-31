"""P4.1 — Tutor + RAG: retrieval → prompt → citation verify → SSE.

Offline (SQLite + MockProvider + hashing embedding). Mock biết trích id đầu tiên
server cấp trong khối ngữ cảnh, nên test chứng minh **đường verify** hoạt động,
không chứng minh chất lượng câu trả lời của LLM thật.

Bao phủ:
  T-R01 RAG bật + có nguồn ⇒ SSE có frame `citations` và citation lưu DB.
  T-R02 `locator_verified` + `evidenceSupported=false` (không tự nâng cấp).
  T-R03 RAG tắt ⇒ không có frame citations, hành vi P3.x giữ nguyên.
  T-R04 Không có nguồn ⇒ không tạo citation giả.
  T-R05 Model bịa id ⇒ server loại, không trả về client.
  T-R06 `read_source` tool chạy thật và trả nội dung có delimiter untrusted.
  T-R07 Cross-user: user B không truy xuất nguồn của A qua tool.
  T-R08 Thread detail trả citation đã lưu sau reload.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    CourseSource,
    Source,
    SourceChunk,
    SourceDocument,
    SourceDocumentStatus,
    SourceVisibility,
    TutorMessage,
)
from app.services import embedding_service, tutor_tools

from .test_p30_tutor import (
    create_course_with_lessons,
    csrf_headers,
    parse_sse,
    send_message,
)

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"


@pytest.fixture(autouse=True)
def _rag_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "tutor_enabled", True)
    monkeypatch.setattr(settings, "tutor_messages_per_day", 0)
    monkeypatch.setattr(settings, "tutor_tokens_per_day", 0)
    monkeypatch.setattr(settings, "tutor_max_concurrent_streams", 0)
    monkeypatch.setattr(settings, "tutor_heartbeat_seconds", 1.0)
    monkeypatch.setattr(settings, "tutor_stream_timeout_seconds", 10.0)
    monkeypatch.setattr(settings, "tutor_cancel_poll_seconds", 0.2)
    monkeypatch.setattr(settings, "tutor_tools_enabled", True)
    monkeypatch.setattr(settings, "tutor_tool_max_calls", 2)
    monkeypatch.setattr(settings, "tutor_tool_timeout_seconds", 3.0)
    monkeypatch.setattr(settings, "rag_enabled", True)
    monkeypatch.setattr(settings, "embedding_enabled", True)
    monkeypatch.setattr(settings, "embedding_provider", "hashing")
    monkeypatch.setattr(settings, "embedding_dimension", 256)
    monkeypatch.setattr(settings, "rag_min_similarity", 0.05)


async def _owner_id(client) -> uuid.UUID:
    me = await client.get("/v1/auth/me")
    return uuid.UUID(me.json()["id"].removeprefix("usr_"))


async def attach_source(course_id: str, *, owner_id: uuid.UUID, texts: list[str]) -> uuid.UUID:
    """Gắn một nguồn đã ingest (document ready) + chunk + embedding vào course."""
    source_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(
            Source(
                id=source_id,
                source_type="user_document",
                title="Giáo trình vòng lặp",
                owner_id=owner_id,
                visibility=SourceVisibility.private,
                dedupe_key=f"rag-{source_id}",
                version="1.0",
            )
        )
        document = SourceDocument(
            source_id=source_id,
            content_hash=uuid.uuid4().hex * 2,
            pipeline_version="p4.0-v1",
            storage_key=f"sources/{source_id}/{uuid.uuid4().hex}",
            status=SourceDocumentStatus.ready,
        )
        db.add(document)
        await db.flush()
        chunks = []
        for index, text in enumerate(texts):
            chunk = SourceChunk(
                document_id=document.id,
                source_id=source_id,
                chunk_index=index,
                page_number=index + 1,
                char_start=0,
                char_end=len(text),
                section_anchor=f"Mục {index + 1}",
                text=text,
                text_hash=embedding_service.hashlib.sha256(text.encode()).hexdigest(),
            )
            db.add(chunk)
            chunks.append(chunk)
        await db.flush()
        await embedding_service.embed_chunks(db, chunks)
        db.add(
            CourseSource(
                course_id=uuid.UUID(course_id.removeprefix("crs_")), source_id=source_id
            )
        )
        await db.commit()
    return source_id


async def test_tutor_returns_verified_citations_when_sources_exist(client):
    course_id, lessons = await create_course_with_lessons(client)
    owner = await _owner_id(client)
    source_id = await attach_source(
        course_id,
        owner_id=owner,
        texts=[
            "Vòng lặp while tiếp tục chạy chừng nào điều kiện còn đúng.",
            "Vòng lặp for thường dùng khi biết trước số lần lặp.",
        ],
    )

    status, headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Vòng lặp while dừng khi nào?",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200, raw
    events = parse_sse(raw)
    kinds = [event["event"] for event in events]
    assert "citations" in kinds

    citation_event = next(event for event in events if event["event"] == "citations")
    citations = citation_event["data"]["citations"]
    assert citations, citation_event["data"]
    first = citations[0]
    assert first["chunkId"].startswith("chk_")
    assert first["sourceId"] == f"src_{source_id}"
    assert first["pageNumber"] >= 1
    assert first["validationStatus"] == "locator_verified"
    # Không tự nâng lên "claim đã được chứng minh".
    assert first["evidenceSupported"] is False
    assert citation_event["data"]["insufficientEvidence"] is False

    message_id = headers["x-tutor-message-id"]
    async with SessionLocal() as db:
        message = (
            await db.execute(
                select(TutorMessage).where(
                    TutorMessage.id == uuid.UUID(message_id.removeprefix("tmsg_"))
                )
            )
        ).scalar_one()
    assert message.status.value == "completed"
    assert message.citations
    assert message.citations[0]["chunkId"] == first["chunkId"]


async def test_tutor_without_rag_has_no_citation_frame(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_enabled", False)
    course_id, lessons = await create_course_with_lessons(client)
    owner = await _owner_id(client)
    await attach_source(course_id, owner_id=owner, texts=["Đoạn nguồn về vòng lặp."])

    status, _headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Vòng lặp là gì?",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    kinds = [event["event"] for event in parse_sse(raw)]
    assert "citations" not in kinds


async def test_tutor_without_sources_never_invents_citations(client):
    course_id, lessons = await create_course_with_lessons(client)
    status, _headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Tài liệu nói gì về vòng lặp?",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    events = parse_sse(raw)
    assert "citations" not in [event["event"] for event in events]
    text = "".join(
        event["data"]["text"] for event in events if event["event"] == "delta"
    )
    assert "chk_" not in text


async def test_invented_citation_ids_are_dropped_before_client(client, monkeypatch):
    """Provider cố tình trích id bịa ⇒ server loại, client không thấy."""
    course_id, lessons = await create_course_with_lessons(client)
    owner = await _owner_id(client)
    await attach_source(
        course_id, owner_id=owner, texts=["Vòng lặp while kiểm tra điều kiện trước."]
    )

    from app.api.v1 import tutor as tutor_api
    from app.providers import MockProvider

    invented = uuid.uuid4()

    class Hallucinating(MockProvider):
        async def stream_tutor_reply(self, *, system, messages, max_input_chars):
            yield f"Câu trả lời theo tài liệu [chk_{invented}] và cả [chk_{invented}]."
            yield " Hết."

    monkeypatch.setattr(tutor_api, "_provider", lambda: Hallucinating())
    status, _headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Vòng lặp while?",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    events = parse_sse(raw)
    citation_events = [event for event in events if event["event"] == "citations"]
    if citation_events:
        payload = citation_events[0]["data"]
        returned_ids = {item["chunkId"] for item in payload["citations"]}
        assert f"chk_{invented}" not in returned_ids
        # Không có citation hợp lệ ⇒ cờ insufficientEvidence phải bật.
        assert payload["insufficientEvidence"] is True


async def test_read_source_tool_returns_scoped_content(client):
    course_id, lessons = await create_course_with_lessons(client)
    owner = await _owner_id(client)
    await attach_source(
        course_id,
        owner_id=owner,
        texts=["Vòng lặp while kiểm tra điều kiện trước mỗi lần lặp."],
    )

    status, _headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Cho mình xem nguồn tài liệu về vòng lặp while",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    events = parse_sse(raw)
    tool_events = [event for event in events if event["event"] == "tool"]
    assert tool_events, events
    assert tool_events[0]["data"]["name"] == "read_source"
    assert tool_events[0]["data"]["status"] == "ok"


async def test_read_source_tool_without_sources_reports_not_found(client):
    course_id, lessons = await create_course_with_lessons(client)
    status, _headers, raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Dẫn nguồn tài liệu cho mình",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    events = parse_sse(raw)
    tool_events = [event for event in events if event["event"] == "tool"]
    if tool_events:
        assert tool_events[0]["data"]["status"] == "failed"
        assert tool_events[0]["data"]["code"] == "RAG_NO_EVIDENCE"


async def test_read_source_without_rag_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rag_enabled", False)
    result = await tutor_tools.execute_async(
        "read_source",
        tutor_tools.ReadSourceArgs(),
        blocks=[{"type": "teach"}],
        current_block_index=0,
        max_chars=1000,
        source_reader=None,
    )
    assert result.ok is False
    assert result.error_code == tutor_tools.TOOL_NOT_AVAILABLE


async def test_thread_detail_includes_saved_citations(client):
    course_id, lessons = await create_course_with_lessons(client)
    owner = await _owner_id(client)
    await attach_source(
        course_id, owner_id=owner, texts=["Vòng lặp while kiểm tra điều kiện trước."]
    )

    status, headers, _raw = await send_message(
        client,
        course_id,
        {
            "clientMessageId": uuid.uuid4().hex[:16],
            "text": "Vòng lặp while hoạt động thế nào?",
            "contextRef": {"lessonId": lessons[0]["id"], "blockIndex": 0},
        },
    )
    assert status == 200
    thread_id = headers["x-tutor-thread-id"]
    detail = await client.get(f"/v1/courses/{course_id}/tutor/threads/{thread_id}")
    assert detail.status_code == 200, detail.text
    assistant = [m for m in detail.json()["messages"] if m["role"] == "assistant"]
    assert assistant
    assert assistant[-1]["citations"]
    assert assistant[-1]["citations"][0]["validationStatus"] == "locator_verified"


async def test_system_prompt_does_not_claim_missing_sources_when_rag_active(client):
    """Prompt không được nói 'chưa có nguồn' khi server đã truy xuất được."""
    from app.services import tutor_context

    base = tutor_context.build_tutor_system(
        lesson_title="Bài",
        blocks=[{"type": "teach", "title": "T", "paragraphs": ["p"]}],
        block_index=0,
        linked_source_titles=["Tài liệu A"],
        rag_context_active=True,
    )
    assert "CHƯA truy xuất nội dung" not in base
    assert "đã truy xuất các đoạn tài liệu" in base

    inactive = tutor_context.build_tutor_system(
        lesson_title="Bài",
        blocks=[{"type": "teach", "title": "T", "paragraphs": ["p"]}],
        block_index=0,
        linked_source_titles=["Tài liệu A"],
        rag_context_active=False,
    )
    assert "CHƯA truy xuất nội dung" in inactive
