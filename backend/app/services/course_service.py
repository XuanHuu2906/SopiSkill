"""Course service — tạo course, interview, proposal, approve, generation status."""

import uuid

from fastapi import HTTPException, status
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Course,
    CourseInterview,
    CourseProposal,
    CourseStatus,
    GenerationJob,
    JobStatus,
    Lesson,
    LessonAttempt,
    Unit,
)
from app.providers import LLMProvider, ProviderError, SchemaInvalidError
from app.providers.usage import collect_usage
from app.schemas.schemas import ProposalPayload
from app.services import llm_usage_service, pedagogy
from app.services.lesson_content import COMPLETION_THRESHOLD_PERCENT

INTERVIEW_QUESTIONS_COUNT = 5

ID_PREFIXES = (
    "crs_", "lsn_", "unt_", "job_", "att_", "src_", "tth_", "tmsg_",
    # P5.0 reviews
    "rvc_", "rve_",
    # P5.2 exposure
    "rce_",
)


def parse_prefixed_uuid(raw: str) -> uuid.UUID | None:
    """Chấp nhận cả 'crs_<uuid>' lẫn uuid trần; trả None nếu sai format."""
    if not raw:
        return None
    value = raw
    for prefix in ID_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


class CourseAccessError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COURSE_NOT_FOUND", "message": "Course không tồn tại hoặc không thuộc quyền của bạn."},
        )


async def get_owned_course(db: AsyncSession, course_id: str, user_id: uuid.UUID) -> Course:
    """Tra cứu course + xác thực ownership — KHÔNG tin id từ client ngoài việc làm khóa tìm kiếm."""
    cid = parse_prefixed_uuid(course_id)
    if cid is None:
        raise CourseAccessError()
    result = await db.execute(
        select(Course).where(Course.id == cid, Course.user_id == user_id)
    )
    course = result.scalar_one_or_none()
    if course is None:
        raise CourseAccessError()
    return course


async def create_course(
    db: AsyncSession, user_id: uuid.UUID, topic: str, client_course_id: str, provider: LLMProvider
) -> tuple[Course, bool]:
    """Trả về (course, created). Idempotent theo (user_id, client_course_id)."""
    result = await db.execute(
        select(Course).where(
            Course.user_id == user_id, Course.client_course_id == client_course_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing, False

    course = Course(user_id=user_id, topic=topic, client_course_id=client_course_id)
    db.add(course)
    await db.flush()

    # Interview questions do NOT consume provider tokens for mock provider, but do
    # for real providers — record usage so cost reports don't silently omit it.
    with collect_usage() as usage:
        questions = await provider.generate_interview_questions(topic)
    await llm_usage_service.record_standalone(usage, user_id=user_id)
    interview = CourseInterview(
        course_id=course.id, questions=questions[:INTERVIEW_QUESTIONS_COUNT], answers=[], completed_count=0
    )
    db.add(interview)
    await db.commit()
    await db.refresh(course)
    return course, True


async def get_interview(db: AsyncSession, course: Course) -> CourseInterview:
    result = await db.execute(
        select(CourseInterview).where(CourseInterview.course_id == course.id)
    )
    interview = result.scalar_one_or_none()
    if interview is None:
        raise HTTPException(status_code=500, detail={"code": "INTERVIEW_MISSING"})
    return interview


async def answer_interview(
    db: AsyncSession,
    course: Course,
    position: int,
    answer: str,
    provider: LLMProvider,
) -> CourseInterview:
    if course.status != CourseStatus.interview:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INTERVIEW_CLOSED", "message": "Phỏng vấn đã đóng cho course này."},
        )
    interview = await get_interview(db, course)

    answers = list(interview.answers or [])
    while len(answers) < INTERVIEW_QUESTIONS_COUNT:
        answers.append(None)
    answers[position] = answer
    interview.answers = answers
    interview.completed_count = sum(1 for a in answers if a)
    await db.flush()

    if interview.completed_count >= INTERVIEW_QUESTIONS_COUNT:
        await _generate_proposal(db, course, interview, provider)
    await db.commit()
    await db.refresh(interview)
    return interview


async def _generate_proposal(
    db: AsyncSession, course: Course, interview: CourseInterview, provider: LLMProvider
) -> None:
    clean_answers = [a for a in (interview.answers or []) if a]
    try:
        with collect_usage() as harness:
            try:
                payload = await provider.generate_proposal(
                    course.topic, interview.questions or [], clean_answers
                )
            finally:
                # Chi phí đã phát sinh kể cả khi provider lỗi/sai schema. Ghi bằng
                # session riêng: request này có thể rollback sau đó.
                await llm_usage_service.record_standalone(
                    harness, user_id=course.user_id
                )
    except SchemaInvalidError as exc:
        course.status = CourseStatus.failed
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "PROPOSAL_SCHEMA_INVALID", "message": str(exc)[:300]},
        )
    except ProviderError as exc:
        # Không lộ chi tiết provider/key cho client.
        course.status = CourseStatus.failed
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": "Không sinh được đề xuất. Vui lòng thử lại."},
        ) from exc

    # P2.1 — hồ sơ người học do SERVER suy ra từ chính câu trả lời (deterministic),
    # không tin field do model tự khai. Curriculum được chuẩn hoá lại lần cuối để
    # mock/legacy provider cũng có DAG hợp lệ.
    try:
        payload.learnerProfile = pedagogy.extract_learner_profile(
            interview.questions or [], clean_answers
        )
        payload = pedagogy.normalize_curriculum(payload)
        pedagogy.validate_curriculum(payload)
    except SchemaInvalidError as exc:
        course.status = CourseStatus.failed
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "PROPOSAL_SCHEMA_INVALID", "message": str(exc)[:300]},
        ) from exc

    result = await db.execute(
        select(CourseProposal)
        .where(CourseProposal.course_id == course.id)
        .order_by(CourseProposal.version.desc())
    )
    latest = result.scalars().first()
    version = (latest.version if latest else 0) + 1
    db.add(
        CourseProposal(course_id=course.id, version=version, payload=payload.model_dump())
    )
    course.status = CourseStatus.proposed


