"""P5.2b — Token HMAC cho `recommendationToken` (server phát, client gửi lại).

Vì sao cần token thay vì client tự tính hash:
  - Client **không có** khoá ⇒ không thể bịa `arm`/`context_hash` để ghi khống
    exposure hoặc ghi arm mình không được gợi ý.
  - Client **luôn có** giá trị để gửi: token nằm trong response `GET learning-path`.
  - Server vẫn tính lại learning-path tại thời điểm POST, nên token chỉ là *bằng
    chứng đã hiển thị*, không phải nguồn sự thật về arm.

Token = `<b64url(payload_json)>.<b64url(HMAC-SHA256)>`, khoá = `JWT_SECRET`
(server-side, không bao giờ trả ra client). Payload canonical (sort_keys) để
chữ ký tất định.

Hết hạn mặc định 900s (`P52_TOKEN_TTL_SECONDS`): token cũ không ghi được exposure
sau khi lesson đã regenerate (vì `lessonContentVersion` cũng nằm trong payload và
server so lại với version hiện tại).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime

from app.core.config import get_settings

TOKEN_VERSION = 1


class TokenError(Exception):
    """Lỗi verify token. `reason` là mã máy đọc cho response."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _secret() -> str:
    return get_settings().jwt_secret or ""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sign(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return _b64encode(digest)


def mint(
    *,
    user_id: str,
    course_id: str,
    arm_kind: str,
    arm_id: str,
    context_hash: str,
    lesson_content_version: int,
    policy_version: str,
    now: datetime | None = None,
) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError("P52_TOKEN_NOT_CONFIGURED")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    payload = {
        "v": TOKEN_VERSION,
        "uid": str(user_id),
        "cid": str(course_id),
        "kind": str(arm_kind),
        "aid": str(arm_id),
        "ctx": str(context_hash),
        "cv": int(lesson_content_version),
        "pv": str(policy_version),
        "iat": int(now.timestamp()),
    }
    raw = _canonical(payload)
    return f"{_b64encode(raw)}.{_sign(raw, secret)}"


def verify(
    token: str,
    *,
    user_id: str,
    course_id: str,
    now: datetime | None = None,
) -> dict:
    """Trả payload đã chuẩn hoá (camelCase) hoặc raise `TokenError`."""
    secret = _secret()
    if not secret:
        raise TokenError("TOKEN_INVALID")

    try:
        payload_part, signature_part = token.split(".", 1)
        raw = _b64decode(payload_part)
        expected = _b64encode(
            hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        )
        provided = _b64encode(_b64decode(signature_part))
    except Exception as exc:  # token rỗng/sai định dạng/base64 hỏng
        raise TokenError("TOKEN_INVALID") from exc

    # So sánh hai chuỗi base64 **ASCII** đã chuẩn hoá. Không dùng `compare_digest`
    # trực tiếp trên str do client gửi: str non-ASCII sẽ ném TypeError (⇒ HTTP 500)
    # thay vì bị coi là token không hợp lệ.
    if not hmac.compare_digest(expected, provided):
        raise TokenError("TOKEN_INVALID")

    try:
        payload = json.loads(raw.decode("utf-8"))
        iat = int(payload["iat"])
        version = int(payload["v"])
        uid = str(payload["uid"])
        cid = str(payload["cid"])
        kind = str(payload["kind"])
        aid = str(payload["aid"])
        ctx = str(payload["ctx"])
        cv = int(payload["cv"])
        pv = str(payload["pv"])
    except Exception as exc:
        raise TokenError("TOKEN_INVALID") from exc

    if version != TOKEN_VERSION:
        raise TokenError("TOKEN_INVALID")
    # So sánh cả user lẫn course: token của user A không dùng được cho user B, kể cả
    # khi B đoán đúng course id.
    if uid != str(user_id) or cid != str(course_id):
        raise TokenError("TOKEN_INVALID")

    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    ttl = max(1, int(get_settings().p52_token_ttl_seconds))
    if now.timestamp() - iat > ttl:
        raise TokenError("TOKEN_EXPIRED")
    # iat ở tương lai quá xa (đồng hồ lệch) cũng bị coi là không hợp lệ.
    if iat - now.timestamp() > ttl:
        raise TokenError("TOKEN_INVALID")

    return {
        "armKind": kind,
        "armId": aid,
        "contextHash": ctx,
        "lessonContentVersion": cv,
        "policyVersion": pv,
        "issuedAt": iat,
    }


def context_hash_from_path(path: dict) -> str:
    """Hash sha256 (64 hex) của context **hẹp**, bỏ tiêu đề/message hiển thị.

    Chỉ gồm: lesson kế tiếp, lesson ôn, số bài đến hạn, danh sách lesson bị chặn.
    Nhờ vậy đổi wording UI không làm token cũ thành "stale", nhưng đổi **arm** hoặc
    đổi tiến độ thì hash đổi (đúng ý: đó là context mới).
    """
    next_lesson = path.get("nextLesson") or {}
    blocked = sorted(
        str(item.get("lessonId"))
        for item in (path.get("blockedBy") or [])
        if isinstance(item, dict) and item.get("lessonId")
    )
    narrow = {
        "next": next_lesson.get("lessonId") if isinstance(next_lesson, dict) else None,
        "review": path.get("reviewLessonId"),
        "due": int(path.get("reviewDueCount") or 0),
        "blocked": blocked,
    }
    return hashlib.sha256(_canonical(narrow)).hexdigest()
