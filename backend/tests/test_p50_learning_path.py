"""P5.0 learning path — prerequisite gating + weakest-lesson fallback."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Course,
    CourseProposal,
    Lesson,
    LessonSkill,
    Skill,
    SkillMastery,
    Unit,
    User,
)
from app.services import learning_path_service
from app.services.learning_path_service import position_key

NOW_TEXT = "2026-11-02T12:00:00+00:00"

SKILL_A = {
    "id": "s1",
    "title": "Kiến thức nền",
    "lesson": "Bài 1",
    "bloomLevel": "understand",
    "outcome": "Hiểu nền",
}
SKILL_B = {
    "id": "s2",
    "title": "Kỹ năng nâng cao",
    "lesson": "Bài 2",
    "bloomLevel": "apply",
    "outcome": "Áp dụng được",
}


def _payload():
    return {
        "name": "Khóa",
        "objective": "Mục tiêu",
        "outcomes": ["a", "b"],
        "units": [
            {"title": "U1", "blurb": "", "lessonTitles": ["Bài 1"]},
            {"title": "U2", "blurb": "", "lessonTitles": ["Bài 2"]},
        ],
        "skills": [SKILL_A, SKILL_B],
        "prerequisites": [["s1", "s2"]],
    }


async def _seed(db, mastery_a):
    suffix = uuid.uuid4().hex[:10]
    user = User(external_id=f"lp-{suffix}", email=f"lp-{suffix}@test.dev")
    db.add(user)
    await db.flush()
    course = Course(
        user_id=user.id, topic="Khóa", status="ready", client_course_id=f"c-{uuid.uuid4()}"
    )
    db.add(course)
    await db.flush()
    db.add(CourseProposal(course_id=course.id, version=1, payload=_payload()))

    lessons = {}
    skills = {}
    for index, (key, title, lesson_title) in enumerate(
        [("s1", "Kiến thức nền", "Bài 1"), ("s2", "Kỹ năng nâng cao", "Bài 2")]
    ):
        unit = Unit(course_id=course.id, order_index=index, title=f"U{index + 1}", blurb="")
        db.add(unit)
        await db.flush()
        lesson = Lesson(
            unit_id=unit.id,
            course_id=course.id,
            order_index=0,
            title=lesson_title,
            content=[],
            content_version=1,
            status="ready",
        )
        db.add(lesson)
        await db.flush()
        skill = Skill(
            course_id=course.id,
            key=key,
            title=title,
            bloom_level="understand",
            order_index=index,
        )
        db.add(skill)
        await db.flush()
        db.add(LessonSkill(lesson_id=lesson.id, skill_id=skill.id))
        lessons[key] = lesson
        skills[key] = skill

    if mastery_a is not None:
        db.add(
            SkillMastery(
                user_id=user.id,
                skill_id=skills["s1"].id,
                attempts=1,
                correct=1,
                total=1,
                mastery_score=mastery_a,
            )
        )
    await db.commit()
    return user, course, lessons, skills


@pytest.mark.asyncio
async def test_blocks_next_lesson_when_prerequisite_not_met():
    async with SessionLocal() as db:
        user, course, lessons, _skills = await _seed(db, mastery_a=0.4)

        # bài 1 đã "completed" (đạt 80%) nhưng mastery 0.4 < 0.7
        from app.models import LessonAttempt

        db.add(
            LessonAttempt(
                lesson_id=lessons["s1"].id,
                user_id=user.id,
                client_attempt_id=f"a-{uuid.uuid4().hex[:8]}",
                content_version=1,
                score_correct=4,
                score_total=4,
                results=[],
            )
        )
        await db.commit()

        path = await learning_path_service.build_learning_path(db, course, user.id)
        assert path["nextLesson"] is None
        assert path["blockedBy"]
        assert path["blockedBy"][0]["prerequisites"][0]["met"] is False
        assert path["reviewLessonId"] is not None
        assert path["blockedBy"][0]["reason"]["code"] == "PREREQUISITE_NOT_MET"


@pytest.mark.asyncio
async def test_recommends_next_when_prerequisite_met():
    async with SessionLocal() as db:
        user, course, lessons, _skills = await _seed(db, mastery_a=0.9)
        from app.models import LessonAttempt

        db.add(
            LessonAttempt(
                lesson_id=lessons["s1"].id,
                user_id=user.id,
                client_attempt_id=f"a-{uuid.uuid4().hex[:8]}",
                content_version=1,
                score_correct=4,
                score_total=4,
                results=[],
            )
        )
        await db.commit()

        path = await learning_path_service.build_learning_path(db, course, user.id)
        assert path["nextLesson"] is not None
        assert path["nextLesson"]["reason"]["code"] in {
            "NEXT_IN_SEQUENCE",
            "PREREQUISITES_MET",
        }
        assert path["blockedBy"] == []


@pytest.mark.asyncio
async def test_dag_exposes_nodes_and_edges():
    async with SessionLocal() as db:
        user, course, _lessons, _skills = await _seed(db, mastery_a=0.9)
        path = await learning_path_service.build_learning_path(db, course, user.id)
        dag = path["prerequisitesDag"]
        assert {n["id"] for n in dag["nodes"]} >= {"s1", "s2"}
        assert [list(edge) for edge in dag["edges"]] == [["s1", "s2"]]


@pytest.mark.asyncio
async def test_first_lesson_recommended_without_prerequisites():
    async with SessionLocal() as db:
        user, course, _lessons, _skills = await _seed(db, mastery_a=None)
        path = await learning_path_service.build_learning_path(db, course, user.id)
        assert path["nextLesson"]["reason"]["code"] == "NEXT_IN_SEQUENCE"
        # Bài 2 vẫn bị chặn vì s1 chưa có mastery — đó là hành vi đúng.
        assert len(path["blockedBy"]) == 1
        assert path["blockedBy"][0]["reason"]["code"] == "PREREQUISITE_NOT_MET"


@pytest.mark.asyncio
async def test_position_key_helper():
    assert position_key(1, 2) == (1, 2)