async def get_latest_proposal(db: AsyncSession, course: Course) -> CourseProposal | None:
    result = await db.execute(
        select(CourseProposal)
        .where(CourseProposal.course_id == course.id)
        .order_by(CourseProposal.version.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _lock_course_row(db: AsyncSession, course_id: uuid.UUID) -> Course:
    """Khoá row course và đọc lại trạng thái mới nhất.

    `populate_existing` cần thiết vì `get_owned_course` đã nạp object vào identity
    map; nếu không, ta sẽ kiểm tra state cũ và bỏ qua khoá.
    """
    result = await db.execute(
        select(Course)
        .where(Course.id == course_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _active_job(db: AsyncSession, course_id: uuid.UUID) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(
            GenerationJob.course_id == course_id,
            GenerationJob.status.in_((JobStatus.queued, JobStatus.running)),
        )
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def approve_course(db: AsyncSession, course: Course) -> GenerationJob:
    # Khoá TRƯỚC khi kiểm tra trạng thái: hai request song song (double-click,
    # 2 tab) phải tuần tự hoá, người thứ hai thấy status đã đổi và bị 409.
    course = await _lock_course_row(db, course.id)
    if await _active_job(db, course.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "JOB_ALREADY_ACTIVE", "message": "Khóa học đang được sinh."},
        )
    if course.status not in (CourseStatus.proposed, CourseStatus.failed, CourseStatus.ready):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "INVALID_STATE", "message": f"Không thể approve course ở trạng thái {course.status.value}."},
        )
    proposal = await get_latest_proposal(db, course)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "NO_PROPOSAL"},
        )

    job = GenerationJob(
        course_id=course.id,
        status=JobStatus.queued,
        attempts_count=0,
        proposal_version=proposal.version,
    )
    db.add(job)
    course.status = CourseStatus.generating
    if proposal.approved_at is None:
        proposal.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return job


async def retry_course(db: AsyncSession, course: Course) -> GenerationJob:
    course = await _lock_course_row(db, course.id)
    if await _active_job(db, course.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "JOB_ALREADY_ACTIVE", "message": "Khóa học đang được sinh."},
        )
    if course.status not in (CourseStatus.failed, CourseStatus.ready):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RETRY_NOT_ALLOWED", "message": f"Không thể retry course ở trạng thái {course.status.value}."},
        )
    proposal = await get_latest_proposal(db, course)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "NO_PROPOSAL"})

    job = GenerationJob(
        course_id=course.id,
        status=JobStatus.queued,
        # attempts_count là retry do người dùng; claim của worker tách riêng.
        attempts_count=0,
        proposal_version=proposal.version,
    )
    db.add(job)
    course.status = CourseStatus.generating
    await db.commit()
    await db.refresh(job)
    return job


