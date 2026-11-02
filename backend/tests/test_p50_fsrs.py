"""P5.0 FSRS — deterministic scheduling, idempotency, UTC coercion."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fsrs import Rating, State
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Course, Lesson, LessonAttempt, ReviewCard, ReviewEvent, Unit, User
from app.services import spaced_repetition_service as srp

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_initial_rating_thresholds():
    assert srp.initial_rating(0.3) == Rating.Again
    assert srp.initial_rating(0.7) == Rating.Hard
    assert srp.initial_rating(0.9) == Rating.Good
    assert srp.initial_rating(1.0) == Rating.Easy


def test_zero_total_is_treated_as_again():
    assert srp.initial_rating(0.0) == Rating.Again


def test_scheduler_is_deterministic_and_reaches_review_state():
    card, _ = srp.review(srp.new_card(123), Rating.Good, NOW)
    assert card.state == State.Review
    assert card.step is None
    assert card.due == NOW + timedelta(days=2)


@pytest.mark.parametrize(
    "rating,days",
    [(Rating.Again, 1), (Rating.Hard, 1), (Rating.Good, 2), (Rating.Easy, 8)],
)
def test_initial_intervals(rating, days):
    card, _ = srp.review(srp.new_card(123), rating, NOW)
    assert card.due == NOW + timedelta(days=days)


def test_naive_datetime_is_coerced():
    card, _ = srp.review(srp.new_card(1), Rating.Good, datetime(2026, 11, 2, 12, 0))
    assert card.due.tzinfo is not None


def test_card_id_is_derived_from_uuid():
    value = uuid.uuid4()
    derived = srp._card_id(value)
    assert isinstance(derived, int)
    assert 0 <= derived < 2**63


async def _seed(db, score_correct=1, score_total=3):
    suffix = uuid.uuid4().hex[:10]
    user = User(external_id=f"fsrs-{suffix}", email=f"fsrs-{suffix}@test.dev")
    db.add(user)
    await db.flush()
    course = Course(
        user_id=user.id, topic="T", status="ready", client_course_id=f"c-{uuid.uuid4()}"
    )
    db.add(course)
    await db.flush()
    unit = Unit(course_id=course.id, order_index=0, title="U", blurb="")
    db.add(unit)
    await db.flush()
    lesson = Lesson(
        unit_id=unit.id,
        course_id=course.id,
        order_index=0,
        title="Bài",
        content=[],
        content_version=1,
        status="ready",
    )
    db.add(lesson)
    await db.flush()
    attempt = LessonAttempt(
        lesson_id=lesson.id,
        user_id=user.id,
        client_attempt_id=f"att-{suffix}",
        content_version=1,
        score_correct=score_correct,
        score_total=score_total,
        results=[],
    )
    db.add(attempt)
    await db.commit()
    return user, lesson, attempt


@pytest.mark.asyncio
async def test_card_creation_race_does_not_rollback_attempt():
    """C1: ensure_card gặp IntegrityError không được rollback transaction của attempt."""
    from sqlalchemy.exc import IntegrityError

    from app.services import spaced_repetition_service as srp_mod

    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        # Giả lập card đã tồn tại (race) TRƯỚC khi ensure chạy, và cho ensure đi
        # vào nhánh insert để ném IntegrityError.
        original = srp_mod._owned_card

        async def boom(*args, **kwargs):
            raise IntegrityError("stmt", {}, Exception("dup"))

        # Chỉ chặn flush của event (mô phỏng race unique card/lesson).
        real_flush = db.flush
        calls = {"n": 0}

        async def flaky_flush(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise IntegrityError("stmt", {}, Exception("unique"))
            return await real_flush(*a, **kw)

        db.flush = flaky_flush  # type: ignore[method-assign]
        created = await srp_mod.ensure_card_for_attempt(db, lesson, attempt, user.id)
        db.flush = real_flush  # type: ignore[method-assign]
        assert created is False
        # Attempt row vẫn phải còn trong session/DB
        still = (
            await db.execute(select(LessonAttempt).where(LessonAttempt.id == attempt.id))
        ).scalar_one_or_none()
        assert still is not None, "attempt không được bị rollback bởi lỗi P5.0"


@pytest.mark.asyncio
async def test_due_cards_total_is_unbounded_by_limit():
    """I2: total phải là tổng số thẻ đến hạn, không phải len(items)."""
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        # tạo 3 card đến hạn cho cùng user (khác lesson)
        from app.models import Course, Unit

        course = (
            await db.execute(select(Course).where(Course.id == lesson.course_id))
        ).scalar_one()
        unit = (await db.execute(select(Unit).where(Unit.id == lesson.unit_id))).scalar_one()
        for i in range(2):
            other = Lesson(
                unit_id=unit.id,
                course_id=course.id,
                order_index=10 + i,
                title=f"B{i}",
                content=[],
                content_version=1,
                status="ready",
            )
            db.add(other)
            await db.flush()
            db.add(
                ReviewCard(
                    user_id=user.id,
                    lesson_id=other.id,
                    state=2,
                    due_at=NOW - timedelta(days=1),
                    scheduler_version=srp.FSRS_SCHEDULER_VERSION,
                )
            )
        db.add(
            ReviewCard(
                user_id=user.id,
                lesson_id=lesson.id,
                state=2,
                due_at=NOW - timedelta(days=1),
                scheduler_version=srp.FSRS_SCHEDULER_VERSION,
            )
        )
        await db.commit()

        page = await srp.due_cards(db, user.id, limit=1, now=NOW)
        assert len(page["items"]) == 1
        assert page["total"] == 3


@pytest.mark.asyncio
async def test_ensure_card_creates_on_first_attempt_even_below_threshold():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db, score_correct=1, score_total=3)
        created = await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        assert created is True

        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()
        assert card.scheduler_version == srp.FSRS_SCHEDULER_VERSION
        assert card.created_from_attempt_id == attempt.id

        # Attempt thứ hai không tạo card mới
        created_again = await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        assert created_again is False


@pytest.mark.asyncio
async def test_ensure_card_handles_zero_total():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db, score_correct=0, score_total=0)
        created = await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        assert created is True
        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()
        assert card.due_at is not None


@pytest.mark.asyncio
async def test_grade_is_idempotent_by_client_review_id():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()

        first = await srp.grade_card(db, card.id, user.id, 3, "rv-1", now=NOW)
        second = await srp.grade_card(db, card.id, user.id, 3, "rv-1", now=NOW)
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["card"]["dueAt"] == first["card"]["dueAt"]

        events = (
            await db.execute(select(ReviewEvent).where(ReviewEvent.card_id == card.id))
        ).scalars().all()
        assert len(events) == 2  # 1 initial event + 1 graded event


@pytest.mark.asyncio
async def test_cross_user_card_is_not_found():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()

        other = User(external_id=f"other-{uuid.uuid4().hex[:8]}", email=f"o-{uuid.uuid4().hex[:8]}@t.dev")
        db.add(other)
        await db.commit()

        with pytest.raises(srp.CardNotFoundError):
            await srp.grade_card(db, card.id, other.id, 3, "rv-x", now=NOW)


@pytest.mark.asyncio
async def test_grade_rejects_invalid_rating():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()
        with pytest.raises(ValueError):
            await srp.grade_card(db, card.id, user.id, 5, "rv-bad", now=NOW)


@pytest.mark.asyncio
async def test_due_cards_only_returns_due():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        # Card vừa tạo có due = created_at + 1 ngày (Again vì 1/3)
        early = await srp.due_cards(db, user.id, now=NOW)
        assert early["total"] == 0
        later = await srp.due_cards(db, user.id, now=NOW + timedelta(days=30))
        assert later["total"] == 1
        assert later["items"][0]["overdueDays"] >= 0


@pytest.mark.asyncio
async def test_due_cards_scoped_by_user():
    async with SessionLocal() as db:
        user, lesson, attempt = await _seed(db)
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        other = User(external_id=f"other2-{uuid.uuid4().hex[:8]}", email=f"o2-{uuid.uuid4().hex[:8]}@t.dev")
        db.add(other)
        await db.commit()
        result = await srp.due_cards(db, other.id, now=NOW + timedelta(days=30))
        assert result["total"] == 0
