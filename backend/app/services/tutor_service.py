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
TUTOR_PROVIDER_ERROR = "TUTOR_PROVIDER_ERROR"
TUTOR_TIMEOUT = "TUTOR_TIMEOUT"
TUTOR_CANCELLED = "TUTOR_CANCELLED"

IN_PROGRESS_STATUSES = (TutorMessageStatus.pending, TutorMessageStatus.running)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


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


async def _check_daily_quota(db: AsyncSession, user_id: uuid.UUID) -> None:
    limit = int(get_settings().tutor_messages_per_day or 0)
    if limit <= 0:
        return
    since = datetime.now(UTC) - timedelta(days=1)
    used = (
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
    if int(used) >= limit:
        raise _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            TUTOR_LIMIT_REACHED,
            "Bạn đã hết lượt hỏi trợ giảng trong 24 giờ qua.",
        )


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
    message.updated_at = datetime.now(UTC)
    await db.commit()
    return True