async def get_latest_job(db: AsyncSession, course: Course) -> GenerationJob | None:
    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.course_id == course.id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def _completed_lesson_ids(
    db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Lesson 'completed' = có attempt đạt ngưỡng trên contentVersion hiện hành.

    PROPOSAL policy (P1.1): không suy từ LessonStatus.ready và không tính attempt
    của version cũ sau khi bài được sinh lại.
    """
    rows = await db.execute(
        select(
            LessonAttempt.lesson_id,
            LessonAttempt.score_correct,
            LessonAttempt.score_total,
        )
        .join(Lesson, Lesson.id == LessonAttempt.lesson_id)
        .where(
            Lesson.course_id == course_id,
            LessonAttempt.user_id == user_id,
            LessonAttempt.content_version == Lesson.content_version,
        )
    )
    done: set[uuid.UUID] = set()
    for lesson_id, correct, total in rows.all():
        if total > 0 and correct * 100 >= total * COMPLETION_THRESHOLD_PERCENT:
            done.add(lesson_id)
    return done


async def list_courses(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> dict:
    """Danh sách course của chính user, có tiến độ + resume link.

    Ownership được enforce bằng `Course.user_id == user_id` (không tin client).
    """
    total = (
        await db.execute(
            select(func.count()).select_from(Course).where(Course.user_id == user_id)
        )
    ).scalar_one()

    rows = (
        await db.execute(
            select(Course)
            .where(Course.user_id == user_id)
            .order_by(Course.updated_at.desc(), Course.created_at.desc())
            .limit(limit)
            .offset(offset)
            .options(selectinload(Course.units).selectinload(Unit.lessons))
        )
    ).scalars().all()

    completed_map = {}
    for course in rows:
        completed_map[course.id] = await _completed_lesson_ids(db, course.id, user_id)

    items = []
    for course in rows:
        done_ids = completed_map[course.id]
        unit_order = {unit.id: unit.order_index for unit in course.units}
        lessons = sorted(
            (l for u in course.units for l in u.lessons),
            key=lambda l: (unit_order.get(l.unit_id, 0), l.order_index),
        )
        total_lessons = len(lessons)
        done = sum(1 for l in lessons if l.status.value == "ready" and l.id in done_ids)
        resume = next(
            (l for l in lessons if l.status.value == "ready" and l.id not in done_ids),
            None,
        )
        current = next((l for l in lessons if l.id in done_ids), None)
        items.append(
            {
                "id": f"crs_{course.id}",
                "topic": course.topic,
                "status": course.status.value,
                "createdAt": course.created_at.isoformat() if course.created_at else None,
                "updatedAt": course.updated_at.isoformat() if course.updated_at else None,
                "progress": {
                    "completed": done,
                    "total": total_lessons,
                    "percent": 0 if total_lessons == 0 else round(done / total_lessons * 100),
                },
                "resumeLessonId": f"lsn_{resume.id}" if resume else None,
                "resumeLessonTitle": resume.title if resume else None,
                "lastCompletedLessonTitle": current.title if current else None,
            }
        )

    return {
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(items) < int(total),
    }


async def get_course_detail(db: AsyncSession, course: Course, user_id: uuid.UUID) -> dict:
    result = await db.execute(
        select(Course)
        .where(Course.id == course.id)
        .options(
            selectinload(Course.units).selectinload(Unit.lessons)  # type: ignore[attr-defined]
        )
    )
    course_full = result.scalar_one()

    completed_ids = await _completed_lesson_ids(db, course.id, user_id)

    units = sorted(course_full.units, key=lambda u: u.order_index)
    units_out = []
    total = 0
    completed = 0
    for unit in units:
        lessons = sorted(unit.lessons, key=lambda l: l.order_index)
        lesson_out = []
        for lesson in lessons:
            total += 1
            is_done = lesson.status.value == "ready" and lesson.id in completed_ids
            if is_done:
                completed += 1
            lesson_out.append(
                {
                    "id": f"lsn_{lesson.id}",
                    "orderIndex": lesson.order_index,
                    "title": lesson.title,
                    "status": lesson.status.value,
                    "contentVersion": lesson.content_version,
                    "completed": is_done,
                }
            )
        units_out.append(
            {
                "id": f"unt_{unit.id}",
                "orderIndex": unit.order_index,
                "title": unit.title,
                "blurb": unit.blurb,
                "lessons": lesson_out,
            }
        )
    return {
        "id": f"crs_{course.id}",
        "topic": course.topic,
        "status": course.status.value,
        "units": units_out,
        "progress": {"completed": completed, "total": total, "percent": 0 if total == 0 else round(completed / total * 100)},
    }
