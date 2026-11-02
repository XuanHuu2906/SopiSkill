"""P5.0 FSRS — spaced repetition trên lesson (1 card / (user, lesson)).

Quyết định đã chốt (xem `docs/specs/22-P50-LEARNER-PROFILE.md`):
  - Card tạo ở **attempt đầu tiên**, kể cả <80% ⇒ ôn bài yếu là luồng thật.
  - `learning_steps=()` / `relearning_steps=()` ⇒ card vào thẳng `State.Review`
    để lịch theo ngày, deterministic (đo: Again 1d, Hard 1d, Good 2d, Easy 8d).
  - `enable_fuzzing=False` ⇒ test tái lập được. Production muốn ngẫu nhiên hoá
    phải đổi qua config (chưa mở trong phase này).
  - `FSRS_SCHEDULER_VERSION` pin thuật toán vào từng card/event.
  - SQLite trả datetime naive ⇒ mọi mốc được ép UTC trước khi gọi thư viện
    (`fsrs` raise `ValueError` nếu naive/không UTC).
"""

import logging
import uuid
from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler, State
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Lesson, LessonAttempt, ReviewCard, ReviewEvent

logger = logging.getLogger(__name__)

FSRS_SCHEDULER_VERSION = "py-fsrs-6.3.2"
MAX_DUE_LIMIT = 100


class CardNotFoundError(Exception):
    """Card không tồn tại hoặc không thuộc user đang gọi (giữ nguyên tắc 404)."""


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


_SCHEDULER: Scheduler | None = None


def scheduler() -> Scheduler:
    global _SCHEDULER
    if _SCHEDULER is None:
        _SCHEDULER = Scheduler(
            desired_retention=get_settings().fsrs_desired_retention,
            learning_steps=(),
            relearning_steps=(),
            enable_fuzzing=False,
        )
    return _SCHEDULER


def new_card(card_id: int) -> Card:
    return Card(card_id=card_id)


def _card_id(value: uuid.UUID) -> int:
    """`fsrs.Card.card_id` là int; UUID vẫn là khoá DB."""
    return int(value.int % (2**63 - 1))


def review(card: Card, rating: Rating, now: datetime) -> tuple[Card, object]:
    return scheduler().review_card(card, rating, review_datetime=_as_utc(now))


def initial_rating(block_accuracy: float) -> Rating:
    if block_accuracy < 0.6:
        return Rating.Again
    if block_accuracy < 0.8:
        return Rating.Hard
    if block_accuracy < 1.0:
        return Rating.Good
    return Rating.Easy


def _card_payload(card: ReviewCard) -> dict:
    return {
        "cardId": f"rvc_{card.id}",
        "lessonId": f"lsn_{card.lesson_id}",
        "state": card.state,
        "dueAt": _as_utc(card.due_at).isoformat(),
        "lastReviewAt": _as_utc(card.last_review_at).isoformat()
        if card.last_review_at
        else None,
    }


