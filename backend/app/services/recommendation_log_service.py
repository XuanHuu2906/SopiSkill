"""P5.2b — Ghi exposure recommendation (append-only) + suy reward offline.

Nguyên tắc:
  - Arm do **server** quyết định (từ learning-path vừa tính), không nhận từ client.
  - Ghi idempotent theo UNIQUE `(user, course, context_hash, arm_kind, arm_id)`.
    Dùng SAVEPOINT để race không phá transaction của caller.
  - Bảng append-only: service không UPDATE/DELETE. Reward suy ra offline bằng JOIN.
  - `propensity = 1.0` vì policy hiện deterministic ⇒ **OPE chưa hợp lệ**.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Course,
    Lesson,
    LessonAttempt,
    RecommendationEvent,
    ReviewCard,
    ReviewEvent,
)
from app.services import course_service, recommendation_token_service

logger = logging.getLogger(__name__)

POLICY_VERSION = "p5.0-rule-v1"
EVENT_ID_PREFIX = "rce_"
REASON_REVIEW_FALLBACK = "FALLBACK_REVIEW_WEAKEST"
REASON_NEXT = "NEXT_IN_SEQUENCE"

ARM_NEXT_LESSON = "next_lesson"
ARM_REVIEW_LESSON = "review_lesson"


class NoArmError(Exception):
    """Learning path không có arm nào để ghi (không gợi ý gì)."""


def _parse_arm_id(raw: str | None) -> uuid.UUID:
    parsed = course_service.parse_prefixed_uuid(raw or "")
    if parsed is None:
        raise NoArmError("arm id không hợp lệ")
    return parsed


def derive_arm(path: dict) -> tuple[str, str, str]:
    """Trả `(arm_kind, arm_id, reason_code)` từ payload learning-path.

    Ưu tiên `nextLesson`; nếu không có thì `reviewLessonId` (đường duy nhất sinh
    field này là fallback ôn bài yếu nhất ⇒ reason cố định, đúng sự thật).
    """
    next_lesson = path.get("nextLesson") or None
    if isinstance(next_lesson, dict) and next_lesson.get("lessonId"):
        lesson_id = _parse_arm_id(str(next_lesson["lessonId"]))
        reason = str((next_lesson.get("reason") or {}).get("code") or REASON_NEXT)
        return ARM_NEXT_LESSON, str(lesson_id), reason

    review_id = path.get("reviewLessonId")
    if review_id:
        lesson_id = _parse_arm_id(str(review_id))
        return ARM_REVIEW_LESSON, str(lesson_id), REASON_REVIEW_FALLBACK

    raise NoArmError("learning path không có nextLesson lẫn reviewLessonId")


async def _existing(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    context_hash: str,
    arm_kind: str,
    arm_id: str,
    lesson_content_version: int,
) -> RecommendationEvent | None:
    return (
        await db.execute(
            select(RecommendationEvent).where(
                RecommendationEvent.user_id == user_id,
                RecommendationEvent.course_id == course_id,
                RecommendationEvent.context_hash == context_hash,
                RecommendationEvent.arm_kind == arm_kind,
                RecommendationEvent.arm_id == uuid.UUID(arm_id),
                RecommendationEvent.lesson_content_version == int(lesson_content_version),
            )
        )
    ).scalars().first()


def _payload(event: RecommendationEvent, *, duplicate: bool) -> dict:
    return {
        "recorded": True,
        "duplicate": duplicate,
        "exposureId": f"{EVENT_ID_PREFIX}{event.id}",
        "reason": None,
    }


async def record_exposure(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course: Course,
    path: dict,
    lesson_content_version: int,
    now: datetime | None = None,
) -> dict:
    """Ghi 1 exposure idempotent. Không commit — caller sở hữu transaction."""
    arm_kind, arm_id, reason_code = derive_arm(path)
    context_hash = recommendation_token_service.context_hash_from_path(path)
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    existing = await _existing(
        db,
        user_id=user_id,
        course_id=course.id,
        context_hash=context_hash,
        arm_kind=arm_kind,
        arm_id=arm_id,
        lesson_content_version=lesson_content_version,
    )
    if existing is not None:
        return _payload(existing, duplicate=True)

    event = RecommendationEvent(
        user_id=user_id,
        course_id=course.id,
        context_hash=context_hash,
        policy_version=POLICY_VERSION,
        arm_kind=arm_kind,
        arm_id=uuid.UUID(arm_id),
        lesson_content_version=int(lesson_content_version),
        propensity=1.0,
        reason_code=reason_code,
        exposed_at=now,
    )
    try:
        # SAVEPOINT: request đồng thời có thể thắng UNIQUE; lỗi ở đây không được
        # phá transaction của attempt/API bên ngoài.
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        winner = await _existing(
            db,
            user_id=user_id,
            course_id=course.id,
            context_hash=context_hash,
            arm_kind=arm_kind,
            arm_id=arm_id,
            lesson_content_version=lesson_content_version,
        )
        if winner is not None:
            return _payload(winner, duplicate=True)
        raise
    return _payload(event, duplicate=False)


async def reward_for_events(
    db: AsyncSession,
    events: list[RecommendationEvent],
    *,
    window_days: int = 14,
) -> list[dict]:
    """Suy reward **offline** cho từng exposure. Chỉ SELECT.

    Thứ tự nguồn: attempt đúng version sau `exposed_at` → review sau `exposed_at`
    (qua `review_cards` vì `review_events` không có `lesson_id`) → `None`.
    Không gán 0 giả khi chưa có tín hiệu.
    """
    window = timedelta(days=max(1, int(window_days)))
    out: list[dict] = []

    for event in events:
        exposed_at = event.exposed_at
        if exposed_at.tzinfo is None:
            exposed_at = exposed_at.replace(tzinfo=UTC)
        deadline = exposed_at + window

        attempt = (
            await db.execute(
                select(LessonAttempt)
                .where(
                    LessonAttempt.user_id == event.user_id,
                    LessonAttempt.lesson_id == event.arm_id,
                    LessonAttempt.content_version == event.lesson_content_version,
                    LessonAttempt.created_at > exposed_at,
                    LessonAttempt.created_at <= deadline,
                    LessonAttempt.score_total > 0,
                )
                .order_by(LessonAttempt.created_at)
                .limit(1)
            )
        ).scalars().first()

        reward: float | None = None
        source: str | None = None
        at: datetime | None = None

        if attempt is not None:
            reward = float(attempt.score_correct) / float(attempt.score_total)
            source = "attempt"
            at = attempt.created_at
        else:
            review = (
                await db.execute(
                    select(ReviewEvent, ReviewCard)
                    .join(ReviewCard, ReviewCard.id == ReviewEvent.card_id)
                    .where(
                        ReviewEvent.user_id == event.user_id,
                        ReviewCard.lesson_id == event.arm_id,
                        ReviewEvent.reviewed_at > exposed_at,
                        ReviewEvent.reviewed_at <= deadline,
                    )
                    .order_by(ReviewEvent.reviewed_at)
                    .limit(1)
                )
            ).first()
            if review is not None:
                review_event, _card = review
                # 1..4 (Again..Easy) chuẩn hoá về [0,1] để cùng thang với attempt.
                reward = (int(review_event.rating) - 1) / 3.0
                source = "review"
                at = review_event.reviewed_at

        latency_hours = None
        if at is not None:
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            latency_hours = round((at - exposed_at).total_seconds() / 3600.0, 3)

        out.append(
            {
                "exposureId": f"{EVENT_ID_PREFIX}{event.id}",
                "reward": reward,
                "rewardSource": source,
                "latencyHours": latency_hours,
            }
        )
    return out


async def lesson_content_version(db: AsyncSession, lesson_id: uuid.UUID) -> int | None:
    return (
        await db.execute(select(Lesson.content_version).where(Lesson.id == lesson_id))
    ).scalar_one_or_none()
