"""P5.0 skill backfill — proposal payload → skills/lesson_skills."""

import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Course, CourseProposal, Lesson, Unit, User
from app.services import learner_profile_service

pytestmark = pytest.mark.asyncio


def _payload(**overrides) -> dict:
    base = {
        "name": "Học Python",
        "objective": "Nắm cú pháp cơ bản",
        "outcomes": ["Viết script đơn giản", "Hiểu kiểu dữ liệu"],
        "units": [
            {"title": "U1", "blurb": "", "lessonTitles": ["Biến và kiểu", "Vòng lặp"]},
            {"title": "U2", "blurb": "", "lessonTitles": ["Hàm"]},
        ],
        "skills": [],
        "prerequisites": [],
    }
    base.update(overrides)
    return base


async def _new_user(db) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        external_id=f"p50-{suffix}",
        email=f"p50-{suffix}@test.dev",
        display_name="P50 Learner",
    )
    db.add(user)
    await db.flush()
    return user


async def _seed_course(db, user, proposal_payload, real_lesson_title):
    course = Course(
        user_id=user.id, topic="Python", status="ready", client_course_id=f"c-{uuid.uuid4()}"
    )
    db.add(course)
    await db.flush()
    db.add(CourseProposal(course_id=course.id, version=1, payload=proposal_payload))
    unit = Unit(course_id=course.id, order_index=0, title="U1", blurb="")
    db.add(unit)
    await db.flush()
    lesson = Lesson(
        unit_id=unit.id,
        course_id=course.id,
        order_index=0,
        title=real_lesson_title,
        content=[],
        content_version=1,
        status="ready",
    )
    db.add(lesson)
    await db.commit()
    return course, lesson


async def test_backfill_creates_skills_and_links():
    async with SessionLocal() as db:
        user = await _new_user(db)
        course, _ = await _seed_course(db, user, _payload(), "Tiêu đề do model sinh: Biến")
        written = await learner_profile_service.backfill_course_skills(db, course)
        assert written >= 1

        skills = await learner_profile_service.skills_for_course(db, course.id)
        assert skills[0].key == "bi-n-v-ki-u"
        assert skills[0].title == "Biến và kiểu"


async def test_backfill_maps_by_position_not_title():
    async with SessionLocal() as db:
        user = await _new_user(db)
        course, lesson = await _seed_course(db, user, _payload(), "Tiêu đề hoàn toàn khác")
        await learner_profile_service.backfill_course_skills(db, course)
        row = await learner_profile_service.skill_for_lesson(db, lesson.id)
        assert row is not None
        assert row.key == "bi-n-v-ki-u"


async def test_backfill_is_idempotent():
    async with SessionLocal() as db:
        user = await _new_user(db)
        course, _ = await _seed_course(db, user, _payload(), "X")
        first = await learner_profile_service.backfill_course_skills(db, course)
        second = await learner_profile_service.backfill_course_skills(db, course)
        assert first == second
        skills = await learner_profile_service.skills_for_course(db, course.id)
        assert len({s.key for s in skills}) == len(skills)


async def test_backfill_without_proposal_returns_zero():
    async with SessionLocal() as db:
        user = await _new_user(db)
        course = Course(
            user_id=user.id, topic="T", status="ready", client_course_id=f"c-{uuid.uuid4()}"
        )
        db.add(course)
        await db.commit()
        assert await learner_profile_service.backfill_course_skills(db, course) == 0


async def test_duplicate_slugs_get_deterministic_suffixes():
    payload = _payload(
        units=[
            {
                "title": "U",
                "blurb": "",
                "lessonTitles": [
                    "Cùng một tiêu đề rất dài giống nhau A",
                    "Cùng một tiêu đề rất dài giống nhau B",
                ],
            },
            {"title": "U2", "blurb": "", "lessonTitles": ["Bài khác"]},
        ]
    )
    async with SessionLocal() as db:
        user = await _new_user(db)
        course, _ = await _seed_course(db, user, payload, "X")
        await learner_profile_service.backfill_course_skills(db, course)
        skills = await learner_profile_service.skills_for_course(db, course.id)
        keys = [s.key for s in skills]
        assert len(keys) == len(set(keys))
        assert any(k.endswith("-2") for k in keys)


async def test_backfill_does_not_delete_existing_mastery_rows():
    """Upsert theo (course_id, key): chạy lại không được xoá skill ⇒ không cascade mastery."""
    from app.models import SkillMastery

    async with SessionLocal() as db:
        user = await _new_user(db)
        course, lesson = await _seed_course(db, user, _payload(), "X")
        await learner_profile_service.backfill_course_skills(db, course)
        skill = await learner_profile_service.skill_for_lesson(db, lesson.id)
        db.add(
            SkillMastery(user_id=user.id, skill_id=skill.id, attempts=1, correct=1, total=2,
                         mastery_score=0.5)
        )
        await db.commit()

        await learner_profile_service.backfill_course_skills(db, course)

        row = (
            await db.execute(
                select(SkillMastery).where(
                    SkillMastery.user_id == user.id, SkillMastery.skill_id == skill.id
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.mastery_score == 0.5
