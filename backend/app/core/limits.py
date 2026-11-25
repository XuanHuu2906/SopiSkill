"""Distributed sliding-window rate limiter (Redis + in-memory fallback, Wave 3 / M1-SEC-LIMITER).

Hành vi theo `RATE_LIMIT_BACKEND`:
  - `auto` (mặc định): dùng Redis khi `REDIS_URL` được cấu hình, ngược lại dùng in-memory.
  - `redis`: dùng Redis; nếu `REDIS_URL` trống hoặc Redis lỗi:
      * `RATE_LIMIT_FAIL_CLOSED=true`  ⇒ 503 `RATE_LIMITER_UNAVAILABLE` (production).
      * `RATE_LIMIT_FAIL_CLOSED=false` ⇒ ghi warning (không log secret/URL) và fallback
        in-memory để vẫn bảo vệ per-process.
  - `memory`: luôn dùng in-memory (thuận tiện cho unit test / local SQLite).

Thuật toán trên Redis dùng 1 Lua script nguyên tử (ZSET sliding window + PEXPIRE) để
nhiều worker/replica chia sẻ chung cửa sổ giới hạn mà không bị race condition.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_buckets: dict[str, list[float]] = defaultdict(list)

# Cached sync Redis client keyed by (redis_url, timeout_seconds)
_redis_client_cache: tuple[str, float, Any] | None = None
_redis_client_override: Any | None = None

# Atomic sliding-window rate limit script.
# Returns {allowed (0|1), current_count, retry_after_ms}.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now_ms - window_ms
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local current = redis.call('ZCARD', key)
if current >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_ms = window_ms
    if oldest and oldest[2] then
        retry_ms = math.max(1, tonumber(oldest[2]) + window_ms - now_ms)
    end
    return {0, current, retry_ms}
end
redis.call('ZADD', key, now_ms, member)
redis.call('PEXPIRE', key, window_ms + 1000)
return {1, current + 1, 0}
"""


def _client_identity(request: Request) -> str:
    """Resolve rate-limit identity: authenticated user_id first, else client IP."""
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"u:{user_id}"

    settings = get_settings()
    if settings.trust_proxy_headers:
        xff = request.headers.get("x-forwarded-for", "")
        first_hop = xff.split(",")[0].strip() if xff else ""
        if first_hop:
            return f"ip:{first_hop[:64]}"

    host = request.client.host if request.client else "anon"
    return f"ip:{host}"


def _resolve_backend() -> str:
    settings = get_settings()
    mode = (settings.rate_limit_backend or "auto").strip().lower()
    if mode == "memory":
        return "memory"
    if mode == "redis":
        return "redis"
    # `auto` (hoặc giá trị không nhận diện ⇒ an toàn như auto)
    if _redis_client_override is not None:
        return "redis"
    return "redis" if bool((settings.redis_url or "").strip()) else "memory"


def _get_redis_client():
    global _redis_client_cache
    if _redis_client_override is not None:
        return _redis_client_override

    settings = get_settings()
    url = (settings.redis_url or "").strip()
    if not url:
        raise RuntimeError("REDIS_URL is empty")

    timeout = max(0.05, float(settings.rate_limit_redis_timeout_seconds or 0.5))
    if _redis_client_cache is not None:
        cached_url, cached_timeout, client = _redis_client_cache
        if cached_url == url and cached_timeout == timeout:
            return client

    import redis

    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=True,
    )
    _redis_client_cache = (url, timeout, client)
    return client


def _rate_limit_memory(bucket_key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    bucket = _buckets[bucket_key]
    cutoff = now - window_seconds
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= limit:
        oldest = bucket[0] if bucket else now
        retry_after = max(1, int(math.ceil((oldest + window_seconds) - now)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Quá nhiều request, thử lại sau."},
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


def _rate_limit_redis(bucket_key: str, limit: int, window_seconds: int) -> None:
    settings = get_settings()
    prefix = (settings.rate_limit_key_prefix or "sopiskill:rl").strip().rstrip(":")
    redis_key = f"{prefix}:{bucket_key}"
    now_ms = int(time.time() * 1000)
    window_ms = max(1, int(window_seconds * 1000))
    member = f"{now_ms}:{uuid.uuid4().hex[:12]}"

    client = _get_redis_client()
    result = client.eval(_SLIDING_WINDOW_LUA, 1, redis_key, now_ms, window_ms, limit, member)
    allowed = int(result[0]) if result else 0
    retry_ms = int(result[2]) if result and len(result) > 2 else window_ms
    if not allowed:
        retry_after = max(1, int(math.ceil(retry_ms / 1000.0)))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Quá nhiều request, thử lại sau."},
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(request: Request, key: str, limit: int, window_seconds: int) -> None:
    """Enforce sliding-window rate limit (Redis distributed when configured, else in-memory)."""
    identity = _client_identity(request)
    bucket_key = f"{key}:{identity}"

    if _resolve_backend() == "redis":
        try:
            _rate_limit_redis(bucket_key, limit, window_seconds)
            return
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — fail-closed or degrade cleanly
            settings = get_settings()
            logger.warning(
                "rate_limit redis error type=%s fail_closed=%s",
                type(exc).__name__,
                settings.rate_limit_fail_closed,
            )
            if settings.rate_limit_fail_closed:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "RATE_LIMITER_UNAVAILABLE",
                        "message": "Hệ thống giới hạn truy cập tạm thời không sẵn sàng.",
                    },
                ) from None

    _rate_limit_memory(bucket_key, limit, window_seconds)


def set_redis_client_for_tests(client: Any | None) -> None:
    """Inject a fake/test Redis client (strictly for automated tests)."""
    global _redis_client_override
    _redis_client_override = client


def clear_rate_limits() -> None:
    """Reset in-memory buckets and cached Redis client — dùng cho tests."""
    global _redis_client_cache, _redis_client_override
    _buckets.clear()
    _redis_client_cache = None
    _redis_client_override = None
