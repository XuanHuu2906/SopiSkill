"""User service — đăng ký/đăng nhập email + password, resolve user từ JWT.

Demo mode (header X-User-Id) chỉ được bật qua cấu hình cho local development.
"""

import re

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import User

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEMO_PREFIX = "demo:"


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_EMAIL", "message": "Email không hợp lệ."},
        )
    return email


def validate_password(password: str) -> str:
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
