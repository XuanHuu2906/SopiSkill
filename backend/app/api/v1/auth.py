"""Auth endpoints: register, login, logout, me.

Session bằng JWT trong HttpOnly cookie + CSRF double-submit cho mutating requests.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ACCESS_COOKIE, get_current_user
from app.core.config import get_settings
from app.core.csrf import CSRF_COOKIE, new_csrf_token, verify_csrf
from app.core.limits import rate_limit
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import User
from app.services import user_service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    email: str | None
    displayName: str
    xp: int


def _set_session_cookies(response: Response, request: Request, user: User) -> None:
    settings = get_settings()
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(user.id),
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    existing = request.cookies.get(CSRF_COOKIE)
    response.set_cookie(
        CSRF_COOKIE,
        existing or new_csrf_token(),
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=f"usr_{user.id}",
        email=user.email,
        displayName=user.display_name,
        xp=user.xp,
    )


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    rate_limit(request, "auth_register", limit=10, window_seconds=60)
    user = await user_service.register_user(db, body.email, body.password)
    _set_session_cookies(response, request, user)
    return _user_out(user)


@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    rate_limit(request, "auth_login", limit=10, window_seconds=60)
    user = await user_service.authenticate(db, body.email, body.password)
    _set_session_cookies(response, request, user)
    return _user_out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    verify_csrf(request)
    rate_limit(request, "auth_logout", limit=30, window_seconds=60)
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return _user_out(user)
