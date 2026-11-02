"""P5.0 learner profile/review API — mastery, learning path, spaced repetition.

Bảo mật:
  - Mọi endpoint yêu cầu identity đã xác thực; course/card scope theo owner ⇒ 404.
  - Feature flag `P50_ENABLED` mặc định TẮT: route vẫn đăng ký nhưng trả 503
    `P50_NOT_ENABLED` (cùng convention tutor), KHÔNG ghi dữ liệu.
  - POST grade bắt buộc CSRF + rate limit; rating validate 1..4 ở schema.
  - Mastery do server tính từ `lesson_attempts`; rating của client chỉ là input
    FSRS và không ảnh hưởng điểm quiz/XP.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.schemas import (
    LearningPathOut,
    MasteryOut,
    ReviewDueOut,
    ReviewGradeOut,
    ReviewGradeRequest,
)
from app.services import (
    course_service,
    learner_profile_service,
    learning_path_service,
    spaced_repetition_service,
)

router = APIRouter(prefix="/v1")

P50_DISABLED_CODE = "P50_NOT_ENABLED"
REVIEW_CARD_NOT_FOUND = "REVIEW_CARD_NOT_FOUND"


def _require_enabled() -> None:
    if not get_settings().p50_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": P50_DISABLED_CODE,
                "message": "Tính năng hồ sơ học tập chưa được bật trên hệ thống này.",
            },
        )


@router.get("/courses/{course_id}/mastery", response_model=MasteryOut)
async def get_course_mastery(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    course = await course_service.get_owned_course(db, course_id, user.id)
    payload = await learner_profile_service.course_mastery(db, course, user.id)
    due = await spaced_repetition_service.due_cards(
        db, user.id, course_id=course.id, limit=1
    )
    return {**payload, "reviewDueCount": due["total"]}


@router.get("/courses/{course_id}/learning-path", response_model=LearningPathOut)
async def get_learning_path(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    course = await course_service.get_owned_course(db, course_id, user.id)
    return await learning_path_service.build_learning_path(db, course, user.id)


@router.get("/reviews/due", response_model=ReviewDueOut)
async def get_due_reviews(
    courseId: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    cid: uuid.UUID | None = None
    if courseId:
        course = await course_service.get_owned_course(db, courseId, user.id)
        cid = course.id
    return await spaced_repetition_service.due_cards(db, user.id, course_id=cid, limit=limit)


@router.post("/reviews/{card_id}/grade", response_model=ReviewGradeOut)
async def grade_review(
    card_id: str,
    body: ReviewGradeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_enabled()
    verify_csrf(request)
    rate_limit(request, "review_grade", limit=120, window_seconds=60)

    parsed = course_service.parse_prefixed_uuid(card_id)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": REVIEW_CARD_NOT_FOUND,
                "message": "Thẻ ôn tập không tồn tại hoặc không thuộc quyền của bạn.",
            },
        )
    try:
        return await spaced_repetition_service.grade_card(
            db,
            card_id=parsed,
            user_id=user.id,
            rating=body.rating,
            client_review_id=body.clientReviewId,
            duration_ms=body.durationMs,
        )
    except spaced_repetition_service.CardNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": REVIEW_CARD_NOT_FOUND,
                "message": "Thẻ ôn tập không tồn tại hoặc không thuộc quyền của bạn.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_RATING", "message": str(exc)},
        ) from exc
