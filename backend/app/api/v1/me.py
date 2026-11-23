"""User profile surface & settings endpoints (Wave 4 / M1-ME-SURFACE, GAP-03, GAP-21).

Endpoints:
  GET    /v1/me/stats  → thống kê học tập thực từ DB cho user hiện tại
  PATCH  /v1/me        → cập nhật displayName (CSRF + rate-limit)
  DELETE /v1/me        → xóa tài khoản + toàn bộ dữ liệu sở hữu (CSRF + password/DELETE confirm)
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ACCESS_COOKIE, get_current_user
from app.api.v1.auth import UserOut, _user_out
from app.core.csrf import CSRF_COOKIE, verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import User
from app.schemas.schemas import MeDeleteRequest, MeStatsOut, MeUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/v1/me", tags=["me"])


@router.get("/stats", response_model=MeStatsOut)
async def get_my_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await user_service.get_user_stats(db, user)


@router.patch("", response_model=UserOut)
async def update_me(
    body: MeUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "me_update", limit=20, window_seconds=60)
    updated = await user_service.update_user_profile(db, user, body.displayName)
    return _user_out(updated)


@router.delete("", status_code=204)
async def delete_me(
    body: MeDeleteRequest,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "me_delete", limit=5, window_seconds=60)
    await user_service.delete_user_account(
        db,
        user,
        confirm_text=body.confirmText,
        password=body.password,
    )
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
