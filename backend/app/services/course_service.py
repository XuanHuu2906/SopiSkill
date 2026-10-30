"""Course service — tạo course, interview, proposal, approve, generation status."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
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
    Unit,
)
from app.providers import LLMProvider, SchemaInvalidError
from app.schemas.schemas import ProposalPayload

INTERVIEW_QUESTIONS_COUNT = 5

ID_PREFIXES = ("crs_", "lsn_", "unt_", "job_", "att_")


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

    questions = await provider.generate_interview_questions(topic)
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
        payload = await provider.generate_proposal(
            course.topic, interview.questions or [], clean_answers
        )
    except SchemaInvalidError as exc:
        course.status = CourseStatus.failed
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "PROPOSAL_SCHEMA_INVALID", "message": str(exc)},
        )

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


async def approve_course(db: AsyncSession, course: Course) -> GenerationJob:
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

    job = GenerationJob(course_id=course.id, status=JobStatus.queued)
    db.add(job)
    course.status = CourseStatus.generating
    await db.commit()
    await db.refresh(job)
    return job


async def retry_course(db: AsyncSession, course: Course) -> GenerationJob:
    if course.status not in (CourseStatus.failed, CourseStatus.ready):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RETRY_NOT_ALLOWED", "message": f"Không thể retry course ở trạng thái {course.status.value}."},
        )
    proposal = await get_latest_proposal(db, course)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": "NO_PROPOSAL"})

    prev = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.course_id == course.id)
        .order_by(GenerationJob.created_at.desc())
        .limit(1)
    )
    prev_job = prev.scalars().first()
    job = GenerationJob(
        course_id=course.id,
        status=JobStatus.queued,
        attempts_count=(prev_job.attempts_count + 1) if prev_job else 1,
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


async def get_course_detail(db: AsyncSession, course: Course) -> dict:
    result = await db.execute(
        select(Course)
        .where(Course.id == course.id)
        .options(
            selectinload(Course.units).selectinload(Unit.lessons)  # type: ignore[attr-defined]
        )
    )
    course_full = result.scalar_one()

    units = sorted(course_full.units, key=lambda u: u.order_index)
    units_out = []
    total = 0
    completed = 0
    for unit in units:
        lessons = sorted(unit.lessons, key=lambda l: l.order_index)
        for lesson in lessons:
            total += 1
            if lesson.status.value == "ready":
                pass
        units_out.append(
            {
                "id": f"unt_{unit.id}",
                "orderIndex": unit.order_index,
                "title": unit.title,
                "blurb": unit.blurb,
                "lessons": [
                    {
                        "id": f"lsn_{lesson.id}",
                        "orderIndex": lesson.order_index,
                        "title": lesson.title,
                        "status": lesson.status.value,
                        "contentVersion": lesson.content_version,
                    }
                    for lesson in lessons
                ],
            }
        )
    return {
        "id": f"crs_{course.id}",
        "topic": course.topic,
        "status": course.status.value,
        "units": units_out,
        "progress": {"completed": completed, "total": total, "percent": 0 if total == 0 else round(completed / total * 100)},
    }
