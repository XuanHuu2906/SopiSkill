"""User service — đăng ký/đăng nhập email + password, profile stats, update & account deletion.

Demo mode (header X-User-Id) chỉ được bật qua cấu hình cho local development.
"""

from datetime import UTC, datetime
import re

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import (
    Course,
    CourseGlossaryTerm,
    CourseInterview,
    CourseProposal,
    CourseSource,
    CourseStatus,
    GenerationJob,
    Lesson,
    LessonAttempt,
    LessonCitation,
    LessonSkill,
    LlmUsageEvent,
    RecommendationEvent,
    ReviewCard,
    ReviewEvent,
    Skill,
    SkillMastery,
    Source,
    SourceChunk,
    SourceChunkEmbedding,
    SourceDocument,
    SourceResearchRun,
    TutorMessage,
    TutorThread,
    TutorToolCall,
    TutorUsageEvent,
    Unit,
    User,
    XpEvent,
)
from app.services.lesson_content import is_completed

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEMO_PREFIX = "demo:"


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_EMAIL", "message": "Email không hợp lệ."},
        )
    return email


def validate_password(password: str) -> str:
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "WEAK_PASSWORD", "message": "Mật khẩu phải từ 8 đến 128 ký tự."},
        )
    return password


async def get_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def register_user(db: AsyncSession, email: str, password: str) -> User:
    email = normalize_email(email)
    validate_password(password)
    if await get_by_email(db, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_TAKEN", "message": "Email đã được đăng ký."},
        )
    user = User(
        external_id=f"email:{email}",
        email=email,
        password_hash=hash_password(password),
        display_name=email.split("@")[0],
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    email = normalize_email(email)
    user = await get_by_email(db, email)
    # So khớp cả khi user không tồn tại để tránh user-enumeration timing.
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Email hoặc mật khẩu không đúng."},
        )
    return user