async def ensure_card_for_attempt(
    db: AsyncSession,
    lesson: Lesson,
    attempt: LessonAttempt,
    user_id: uuid.UUID,
) -> bool:
    """Tạo card + event khởi tạo nếu chưa có. Trả True khi vừa tạo."""
    existing = (
        await db.execute(
            select(ReviewCard).where(
                ReviewCard.user_id == user_id, ReviewCard.lesson_id == lesson.id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    accuracy = (
        attempt.score_correct / attempt.score_total if attempt.score_total else 0.0
    )
    rating = initial_rating(accuracy)
    reviewed_at = _as_utc(attempt.created_at or datetime.now(UTC))
    card, _log = review(new_card(_card_id(uuid.uuid4())), rating, reviewed_at)

    from app.services import learner_profile_service

    skill = await learner_profile_service.skill_for_lesson(db, lesson.id)

    row = ReviewCard(
        user_id=user_id,
        lesson_id=lesson.id,
        skill_id=skill.id if skill else None,
        state=int(card.state),
        step=card.step,
        stability=card.stability,
        difficulty=card.difficulty,
        due_at=_as_utc(card.due),
        last_review_at=reviewed_at,
        scheduler_version=FSRS_SCHEDULER_VERSION,
        created_from_attempt_id=attempt.id,
    )
    db.add(row)
    await db.flush()
    db.add(
        ReviewEvent(
            card_id=row.id,
            user_id=user_id,
            rating=int(rating),
            reviewed_at=reviewed_at,
            elapsed_days=0,
            scheduled_days=max(0, (_as_utc(card.due) - reviewed_at).days),
            state_before=int(State.Learning),
            state_after=int(card.state),
            scheduler_version=FSRS_SCHEDULER_VERSION,
            client_review_id=f"initial:{attempt.id}",
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return False
    return True


async def _owned_card(
    db: AsyncSession, card_id: uuid.UUID, user_id: uuid.UUID
) -> ReviewCard:
    card = (
        await db.execute(
            select(ReviewCard).where(
                ReviewCard.id == card_id, ReviewCard.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if card is None:
        raise CardNotFoundError(str(card_id))
    return card


async def grade_card(
    db: AsyncSession,
    card_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: int,
    client_review_id: str,
    duration_ms: int | None = None,
    now: datetime | None = None,
) -> dict:
    if rating not in (1, 2, 3, 4):
        raise ValueError("rating phải trong khoảng 1..4")

    card = await _owned_card(db, card_id, user_id)

    existing_event = (
        await db.execute(
            select(ReviewEvent).where(
                ReviewEvent.card_id == card.id,
                ReviewEvent.client_review_id == client_review_id,
            )
        )
    ).scalar_one_or_none()
    if existing_event is not None:
        return {
            "card": _card_payload(card),
            "eventId": f"rve_{existing_event.id}",
            "duplicate": True,
        }

    now = _as_utc(now or datetime.now(UTC))
    last_review_at = _as_utc(card.last_review_at) if card.last_review_at else now

    fsrs_card = Card(
        card_id=_card_id(card.id),
        state=State(card.state),
        step=card.step,
        stability=card.stability,
        difficulty=card.difficulty,
        due=_as_utc(card.due_at),
        last_review=last_review_at,
    )
    updated, _log = review(fsrs_card, Rating(rating), now)

    state_before = card.state
    card.state = int(updated.state)
    card.step = updated.step
    card.stability = updated.stability
    card.difficulty = updated.difficulty
    card.due_at = _as_utc(updated.due)
    card.last_review_at = now
    card.scheduler_version = FSRS_SCHEDULER_VERSION

    event = ReviewEvent(
        card_id=card.id,
        user_id=user_id,
        rating=int(rating),
        reviewed_at=now,
        elapsed_days=max(0, (now - last_review_at).days),
        scheduled_days=max(0, (_as_utc(updated.due) - now).days),
        duration_ms=duration_ms,
        state_before=int(state_before),
        state_after=int(updated.state),
        scheduler_version=FSRS_SCHEDULER_VERSION,
        client_review_id=client_review_id,
    )
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:  # pragma: no cover - race trên cùng clientReviewId
        await db.rollback()
        found = (
            await db.execute(
                select(ReviewEvent).where(
                    ReviewEvent.card_id == card_id,
                    ReviewEvent.client_review_id == client_review_id,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise
        refreshed = await _owned_card(db, card_id, user_id)
        return {"card": _card_payload(refreshed), "eventId": f"rve_{found.id}", "duplicate": True}

    return {"card": _card_payload(card), "eventId": f"rve_{event.id}", "duplicate": False}


async def due_cards(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    limit: int = 20,
    now: datetime | None = None,
) -> dict:
    now = _as_utc(now or datetime.now(UTC))
    limit = max(1, min(limit, MAX_DUE_LIMIT))

    from app.models import Lesson as _Lesson

    query = (
        select(ReviewCard, _Lesson)
        .join(_Lesson, _Lesson.id == ReviewCard.lesson_id)
        .where(ReviewCard.user_id == user_id, ReviewCard.due_at <= now)
    )
    if course_id is not None:
        query = query.where(_Lesson.course_id == course_id)
    query = query.order_by(ReviewCard.due_at).limit(limit)

    rows = (await db.execute(query)).all()
    items = []
    for card, lesson in rows:
        items.append(
            {
                "cardId": f"rvc_{card.id}",
                "lessonId": f"lsn_{lesson.id}",
                "lessonTitle": lesson.title,
                "dueAt": _as_utc(card.due_at).isoformat(),
                "state": card.state,
                "overdueDays": max(0, (now - _as_utc(card.due_at)).days),
            }
        )
    return {"items": items, "total": len(items)}
