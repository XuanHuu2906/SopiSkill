"""P5.0 learner profile — backfill skill từ proposal, mastery theo (user, skill).

Nguyên tắc:
  - Skill lấy từ `CurriculumSkill` đã sinh ở P2.1, KHÔNG bịa skill mới.
  - Map skill ↔ lesson theo **VỊ TRÍ** `(unit.order_index, lesson.order_index)`,
    không theo title: worker generation ghi đè `lesson.title` bằng `content.title`
    của provider nên title thật khác title trong proposal.
  - Upsert `skills` theo `(course_id, key)` — không delete+insert, vì
    `skill_mastery.skill_id` là CASCADE (xoá skill sẽ xoá mastery).
  - `mastery_score` là heuristic accuracy có trọng số thời gian, **KHÔNG** phải
    xác suất đã hiệu chuẩn.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Course,
    CourseProposal,
    Lesson,
    LessonAttempt,
    LessonSkill,
    Skill,
    SkillMastery,
    Unit,
)
from app.schemas.schemas import ProposalPayload
from app.services import pedagogy

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    """SQLite trả datetime naive; `fsrs`/mốc thời gian cần aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def position_key(unit_index: int, lesson_index: int) -> tuple[int, int]:
    return (unit_index, lesson_index)


async def _latest_proposal(db: AsyncSession, course_id: uuid.UUID) -> CourseProposal | None:
    return (
        await db.execute(
            select(CourseProposal)
            .where(CourseProposal.course_id == course_id)
            .order_by(CourseProposal.version.desc())
            .limit(1)
        )
    ).scalars().first()


def _dedupe_keys(payload: ProposalPayload) -> list[tuple[str, str]]:
    """Trả [(skill_id, khoá duy nhất)] theo thứ tự proposal.

    `_slug()` cắt 24 ký tự nên hai tiêu đề dài giống nhau có thể ra cùng khoá;
    thêm hậu tố `-2`, `-3`… deterministic theo thứ tự để UNIQUE không abort.
    """
    seen: dict[str, int] = {}
    out: list[tuple[str, str]] = []
    for skill in payload.skills:
        base = skill.id
        count = seen.get(base, 0)
        seen[base] = count + 1
        key = base if count == 0 else f"{base}-{count + 1}"
        out.append((skill.id, key))
    return out


async def backfill_course_skills(db: AsyncSession, course: Course) -> int:
    """Idempotent. Trả số cặp `lesson_skills` hiện có sau khi chạy."""
    proposal_row = await _latest_proposal(db, course.id)
    if proposal_row is None:
        return 0

    try:
        payload = ProposalPayload.model_validate(proposal_row.payload or {})
    except Exception:  # pragma: no cover - payload hỏng không được làm sập caller
        logger.warning("p50 backfill skip: proposal payload không hợp lệ course=%s", course.id)
        return 0

    payload = pedagogy.normalize_curriculum(payload)
    key_by_skill_id = dict(_dedupe_keys(payload))

    # Vị trí lesson theo proposal: (unit_index, lesson_index) → title
    proposal_positions: dict[tuple[int, int], str] = {}
    for u_idx, unit in enumerate(payload.units):
        for l_idx, title in enumerate(unit.lessonTitles):
            proposal_positions[position_key(u_idx, l_idx)] = title

    # Vị trí lesson thật trong DB: tra theo (unit.order_index, lesson.order_index)
    rows = (
        await db.execute(
            select(Unit.order_index, Lesson.order_index, Lesson.id)
            .join(Lesson, Lesson.unit_id == Unit.id)
            .where(Unit.course_id == course.id)
        )
    ).all()
    lesson_by_position: dict[tuple[int, int], uuid.UUID] = {
        position_key(u_idx, l_idx): lesson_id for u_idx, l_idx, lesson_id in rows
    }

    # Upsert skills theo (course_id, key)
    skill_by_key: dict[str, Skill] = {
        skill.key: skill
        for skill in (
            await db.execute(select(Skill).where(Skill.course_id == course.id))
        ).scalars().all()
    }
    for order_index, skill in enumerate(payload.skills):
        key = key_by_skill_id.get(skill.id, skill.id)
        existing = skill_by_key.get(key)
        if existing is None:
            existing = Skill(
                course_id=course.id,
                key=key,
                title=skill.title,
                bloom_level=skill.bloomLevel,
                outcome=skill.outcome,
                order_index=order_index,
            )
            db.add(existing)
            skill_by_key[key] = existing
        else:
            existing.title = skill.title
            existing.bloom_level = skill.bloomLevel
            existing.outcome = skill.outcome
            existing.order_index = order_index
    await db.flush()

    # Upsert lesson_skills theo vị trí
    existing_links = {
        (link.lesson_id, link.skill_id)
        for link in (
            await db.execute(
                select(LessonSkill).join(Skill, Skill.id == LessonSkill.skill_id).where(
                    Skill.course_id == course.id
                )
            )
        ).scalars().all()
    }
    for order_index, skill in enumerate(payload.skills):
        key = key_by_skill_id.get(skill.id, skill.id)
        skill_row = skill_by_key.get(key)
        if skill_row is None:
            continue
        lesson_title = skill.lesson
        # Tìm vị trí proposal của title này (giữ thứ tự xuất hiện đầu tiên).
        position = next(
            (pos for pos, title in proposal_positions.items() if title == lesson_title),
            None,
        )
        if position is None:
            continue
        lesson_id = lesson_by_position.get(position)
        if lesson_id is None:
            continue
        if (lesson_id, skill_row.id) in existing_links:
            continue
        db.add(LessonSkill(lesson_id=lesson_id, skill_id=skill_row.id))
        existing_links.add((lesson_id, skill_row.id))

    try:
        await db.commit()
    except IntegrityError:  # pragma: no cover - race với worker khác
        await db.rollback()
        logger.warning("p50 backfill race course=%s", course.id)
        return 0

    return len(existing_links)


