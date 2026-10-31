"""AI Tutor API (P3.1) — authenticated, owner-scoped SSE tutor.

Endpoints:
  POST /v1/courses/{courseId}/tutor/messages   → SSE stream (delta/done/error/heartbeat)
  POST /v1/courses/{courseId}/tutor/messages/{messageId}/stop → cờ dừng server-side
  GET  /v1/courses/{courseId}/tutor/usage      → trạng thái allowance 24h
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

Replay (P3.1.5, quyết định tường minh): **không hỗ trợ resume `Last-Event-ID`**
vì không có event log bền vững. Mất mạng giữa stream ⇒ client tải lại lịch sử;
`replaySupported=false` được trả trong thread detail để không hứa quá khả năng.

Cancel (P3.1.4): stop là **best-effort có kiểm soát**. Server ghi cờ
`cancel_requested_at`, vòng stream thấy cờ thì dừng producer và ghi `cancelled`
kèm phần đã nhận. Không xóa chi phí/token đã phát sinh ở provider.
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
from app.providers.usage import UsageCollector, collect_usage
from app.schemas.schemas import (
    TutorMessageRequest,
    TutorStopOut,
    TutorThreadListOut,
    TutorThreadOut,
    TutorUsageOut,
)
from app.services import course_service, sse, tutor_context, tutor_service, tutor_tools

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["tutor"])

_CONFIG_ERROR = {
    "code": "TUTOR_NOT_CONFIGURED",
    "message": "Trợ giảng AI chưa được cấu hình hợp lệ trên server.",
}

# Giữ tham chiếu tới task nền: asyncio chỉ giữ weak ref, task không được ref
# có thể bị GC trước khi ghi xong trạng thái cuối.
_BACKGROUND: set[asyncio.Task] = set()

# Trần chờ producer đóng generator (giây). Provider không hợp tác với
# CancelledError không được phép treo kết nối của người học vô hạn.
_PRODUCER_JOIN_TIMEOUT = 5.0


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


@router.get("/courses/{course_id}/tutor/usage", response_model=TutorUsageOut)
async def get_tutor_usage(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Allowance 24h của user. Không gọi provider, không tiêu quota."""
    _require_enabled()
    course = await course_service.get_owned_course(db, course_id, user.id)
    # Dọn message mồ côi rồi mới đếm: nếu không commit, thay đổi bị rollback khi
    # session đóng và user vẫn thấy stream "đang chạy" không tồn tại.
    if await tutor_service.reap_stale_messages(db, user.id):
        await db.commit()
    return {"courseId": f"crs_{course.id}", **await tutor_service.quota_state(db, user.id)}


