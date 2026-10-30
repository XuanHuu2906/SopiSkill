"""P2.0 — fail-fast ở API: provider lạ/thiếu key trả 503 cấu hình, KHÔNG dùng mock."""

import uuid

import pytest

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def _register(client) -> None:
    r = await client.post(
        "/v1/auth/register",
        json={"email": f"p20-{uuid.uuid4().hex[:8]}@test.dev", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text


async def test_unknown_provider_returns_503_not_mock(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "totally-unknown")
    await _register(client)

    r = await client.post(
        "/v1/courses",
        json={"topic": "fail fast", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "PROVIDER_NOT_CONFIGURED"


async def test_real_provider_without_key_returns_503(client, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.example/v1")
    monkeypatch.setattr(settings, "llm_model", "some-model")

    await _register(client)
    r = await client.post(
        "/v1/courses",
        json={"topic": "no key", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["code"] == "PROVIDER_NOT_CONFIGURED"
    # Không lộ chi tiết env/key cho client.
    assert "api_key" not in str(detail).lower()


async def test_mock_provider_still_works(client):
    await _register(client)
    r = await client.post(
        "/v1/courses",
        json={"topic": "mock ok", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201
    assert r.json()["status"] == "interview"


async def test_health_reports_provider(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["provider"] == "mock"
