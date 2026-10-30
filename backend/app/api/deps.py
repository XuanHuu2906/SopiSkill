"""Authentication dependency — resolve user từ JWT HttpOnly cookie.

Fallback demo header `X-User-Id` chỉ chấp nhận khi:
  - ALLOW_DEMO_HEADER=true VÀ ENV=development (local only).
Production không bao giờ chấp nhận demo header.
"""

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.services import user_service

ACCESS_COOKIE = "access_token"


def get_token(request: Request) -> str:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        # Bearer fallback (cho script/test; không phải cách frontend dùng).
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "NOT_AUTHENTICATED", "message": "Chưa đăng nhập."},
        )
    return token


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    settings = get_settings()

    # Demo mode: opt-in qua cấu hình, chỉ cho local development.
    demo_id = request.headers.get("x-user-id", "")
    if demo_id and settings.allow_demo_header and settings.env == "development":
        return await user_service.get_or_create_user(db, f"demo:{demo_id}")

    payload = decode_access_token(get_token(request))
    user = await user_service.get_by_id(db, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "USER_NOT_FOUND", "message": "Tài khoản không tồn tại."},
        )
    request.state.user_id = str(user.id)
    return user
