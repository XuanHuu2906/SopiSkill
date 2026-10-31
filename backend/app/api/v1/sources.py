"""Source Registry API (P3.0) — registry, discovery, evaluation, course linking.

Authorization:
  - Mọi endpoint yêu cầu identity đã xác thực.
  - Nguồn private chỉ chủ sở hữu truy cập; truy cập trái quyền trả 404 (không xác
    nhận sự tồn tại).
  - Course phải thuộc user (dùng `course_service.get_owned_course`).
  - Discovery chỉ trả candidate; không tự đăng ký nguồn và không tự đánh dấu verified.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.schemas import (
    CourseSourceListOut,
    CourseSourceOut,
    SourceCreateRequest,
    SourceDiscoveryOut,
    SourceEvaluationOut,
    SourceLinkRequest,
    SourceListOut,
    SourceOut,
)
from app.services import course_service, source_discovery, source_evaluation, source_service

router = APIRouter(prefix="/v1", tags=["sources"])


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "source_create", limit=30, window_seconds=60)
    source, _created = await source_service.create_source(db, user.id, body)
    return source_service.to_source_out(source)


@router.get("/sources", response_model=SourceListOut)
async def list_sources(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await source_service.list_accessible_sources(db, user.id, limit=limit, offset=offset)


# Khai báo TRƯỚC `/sources/{source_id}` để không bị route động "nuốt" mất.
@router.get("/sources/discover", response_model=SourceDiscoveryOut)
async def discover_sources(
    request: Request,
    topic: str = Query(min_length=1, max_length=200),
    adapter: str | None = Query(default=None, max_length=32),
    user: User = Depends(get_current_user),
):
    # Không gọi network: adapter mặc định là curated/mock; `web` bị từ chối rõ ràng.
    rate_limit(request, "source_discover", limit=30, window_seconds=60)
    try:
        resolved = source_discovery.get_discovery_adapter(adapter)
        items = await resolved.search_sources(topic, context={"userId": str(user.id)})
    except source_discovery.SourceDiscoveryConfigError as exc:
        # Cấu hình/khả năng chưa có ⇒ 503 có mã lỗi, không lộ chi tiết nội bộ.
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": "Tính năng tìm nguồn này chưa được cấu hình hoặc chưa hỗ trợ.",
            },
        ) from exc
    return SourceDiscoveryOut(
        adapter=resolved.name,
        query=topic,
        deterministic=resolved.deterministic,
        isMock=resolved.is_mock,
        items=items,
        notice=(
            "Kết quả MOCK, không phải tìm kiếm thật và không được xem là nguồn đã xác minh."
            if resolved.is_mock
            else "Ứng viên chưa phải nguồn đã đăng ký; cần bạn xác nhận trước khi liên kết."
        ),
    )


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    return source_service.to_source_out(source)


@router.get("/sources/{source_id}/evaluation", response_model=SourceEvaluationOut)
async def evaluate_source(
    source_id: str,
    topic: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    result = source_evaluation.evaluate_source(source, topics=[topic] if topic else [])
    payload = result.to_dict()
    return SourceEvaluationOut(
        sourceId=f"src_{source.id}",
        criteria=payload["criteria"],
        knownWeight=payload["knownWeight"],
        totalWeight=payload["totalWeight"],
        weightedScore=payload["weightedScore"],
        verdict=payload["verdict"],
        suggestedVerificationStatus=payload["suggestedVerificationStatus"],
        limitations=payload["limitations"],
        evaluator=payload["evaluator"],
    )


@router.post("/courses/{course_id}/sources", response_model=CourseSourceOut, status_code=201)
async def link_course_source(
    course_id: str,
    body: SourceLinkRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "course_source_link", limit=60, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    source = await source_service.get_accessible_source(db, body.sourceId, user.id)
    evaluation = source_evaluation.evaluate_source(source, topics=[course.topic]).to_dict()
    link, source, _created = await source_service.link_source_to_course(
        db, course, user.id, body.sourceId, evaluation=evaluation
    )
    return CourseSourceOut(
        courseId=f"crs_{course.id}",
        source=source_service.to_source_out(source),
        evaluation=link.evaluation,
        linkedAt=link.created_at.isoformat() if link.created_at else None,
    )


@router.get("/courses/{course_id}/sources", response_model=CourseSourceListOut)
async def list_course_sources(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    rows = await source_service.list_course_sources(db, course.id, user.id)
    items = [
        CourseSourceOut(
            courseId=f"crs_{course.id}",
            source=source_service.to_source_out(source),
            evaluation=link.evaluation,
            linkedAt=link.created_at.isoformat() if link.created_at else None,
        )
        for link, source in rows
    ]
    # P3.0: chưa có ingestion nội dung nên grounding KHÔNG khả dụng dù có nguồn.
    has_sources = len(items) > 0
    return CourseSourceListOut(
        items=items,
        total=len(items),
        groundingAvailable=False,
        contentIngested=False,
        notice=(
            "Nguồn đã liên kết nhưng chưa ingest nội dung: bài học vẫn dựa trên kiến thức "
            "chung của AI và citation sẽ ở trạng thái chưa xác minh."
            if has_sources
            else "Khóa học chưa liên kết nguồn nào; nội dung bài học là kiến thức chung của AI."
        ),
    )
