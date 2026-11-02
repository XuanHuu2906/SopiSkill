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
        # Không còn attempt nào đúng version hiện hành ⇒ không có row mới
        assert row is None
        existing = (
            await db.execute(
                select(SkillMastery).where(
                    SkillMastery.user_id == user.id, SkillMastery.skill_id == skill.id
                )
            )
        ).scalar_one()
        # Row cũ giữ nguyên (không reset dữ liệu), nhưng không còn attempt hợp lệ
        assert existing.attempts == 1


@pytest.mark.asyncio
async def test_attempt_without_skill_does_not_fail(client):
    """Lesson chưa backfill skill ⇒ attempt vẫn thành công, reviewCardCreated=False."""

    def csrf() -> dict:
        return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}

    suffix = uuid.uuid4().hex[:8]
    reg = await client.post(
        "/v1/auth/register",
        json={"email": f"noskill-{suffix}@test.dev", "password": "Passw0rd!123"},
    )
    assert reg.status_code == 201, reg.text

    course = await client.post(
        "/v1/courses",
        json={"topic": "Python", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf(),
    )
    assert course.status_code == 201, course.text
    course_id = course.json()["id"]
    for i in range(5):
        await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=csrf(),
        )
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf())
    detail = await client.get(f"/v1/courses/{course_id}", headers=csrf())
    lesson_id = next(
        lesson["id"]
        for unit in detail.json()["units"]
        for lesson in unit["lessons"]
    )

    from tests.support import correct_answers

    version, answers = await correct_answers(lesson_id)
    resp = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        headers=csrf(),
        json={"clientAttemptId": "att-noskill-1", "contentVersion": version, "answers": answers},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["reviewCardCreated"] is False

