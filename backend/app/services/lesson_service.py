"""Lesson service — lấy lesson (kiểm ownership), nộp/chấm attempts, XP policy.

Bảo mật (P1.1):
  - Answer key chỉ tồn tại trong `lessons.content` (private, server-side).
  - API trả public blocks qua `lesson_content.public_blocks`.
  - Grading deterministic từ private content; không tin bất kỳ `correct` nào từ client.
  - Idempotency attempt do DB unique constraint đảm bảo + row lock trên user để
    tính XP tuần tự (không nhân XP khi retry/concurrency).
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Course, Lesson, LessonAttempt, User, XpEvent
from app.schemas.schemas import AttemptRequest
from app.services.course_service import parse_prefixed_uuid
from app.services.lesson_content import grade_attempt

XP_PER_CORRECT = 10
XP_LESSON_COMPLETED_BONUS = 20


async def get_owned_lesson(db: AsyncSession, lesson_id: str, user_id: uuid.UUID) -> Lesson:
    lid = parse_prefixed_uuid(lesson_id)
    if lid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LESSON_NOT_FOUND", "message": "Lesson không tồn tại hoặc không thuộc quyền của bạn."},
        )
    result = await db.execute(
        select(Lesson)
        .join(Course, Course.id == Lesson.course_id)
        .where(Lesson.id == lid, Course.user_id == user_id)
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LESSON_NOT_FOUND", "message": "Lesson không tồn tại hoặc không thuộc quyền của bạn."},
        )
    return lesson


def _validate_answers(blocks: list[dict], request: AttemptRequest) -> None:
    """Reject index ngoài bounds và duplicate index (contract P1.1)."""
    seen: set[int] = set()
    for answer in request.answers:
        if answer.index in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "DUPLICATE_ANSWER_INDEX", "message": f"Trùng index {answer.index}."},
            )
        if answer.index >= len(blocks):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "ANSWER_INDEX_OUT_OF_BOUNDS", "message": f"Index {answer.index} vượt quá số block."},
            )
        seen.add(answer.index)


def _desired_xp(correct: int, total: int) -> int:
    """XP 'best-effort' cho (user, lesson, contentVersion): cao nhất đạt được.

    Cùng một version nội dung chỉ nhận thêm phần chênh lệch so với XP đã cộng —
    retry/nộp lại không farm được XP.
    """
    amount = correct * XP_PER_CORRECT
    if total > 0 and correct == total:
        amount += XP_LESSON_COMPLETED_BONUS
    return amount


async def _find_attempt(
    db: AsyncSession, lesson_id: uuid.UUID, user_id: uuid.UUID, client_attempt_id: str
) -> LessonAttempt | None:
    result = await db.execute(
        select(LessonAttempt).where(
            LessonAttempt.lesson_id == lesson_id,
            LessonAttempt.user_id == user_id,
            LessonAttempt.client_attempt_id == client_attempt_id,
        )
    )
    return result.scalar_one_or_none()


async def submit_attempt(
    db: AsyncSession, lesson: Lesson, user: User, request: AttemptRequest
) -> tuple[LessonAttempt, bool]:
    """Idempotent theo (lesson, user, clientAttemptId). Chấm server-side."""
    _validate_answers(lesson.content or [], request)

    existing = await _find_attempt(db, lesson.id, user.id, request.clientAttemptId)
    if existing is not None:
        return existing, True

    # Serialize XP computation per user (PostgreSQL row lock; SQLite no-op).
    # Lấy luôn giá trị xp hiện tại trong cùng câu SELECT ... FOR UPDATE để không
    # dùng object User cũ (tránh ghi đè XP do request khác vừa cộng).
    locked_xp = (
        await db.execute(select(User.xp).where(User.id == user.id).with_for_update())
    ).scalar_one_or_none()
    if locked_xp is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "Tài khoản không tồn tại."},
        )
    # Re-check sau khi có lock: request khác có thể vừa commit cùng clientAttemptId.
    existing = await _find_attempt(db, lesson.id, user.id, request.clientAttemptId)
    if existing is not None:
        return existing, True

    results, correct, total = grade_attempt(
        lesson.id, lesson.content_version, lesson.content or [], request.answers
    )

    already = (
        await db.execute(
            select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
                XpEvent.user_id == user.id,
                XpEvent.lesson_id == lesson.id,
                XpEvent.content_version == lesson.content_version,
            )
        )
    ).scalar_one()
    award = max(0, _desired_xp(correct, total) - int(already))

    attempt = LessonAttempt(
        lesson_id=lesson.id,
        user_id=user.id,
        client_attempt_id=request.clientAttemptId,
        content_version=lesson.content_version,
        score_correct=correct,
        score_total=total,
        duration_ms=request.durationMs,
        results=results,
        xp_awarded=award,
    )
    db.add(attempt)

    if award > 0:
        # user.xp có thể stale trong session của request này → cộng trên giá trị đã lock.
        user.xp = int(locked_xp) + award
        db.add(
            XpEvent(
                user_id=user.id,
                lesson_id=lesson.id,
                amount=award,
                reason="quiz_score",
                content_version=lesson.content_version,
            )
        )

    try:
        await db.commit()
    except IntegrityError:
        # Race: request đồng thời cùng clientAttemptId đã thắng. Trả bản ghi đã lưu.
        await db.rollback()
        found = await _find_attempt(db, lesson.id, user.id, request.clientAttemptId)
        if found is None:
            raise
        return found, True

    await db.refresh(attempt)
    return attempt, False
