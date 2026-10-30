"""Lesson service — lấy lesson (kiểm ownership) và nộp/chấm attempts."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonAttempt, User, XpEvent
from app.schemas.schemas import AttemptRequest
from app.services.course_service import parse_prefixed_uuid
from app.services.grading_service import grade_attempt

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
        select(Lesson).where(Lesson.id == lid, Lesson.course_id == Lesson.course_id)
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LESSON_NOT_FOUND"},
        )
    # ownership: lesson thuộc course của user?
    from app.models import Course
    from sqlalchemy import select as _select

    own = await db.execute(_select(Course.user_id).where(Course.id == lesson.course_id))
    owner_id = own.scalar_one_or_none()
    if owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LESSON_NOT_FOUND", "message": "Lesson không tồn tại hoặc không thuộc quyền của bạn."},
        )
    return lesson


async def submit_attempt(
    db: AsyncSession, lesson: Lesson, user: User, request: AttemptRequest
) -> tuple[LessonAttempt, bool]:
    """Idempotent theo (lesson, user, clientAttemptId). Chấm server-side."""
    existing = await db.execute(
        select(LessonAttempt).where(
            LessonAttempt.lesson_id == lesson.id,
            LessonAttempt.user_id == user.id,
            LessonAttempt.client_attempt_id == request.clientAttemptId,
        )
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        return found, True  # duplicate

    results, correct, total = grade_attempt(lesson.content or [], request.answers)

    attempt = LessonAttempt(
        lesson_id=lesson.id,
        user_id=user.id,
        client_attempt_id=request.clientAttemptId,
        content_version=request.contentVersion,
        score_correct=correct,
        score_total=total,
        duration_ms=request.durationMs,
        results=results,
    )
    db.add(attempt)

    xp_amount = correct * XP_PER_CORRECT
    if total > 0 and correct == total:
        xp_amount += XP_LESSON_COMPLETED_BONUS
    user.xp += xp_amount
    db.add(XpEvent(user_id=user.id, lesson_id=lesson.id, amount=xp_amount, reason="quiz_score"))

    await db.commit()
    await db.refresh(attempt)
    return attempt, False
