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
    RecommendationEventOut,
    RecommendationEventRequest,
    ReviewDueOut,
    ReviewGradeOut,
    ReviewGradeRequest,
)
from app.services import (
    course_service,
    learner_profile_service,
    learning_path_service,
    recommendation_log_service,
    recommendation_token_service,
    spaced_repetition_service,
)

router = APIRouter(prefix="/v1")

P50_DISABLED_CODE = "P50_NOT_ENABLED"
P52_DISABLED_CODE = "P52_NOT_ENABLED"
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
    payload = await learning_path_service.build_learning_path(db, course, user.id)

    if get_settings().p52_exposure_enabled:
        payload["recommendationToken"] = await _mint_token(db, course, payload, user)
    else:
        payload["recommendationToken"] = None
    return payload


async def _mint_token(db: AsyncSession, course, payload: dict, user: User) -> str | None:
    """Ký token cho arm hiện tại. Lỗi token KHÔNG được làm hỏng GET."""
    try:
        arm_kind, arm_id, _reason = recommendation_log_service.derive_arm(payload)
        version = await recommendation_log_service.lesson_content_version(
            db, uuid.UUID(arm_id)
        )
        if version is None:
            return None
        return recommendation_token_service.mint(
            user_id=str(user.id),
            course_id=str(course.id),
            arm_kind=arm_kind,
            arm_id=arm_id,
            context_hash=recommendation_token_service.context_hash_from_path(payload),
            lesson_content_version=int(version),
            policy_version=recommendation_log_service.POLICY_VERSION,
        )
    except Exception:  # pragma: no cover - thiếu secret/không có arm
        import logging

        logging.getLogger(__name__).warning(
            "p52 token mint failed course=%s", course.id, exc_info=True
        )
        return None


@router.post(
    "/courses/{course_id}/recommendation-events", response_model=RecommendationEventOut
)
async def record_recommendation_event(
    course_id: str,
    body: RecommendationEventRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ghi exposure của một gợi ý đã hiển thị (P5.2b). Idempotent theo context+arm.

    Thứ tự kiểm tra quan trọng: cờ TẮT phải trả 503 **trước** khi chạm bảng
    `recommendation_events`, để DB cũ chưa chạy migration 0016 vẫn an toàn.
    """
    settings = get_settings()
    if not settings.p52_exposure_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": P52_DISABLED_CODE,
                "message": "Ghi nhận gợi ý chưa được bật trên hệ thống này.",
            },
        )
    _require_enabled()  # route cần learning-path ⇒ cần P50
    verify_csrf(request)
    rate_limit(request, "recommendation_event", limit=60, window_seconds=60)

    course = await course_service.get_owned_course(db, course_id, user.id)

    try:
        token_payload = recommendation_token_service.verify(
            body.recommendationToken, user_id=str(user.id), course_id=str(course.id)
        )
    except recommendation_token_service.TokenError as exc:
        return {
            "recorded": False,
            "duplicate": False,
            "exposureId": None,
            "reason": exc.reason,
        }

    # Server luôn tính lại: token chỉ là bằng chứng "đã hiển thị", không phải nguồn
    # sự thật về arm. Lệch context/version ⇒ không ghi.
    current = await learning_path_service.build_learning_path(db, course, user.id)
    try:
        arm_kind, arm_id, _reason = recommendation_log_service.derive_arm(current)
    except recommendation_log_service.NoArmError:
        return {
            "recorded": False,
            "duplicate": False,
            "exposureId": None,
            "reason": "CONTEXT_STALE",
        }

    current_hash = recommendation_token_service.context_hash_from_path(current)
    version = await recommendation_log_service.lesson_content_version(
        db, uuid.UUID(arm_id)
    )
    if (
        token_payload["contextHash"] != current_hash
        or token_payload["armKind"] != arm_kind
        or token_payload["armId"] != arm_id
        # Policy version cũng phải khớp: token phát dưới policy cũ không được ghi
        # nhận như thể do policy mới sinh ra (sẽ làm sai attribution khi bump).
        or token_payload["policyVersion"] != recommendation_log_service.POLICY_VERSION
        or version is None
        or int(token_payload["lessonContentVersion"]) != int(version)
    ):
        return {
            "recorded": False,
            "duplicate": False,
            "exposureId": None,
            "reason": "CONTEXT_STALE",
        }

    result = await recommendation_log_service.record_exposure(
        db,
        user_id=user.id,
        course=course,
        path=current,
        lesson_content_version=int(version),
    )
    await db.commit()
    return result


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
