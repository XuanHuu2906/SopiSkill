"""Rate limit đơn giản in-memory per-process (đủ cho slice này; Redis-based khi cần distributed)."""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

_buckets: dict[str, list[float]] = defaultdict(list)


def rate_limit(request: Request, key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    # Ưu tiên user đã xác thực (đặt bởi dependency auth); fallback client host.
    identity = getattr(request.state, "user_id", None)
    if not identity:
        identity = request.client.host if request.client else "anon"
    bucket_key = f"{key}:{identity}"
    bucket = _buckets[bucket_key]
    cutoff = now - window_seconds
    bucket[:] = [t for t in bucket if t > cutoff]
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "message": "Quá nhiều request, thử lại sau."},
        )
    bucket.append(now)
