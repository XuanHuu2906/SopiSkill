"""AI Tutor API (P3.0) — authenticated, owner-scoped SSE tutor.

Endpoints:
  POST /v1/courses/{courseId}/tutor/messages   → SSE stream (delta/done/error/heartbeat)
  GET  /v1/courses/{courseId}/tutor/threads    → danh sách thread của user trong course
  GET  /v1/courses/{courseId}/tutor/threads/{threadId} → lịch sử đầy đủ

Bảo mật:
  - Identity từ session (JWT cookie); course phải thuộc user ⇒ 404 nếu không.
  - `contextRef.lessonId` được resolve lại với `lesson.course_id == course.id`
    và `blockIndex` phải nằm trong biên public blocks ⇒ client không thể trỏ bài
    của user khác hay ép server đọc nội dung ngoài bài.
  - Request **không** nhận system prompt / lesson content / source content.
  - CSRF bắt buộc cho POST, rate limit riêng.
  - Stream không chứa secret; lỗi provider chỉ gửi mã + thông điệp chung.

Giới hạn đã biết (P3.0): không có resume `Last-Event-ID`; không có endpoint stop
server-side (P3.1). Client hủy stream thì server ghi trạng thái `cancelled` khi
phát hiện ngắt kết nối, nhưng không bảo đảm provider dừng tính phí tức thời.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import SessionLocal, get_db
from app.models import TutorMessageStatus, User
from app.providers import (
    ProviderBudgetError,
    ProviderConfigError,
    ProviderError,
    get_provider,
)
from app.schemas.schemas import (
    TutorMessageRequest,
    TutorThreadListOut,
    TutorThreadOut,
)
from app.services import course_service, sse, tutor_context, tutor_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["tutor"])

_CONFIG_ERROR = {
    "code": "TUTOR_NOT_CONFIGURED",
    "message": "Trợ giảng AI chưa được cấu hình hợp lệ trên server.",
}

# Giữ tham chiếu tới task nền: asyncio chỉ giữ weak ref, task không được ref
# có thể bị GC trước khi ghi xong trạng thái cuối.
_BACKGROUND: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)



def _require_enabled() -> None:
    if not tutor_service.tutor_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": tutor_service.TUTOR_DISABLED_CODE,
                "message": "Trợ giảng AI chưa được bật trên hệ thống này.",
            },
        )


def _provider():
    try:
        return get_provider()
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_CONFIG_ERROR
        ) from exc


def _stream_headers(prepared: tutor_service.PreparedTurn) -> dict[str, str]:
    """Cho client biết thread/message ngay từ header, trước byte SSE đầu tiên."""
    return {
        **sse.SSE_HEADERS,
        "X-Tutor-Thread-Id": prepared.thread_id(),
        "X-Tutor-Message-Id": prepared.assistant_id(),
    }


@router.post("/courses/{course_id}/tutor/messages")
async def send_tutor_message(
    course_id: str,
    body: TutorMessageRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    verify_csrf(request)
    rate_limit(request, "tutor_message", limit=30, window_seconds=60)
    rate_limit(request, "tutor_message_burst", limit=6, window_seconds=10)
    provider = _provider()
    course = await course_service.get_owned_course(db, course_id, user.id)

    prepared = await tutor_service.prepare_turn(db, course, user, body)
    settings = get_settings()

    # Retry cùng clientMessageId:
    #   - đã completed ⇒ replay nội dung đã lưu, TUYỆT ĐỐI không gọi provider.
    #   - failed/cancelled ⇒ báo lại trạng thái thật (không tự chạy lại).
    #   - pending/running ⇒ 409 MESSAGE_IN_PROGRESS (prepare_turn đã chặn).
    if prepared.assistant_message.status == TutorMessageStatus.completed:
        return _replay_response(prepared)
    if prepared.assistant_message.status in (
        TutorMessageStatus.failed,
        TutorMessageStatus.cancelled,
    ):
        return _terminal_error_response(prepared, prepared.assistant_message.status)

    source_titles = await tutor_service.linked_source_titles(db, course.id, user.id)
    system = tutor_context.build_tutor_system(
        lesson_title=prepared.lesson.title,
        blocks=prepared.blocks,
        block_index=prepared.block_index,
        linked_source_titles=source_titles,
        max_context_chars=settings.tutor_context_max_chars,
    )
    history_rows = await tutor_service.history_for_prompt(
        db,
        prepared.thread,
        exclude_assistant_id=prepared.assistant_message.id,
        limit=settings.tutor_history_max_messages,
    )
    history = tutor_context.build_history(
        history_rows, settings.tutor_history_max_messages
    )
    if not history or history[-1].get("role") != "user":
        history.append({"role": "user", "content": prepared.user_message.content})

    return StreamingResponse(
        _stream_turn(prepared, system, history, provider),
        media_type="text/event-stream; charset=utf-8",
        headers=_stream_headers(prepared),
    )


@router.get("/courses/{course_id}/tutor/threads", response_model=TutorThreadListOut)
async def list_threads(
    course_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await tutor_service.list_threads(
        db, course, user.id, limit=limit, offset=offset
    )


@router.get(
    "/courses/{course_id}/tutor/threads/{thread_id}", response_model=TutorThreadOut
)
async def get_thread(
    course_id: str,
    thread_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await tutor_service.get_thread_detail(db, course, user.id, thread_id)


def _replay_response(prepared: tutor_service.PreparedTurn) -> StreamingResponse:
    stream_id = prepared.stream_id()
    message_id = prepared.assistant_id()
    text = prepared.assistant_message.content or ""
    chunks: list[str] = []
    seq = 0
    if text:
        chunks.append(
            sse.frame(
                "delta",
                {
                    "streamId": stream_id,
                    "messageId": message_id,
                    "seq": seq,
                    "text": text,
                },
                event_id=sse.seq_id(stream_id, seq),
            )
        )
        seq += 1
    chunks.append(
        sse.frame(
            "done",
            {
                "streamId": stream_id,
                "messageId": message_id,
                "seq": seq,
                "finishReason": prepared.assistant_message.finish_reason or "stop",
                "replayed": True,
                "usage": {
                    "promptTokens": prepared.assistant_message.prompt_tokens,
                    "completionTokens": prepared.assistant_message.completion_tokens,
                },
            },
            event_id=sse.seq_id(stream_id, seq),
        )
    )

    async def body() -> AsyncIterator[str]:
        for chunk in chunks:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="text/event-stream; charset=utf-8",
        headers=_stream_headers(prepared),
    )


def _terminal_error_response(
    prepared: tutor_service.PreparedTurn, state: TutorMessageStatus
) -> StreamingResponse:
    stream_id = prepared.stream_id()
    code = (
        tutor_service.TUTOR_CANCELLED
        if state == TutorMessageStatus.cancelled
        else tutor_service.TUTOR_PROVIDER_ERROR
    )

    async def body() -> AsyncIterator[str]:
        yield sse.frame(
            "error",
            {
                "streamId": stream_id,
                "messageId": prepared.assistant_id(),
                "seq": 0,
                "code": code,
                "message": "Lượt trả lời trước đã kết thúc không thành công.",
                # Muốn thử lại, client phải tạo clientMessageId mới.
                "retryable": False,
                "replayed": True,
            },
            event_id=sse.seq_id(stream_id, 0),
        )

    return StreamingResponse(
        body(),
        media_type="text/event-stream; charset=utf-8",
        headers=_stream_headers(prepared),
    )


async def _persist_final_state(
    prepared: tutor_service.PreparedTurn, state: tutor_service.FinalState
) -> None:
    """Ghi trạng thái cuối bằng session riêng, không bị hủy theo response.

    Client ngắt kết nối làm Starlette cancel generator; task tách rời bảo đảm
    trạng thái thật (`completed`/`failed`/`cancelled`) vẫn được ghi, không để
    message treo `running` mãi.
    """
    async with SessionLocal() as session:
        try:
            await tutor_service.finalize(session, prepared.assistant_message.id, state)
        except Exception:  # noqa: BLE001
            logger.warning(
                "tutor finalize failed assistant=%s", prepared.assistant_message.id
            )


async def _persist_cancelled(prepared: tutor_service.PreparedTurn, content: str) -> None:
    async with SessionLocal() as session:
        try:
            await tutor_service.cancel_if_running(
                session, prepared.assistant_message.id, content
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "tutor cancel persist failed assistant=%s",
                prepared.assistant_message.id,
            )


async def _stream_turn(
    prepared: tutor_service.PreparedTurn,
    system: str,
    history: list[dict[str, str]],
    provider,
) -> AsyncIterator[str]:
    settings = get_settings()
    stream_id = prepared.stream_id()
    message_id = prepared.assistant_id()
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    collected: list[str] = []
    seq = 0
    terminal: tutor_service.FinalState | None = None
    persisted = False

    async with SessionLocal() as db:
        await tutor_service.mark_running(db, prepared.assistant_message.id)

    async def produce() -> None:
        try:
            async for piece in provider.stream_tutor_reply(
                system=system,
                messages=history,
                max_input_chars=settings.llm_max_input_chars,
            ):
                await queue.put(("delta", piece))
            await queue.put(("done", None))
        except ProviderError as exc:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(("provider_error", exc))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — biến mọi lỗi lạ thành SSE error có mã
            logger.warning("tutor stream crashed", exc_info=False)
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(("crash", None))

    producer = asyncio.create_task(produce())
    heartbeat = max(1.0, float(settings.tutor_heartbeat_seconds))
    deadline = time.monotonic() + max(1.0, float(settings.tutor_stream_timeout_seconds))

    try:
        while True:
            now = time.monotonic()
            if now >= deadline:
                terminal = tutor_service.FinalState(
                    status=TutorMessageStatus.failed,
                    content="".join(collected),
                    error_code=tutor_service.TUTOR_TIMEOUT,
                )
                yield sse.frame(
                    "error",
                    {
                        "streamId": stream_id,
                        "messageId": message_id,
                        "seq": seq,
                        "code": tutor_service.TUTOR_TIMEOUT,
                        "message": "Hết thời gian chờ câu trả lời.",
                        "retryable": True,
                    },
                    event_id=sse.seq_id(stream_id, seq),
                )
                break

            try:
                kind, value = await asyncio.wait_for(
                    queue.get(), timeout=min(heartbeat, deadline - now)
                )
            except asyncio.TimeoutError:
                # Heartbeat không chứa nội dung người học.
                yield sse.frame(
                    "heartbeat",
                    {"ts": int(time.time() * 1000)},
                    event_id=sse.seq_id(stream_id, seq),
                )
                seq += 1
                continue

            if kind == "delta":
                text = str(value or "")
                if not text:
                    continue
                collected.append(text)
                yield sse.frame(
                    "delta",
                    {
                        "streamId": stream_id,
                        "messageId": message_id,
                        "seq": seq,
                        "text": text,
                    },
                    event_id=sse.seq_id(stream_id, seq),
                )
                seq += 1
                continue

            if kind == "done":
                terminal = tutor_service.FinalState(
                    status=TutorMessageStatus.completed,
                    content="".join(collected),
                    finish_reason="stop",
                )
                break

            if kind == "provider_error":
                exc = value
                code = getattr(exc, "code", tutor_service.TUTOR_PROVIDER_ERROR)
                if isinstance(exc, ProviderBudgetError):
                    code = "TUTOR_BUDGET_EXCEEDED"
                terminal = tutor_service.FinalState(
                    status=TutorMessageStatus.failed,
                    content="".join(collected),
                    error_code=code,
                )
                yield sse.frame(
                    "error",
                    {
                        "streamId": stream_id,
                        "messageId": message_id,
                        "seq": seq,
                        "code": code,
                        "message": "Không lấy được câu trả lời từ mô hình. Vui lòng thử lại.",
                        "retryable": bool(getattr(exc, "retryable", False)),
                    },
                    event_id=sse.seq_id(stream_id, seq),
                )
                break

            # crash — lỗi ngoài taxonomy provider
            terminal = tutor_service.FinalState(
                status=TutorMessageStatus.failed,
                content="".join(collected),
                error_code=tutor_service.TUTOR_PROVIDER_ERROR,
            )
            yield sse.frame(
                "error",
                {
                    "streamId": stream_id,
                    "messageId": message_id,
                    "seq": seq,
                    "code": tutor_service.TUTOR_PROVIDER_ERROR,
                    "message": "Trợ giảng gặp lỗi không xác định.",
                    "retryable": True,
                },
                event_id=sse.seq_id(stream_id, seq),
            )
            break

        assert terminal is not None
        await _persist_final_state(prepared, terminal)
        persisted = True
        if terminal.status == TutorMessageStatus.completed:
            yield sse.frame(
                "done",
                {
                    "streamId": stream_id,
                    "messageId": message_id,
                    "seq": seq,
                    "finishReason": terminal.finish_reason,
                    "replayed": False,
                },
                event_id=sse.seq_id(stream_id, seq),
            )
    finally:
        if not producer.done():
            producer.cancel()
        with contextlib.suppress(BaseException):
            await producer
        if not persisted:
            # Client ngắt giữa stream (hoặc lỗi trước terminal): ghi `cancelled`
            # bằng task tách rời — không tuyên bố đã xong, không để treo `running`.
            _spawn(_persist_cancelled(prepared, "".join(collected)))
