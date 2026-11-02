"""P5.0 learning path — gợi ý bài kế tiếp tôn trọng prerequisite DAG.

Quyết định đã chốt:
  - Prerequisite chưa đạt ⇒ **KHÔNG** đề xuất bài mới; trả `blockedBy` kèm lý do
    và fallback `reviewLessonId` = bài đã học có mastery thấp nhất (tránh dead-end).
  - Thứ tự lesson dùng `(unit.order_index, lesson.order_index)` như course detail.
  - Mọi truy vấn scope theo course đã được xác thực ownership ở tầng route.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Course,
    CourseProposal,
    Lesson,
    LessonSkill,
    Skill,
    SkillMastery,
    Unit,
)
from app.schemas.schemas import ProposalPayload
from app.services import course_service, pedagogy, spaced_repetition_service

logger = logging.getLogger(__name__)

REASON_NEXT_IN_SEQUENCE = "NEXT_IN_SEQUENCE"
REASON_PREREQUISITES_MET = "PREREQUISITES_MET"
REASON_PREREQUISITE_NOT_MET = "PREREQUISITE_NOT_MET"
REASON_FALLBACK_REVIEW_WEAKEST = "FALLBACK_REVIEW_WEAKEST"

_REASON_MESSAGES = {
    REASON_NEXT_IN_SEQUENCE: "Bài tiếp theo trong lộ trình.",
    REASON_PREREQUISITES_MET: "Bạn đã đạt các kỹ năng cần trước.",
    REASON_PREREQUISITE_NOT_MET: "Cần đạt kỹ năng trước khi học bài này.",
    REASON_FALLBACK_REVIEW_WEAKEST: "Ôn lại bài yếu nhất trước khi học tiếp.",
}


def position_key(unit_index: int, lesson_index: int) -> tuple[int, int]:
    return (unit_index, lesson_index)


def _status_value(lesson: Lesson) -> str:
    """`Lesson.status` có thể là enum hoặc str tuỳ session/nơi nạp."""
    status = lesson.status
    return status.value if hasattr(status, "value") else str(status)


async def _latest_proposal(db: AsyncSession, course_id: uuid.UUID) -> CourseProposal | None:
    return (
        await db.execute(
            select(CourseProposal)
            .where(CourseProposal.course_id == course_id)
            .order_by(CourseProposal.version.desc())
            .limit(1)
        )
    ).scalars().first()


async def build_learning_path(db: AsyncSession, course: Course, user_id: uuid.UUID) -> dict:
    settings = get_settings()
    threshold = settings.mastery_pass_threshold

    proposal_row = await _latest_proposal(db, course.id)
    payload: ProposalPayload | None = None
    if proposal_row is not None:
        try:
            payload = pedagogy.normalize_curriculum(
                ProposalPayload.model_validate(proposal_row.payload or {})
            )
        except Exception:  # pragma: no cover - payload hỏng không làm sập endpoint
            logger.warning("p50 learning path: proposal không hợp lệ course=%s", course.id)

    proposal_title_by_position: dict[tuple[int, int], str] = {}
    if payload is not None:
        for u_idx, unit in enumerate(payload.units):
            for l_idx, title in enumerate(unit.lessonTitles):
                proposal_title_by_position[position_key(u_idx, l_idx)] = title

    lessons = (
        await db.execute(
            select(Lesson, Unit.order_index)
            .join(Unit, Unit.id == Lesson.unit_id)
            .where(Lesson.course_id == course.id)
            .order_by(Unit.order_index, Lesson.order_index)
        )
    ).all()

    skills = (
        await db.execute(select(Skill).where(Skill.course_id == course.id))
    ).scalars().all()
    skill_by_id = {skill.id: skill for skill in skills}
    skill_by_key = {skill.key: skill for skill in skills}

    mastery_by_skill = {
        row.skill_id: row.mastery_score
        for row in (
            await db.execute(
                select(SkillMastery)
                .join(Skill, Skill.id == SkillMastery.skill_id)
                .where(SkillMastery.user_id == user_id, Skill.course_id == course.id)
            )
        ).scalars().all()
    }

    lesson_skills = (
        await db.execute(
            select(LessonSkill).join(Skill, Skill.id == LessonSkill.skill_id).where(
                Skill.course_id == course.id
            )
        )
    ).scalars().all()
    skill_by_lesson = {link.lesson_id: link.skill_id for link in lesson_skills}

    completed_ids = await course_service._completed_lesson_ids(db, course.id, user_id)

    # prerequisite skill key → parent keys
    prereqs_of_skill: dict[str, list[str]] = {}
    edges: list[list[str]] = []
    if payload is not None:
        for parent, child in payload.prerequisites:
            prereqs_of_skill.setdefault(child, []).append(parent)
            edges.append([parent, child])

    def prerequisite_status(skill_key: str) -> list[dict]:
        out = []
        for parent_key in prereqs_of_skill.get(skill_key, []):
            parent_skill = skill_by_key.get(parent_key)
            score = mastery_by_skill.get(parent_skill.id, 0.0) if parent_skill else 0.0
            out.append(
                {
                    "skillId": parent_key,
                    "title": parent_skill.title if parent_skill else parent_key,
                    "masteryScore": round(score, 4),
                    "met": score >= threshold,
                }
            )
        return out

    def skill_key_for_lesson(lesson_id: uuid.UUID) -> str | None:
        skill_id = skill_by_lesson.get(lesson_id)
        if skill_id is None:
            return None
        skill = skill_by_id.get(skill_id)
        return skill.key if skill else None

    next_lesson: dict | None = None
    blocked_by: list[dict] = []

    for position, (lesson, unit_index) in enumerate(lessons):
        if _status_value(lesson) != "ready" or lesson.id in completed_ids:
            continue
        key = skill_key_for_lesson(lesson.id)
        if key is None:
            # Lesson không có skill (chưa backfill): không chặn, nhưng không suy đoán
            # prerequisite. Vẫn có thể là bài kế tiếp nếu chưa có gì tốt hơn.
            if next_lesson is None:
                next_lesson = {
                    "lessonId": f"lsn_{lesson.id}",
                    "title": lesson.title,
                    "reason": {
                        "code": REASON_NEXT_IN_SEQUENCE,
                        "message": _REASON_MESSAGES[REASON_NEXT_IN_SEQUENCE],
                    },
                }
            continue

        statuses = prerequisite_status(key)
        unmet = [item for item in statuses if not item["met"]]
        if unmet:
            blocked_by.append(
                {
                    "lessonId": f"lsn_{lesson.id}",
                    "title": lesson.title,
                    "prerequisites": statuses,
                    "reason": {
                        "code": REASON_PREREQUISITE_NOT_MET,
                        "message": _REASON_MESSAGES[REASON_PREREQUISITE_NOT_MET],
                    },
                }
            )
            continue

        if next_lesson is None:
            code = REASON_PREREQUISITES_MET if statuses else REASON_NEXT_IN_SEQUENCE
            next_lesson = {
                "lessonId": f"lsn_{lesson.id}",
                "title": lesson.title,
                "reason": {"code": code, "message": _REASON_MESSAGES[code]},
            }

    # Fallback: bài đã hoàn thành có mastery thấp nhất (chỉ khi không có next lesson)
    review_lesson_id: str | None = None
    if next_lesson is None:
        weakest: tuple[float, Lesson] | None = None
        for lesson, _unit_index in lessons:
            if lesson.id not in completed_ids:
                continue
            skill_id = skill_by_lesson.get(lesson.id)
            score = mastery_by_skill.get(skill_id, 0.0) if skill_id else 0.0
            if weakest is None or score < weakest[0]:
                weakest = (score, lesson)
        if weakest is not None:
            review_lesson_id = f"lsn_{weakest[1].id}"

    due = await spaced_repetition_service.due_cards(db, user_id, course_id=course.id, limit=1)

    nodes = [
        {
            "id": skill.key,
            "title": skill.title,
            "bloomLevel": skill.bloom_level,
        }
        for skill in skills
    ]

    return {
        "nextLesson": next_lesson,
        "reviewLessonId": review_lesson_id,
        "reviewDueCount": due["total"],
        "blockedBy": blocked_by,
        "prerequisitesDag": {"nodes": nodes, "edges": edges},
    }
