"""HMAC-signed HTTP callback client for `ai-worker-llm` and `ai-worker-ingest` -> `core-api`."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.internal_auth import sign_internal_headers

logger = logging.getLogger(__name__)


class CallbackDeliveryError(RuntimeError):
    """Raised when `core-api` callback fails after capped retries."""


class CoreApiCallbackClient:
    """Delivers signed JSON callbacks to `core-api` with bounded retries and strict timeouts."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    async def post_callback(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        correlation_id: str,
    ) -> dict[str, Any]:
        base = self._settings.core_api_url.rstrip("/")
        clean_path = path if path.startswith("/") else f"/{path}"
        url = f"{base}{clean_path}"
        raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        max_attempts = max(1, int(self._settings.callback_max_retries))
        last_exc: Exception | None = None

        async with httpx.AsyncClient(
            timeout=float(self._settings.callback_timeout_seconds),
            trust_env=False,
            transport=self._transport,
        ) as client:
            for attempt in range(1, max_attempts + 1):
                headers = sign_internal_headers(
                    method="POST",
                    path_with_query=clean_path,
                    raw_body=raw_body,
                    settings=self._settings,
                    correlation_id=correlation_id,
                )
                headers["Content-Type"] = "application/json"
                try:
                    resp = await client.post(url, content=raw_body, headers=headers)
                    if 200 <= resp.status_code < 300:
                        return resp.json() if resp.content else {"accepted": True, "duplicate": False}
                    if 400 <= resp.status_code < 500:
                        raise CallbackDeliveryError(
                            f"Callback rejected with status {resp.status_code} at {clean_path}"
                        )
                    last_exc = CallbackDeliveryError(
                        f"Callback transient status {resp.status_code} at {clean_path}"
                    )
                except CallbackDeliveryError:
                    raise
                except httpx.HTTPError as exc:
                    last_exc = exc

                if attempt < max_attempts:
                    await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))

        logger.error(
            "callback_delivery_failed path=%s correlation_id=%s error_type=%s",
            clean_path,
            correlation_id,
            type(last_exc).__name__,
        )
        raise CallbackDeliveryError(f"Callback failed after {max_attempts} attempts: {clean_path}") from last_exc