async def get_or_create_user(db: AsyncSession, external_id: str) -> User:
    """Demo-mode helper: chỉ gọi khi ALLOW_DEMO_HEADER được bật."""
    if not external_id or not external_id.strip():
        external_id = "anonymous"
    external_id = external_id.strip()[:128]

    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(external_id=external_id, display_name=external_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


# ---------- Wave 4 / M1-ME-SURFACE: stats, profile update, account deletion ----------


async def get_user_stats(db: AsyncSession, user: User) -> dict:
    """Tổng hợp số liệu học tập thực tế từ DB cho người dùng hiện tại."""
    courses_total = int(
        (await db.execute(select(func.count(Course.id)).where(Course.user_id == user.id))).scalar_one()
        or 0
    )
    courses_ready = int(
        (
            await db.execute(
                select(func.count(Course.id)).where(
                    Course.user_id == user.id, Course.status == CourseStatus.ready
                )
            )
        ).scalar_one()
        or 0
    )

    lesson_rows = (
        await db.execute(
            select(Lesson.id, Lesson.content_version)
            .join(Course, Course.id == Lesson.course_id)
            .where(Course.user_id == user.id)
        )
    ).all()
    lesson_version_map = {lid: cver for lid, cver in lesson_rows}
    lessons_total = len(lesson_version_map)

    attempt_rows = (
        await db.execute(
            select(
                LessonAttempt.lesson_id,
                LessonAttempt.content_version,
                LessonAttempt.score_correct,
                LessonAttempt.score_total,
            ).where(LessonAttempt.user_id == user.id)
        )
    ).all()
    attempts_total = len(attempt_rows)
    completed_lesson_ids = {
        lid
        for lid, cver, correct, total in attempt_rows
        if lesson_version_map.get(lid) == cver and is_completed(int(correct or 0), int(total or 0))
    }

    reviews_due = 0
    if get_settings().p50_enabled:
        now = datetime.now(UTC)
        reviews_due = int(
            (
                await db.execute(
                    select(func.count(ReviewCard.id)).where(
                        ReviewCard.user_id == user.id,
                        ReviewCard.due_at <= now,
                    )
                )
            ).scalar_one()
            or 0
        )

    return {
        "userId": f"usr_{user.id}",
        "email": user.email,
        "displayName": user.display_name,
        "xp": int(user.xp or 0),
        "streakDays": int(user.streak_days or 0),
        "lastActiveDate": user.last_active_date,
        "coursesTotal": courses_total,
        "coursesReady": courses_ready,
        "lessonsCompleted": len(completed_lesson_ids),
        "lessonsTotal": lessons_total,
        "attemptsTotal": attempts_total,
        "reviewsDue": reviews_due,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
    }


async def update_user_profile(db: AsyncSession, user: User, display_name: str) -> User:
    cleaned = " ".join((display_name or "").split()).strip()
    if not cleaned or len(cleaned) > 80:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_DISPLAY_NAME",
                "message": "Tên hiển thị phải từ 1 đến 80 ký tự.",
            },
        )
    user.display_name = cleaned
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user_account(
    db: AsyncSession,
    user: User,
    *,
    confirm_text: str,
    password: str | None = None,
) -> None:
    """Xóa toàn bộ dữ liệu thuộc sở hữu user theo đúng thứ tự FK trong 1 transaction."""
    if (confirm_text or "").strip().upper() != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DELETE_CONFIRMATION_REQUIRED",
                "message": "Vui lòng nhập chính xác 'DELETE' để xác nhận xóa tài khoản.",
            },
        )
    if user.password_hash:
        if not password or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Mật khẩu xác nhận không đúng.",
                },
            )

    course_ids = [
        row[0]
        for row in (await db.execute(select(Course.id).where(Course.user_id == user.id))).all()
    ]
    lesson_ids = (
        [
            row[0]
            for row in (
                await db.execute(select(Lesson.id).where(Lesson.course_id.in_(course_ids)))
            ).all()
        ]
        if course_ids
        else []
    )
    job_ids = (
        [
            row[0]
            for row in (
                await db.execute(
                    select(GenerationJob.id).where(GenerationJob.course_id.in_(course_ids))
                )
            ).all()
        ]
        if course_ids
        else []
    )
    source_ids = [
        row[0]
        for row in (await db.execute(select(Source.id).where(Source.owner_id == user.id))).all()
    ]

    thread_conds = [TutorThread.user_id == user.id]
    if course_ids:
        thread_conds.append(TutorThread.course_id.in_(course_ids))
    thread_ids = [
        row[0]
        for row in (await db.execute(select(TutorThread.id).where(or_(*thread_conds)))).all()
    ]

    msg_conds = []
    if thread_ids:
        msg_conds.append(TutorMessage.thread_id.in_(thread_ids))
    if course_ids:
        msg_conds.append(TutorMessage.course_id.in_(course_ids))
    msg_ids = (
        [
            row[0]
            for row in (await db.execute(select(TutorMessage.id).where(or_(*msg_conds)))).all()
        ]
        if msg_conds
        else []
    )

    # 1. P5.0 / P5.2 adaptive leaf tables
    await db.execute(delete(ReviewEvent).where(ReviewEvent.user_id == user.id))
    card_conds = [ReviewCard.user_id == user.id]
    if lesson_ids:
        card_conds.append(ReviewCard.lesson_id.in_(lesson_ids))
    await db.execute(delete(ReviewCard).where(or_(*card_conds)))

    rec_conds = [RecommendationEvent.user_id == user.id]
    if course_ids:
        rec_conds.append(RecommendationEvent.course_id.in_(course_ids))
    await db.execute(delete(RecommendationEvent).where(or_(*rec_conds)))

    await db.execute(delete(SkillMastery).where(SkillMastery.user_id == user.id))
    if lesson_ids:
        await db.execute(delete(LessonSkill).where(LessonSkill.lesson_id.in_(lesson_ids)))
    if course_ids:
        await db.execute(delete(Skill).where(Skill.course_id.in_(course_ids)))

    # 2. Tutor tables
    ttc_conds = [TutorToolCall.user_id == user.id]
    if course_ids:
        ttc_conds.append(TutorToolCall.course_id.in_(course_ids))
    if msg_ids:
        ttc_conds.append(TutorToolCall.message_id.in_(msg_ids))
    await db.execute(delete(TutorToolCall).where(or_(*ttc_conds)))

    tue_conds = [TutorUsageEvent.user_id == user.id]
    if course_ids:
        tue_conds.append(TutorUsageEvent.course_id.in_(course_ids))
    if msg_ids:
        tue_conds.append(TutorUsageEvent.message_id.in_(msg_ids))
    await db.execute(delete(TutorUsageEvent).where(or_(*tue_conds)))

    if msg_ids:
        await db.execute(delete(TutorMessage).where(TutorMessage.id.in_(msg_ids)))
    if thread_ids:
        await db.execute(delete(TutorThread).where(TutorThread.id.in_(thread_ids)))

    # 3. LLM usage events
    usage_conds = [LlmUsageEvent.user_id == user.id]
    if job_ids:
        usage_conds.append(LlmUsageEvent.job_id.in_(job_ids))
    await db.execute(delete(LlmUsageEvent).where(or_(*usage_conds)))

    # 4. Citations, glossary, XP, attempts, lessons, units, courses
    cit_conds = []
    if lesson_ids:
        cit_conds.append(LessonCitation.lesson_id.in_(lesson_ids))
    if source_ids:
        cit_conds.append(LessonCitation.source_id.in_(source_ids))
    if cit_conds:
        await db.execute(delete(LessonCitation).where(or_(*cit_conds)))

    if course_ids:
        await db.execute(
            delete(CourseGlossaryTerm).where(CourseGlossaryTerm.course_id.in_(course_ids))
        )

    xp_conds = [XpEvent.user_id == user.id]
    if lesson_ids:
        xp_conds.append(XpEvent.lesson_id.in_(lesson_ids))
    await db.execute(delete(XpEvent).where(or_(*xp_conds)))

    att_conds = [LessonAttempt.user_id == user.id]
    if lesson_ids:
        att_conds.append(LessonAttempt.lesson_id.in_(lesson_ids))
    await db.execute(delete(LessonAttempt).where(or_(*att_conds)))

    if course_ids:
        await db.execute(delete(Lesson).where(Lesson.course_id.in_(course_ids)))
        await db.execute(delete(Unit).where(Unit.course_id.in_(course_ids)))
        await db.execute(delete(GenerationJob).where(GenerationJob.course_id.in_(course_ids)))
        await db.execute(delete(CourseProposal).where(CourseProposal.course_id.in_(course_ids)))
        await db.execute(delete(CourseInterview).where(CourseInterview.course_id.in_(course_ids)))

    cs_conds = []
    if course_ids:
        cs_conds.append(CourseSource.course_id.in_(course_ids))
    if source_ids:
        cs_conds.append(CourseSource.source_id.in_(source_ids))
    if cs_conds:
        await db.execute(delete(CourseSource).where(or_(*cs_conds)))

    srr_conds = [SourceResearchRun.user_id == user.id]
    if course_ids:
        srr_conds.append(SourceResearchRun.course_id.in_(course_ids))
    await db.execute(delete(SourceResearchRun).where(or_(*srr_conds)))

    if course_ids:
        await db.execute(delete(Course).where(Course.id.in_(course_ids)))

    # 5. Owned sources & RAG chunks/embeddings
    if source_ids:
        await db.execute(
            delete(SourceChunkEmbedding).where(SourceChunkEmbedding.source_id.in_(source_ids))
        )
        await db.execute(delete(SourceChunk).where(SourceChunk.source_id.in_(source_ids)))
        await db.execute(delete(SourceDocument).where(SourceDocument.source_id.in_(source_ids)))
        await db.execute(delete(Source).where(Source.id.in_(source_ids)))

    # 6. User row itself
    await db.execute(delete(User).where(User.id == user.id))
    await db.commit()
