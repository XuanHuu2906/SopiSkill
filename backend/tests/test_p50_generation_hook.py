"""P5.0 generation hook — skills written when flag on, reconciler respects flag."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Course, CourseProposal, Lesson, Unit, User
from app.services import learner_profile_service


def _payload():
    return {
        "name": "Khóa",
        "objective": "Mục tiêu",
        "outcomes": ["a", "b"],
        "units": [
            {"title": "U1", "blurb": "", "lessonTitles": ["Bài 1"]},
            {"title": "U2", "blurb": "", "lessonTitles": ["Bài 2"]},
        ],
        "skills": [],
        "prerequisites": [],
    }


async def _seed(db, with_proposal=True):
    suffix = uuid.uuid4().hex[:10]
    user = User(external_id=f"gen-{suffix}", email=f"gen-{suffix}@test.dev")
    db.add(user)
    await db.flush()
    course = Course(
        user_id=user.id, topic="Khóa", status="ready", client_course_id=f"c-{uuid.uuid4()}"
    )
    db.add(course)
    await db.flush()
    if with_proposal:
        db.add(CourseProposal(course_id=course.id, version=1, payload=_payload()))
    unit = Unit(course_id=course.id, order_index=0, title="U1", blurb="")
    db.add(unit)
    await db.flush()
    lesson = Lesson(
        unit_id=unit.id,
        course_id=course.id,
        order_index=0,
        title="Bài 1",
        content=[],
        content_version=1,
        status="ready",
    )
    db.add(lesson)
    await db.commit()
    return course


@pytest.mark.asyncio
async def test_backfill_writes_skills_for_generated_course():
    async with SessionLocal() as db:
        course = await _seed(db)
        await learner_profile_service.backfill_course_skills(db, course)
        skills = await learner_profile_service.skills_for_course(db, course.id)
        assert skills
        assert all(s.course_id == course.id for s in skills)


@pytest.mark.asyncio
async def test_reconciler_respects_backfill_flag(monkeypatch):
    settings = get_settings()
    async with SessionLocal() as db:
        course = await _seed(db)

        monkeypatch.setattr(settings, "p50_backfill_enabled", False)
        assert await learner_profile_service.backfill_all_skills(db) == 0

        monkeypatch.setattr(settings, "p50_backfill_enabled", True)
        written = await learner_profile_service.backfill_all_skills(db)
        assert written >= 1

        skills = await learner_profile_service.skills_for_course(db, course.id)
        assert skills
        monkeypatch.setattr(settings, "p50_backfill_enabled", False)


@pytest.mark.asyncio
async def test_generation_writes_skills_when_enabled(client, monkeypatch):
    """Chạy generation thật (mock provider, inline) với P50_ENABLED ⇒ skills tồn tại."""
    settings = get_settings()
    monkeypatch.setattr(settings, "p50_enabled", True)
    try:
        suffix = uuid.uuid4().hex[:8]
        reg = await client.post(
            "/v1/auth/register",
            json={"email": f"genhook-{suffix}@test.dev", "password": "Passw0rd!123"},
        )
        assert reg.status_code == 201, reg.text

        def csrf() -> dict:
            return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}

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
        approved = await client.post(
            f"/v1/courses/{course_id}/approve", headers=csrf()
        )
        assert approved.status_code == 202, approved.text

        raw_id = uuid.UUID(course_id.removeprefix("crs_"))
        async with SessionLocal() as db:
            skills = await learner_profile_service.skills_for_course(db, raw_id)
            assert skills, "generation hook phải backfill skill khi P50_ENABLED"
    finally:
        monkeypatch.setattr(settings, "p50_enabled", False)
