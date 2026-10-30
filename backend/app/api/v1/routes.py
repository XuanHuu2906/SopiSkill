from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import User
from app.providers import get_provider
from app.schemas.schemas import (
    AttemptOut,
    AttemptRequest,
    CourseCreateRequest,
    CourseDetailOut,
    CourseOut,
    GenerationOut,
    InterviewAnswerRequest,
    InterviewOut,
    LessonOut,
    ProposalOut,
)
from app.services import course_service, lesson_service
from app.worker.generation import dispatch_generation

router = APIRouter(prefix="/v1")


@router.post("/courses", response_model=CourseOut, status_code=201)
async def create_course(
    body: CourseCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "create_course", limit=30, window_seconds=60)
    course, created = await course_service.create_course(
        db, user.id, body.topic, body.clientCourseId, get_provider()
    )
    return CourseOut(
        id=f"crs_{course.id}",
        topic=course.topic,
        status=course.status.value,
        clientCourseId=course.client_course_id,
    )


@router.post("/courses/{course_id}/interview/answer", response_model=InterviewOut)
async def answer_interview(
    course_id: str,
    body: InterviewAnswerRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "interview", limit=60, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    interview = await course_service.answer_interview(db, course, body.position, body.answer, get_provider())
    return InterviewOut(
        questions=interview.questions or [],
        completedCount=interview.completed_count,
    )


@router.get("/courses/{course_id}/interview", response_model=InterviewOut)
async def get_interview(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    interview = await course_service.get_interview(db, course)
    return InterviewOut(questions=interview.questions or [], completedCount=interview.completed_count)


@router.get("/courses/{course_id}/proposal", response_model=ProposalOut)
async def get_proposal(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    proposal = await course_service.get_latest_proposal(db, course)
    if proposal is None:
        raise HTTPException(status_code=404, detail={"code": "NO_PROPOSAL"})
    return ProposalOut(
        version=proposal.version,
        approved=proposal.approved_at is not None,
        payload=proposal.payload,
    )


@router.post("/courses/{course_id}/approve", status_code=202)
async def approve_course(
    course_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "approve", limit=20, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    job = await course_service.approve_course(db, course)
    dispatch_generation(str(job.id))
    return {"jobId": f"job_{job.id}", "status": job.status.value}


@router.post("/courses/{course_id}/retry", status_code=202)
async def retry_course(
    course_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "retry", limit=10, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    job = await course_service.retry_course(db, course)
    dispatch_generation(str(job.id))
    return {"jobId": f"job_{job.id}", "status": job.status.value}


@router.get("/courses/{course_id}/generation", response_model=GenerationOut)
async def get_generation(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    job = await course_service.get_latest_job(db, course)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "NO_JOB"})
    return GenerationOut(
        jobId=f"job_{job.id}",
        status=job.status.value,
        stage=job.stage,
        lessonsDone=job.lessons_done,
        lessonsTotal=job.lessons_total,
        error=job.error,
    )


@router.get("/courses/{course_id}", response_model=CourseDetailOut)
async def get_course(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await course_service.get_course_detail(db, course)


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await lesson_service.get_owned_lesson(db, lesson_id, user.id)
    return LessonOut(
        id=f"lsn_{lesson.id}",
        title=lesson.title,
        orderIndex=lesson.order_index,
        contentVersion=lesson.content_version,
        status=lesson.status.value,
        blocks=lesson.content or [],
    )


@router.post("/lessons/{lesson_id}/attempts", response_model=AttemptOut, status_code=201)
async def submit_attempt(
    lesson_id: str,
    body: AttemptRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "attempt", limit=60, window_seconds=60)
    lesson = await lesson_service.get_owned_lesson(db, lesson_id, user.id)
    if lesson.content_version != body.contentVersion:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONTENT_VERSION_MISMATCH", "message": "Nội dung bài học đã đổi, hãy tải lại."},
        )
    attempt, duplicate = await lesson_service.submit_attempt(db, lesson, user, body)
    return AttemptOut(
        attemptId=f"att_{attempt.id}",
        duplicate=duplicate,
        score={"correct": attempt.score_correct, "total": attempt.score_total},
        rewards={
            "xp": user.xp,
            "xpEarned": attempt.score_correct * 10
            + (20 if attempt.score_total > 0 and attempt.score_correct == attempt.score_total else 0),
        },
        results=attempt.results or [],
    )
