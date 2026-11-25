"""Shared fixtures for ai-engine unit & integration tests."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings, reset_settings_cache
from app.core.internal_auth import sign_internal_headers
from app.db.session import dispose_engine, ensure_sqlite_tables
from app.main import app


@pytest.fixture
async def ai_client(tmp_path, monkeypatch):
    db_file = tmp_path / "ai_engine_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hashing")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "256")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")
    monkeypatch.setenv("INTERNAL_HMAC_SECRET", "test-hmac-secret")
    reset_settings_cache()
    await dispose_engine()
    await ensure_sqlite_tables()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ai-api.test") as client:
        yield client

    await dispose_engine()
    reset_settings_cache()


def signed_json_request(method: str, path: str, payload: dict[str, Any] | None = None, *, correlation_id: str | None = None) -> tuple[bytes, dict[str, str]]:
    raw = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = sign_internal_headers(
        method=method,
        path_with_query=path,
        raw_body=raw,
        settings=get_settings(),
        correlation_id=correlation_id,
    )
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return raw, headers
