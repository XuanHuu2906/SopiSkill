"""CSRF protection — double-submit cookie cho các request thay đổi trạng thái.

Client đọc cookie `csrf_token` (không HttpOnly) và gửi lại trong header
`X-CSRF-Token`. Backend so khớp hai giá trị. Cookie session (HttpOnly)
không thể đọc từ JS nên attacker site khác không có được cặp giá trị khớp.
"""

import secrets

from fastapi import HTTPException, Request, status

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def ensure_csrf_cookie(request: Request) -> str | None:
    """Trả về token hiện có hoặc None (response handler sẽ set cookie mới)."""
    return request.cookies.get(CSRF_COOKIE)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie_value = request.cookies.get(CSRF_COOKIE)
    header_value = request.headers.get(CSRF_HEADER)
    if not cookie_value or not header_value or not secrets.compare_digest(cookie_value, header_value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "CSRF_INVALID", "message": "Thiếu hoặc sai CSRF token."},
        )
