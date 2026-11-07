"""P5.0 mastery — deterministic, recency-weighted, version-aware."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    Course,
    Lesson,
    LessonAttempt,
    LessonSkill,
    ReviewCard,
    Skill,
    SkillMastery,
    Unit,
    User,
)
from app.services import learner_profile_service as lps

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_empty_attempts_is_zero():
    assert lps.compute_mastery([], NOW) == 0.0


def test_single_recent_perfect_attempt_is_one():
    assert lps.compute_mastery([(1.0, NOW)], NOW) == 1.0


def test_zero_accuracy_is_zero():
    assert lps.compute_mastery([(0.0, NOW)], NOW) == 0.0


def test_recency_weights_recent_more():
    old = NOW - timedelta(days=30)
    score = lps.compute_mastery([(0.0, old), (1.0, NOW)], NOW, half_life_days=30)
    assert score > 0.5


def test_deterministic():
    data = [(0.5, NOW - timedelta(days=10)), (0.9, NOW)]
    assert lps.compute_mastery(data, NOW) == lps.compute_mastery(data, NOW)


def test_score_is_clamped():
    assert 0.0 <= lps.compute_mastery([(5.0, NOW)], NOW) <= 1.0


def test_naive_datetime_is_coerced():
    naive = datetime(2026, 11, 2, 12, 0)
    assert lps.compute_mastery([(1.0, naive)], datetime(2026, 11, 2, 12, 0)) == 1.0


async def _seed(db, score_correct=3, score_total=3):
    suffix = uuid.uuid4().hex[:10]
    user = User(external_id=f"mst-{suffix}", email=f"mst-{suffix}@test.dev")
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
    skill = Skill(course_id=course.id, key=f"k-{suffix}", title="Kỹ năng", order_index=0)
    db.add(skill)
    await db.flush()
    db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
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
    return user, course, lesson, skill, attempt


@pytest.mark.asyncio
async def test_refresh_creates_mastery_row():
    async with SessionLocal() as db:
        user, _course, _lesson, skill, _attempt = await _seed(db)
        row = await lps.refresh_skill_mastery(db, user.id, skill.id, now=NOW)
        await db.commit()
        assert row is not None
        assert row.mastery_score == 1.0
        assert row.attempts == 1
        assert row.correct == 3
        assert row.total == 3


@pytest.mark.asyncio
async def test_same_version_attempt_accumulates_not_inflates():
    """Nộp lại cùng version: mastery = 1 attempt trung bình, không tăng >1."""
    async with SessionLocal() as db:
        user, _course, lesson, skill, _attempt = await _seed(db)
        db.add(
            LessonAttempt(
                lesson_id=lesson.id,
                user_id=user.id,
                client_attempt_id=f"att2-{uuid.uuid4().hex[:8]}",
                content_version=1,
                score_correct=0,
                score_total=3,
                results=[],
            )
        )
        await db.commit()

        row = await lps.refresh_skill_mastery(db, user.id, skill.id, now=NOW)
        assert row.mastery_score == 0.5
        assert row.attempts == 2
        assert row.mastery_score <= 1.0


@pytest.mark.asyncio
async def test_version_bump_drops_mastery_to_zero_until_relearned():
    async with SessionLocal() as db:
        user, _course, lesson, skill, _attempt = await _seed(db)
        await lps.refresh_skill_mastery(db, user.id, skill.id, now=NOW)
        await db.commit()

        lesson.content_version = 2
        await db.commit()

        row = await lps.refresh_skill_mastery(db, user.id, skill.id, now=NOW)
        await db.commit()
        # Không còn attempt nào đúng version hiện hành ⇒ mastery phải về 0 (không
        # tiếp tục gate next-lesson bằng điểm của nội dung cũ).
        assert row is not None
        assert row.mastery_score == 0.0
        assert row.attempts == 0

        existing = (
            await db.execute(
                select(SkillMastery).where(
                    SkillMastery.user_id == user.id, SkillMastery.skill_id == skill.id
                )
            )
        ).scalar_one()
        assert existing.mastery_score == 0.0
        # Attempt cũ vẫn còn trong bảng lịch sử (không xoá dữ liệu).
        attempts = (
            await db.execute(
                select(LessonAttempt).where(LessonAttempt.user_id == user.id)
            )
        ).scalars().all()
        assert len(attempts) == 1


@pytest.mark.asyncio
async def test_attempt_without_skill_does_not_fail(client, monkeypatch):
    """Lesson không có `lesson_skills` (legacy/chưa backfill) ⇒ attempt vẫn OK."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "p50_enabled", True)

    def csrf() -> dict:
        return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}

    suffix = uuid.uuid4().hex[:8]
    reg = await client.post(
        "/v1/auth/register",
        json={"email": f"noskill-{suffix}@test.dev", "password": "Passw0rd!123"},
    )
    assert reg.status_code == 201, reg.text

    # Seed trực tiếp course/unit/lesson KHÔNG có Skill/LessonSkill — không dùng
    # generation (generation với flag on sẽ tự backfill skill).
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == f"noskill-{suffix}@test.dev"))
        ).scalars().first()
        assert user is not None
        course = Course(
            user_id=user.id,
            topic="Không skill",
            status="ready",
            client_course_id=f"c-{uuid.uuid4()}",
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
            content=[
                {"type": "mc", "question": "1+1?", "options": ["1", "2"], "answerIndex": 1}
            ],
            content_version=1,
            status="ready",
        )
        db.add(lesson)
        await db.commit()
        lesson_id = f"lsn_{lesson.id}"
        lesson_uuid = lesson.id

    resp = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        headers=csrf(),
        json={"clientAttemptId": "att-noskill-1", "contentVersion": 1,
              "answers": [{"index": 0, "answer": 1}]},
    )
    assert resp.status_code == 201, resp.text
    # Flag bật + không có skill ⇒ card vẫn tạo nhưng không gắn skill, mastery bỏ qua.
    assert resp.json()["reviewCardCreated"] is True

    async with SessionLocal() as db:
        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.lesson_id == lesson_uuid))
        ).scalar_one()
        assert card.skill_id is None
