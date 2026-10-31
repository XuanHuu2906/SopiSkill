"""AI Tutor service (P3.0) — thread/message persistence + grounded turn preparation.

Luồng một lượt hỏi:

  1. Resolve course theo ownership (404 nếu không thuộc user).
  2. Resolve lesson theo `contextRef.lessonId` **và** `lesson.course_id == course.id`
     (client không thể trỏ bài của khóa khác), kiểm `blockIndex` trong biên.
  3. Serialize theo user (`SELECT ... FOR UPDATE` trên row user) để double-click
     cùng `clientMessageId` không sinh hai message và không gọi provider hai lần.
  4. Tạo user message (`completed`) + assistant message (`pending`) trong **một**
     transaction; commit xong mới bắt đầu stream.
  5. Stream: assistant chuyển `running`, nội dung cuối cùng được ghi với trạng
     thái `completed` / `failed` / `cancelled` — không bao giờ để `running` mà
     tuyên bố đã xong.

Quan trọng (trung thực):
  - `blockIndex` chỉ chọn vị trí trong **public blocks** (đã loại answer key).
  - Duplicate request đã xong ⇒ replay nội dung đã lưu, **không** gọi LLM lần nữa.
  - Duplicate request đang chạy ⇒ 409 `MESSAGE_IN_PROGRESS` (không multiplex).
  - Không hỗ trợ resume `Last-Event-ID`; lỗi mạng giữa stream ⇒ GET thread.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Course,
    CourseSource,
    Lesson,
    LessonStatus,
    Source,
    TutorMessage,
    TutorMessageRole,
    TutorMessageStatus,
    TutorThread,
    TutorToolCall,
    TutorUsageEvent,
    User,
)
from app.schemas.schemas import TutorMessageRequest
from app.services.course_service import parse_prefixed_uuid
from app.services.lesson_content import public_blocks

logger = logging.getLogger(__name__)

TUTOR_DISABLED_CODE = "TUTOR_DISABLED"
TUTOR_LESSON_NOT_FOUND = "TUTOR_LESSON_NOT_FOUND"
TUTOR_THREAD_NOT_FOUND = "TUTOR_THREAD_NOT_FOUND"
TUTOR_CONTEXT_INVALID = "TUTOR_CONTEXT_INVALID"
MESSAGE_IN_PROGRESS = "MESSAGE_IN_PROGRESS"
TUTOR_LIMIT_REACHED = "TUTOR_LIMIT_REACHED"
TUTOR_TOKEN_LIMIT_REACHED = "TUTOR_TOKEN_LIMIT_REACHED"
TUTOR_CONCURRENCY_LIMIT = "TUTOR_CONCURRENCY_LIMIT"
TUTOR_STALE = "TUTOR_STALE"
TUTOR_STOP_NOT_FOUND = "TUTOR_STOP_NOT_FOUND"
TUTOR_PROVIDER_ERROR = "TUTOR_PROVIDER_ERROR"
TUTOR_TIMEOUT = "TUTOR_TIMEOUT"
TUTOR_CANCELLED = "TUTOR_CANCELLED"

IN_PROGRESS_STATUSES = (TutorMessageStatus.pending, TutorMessageStatus.running)


def _error(status_code: int, code: str, message: str, **extra) -> HTTPException:
    detail = {"code": code, "message": message, **extra}
    return HTTPException(status_code=status_code, detail=detail)


def tutor_enabled() -> bool:
    return bool(get_settings().tutor_enabled)


def _prefixed(prefix: str, value: uuid.UUID | str) -> str:
    return f"{prefix}{value}"


def to_message_out(message: TutorMessage) -> dict:
    return {
        "id": _prefixed("tmsg_", message.id),
        "role": message.role.value,
        "status": message.status.value,
        "content": message.content or "",
        "contextRef": message.context_ref,
        "errorCode": message.error_code,
        "finishReason": message.finish_reason,
        "createdAt": message.created_at.isoformat() if message.created_at else None,
    }


def to_thread_summary(thread: TutorThread) -> dict:
    return {
        "id": _prefixed("tth_", thread.id),
        "courseId": _prefixed("crs_", thread.course_id),
        "lessonId": _prefixed("lsn_", thread.lesson_id),
        "title": thread.title or "",
        "messageCount": thread.message_count or 0,
        "createdAt": thread.created_at.isoformat() if thread.created_at else None,
        "updatedAt": thread.updated_at.isoformat() if thread.updated_at else None,
    }


async def get_owned_thread(
    db: AsyncSession, course: Course, user_id: uuid.UUID, thread_id: str
) -> TutorThread:
    tid = parse_prefixed_uuid(thread_id)
    if tid is None:
        raise _error(status.HTTP_404_NOT_FOUND, TUTOR_THREAD_NOT_FOUND, "Thread không tồn tại.")
    thread = (
        await db.execute(
            select(TutorThread).where(
                TutorThread.id == tid,
                TutorThread.user_id == user_id,
                TutorThread.course_id == course.id,
            )
        )
    ).scalar_one_or_none()
    if thread is None:
        raise _error(status.HTTP_404_NOT_FOUND, TUTOR_THREAD_NOT_FOUND, "Thread không tồn tại.")
    return thread


async def resolve_lesson(
    db: AsyncSession, course: Course, user_id: uuid.UUID, lesson_id: str, block_index: int
) -> tuple[Lesson, list[dict]]:
    """Resolve lesson theo ownership + course, và trả public blocks đã kiểm biên."""
    lid = parse_prefixed_uuid(lesson_id)
    if lid is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            TUTOR_LESSON_NOT_FOUND,
            "Bài học không tồn tại hoặc không thuộc quyền của bạn.",
        )
    lesson = (
        await db.execute(
            select(Lesson)
            .join(Course, Course.id == Lesson.course_id)
            .where(
                Lesson.id == lid,
                Lesson.course_id == course.id,
                Lesson.status == LessonStatus.ready,
                Course.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if lesson is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            TUTOR_LESSON_NOT_FOUND,
            "Bài học không tồn tại hoặc không thuộc quyền của bạn.",
        )
    blocks = public_blocks(lesson.id, lesson.content_version, lesson.content or [])
    if not blocks:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TUTOR_CONTEXT_INVALID,
            "Bài học chưa có nội dung để hỏi.",
        )
    if block_index >= len(blocks):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TUTOR_CONTEXT_INVALID,
            f"blockIndex {block_index} vượt quá số block của bài ({len(blocks)}).",
        )
    return lesson, blocks


async def linked_source_titles(
    db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[str]:
    """Chỉ tiêu đề nguồn user được đọc — dùng cho prompt, KHÔNG gửi nội dung."""
    rows = (
        await db.execute(
            select(Source.title)
            .join(CourseSource, CourseSource.source_id == Source.id)
            .where(
                CourseSource.course_id == course_id,
                (Source.owner_id == user_id) | (Source.visibility == "public"),
            )
            .limit(8)
        )
    ).scalars().all()
    return [title for title in rows if title]


async def _lock_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Serialize lượt hỏi theo user (PostgreSQL row lock; SQLite no-op).

    Cần thiết để double-click cùng `clientMessageId` không tạo 2 thread khi
    request đầu chưa kịp trả `threadId`.
    """
    xp = (
        await db.execute(select(User.xp).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if xp is None:
        raise _error(
            status.HTTP_401_UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."
        )
    return int(xp)


async def _find_by_client_id(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID, client_message_id: str
) -> tuple[TutorThread, TutorMessage, TutorMessage | None] | None:
    row = (
        await db.execute(
            select(TutorMessage, TutorThread)
            .join(TutorThread, TutorThread.id == TutorMessage.thread_id)
            .where(
                TutorThread.user_id == user_id,
                TutorThread.course_id == course_id,
                TutorMessage.client_message_id == client_message_id,
                TutorMessage.role == TutorMessageRole.user,
            )
        )
    ).first()
    if row is None:
        return None
    user_message, thread = row
    assistant = (
        await db.execute(
            select(TutorMessage)
            .where(
                TutorMessage.thread_id == thread.id,
                TutorMessage.role == TutorMessageRole.assistant,
                TutorMessage.client_message_id == client_message_id,
            )
            .order_by(TutorMessage.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return thread, user_message, assistant


async def _used_today(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """(số lượt hỏi, tổng token đã dùng) trong 24h gần nhất.

    Đếm **user message đã chấp nhận** (một lượt = một user message) để retry
    hoặc assistant lỗi không bị tính thêm lần nữa. Token cộng từ usage events;
    provider không báo usage ⇒ token = 0 và trần token KHÔNG bảo vệ được —
    điều này được ghi rõ trong cấu hình và response (`tokensKnown`).
    """
    since = datetime.now(UTC) - timedelta(days=1)
    used_messages = (
        await db.execute(
            select(func.count())
            .select_from(TutorMessage)
            .join(TutorThread, TutorThread.id == TutorMessage.thread_id)
            .where(
                TutorThread.user_id == user_id,
                TutorMessage.role == TutorMessageRole.user,
                TutorMessage.created_at >= since,
            )
        )
    ).scalar_one()
    tokens = (
        await db.execute(
            select(
                func.coalesce(func.sum(TutorUsageEvent.prompt_tokens), 0),
                func.coalesce(func.sum(TutorUsageEvent.completion_tokens), 0),
            ).where(
                TutorUsageEvent.user_id == user_id,
                TutorUsageEvent.created_at >= since,
            )
        )
    ).one()
    return int(used_messages), int(tokens[0]) + int(tokens[1])


async def quota_state(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Trạng thái allowance hiện tại (không raise) — dùng cho GET và error body."""
    settings = get_settings()
    limits = {
        "messagesPerDay": int(settings.tutor_messages_per_day or 0),
        "tokensPerDay": int(settings.tutor_tokens_per_day or 0),
        "maxConcurrentStreams": int(settings.tutor_max_concurrent_streams or 0),
    }
    used_messages, used_tokens = await _used_today(db, user_id)
    running = await count_running_streams(db, user_id)
    return {
        "windowSeconds": 86400,
        "used": {"messages": used_messages, "tokens": used_tokens},
        "limits": limits,
        "remaining": {
            "messages": (
                max(0, limits["messagesPerDay"] - used_messages)
                if limits["messagesPerDay"] > 0
                else None
            ),
            "tokens": (
                max(0, limits["tokensPerDay"] - used_tokens)
                if limits["tokensPerDay"] > 0
                else None
            ),
        },
        "runningStreams": running,
        # Provider không báo token ⇒ trần token không chặn được chi phí thật.
        "tokensKnown": used_tokens > 0,
    }


async def _check_daily_quota(db: AsyncSession, user_id: uuid.UUID) -> None:
    settings = get_settings()
    limit = int(settings.tutor_messages_per_day or 0)
    token_limit = int(settings.tutor_tokens_per_day or 0)
    if limit <= 0 and token_limit <= 0:
        return
    used_messages, used_tokens = await _used_today(db, user_id)
    if limit > 0 and used_messages >= limit:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TUTOR_LIMIT_REACHED,
            "Bạn đã hết lượt hỏi trợ giảng trong 24 giờ qua.",
            quota=await quota_state(db, user_id),
        )
    if token_limit > 0 and used_tokens >= token_limit:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TUTOR_TOKEN_LIMIT_REACHED,
            "Bạn đã dùng hết hạn mức token trợ giảng trong 24 giờ qua.",
            quota=await quota_state(db, user_id),
        )


async def count_running_streams(db: AsyncSession, user_id: uuid.UUID) -> int:
    count = (
        await db.execute(
            select(func.count())
            .select_from(TutorMessage)
            .join(TutorThread, TutorThread.id == TutorMessage.thread_id)
            .where(
                TutorThread.user_id == user_id,
                TutorMessage.role == TutorMessageRole.assistant,
                TutorMessage.status.in_(IN_PROGRESS_STATUSES),
            )
        )
    ).scalar_one()
    return int(count)


async def _check_concurrency(db: AsyncSession, user_id: uuid.UUID) -> None:
    limit = int(get_settings().tutor_max_concurrent_streams or 0)
    if limit <= 0:
        return
    running = await count_running_streams(db, user_id)
    if running >= limit:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TUTOR_CONCURRENCY_LIMIT,
            f"Bạn đang có {running} câu trả lời đang chạy; hãy đợi hoặc dừng bớt.",
        )


async def reap_stale_messages(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Đánh dấu `failed` các message in-progress quá tuổi của MỘT user.

    Chỉ chạy khi user bắt đầu lượt mới hoặc gọi quota: nếu tiến trình giữ stream
    chết (server restart), không có ai ghi trạng thái cuối và message treo
    `running` mãi. Không tự đánh dấu `completed` — dữ liệu chưa xong không được
    coi là xong.
    """
    seconds = float(get_settings().tutor_stale_stream_seconds or 0)
    if seconds <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
    rows = (
        await db.execute(
            select(TutorMessage)
            .join(TutorThread, TutorThread.id == TutorMessage.thread_id)
            .where(
                TutorThread.user_id == user_id,
                TutorMessage.role == TutorMessageRole.assistant,
                TutorMessage.status.in_(IN_PROGRESS_STATUSES),
                TutorMessage.updated_at < cutoff,
            )
        )
    ).scalars().all()
    for message in rows:
        message.status = TutorMessageStatus.failed
        message.error_code = TUTOR_STALE
        message.finish_reason = "stale"
        message.updated_at = datetime.now(UTC)
    if rows:
        await db.flush()
    return len(rows)


@dataclass
class PreparedTurn:
    thread: TutorThread
    user_message: TutorMessage
    assistant_message: TutorMessage
    lesson: Lesson
    blocks: list[dict]
    block_index: int
    replay: bool

    def stream_id(self) -> str:
        return f"tts_{self.assistant_message.id}"

    def assistant_id(self) -> str:
        return _prefixed("tmsg_", self.assistant_message.id)

    def user_id(self) -> str:
        return _prefixed("tmsg_", self.user_message.id)

    def thread_id(self) -> str:
        return _prefixed("tth_", self.thread.id)


async def prepare_turn(
    db: AsyncSession, course: Course, user: User, body: TutorMessageRequest
) -> PreparedTurn:
    """Chuẩn bị một lượt hỏi; idempotent theo clientMessageId. KHÔNG gọi provider."""
    settings = get_settings()
    text = " ".join(body.text.split())
    if not text:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TUTOR_CONTEXT_INVALID,
            "Câu hỏi không được để trống.",
        )
    if len(text) > settings.tutor_max_question_chars:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            TUTOR_CONTEXT_INVALID,
            f"Câu hỏi vượt quá {settings.tutor_max_question_chars} ký tự.",
        )

    lesson, blocks = await resolve_lesson(
        db, course, user.id, body.contextRef.lessonId, body.contextRef.blockIndex
    )

    # Serialize per-user trước khi kiểm idempotency/quota.
    await _lock_user(db, user.id)
    # Stream mồ côi (tiến trình giữ nó đã chết) phải thành `failed` trước khi
    # quyết định replay/409, nếu không user bị khóa vĩnh viễn ở MESSAGE_IN_PROGRESS.
    await reap_stale_messages(db, user.id)

    existing = await _find_by_client_id(
        db, user.id, course.id, body.clientMessageId
    )
    if existing is not None:
        thread, user_message, assistant = existing
        if thread.lesson_id != lesson.id:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                TUTOR_CONTEXT_INVALID,
                "clientMessageId đã dùng cho bài học khác.",
            )
        if assistant is not None and assistant.status in IN_PROGRESS_STATUSES:
            raise _error(
                status.HTTP_409_CONFLICT,
                MESSAGE_IN_PROGRESS,
                "Câu hỏi này đang được xử lý; hãy tải lại lịch sử thay vì gửi lại.",
            )
        if assistant is None:
            # Thread có user message nhưng chưa có assistant (dữ liệu dở dang):
            # tạo lại assistant để lượt hỏi có phản hồi thay vì treo.
            assistant = TutorMessage(
                thread_id=thread.id,
                course_id=course.id,
                position=(user_message.position or 0) + 1,
                role=TutorMessageRole.assistant,
                status=TutorMessageStatus.pending,
                content="",
                context_ref=user_message.context_ref,
                client_message_id=body.clientMessageId,
            )
            db.add(assistant)
        thread.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(assistant)
        await db.refresh(thread)
        return PreparedTurn(
            thread=thread,
            user_message=user_message,
            assistant_message=assistant,
            lesson=lesson,
            blocks=blocks,
            block_index=body.contextRef.blockIndex,
            replay=True,
        )

    await _check_daily_quota(db, user.id)
    await _check_concurrency(db, user.id)

    if body.threadId:
        thread = await get_owned_thread(db, course, user.id, body.threadId)
        if thread.lesson_id != lesson.id:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                TUTOR_CONTEXT_INVALID,
                "Thread này thuộc bài học khác.",
            )
    else:
        thread = TutorThread(
            user_id=user.id,
            course_id=course.id,
            lesson_id=lesson.id,
            title=text[:120],
            message_count=0,
        )
        db.add(thread)
        await db.flush()

    context_ref = {
        "lessonId": _prefixed("lsn_", lesson.id),
        "lessonTitle": lesson.title,
        "blockIndex": body.contextRef.blockIndex,
        "blockType": blocks[body.contextRef.blockIndex].get("type"),
    }

    # position: 2 slot cho mỗi lượt hỏi (user chẵn, assistant lẻ). Dùng
    # message_count hiện tại để không phụ thuộc timestamp độ phân giải giây.
    base_position = max(0, int(thread.message_count or 0)) * 2
    user_message = TutorMessage(
        thread_id=thread.id,
        course_id=course.id,
        position=base_position,
        role=TutorMessageRole.user,
        status=TutorMessageStatus.completed,
        content=text,
        context_ref=context_ref,
        client_message_id=body.clientMessageId,
    )
    assistant_message = TutorMessage(
        thread_id=thread.id,
        course_id=course.id,
        position=base_position + 1,
        role=TutorMessageRole.assistant,
        status=TutorMessageStatus.pending,
        content="",
        context_ref=context_ref,
        client_message_id=body.clientMessageId,
    )
    db.add(user_message)
    db.add(assistant_message)
    thread.message_count = (thread.message_count or 0) + 1

    try:
        await db.commit()
    except IntegrityError:
        # Backstop UNIQUE(thread_id, client_message_id): request song song đã thắng.
        await db.rollback()
        existing = await _find_by_client_id(
            db, user.id, course.id, body.clientMessageId
        )
        if existing is None:
            raise
        thread, user_message, assistant = existing
        if assistant is None:
            raise _error(
                status.HTTP_409_CONFLICT,
                MESSAGE_IN_PROGRESS,
                "Câu hỏi đang được xử lý.",
            )
        return PreparedTurn(
            thread=thread,
            user_message=user_message,
            assistant_message=assistant,
            lesson=lesson,
            blocks=blocks,
            block_index=body.contextRef.blockIndex,
            replay=assistant.status == TutorMessageStatus.completed,
        )

    await db.refresh(thread)
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    return PreparedTurn(
        thread=thread,
        user_message=user_message,
        assistant_message=assistant_message,
        lesson=lesson,
        blocks=blocks,
        block_index=body.contextRef.blockIndex,
        replay=False,
    )


async def history_for_prompt(
    db: AsyncSession, thread: TutorThread, *, exclude_assistant_id: uuid.UUID, limit: int
) -> list[tuple[str, str]]:
    """Lịch sử **completed** gần nhất, không gồm assistant đang stream."""
    rows = (
        await db.execute(
            select(TutorMessage)
            .where(
                TutorMessage.thread_id == thread.id,
                TutorMessage.status == TutorMessageStatus.completed,
                TutorMessage.id != exclude_assistant_id,
            )
            .order_by(TutorMessage.position.desc())
            .limit(max(1, limit) * 2)
        )
    ).scalars().all()
    ordered = list(reversed(rows))
    return [(m.role.value, m.content or "") for m in ordered]


async def list_threads(
    db: AsyncSession, course: Course, user_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> dict:
    total = (
        await db.execute(
            select(func.count())
            .select_from(TutorThread)
            .where(
                TutorThread.user_id == user_id, TutorThread.course_id == course.id
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(TutorThread)
            .where(
                TutorThread.user_id == user_id, TutorThread.course_id == course.id
            )
            .order_by(TutorThread.updated_at.desc(), TutorThread.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {
        "items": [to_thread_summary(thread) for thread in rows],
        "total": int(total),
    }


async def get_thread_detail(
    db: AsyncSession, course: Course, user_id: uuid.UUID, thread_id: str
) -> dict:
    thread = await get_owned_thread(db, course, user_id, thread_id)
    rows = (
        await db.execute(
            select(TutorMessage)
            .where(TutorMessage.thread_id == thread.id)
            .order_by(TutorMessage.position.asc())
        )
    ).scalars().all()
    payload = to_thread_summary(thread)
    payload["messages"] = [to_message_out(m) for m in rows]
    payload["replaySupported"] = False
    payload["notice"] = (
        "P3.0 không hỗ trợ resume từng byte: nếu mất mạng giữa stream, tải lại "
        "lịch sử để xem trạng thái thật của câu trả lời."
    )
    return payload


async def mark_running(db: AsyncSession, assistant_id: uuid.UUID) -> None:
    message = await db.get(TutorMessage, assistant_id)
    if message is None:
        return
    message.status = TutorMessageStatus.running
    message.updated_at = datetime.now(UTC)
    await db.commit()


@dataclass
class FinalState:
    status: TutorMessageStatus
    content: str
    finish_reason: str | None = None
    error_code: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


async def finalize(
    db: AsyncSession, assistant_id: uuid.UUID, state: FinalState
) -> None:
    """Ghi trạng thái cuối của assistant message (một lần, idempotent theo trạng thái)."""
    message = await db.get(TutorMessage, assistant_id)
    if message is None:
        return
    # Không ghi đè trạng thái terminal đã có (stop/stream race).
    if message.status in (
        TutorMessageStatus.completed,
        TutorMessageStatus.failed,
        TutorMessageStatus.cancelled,
    ):
        return
    message.status = state.status
    message.content = state.content[:20_000]
    message.finish_reason = state.finish_reason
    message.error_code = state.error_code
    message.prompt_tokens = state.prompt_tokens
    message.completion_tokens = state.completion_tokens
    message.updated_at = datetime.now(UTC)
    await db.commit()


async def cancel_if_running(db: AsyncSession, assistant_id: uuid.UUID, content: str) -> bool:
    """Đánh dấu `cancelled` nếu message chưa terminal. Trả True nếu đã đổi."""
    message = await db.get(TutorMessage, assistant_id)
    if message is None or message.status not in IN_PROGRESS_STATUSES:
        return False
    message.status = TutorMessageStatus.cancelled
    message.content = content[:20_000]
    message.error_code = TUTOR_CANCELLED
    message.finish_reason = "cancelled"
    message.updated_at = datetime.now(UTC)
    await db.commit()
    return True


async def request_cancel(
    db: AsyncSession, course: Course, user_id: uuid.UUID, message_id: str
) -> dict:
    """Ghi cờ stop cho một assistant message của CHÍNH user.

    Trả trạng thái thật ngay tại thời điểm gọi:
      - `cancel_requested` nếu stream đang chạy và chưa terminal;
      - `completed`/`failed`/`cancelled` nếu đã xong (stop không xóa nội dung,
        không hoàn chi phí đã phát sinh);
      - 404 nếu message không thuộc user/course hoặc không phải assistant.

    Không ghi trực tiếp `cancelled` ở đây: nếu task stream còn sống, chính nó
    ghi trạng thái cuối (kèm nội dung đã nhận) để không mất phần đã hiển thị.
    """
    mid = parse_prefixed_uuid(message_id)
    if mid is None:
        raise _error(status.HTTP_404_NOT_FOUND, TUTOR_STOP_NOT_FOUND, "Message không tồn tại.")
    message = (
        await db.execute(
            select(TutorMessage)
            .join(TutorThread, TutorThread.id == TutorMessage.thread_id)
            .where(
                TutorMessage.id == mid,
                TutorMessage.course_id == course.id,
                TutorMessage.role == TutorMessageRole.assistant,
                TutorThread.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise _error(status.HTTP_404_NOT_FOUND, TUTOR_STOP_NOT_FOUND, "Message không tồn tại.")

    if message.status in IN_PROGRESS_STATUSES:
        if message.cancel_requested_at is None:
            message.cancel_requested_at = datetime.now(UTC)
            message.updated_at = datetime.now(UTC)
            await db.commit()
        return {
            "messageId": _prefixed("tmsg_", message.id),
            "status": "cancel_requested",
            "providerStopGuaranteed": False,
            "notice": (
                "Đã yêu cầu dừng. Server sẽ dừng stream ở lần kiểm tra kế tiếp; "
                "token đã sinh trước đó vẫn có thể bị tính phí."
            ),
        }

    return {
        "messageId": _prefixed("tmsg_", message.id),
        "status": message.status.value,
        "providerStopGuaranteed": False,
        "notice": "Câu trả lời đã kết thúc trước khi yêu cầu dừng được xử lý.",
    }


async def is_cancel_requested(db: AsyncSession, assistant_id: uuid.UUID) -> bool:
    value = (
        await db.execute(
            select(TutorMessage.cancel_requested_at).where(TutorMessage.id == assistant_id)
        )
    ).scalar_one_or_none()
    return value is not None


async def record_tool_call(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message_id: uuid.UUID,
    name: str,
    ok: bool,
    duration_ms: int | None,
    summary: str,
    error_code: str | None,
) -> None:
    """Audit metadata một lần gọi tool read-only — không lưu nội dung tool."""
    db.add(
        TutorToolCall(
            user_id=user_id,
            course_id=course_id,
            message_id=message_id,
            name=name,
            ok=ok,
            duration_ms=duration_ms,
            summary=(summary or "")[:400],
            error_code=error_code,
        )
    )
    await db.commit()


async def list_tool_calls(db: AsyncSession, assistant_id: uuid.UUID) -> list[TutorToolCall]:
    rows = (
        await db.execute(
            select(TutorToolCall)
            .where(TutorToolCall.message_id == assistant_id)
            .order_by(TutorToolCall.created_at.asc())
        )
    ).scalars().all()
    return list(rows)


async def record_usage(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message_id: uuid.UUID,
    record,
) -> None:
    """Lưu metadata một lượt gọi provider. Không lưu prompt/nội dung."""
    if record is None:
        return
    db.add(
        TutorUsageEvent(
            user_id=user_id,
            course_id=course_id,
            message_id=message_id,
            provider=record.provider or "unknown",
            model=record.model or "unknown",
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            latency_ms=record.latency_ms,
            finish_reason=record.finish_reason,
        )
    )
    await db.commit()
