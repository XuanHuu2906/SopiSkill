"""P5.2 exposure service — derive arm, idempotency, reward offline."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Course,
    Lesson,
    LessonAttempt,
    RecommendationEvent,
    ReviewCard,
    ReviewEvent,
    Unit,
    User,
)
from app.services import recommendation_log_service as svc


def _path(next_id: str | None, review_id: str | None = None) -> dict:
    return {
        "nextLesson": {"lessonId": next_id, "title": "T", "reason": {"code": "NEXT_IN_SEQUENCE"}}
        if next_id
        else None,
        "reviewLessonId": review_id,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }


def test_derive_arm_prefers_next_lesson():
    kind, arm, reason = svc.derive_arm(_path("lsn_" + str(uuid.uuid4())))
    assert kind == "next_lesson"
    assert uuid.UUID(arm)
    assert reason == "NEXT_IN_SEQUENCE"


def test_derive_arm_review_uses_fallback_reason():
    kind, arm, reason = svc.derive_arm(_path(None, "lsn_" + str(uuid.uuid4())))
    assert kind == "review_lesson"
    assert uuid.UUID(arm)
    assert reason == "FALLBACK_REVIEW_WEAKEST"


def test_derive_arm_raises_when_no_arm():
    with pytest.raises(svc.NoArmError):
        svc.derive_arm(_path(None, None))


def test_derive_arm_raises_on_unparseable_id():
    with pytest.raises(svc.NoArmError):
        svc.derive_arm(_path("not-a-uuid"))


async def _seed(content_version: int = 3) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        user = User(external_id=f"p52-{uuid.uuid4().hex[:8]}", xp=0)
        db.add(user)
        await db.flush()
        course = Course(
            user_id=user.id,
            topic="P52",
            status="ready",
            client_course_id=f"c-{uuid.uuid4().hex[:12]}",
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
            title="L",
            content=[],
            content_version=content_version,
            status="ready",
        )
        db.add(lesson)
        await db.commit()
        return user.id, course.id, lesson.id


async def test_record_exposure_is_idempotent():
    user_id, course_id, lesson_id = await _seed()
    path = _path(f"lsn_{lesson_id}")
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        first = await svc.record_exposure(
            db, user_id=user_id, course=course, path=path, lesson_content_version=3
        )
        assert first["recorded"] is True
        assert first["duplicate"] is False
        assert first["exposureId"].startswith("rce_")
        for _ in range(5):
            again = await svc.record_exposure(
                db, user_id=user_id, course=course, path=path, lesson_content_version=3
            )
            assert again["duplicate"] is True
            assert again["exposureId"] == first["exposureId"]
        await db.commit()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].propensity == 1.0
        assert rows[0].policy_version == svc.POLICY_VERSION
        assert rows[0].lesson_content_version == 3


async def test_record_exposure_distinguishes_contexts():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        a = await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        b = await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(None, f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        await db.commit()
        assert a["exposureId"] != b["exposureId"]
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        assert len(rows) == 2


async def test_reward_for_events_none_when_no_signal():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        await db.commit()
    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        rewards = await svc.reward_for_events(db, events)
        assert rewards[0]["reward"] is None
        assert rewards[0]["rewardSource"] is None


async def test_reward_for_events_uses_matching_content_version():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        await db.commit()

    async with SessionLocal() as db:
        event = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().first()
        exposed_at = event.exposed_at
        if exposed_at.tzinfo is None:
            exposed_at = exposed_at.replace(tzinfo=UTC)
        # `func.now()` trên SQLite cắt xuống giây ⇒ phải pin mốc thời gian rõ ràng,
        # nếu không attempt "sau" có thể trông như trước exposure.
        after = exposed_at + timedelta(minutes=5)
        # Attempt trên version CŨ (2) phải bị bỏ qua.
        stale = LessonAttempt(
            lesson_id=lesson_id,
            user_id=user_id,
            client_attempt_id=f"stale-{uuid.uuid4().hex[:8]}",
            content_version=2,
            score_correct=5,
            score_total=5,
            results=[],
            xp_awarded=0,
        )
        db.add(stale)
        await db.flush()
        await db.execute(
            LessonAttempt.__table__.update()
            .where(LessonAttempt.id == stale.id)
            .values(created_at=after)
        )
        attempt = LessonAttempt(
            lesson_id=lesson_id,
            user_id=user_id,
            client_attempt_id=f"ok-{uuid.uuid4().hex[:8]}",
            content_version=3,
            score_correct=3,
            score_total=5,
            results=[],
            xp_awarded=0,
        )
        db.add(attempt)
        await db.flush()
        await db.execute(
            LessonAttempt.__table__.update()
            .where(LessonAttempt.id == attempt.id)
            .values(created_at=after)
        )
        await db.commit()

    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        rewards = await svc.reward_for_events(db, events)
        assert rewards[0]["rewardSource"] == "attempt"
        assert rewards[0]["reward"] == pytest.approx(0.6)


async def test_reward_for_events_review_goes_through_card():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(None, f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        card = ReviewCard(
            user_id=user_id,
            lesson_id=lesson_id,
            state=2,
            due_at=datetime.now(UTC),
            scheduler_version="py-fsrs-6.3.2",
        )
        db.add(card)
        await db.flush()
        db.add(
            ReviewEvent(
                card_id=card.id,
                user_id=user_id,
                rating=3,
                reviewed_at=datetime.now(UTC),
                elapsed_days=1,
                scheduled_days=2,
                scheduler_version="py-fsrs-6.3.2",
                client_review_id=f"rv-{uuid.uuid4().hex[:8]}",
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        rewards = await svc.reward_for_events(db, events)
        assert rewards[0]["rewardSource"] == "review"
        assert rewards[0]["reward"] == pytest.approx(0.6667, abs=1e-3)


async def test_reward_ignores_events_before_exposure():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        await svc.record_exposure(
            db,
            user_id=user_id,
            course=course,
            path=_path(f"lsn_{lesson_id}"),
            lesson_content_version=3,
        )
        await db.commit()

    async with SessionLocal() as db:
        event = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().first()
        exposed = event.exposed_at
        if exposed.tzinfo is None:
            exposed = exposed.replace(tzinfo=UTC)
        attempt = LessonAttempt(
            lesson_id=lesson_id,
            user_id=user_id,
            client_attempt_id=f"early-{uuid.uuid4().hex[:8]}",
            content_version=3,
            score_correct=5,
            score_total=5,
            results=[],
            xp_awarded=0,
        )
        db.add(attempt)
        await db.flush()
        # Đẩy attempt về TRƯỚC exposure ⇒ không được tính là reward.
        await db.execute(
            LessonAttempt.__table__.update()
            .where(LessonAttempt.id == attempt.id)
            .values(created_at=exposed - timedelta(days=1))
        )
        await db.commit()

    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalars().all()
        rewards = await svc.reward_for_events(db, events)
        assert rewards[0]["reward"] is None
