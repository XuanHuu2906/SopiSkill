"""Internal service-to-service authentication & HMAC-SHA256 replay protection.

Contract (`contracts/internal-ai.yaml`):
  - `X-Internal-Service-Token`: shared token verified via constant-time `hmac.compare_digest`.
  - `X-Internal-Timestamp`: Unix epoch seconds; rejected if outside `±max_clock_skew_seconds` (300s).
  - `X-Internal-Signature`: `sha256=<hex(HMAC-SHA256(INTERNAL_HMAC_SECRET, canonical))>`
    where `canonical = "{timestamp}.{UPPERCASE_METHOD}.{path_with_query}.{sha256_hex(raw_body)}"`.
  - `X-Correlation-Id`: request trace ID propagated across logs and responses.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

HEADER_SERVICE_AUTH = "X-Internal-Service-Token"
HEADER_TIMESTAMP = "X-Internal-Timestamp"
HEADER_SIGNATURE = "X-Internal-Signature"
HEADER_CORRELATION = "X-Correlation-Id"

PUBLIC_PROBE_PATHS = frozenset({"/ready", "/health"})


def body_sha256_hex(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def build_canonical_string(timestamp: str, method: str, path_with_query: str, raw_body: bytes) -> str:
    return f"{timestamp}.{method.upper()}.{path_with_query}.{body_sha256_hex(raw_body)}"


def compute_signature(secret: str, timestamp: str, method: str, path_with_query: str, raw_body: bytes) -> str:
    canonical = build_canonical_string(timestamp, method, path_with_query, raw_body)
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def sign_internal_headers(
    *,
    method: str,
    path_with_query: str,
    raw_body: bytes,
    settings: Settings | None = None,
    correlation_id: str | None = None,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Generate complete signed headers for `ai-engine -> core-api` callbacks or test requests."""
    cfg = settings or get_settings()
    ts = str(int(time.time()) if timestamp is None else int(timestamp))
    cid = correlation_id or f"cor_{uuid.uuid4().hex[:16]}"
    sig = compute_signature(cfg.internal_hmac_secret, ts, method, path_with_query, raw_body)
    return {
        HEADER_SERVICE_AUTH: cfg.internal_service_token,
        HEADER_TIMESTAMP: ts,
        HEADER_SIGNATURE: sig,
        HEADER_CORRELATION: cid,
    }


@dataclass(frozen=True)
class AuthFailure:
    code: str
    message: str


def verify_internal_headers(
    *,
    token: str | None,
    timestamp_raw: str | None,
    signature: str | None,
    method: str,
    path_with_query: str,
    raw_body: bytes,
    settings: Settings,
    now_epoch: float | None = None,
) -> AuthFailure | None:
    """Validate internal service headers in constant time. Returns None if valid."""
    expected_token = (settings.internal_service_token or "").strip()
    expected_secret = (settings.internal_hmac_secret or "").strip()
    if not expected_token or not expected_secret:
        return AuthFailure("INTERNAL_AUTH_NOT_CONFIGURED", "Internal service authentication is not configured.")

    if not token or not hmac.compare_digest(token.strip(), expected_token):
        return AuthFailure("INTERNAL_AUTH_INVALID", "Missing or invalid internal service token.")

    if not timestamp_raw:
        return AuthFailure("INTERNAL_TIMESTAMP_MISSING", "Missing X-Internal-Timestamp header.")
    try:
        ts_int = int(timestamp_raw.strip())
    except ValueError:
        return AuthFailure("INTERNAL_TIMESTAMP_INVALID", "Invalid X-Internal-Timestamp header.")

    now = time.time() if now_epoch is None else now_epoch
    skew = abs(now - ts_int)
    if skew > max(1, int(settings.internal_max_clock_skew_seconds)):
        return AuthFailure("INTERNAL_TIMESTAMP_EXPIRED", "Request timestamp outside allowed replay window.")

    if not signature or not signature.strip().startswith("sha256="):
        return AuthFailure("INTERNAL_SIGNATURE_INVALID", "Missing or malformed X-Internal-Signature header.")

    expected_sig = compute_signature(
        expected_secret,
        str(ts_int),
        method,
        path_with_query,
        raw_body,
    )
    if not hmac.compare_digest(signature.strip().lower(), expected_sig.lower()):
        return AuthFailure("INTERNAL_SIGNATURE_INVALID", "HMAC signature verification failed.")

    return None


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Enforce internal token + HMAC replay protection on every `/internal/*` route."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = (request.headers.get(HEADER_CORRELATION) or "").strip() or f"cor_{uuid.uuid4().hex[:16]}"
        request.state.correlation_id = correlation_id

        path = request.url.path
        if path in PUBLIC_PROBE_PATHS:
            response = await call_next(request)
            response.headers.setdefault(HEADER_CORRELATION, correlation_id)
            return response

        raw_body = await request.body()
        path_with_query = path + (f"?{request.url.query}" if request.url.query else "")
        settings = get_settings()

        failure = verify_internal_headers(
            token=request.headers.get(HEADER_SERVICE_AUTH),
            timestamp_raw=request.headers.get(HEADER_TIMESTAMP),
            signature=request.headers.get(HEADER_SIGNATURE),
            method=request.method,
            path_with_query=path_with_query,
            raw_body=raw_body,
            settings=settings,
        )
        if failure is not None:
            logger.warning(
                "internal_auth_rejected code=%s path=%s correlation_id=%s",
                failure.code,
                path,
                correlation_id,
            )
            return JSONResponse(
                status_code=401,
                content={
                    "code": failure.code,
                    "message": failure.message,
                    "correlationId": correlation_id,
                },
                headers={HEADER_CORRELATION: correlation_id},
            )

        response = await call_next(request)
        response.headers.setdefault(HEADER_CORRELATION, correlation_id)
        return response