async def skills_for_course(db: AsyncSession, course_id: uuid.UUID) -> list[Skill]:
    return (
        await db.execute(
            select(Skill).where(Skill.course_id == course_id).order_by(Skill.order_index)
        )
    ).scalars().all()


async def skill_for_lesson(db: AsyncSession, lesson_id: uuid.UUID) -> Skill | None:
    return (
        await db.execute(
            select(Skill)
            .join(LessonSkill, LessonSkill.skill_id == Skill.id)
            .where(LessonSkill.lesson_id == lesson_id)
            .limit(1)
        )
    ).scalars().first()


def compute_mastery(
    attempts: list[tuple[float, datetime]],
    now: datetime,
    half_life_days: int = 30,
) -> float:
    """Accuracy có trọng số thời gian. KHÔNG phải xác suất đã hiệu chuẩn."""
    if not attempts:
        return 0.0
    now = _as_utc(now)
    half_life = max(1, half_life_days)
    weighted_sum = 0.0
    weight_total = 0.0
    for accuracy, created_at in attempts:
        created_at = _as_utc(created_at)
        age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / half_life)
        weighted_sum += weight * min(1.0, max(0.0, float(accuracy)))
        weight_total += weight
    if weight_total <= 0:
        return 0.0
    return min(1.0, max(0.0, weighted_sum / weight_total))


async def refresh_skill_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    skill_id: uuid.UUID,
    now: datetime | None = None,
) -> SkillMastery | None:
    """Tính lại mastery từ attempt ĐÚNG contentVersion hiện hành của lesson."""
    now = _as_utc(now or datetime.now(UTC))
    settings = get_settings()

    rows = (
        await db.execute(
            select(
                LessonAttempt.score_correct,
                LessonAttempt.score_total,
                LessonAttempt.created_at,
            )
            .join(Lesson, Lesson.id == LessonAttempt.lesson_id)
            .join(LessonSkill, LessonSkill.lesson_id == Lesson.id)
            .where(
                LessonAttempt.user_id == user_id,
                LessonSkill.skill_id == skill_id,
                LessonAttempt.content_version == Lesson.content_version,
                LessonAttempt.score_total > 0,
            )
        )
    ).all()
    if not rows:
        return None

    samples = [
        (correct / total, created_at) for correct, total, created_at in rows if total
    ]
    score = compute_mastery(samples, now, settings.mastery_recency_half_life_days)
    attempts_count = len(samples)
    correct_sum = sum(correct for correct, _total, _created in rows)
    total_sum = sum(total for _correct, total, _created in rows)
    last_at = max(_as_utc(created) for _c, _t, created in rows)

    row = (
        await db.execute(
            select(SkillMastery).where(
                SkillMastery.user_id == user_id, SkillMastery.skill_id == skill_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = SkillMastery(user_id=user_id, skill_id=skill_id)
        db.add(row)
    row.attempts = attempts_count
    row.correct = correct_sum
    row.total = total_sum
    row.mastery_score = score
    row.last_attempt_at = last_at
    await db.flush()
    return row


async def course_mastery(
    db: AsyncSession, course: Course, user_id: uuid.UUID
) -> dict:
    settings = get_settings()
    skills = await skills_for_course(db, course.id)
    mastery_rows = {
        row.skill_id: row
        for row in (
            await db.execute(
                select(SkillMastery)
                .join(Skill, Skill.id == SkillMastery.skill_id)
                .where(SkillMastery.user_id == user_id, Skill.course_id == course.id)
            )
        ).scalars().all()
    }

    items = []
    for skill in skills:
        row = mastery_rows.get(skill.id)
        items.append(
            {
                "skillId": skill.key,
                "title": skill.title,
                "bloomLevel": skill.bloom_level,
                "masteryScore": round(row.mastery_score, 4) if row else 0.0,
                "method": "rule_based",
                "attempts": row.attempts if row else 0,
                "correct": row.correct if row else 0,
                "total": row.total if row else 0,
                "lastAttemptAt": row.last_attempt_at.isoformat()
                if row and row.last_attempt_at
                else None,
                "passThreshold": settings.mastery_pass_threshold,
            }
        )

    scored = [i["masteryScore"] for i in items if i["attempts"] > 0]
    course_percent = round(sum(scored) / len(scored) * 100, 1) if scored else 0.0
    return {"items": items, "coursePercent": course_percent}


async def backfill_all_skills(db: AsyncSession) -> int:
    """Reconciler: chỉ chạy khi `P50_BACKFILL_ENABLED`. Trả số link đã có."""
    if not get_settings().p50_backfill_enabled:
        return 0

    written = 0
    courses = (await db.execute(select(Course).order_by(Course.created_at))).scalars().all()
    for course in courses:
        try:
            written += await backfill_course_skills(db, course)
        except Exception:  # pragma: no cover - một course hỏng không chặn cả batch
            await db.rollback()
            logger.exception("p50 backfill failed course=%s", course.id)
    return written