@router.post(
    "/courses/{course_id}/tutor/messages/{message_id}/stop", response_model=TutorStopOut
)
async def stop_tutor_message(
    course_id: str,
    message_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Yêu cầu dừng một câu trả lời đang stream (best-effort, owner-scoped)."""
    _require_enabled()
    verify_csrf(request)
    rate_limit(request, "tutor_stop", limit=60, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await tutor_service.request_cancel(db, course, user.id, message_id)


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


async def _cancel_requested(assistant_id) -> bool:
    """Đọc cờ stop bằng session riêng (không giữ transaction của request)."""
    try:
        async with SessionLocal() as session:
            return await tutor_service.is_cancel_requested(session, assistant_id)
    except Exception:  # noqa: BLE001 — lỗi đọc cờ không được làm chết stream
        logger.warning("tutor cancel flag read failed assistant=%s", assistant_id)
        return False


async def _persist_usage(
    prepared: tutor_service.PreparedTurn, collector: UsageCollector
) -> None:
    """Ghi metadata usage (token/latency) — không ghi prompt hay nội dung."""
    async with SessionLocal() as session:
        for record in collector.records:
            try:
                await tutor_service.record_usage(
                    session,
                    user_id=prepared.thread.user_id,
                    course_id=prepared.thread.course_id,
                    message_id=prepared.assistant_message.id,
                    record=record,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "tutor usage persist failed assistant=%s",
                    prepared.assistant_message.id,
                )
                await session.rollback()


async def _persist_tool_audit(
    prepared: tutor_service.PreparedTurn, result: tutor_tools.ToolLoopResult
) -> None:
    """Lưu audit tool read-only. Không lưu nội dung tool trả về."""
    if not result.executions:
        return
    async with SessionLocal() as session:
        for execution in result.executions:
            try:
                await tutor_service.record_tool_call(
                    session,
                    user_id=prepared.thread.user_id,
                    course_id=prepared.thread.course_id,
                    message_id=prepared.assistant_message.id,
                    name=execution.name,
                    ok=execution.ok,
                    duration_ms=execution.duration_ms,
                    summary=tutor_tools.audit_summary(execution),
                    error_code=execution.error_code,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "tutor tool audit persist failed assistant=%s",
                    prepared.assistant_message.id,
                )
                await session.rollback()


async def _plan_tools(
    prepared: tutor_service.PreparedTurn,
    provider,
    history: list[dict[str, str]],
) -> tutor_tools.ToolLoopResult:
    """Chạy tối đa `TUTOR_TOOL_MAX_CALLS` vòng plan→validate→execute.

    Bất biến bảo mật:
      - Tên tool ngoài allowlist ⇒ dừng, không execute (`TUTOR_TOOL_NOT_ALLOWED`).
      - Args sai schema / blockIndex ngoài biên ⇒ dừng, không execute.
      - Tool chưa khả dụng (read_source trước P4.1) ⇒ trả lỗi hữu ích, không bịa.
      - Planner lỗi/timeout ⇒ coi như "không dùng tool", lượt hỏi vẫn trả lời.
    """
    settings = get_settings()
    result = tutor_tools.ToolLoopResult()
    if not settings.tutor_tools_enabled:
        return result

    available = [name for name, spec in tutor_tools.TOOLS.items()]
    remaining = max(0, int(settings.tutor_tool_max_calls or 0))
    history_msgs = list(history)

    for _ in range(remaining):
        try:
            raw = await asyncio.wait_for(
                provider.plan_tutor_tool(
                    system=tutor_tools.TOOL_PLANNER_SYSTEM,
                    messages=history_msgs,
                    available_tools=available,
                    max_input_chars=settings.llm_max_input_chars,
                ),
                timeout=max(0.5, float(settings.tutor_tool_timeout_seconds or 3.0)),
            )
        except asyncio.TimeoutError:
            logger.warning("tutor tool plan timeout assistant=%s", prepared.assistant_message.id)
            break
        except ProviderError as exc:
            logger.warning("tutor tool plan provider error code=%s", exc.code)
            break
        except Exception:  # noqa: BLE001
            logger.warning("tutor tool plan crashed", exc_info=False)
            break

        name, args = tutor_tools.parse_tool_request(raw)
        if name is None:
            break
        try:
            parsed = tutor_tools.validate_request(
                name, args, block_count=len(prepared.blocks)
            )
        except tutor_tools.ToolRequestError as exc:
            result.executions.append(
                tutor_tools.ToolExecution(
                    name=name,
                    ok=False,
                    duration_ms=0,
                    summary=exc.message,
                    error_code=exc.code,
                    args_summary=f"{name}(rejected)",
                )
            )
            break

        execution = tutor_tools.execute(
            name,
            parsed,
            blocks=prepared.blocks,
            current_block_index=prepared.block_index,
            max_chars=settings.tutor_tool_max_result_chars,
        )
        result.executions.append(execution)
        history_msgs.append(
            {
                "role": "user",
                "content": tutor_tools.audit_summary(execution),
            }
        )
        # Một tool đã đủ ngữ cảnh; không lặp vô hạn vì model có thể xin mãi.
        break

    return result


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
    usage = UsageCollector()

    # Planner cũng là một lời gọi provider → phải nằm trong collector để token của
    # nó được tính vào allowance, không bị "ẩn" khỏi trần token.
    with collect_usage(usage):
        tool_result = await _plan_tools(prepared, provider, history)
    if tool_result.executions:
        for execution in tool_result.executions:
            yield sse.frame(
                "tool",
                {
                    "streamId": stream_id,
                    "messageId": message_id,
                    "seq": seq,
                    "name": execution.name,
                    "status": "ok" if execution.ok else "failed",
                    "summary": execution.summary,
                    "durationMs": execution.duration_ms,
                    "code": execution.error_code,
                },
                event_id=sse.seq_id(stream_id, seq),
            )
            seq += 1
        section = tool_result.prompt_section(settings.tutor_tool_max_result_chars)
        if section:
            # Kết quả tool là DỮ LIỆU KHÔNG TIN CẬY, đặt sau system prompt.
            system = f"{system}\n\n{section}"
    if tool_result.executions:
        # Ghi audit TRƯỚC frame đầu tiên để client đọc xong stream là thấy audit
        # (không phụ thuộc task nền thắng race). Một insert, không đáng kể.
        await _persist_tool_audit(prepared, tool_result)

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

    # Context copy giữ cùng collector object ⇒ usage provider ghi trong `finally`
    # vẫn nhìn thấy được sau khi stream dừng/bị hủy.
    with collect_usage(usage):
        producer = asyncio.create_task(produce())

    heartbeat = max(1.0, float(settings.tutor_heartbeat_seconds))
    cancel_poll = max(0.2, float(settings.tutor_cancel_poll_seconds or 1.0))
    deadline = time.monotonic() + max(1.0, float(settings.tutor_stream_timeout_seconds))
    last_heartbeat = time.monotonic()
    last_cancel_check = time.monotonic()

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

            # P3.1 — stop server-side: kiểm tra cờ theo thời gian, KHÔNG chỉ khi
            # queue timeout. Provider trả token liên tục thì vòng lặp không bao
            # giờ rơi vào nhánh timeout, nên stop sẽ không được thấy.
            if now - last_cancel_check >= cancel_poll:
                last_cancel_check = now
                if await _cancel_requested(prepared.assistant_message.id):
                    terminal = tutor_service.FinalState(
                        status=TutorMessageStatus.cancelled,
                        content="".join(collected),
                        finish_reason="cancelled",
                        error_code=tutor_service.TUTOR_CANCELLED,
                    )
                    yield sse.frame(
                        "cancelled",
                        {
                            "streamId": stream_id,
                            "messageId": message_id,
                            "seq": seq,
                            "reason": tutor_service.TUTOR_CANCELLED,
                            "partial": True,
                        },
                        event_id=sse.seq_id(stream_id, seq),
                    )
                    break

            try:
                kind, value = await asyncio.wait_for(
                    queue.get(), timeout=max(0.05, min(heartbeat, deadline - now))
                )
            except asyncio.TimeoutError:
                # Heartbeat không chứa nội dung người học.
                if time.monotonic() - last_heartbeat >= heartbeat:
                    last_heartbeat = time.monotonic()
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
        # Đợi producer đóng generator để provider kịp ghi usage (`finally` của
        # adapter). Không có bước này thì frame `done` có thể báo thiếu usage dù
        # provider đã trả token.
        if not producer.done():
            if terminal.status != TutorMessageStatus.completed:
                producer.cancel()
            # Provider không hợp tác có thể bỏ qua CancelledError; chờ có trần để
            # generator không treo vô hạn và không giữ kết nối của người học.
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(producer, timeout=_PRODUCER_JOIN_TIMEOUT)
        await _persist_final_state(prepared, terminal)
        persisted = True
        prompt_tokens = sum(r.prompt_tokens or 0 for r in usage.records) or None
        completion_tokens = sum(r.completion_tokens or 0 for r in usage.records) or None
        if terminal.status == TutorMessageStatus.completed:
            yield sse.frame(
                "done",
                {
                    "streamId": stream_id,
                    "messageId": message_id,
                    "seq": seq,
                    "finishReason": terminal.finish_reason,
                    "replayed": False,
                    # NULL/không có ⇒ provider không báo usage, không phải 0.
                    "usage": {
                        "promptTokens": prompt_tokens,
                        "completionTokens": completion_tokens,
                        "known": bool(usage.records),
                    },
                },
                event_id=sse.seq_id(stream_id, seq),
            )
    finally:
        if not producer.done():
            producer.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(producer, timeout=_PRODUCER_JOIN_TIMEOUT)
        if usage.records:
            _spawn(_persist_usage(prepared, usage))
        if not persisted:
            # Client ngắt giữa stream (hoặc lỗi trước terminal): ghi `cancelled`
            # bằng task tách rời — không tuyên bố đã xong, không để treo `running`.
            _spawn(_persist_cancelled(prepared, "".join(collected)))
