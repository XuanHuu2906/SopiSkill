"""Source Research Agent API (P2.SR).

Endpoints (đều yêu cầu identity đã xác thực + course thuộc user):
  POST /v1/courses/{id}/research-runs            → chạy (hoặc trả lại) một lần nghiên cứu
  GET  /v1/courses/{id}/research-runs            → danh sách lần nghiên cứu của course
  GET  /v1/courses/{id}/research-runs/{run_id}   → chi tiết một lần
  POST /v1/courses/{id}/research-runs/{run_id}/accept → link nguồn đã kiểm tra metadata

Bảo mật:
  - `courseId` trong path là khóa tra cứu, ownership do server kiểm tra
    (`course_service.get_owned_course`) → 404 nếu không thuộc user.
  - Run id tra cứu kèm `course_id` + `user_id` ⇒ cross-tenant trả 404.
  - CSRF bắt buộc cho POST (double-submit cookie).
  - Rate limit riêng để không biến agent thành công cụ quét.
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.schemas import (
    ResearchRequestIn,
    ResearchRunListOut,
    ResearchRunOut,
)
from app.services import course_service, source_research_service

router = APIRouter(prefix="/v1", tags=["source-research"])


@router.post("/courses/{course_id}/research-runs", response_model=ResearchRunOut, status_code=201)
async def create_research_run(
    course_id: str,
    body: ResearchRequestIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "source_research", limit=10, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    row, created = await source_research_service.run_research(
        db,
        course,
        max_sources=body.maxSources,
        learning_goals=body.learningGoals,
        learner_level=body.learnerLevel,
    )
    return source_research_service.to_run_out(row, reused=not created)


@router.get("/courses/{course_id}/research-runs", response_model=ResearchRunListOut)
async def list_research_runs(
    course_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await source_research_service.list_runs(db, course, limit=limit, offset=offset)


@router.get("/courses/{course_id}/research-runs/{run_id}", response_model=ResearchRunOut)
async def get_research_run(
    course_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    row = await source_research_service.get_run(db, course, run_id)
    return source_research_service.to_run_out(row)


@router.post(
    "/courses/{course_id}/research-runs/{run_id}/accept",
    response_model=ResearchRunOut,
)
async def accept_research_run(
    course_id: str,
    run_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "source_research_accept", limit=20, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    row = await source_research_service.get_run(db, course, run_id)
    await source_research_service.link_verified_sources(db, course, row)
    await db.refresh(row)
    return source_research_service.to_run_out(row)
