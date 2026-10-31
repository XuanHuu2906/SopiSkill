"""P2.SR — Source Research Agent integration (DB, API, feature flag).

Bao phủ AC06–AC11 (registry/authorization/idempotency/error state/flag).
"""

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import SourceResearchRun, SourceResearchStatus

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def register(client) -> str:
    email = f"p2sr-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def create_course(client, topic="Python cho người mới") -> str:
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def enable_research(monkeypatch, **overrides) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "source_research_enabled", True)
    monkeypatch.setattr(settings, "source_research_provider", "mock")
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)


async def test_research_run_persists_sources_and_warnings(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)

    r = await client.post(
        f"/v1/courses/{course_id}/research-runs",
        json={"maxSources": 3},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["isMock"] is True
    assert 1 <= len(body["sources"]) <= 3
    assert body["insufficientEvidence"] is False
    assert body["analysis"]["domain"] == "programming"
    assert body["notice"]
    for source in body["sources"]:
        assert source["verificationStatus"] == "discovered"
        # Agent/API không cấp sourceId registry: nguồn chỉ vào registry khi accept.
        assert "sourceId" not in source
        assert source["selectionReason"]

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(SourceResearchRun).where(
                    SourceResearchRun.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status is SourceResearchStatus.completed
    assert rows[0].is_mock is True
    assert rows[0].sources


async def test_duplicate_request_is_idempotent(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)
    payload = {"maxSources": 4, "learningGoals": ["xây app AI"]}

    first = await client.post(
        f"/v1/courses/{course_id}/research-runs", json=payload, headers=csrf_headers(client)
    )
    second = await client.post(
        f"/v1/courses/{course_id}/research-runs", json=payload, headers=csrf_headers(client)
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["researchRunId"] == second.json()["researchRunId"]
    assert second.json()["reused"] is True

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(SourceResearchRun).where(
                    SourceResearchRun.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
    assert len(rows) == 1


async def test_research_run_is_scoped_to_course_owner(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)
    run = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    run_id = run.json()["researchRunId"]
    assert (await client.get(f"/v1/courses/{course_id}/research-runs/{run_id}")).status_code == 200

    await register(client)  # user B
    assert (await client.get(f"/v1/courses/{course_id}/research-runs/{run_id}")).status_code == 404
    assert (await client.get(f"/v1/courses/{course_id}/research-runs")).status_code == 404
    blocked = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert blocked.status_code == 404


async def test_feature_flag_off_returns_structured_503(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "source_research_enabled", False)
    await register(client)
    course_id = await create_course(client)
    r = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "SOURCE_RESEARCH_DISABLED"


async def test_research_requires_csrf(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)
    r = await client.post(f"/v1/courses/{course_id}/research-runs", json={})
    assert r.status_code == 403


async def test_adapter_failure_is_stored_as_failed_run(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)

    import app.services.source_research_service as research_service
    from app.agents.source_research.adapters.base import ResearchDiscoveryAdapter

    class _Broken(ResearchDiscoveryAdapter):
        name = "broken"
        deterministic = False
        is_mock = False

        async def search(self, query, *, max_results):
            raise RuntimeError("boom")

        async def metadata(self, external_id):
            return None

    original = research_service.resolve_adapter

    def _patched(_settings):
        return _Broken()

    monkeypatch.setattr(research_service, "resolve_adapter", _patched)
    try:
        r = await client.post(
            f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
        )
    finally:
        monkeypatch.setattr(research_service, "resolve_adapter", original)

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "SOURCE_RESEARCH_ADAPTER_ERROR"
    assert body["insufficientEvidence"] is True

    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(SourceResearchRun).where(
                    SourceResearchRun.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().one()
    assert row.status is SourceResearchStatus.failed
    assert row.error and row.error["code"] == "SOURCE_RESEARCH_ADAPTER_ERROR"


async def test_accept_run_links_only_verified_sources_and_checks_ownership(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)
    run = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    run_id = run.json()["researchRunId"]

    # Nguồn mock không được tự link vào registry (URL không có thật).
    r = await client.post(
        f"/v1/courses/{course_id}/research-runs/{run_id}/accept",
        headers=csrf_headers(client),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "RESEARCH_SOURCES_NOT_LINKABLE"

    assert (await client.get(f"/v1/courses/{course_id}/research-runs/{run_id}")).status_code == 200


async def test_accept_links_verified_curated_sources(client, monkeypatch):
    import json

    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_provider", "curated")
    catalog = json.dumps(
        [
            {
                "id": "py-docs",
                "title": "Python official documentation",
                "sourceType": "official_documentation",
                "canonicalUrl": "https://docs.python.org/3/",
                "publisher": "Python Software Foundation",
                "publicationDate": "2025-06-01",
                "version": "3.13",
                "licenseInfo": "PSF License",
                "language": "en",
                "tags": "python",
            }
        ]
    )
    monkeypatch.setattr(get_settings(), "source_curated_catalog", catalog)
    await register(client)
    course_id = await create_course(client)

    r = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["isMock"] is False
    assert body["status"] == "completed"
    assert body["sources"][0]["verificationStatus"] == "metadata_verified"

    accepted = await client.post(
        f"/v1/courses/{course_id}/research-runs/{body['researchRunId']}/accept",
        headers=csrf_headers(client),
    )
    assert accepted.status_code == 200, accepted.text

    linked = await client.get(f"/v1/courses/{course_id}/sources")
    assert linked.status_code == 200
    assert linked.json()["total"] == 1
    assert linked.json()["items"][0]["source"]["canonicalUrl"] == "https://docs.python.org/3/"
    # Nguồn vào registry vẫn là unverified: metadata_verified của agent KHÔNG được
    # tự ghi thành trạng thái xác minh trong DB.
    assert linked.json()["items"][0]["source"]["verificationStatus"] == "unverified"

    # Accept lần nữa không nhân bản liên kết.
    again = await client.post(
        f"/v1/courses/{course_id}/research-runs/{body['researchRunId']}/accept",
        headers=csrf_headers(client),
    )
    assert again.status_code == 200
    linked2 = await client.get(f"/v1/courses/{course_id}/sources")
    assert linked2.json()["total"] == 1


async def test_generation_unchanged_when_flag_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "source_research_enabled", False)
    await register(client)
    course_id = await create_course(client)
    for i in range(5):
        r = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 200
    approve = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert approve.status_code == 202

    for _ in range(100):
        gen = await client.get(f"/v1/courses/{course_id}/generation")
        if gen.json()["status"] in ("ready", "failed"):
            break
        import asyncio

        await asyncio.sleep(0.05)
    assert gen.json()["status"] == "ready"

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(SourceResearchRun).where(
                    SourceResearchRun.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
    assert rows == []


async def test_auto_link_on_generation_when_enabled(client, monkeypatch):
    import json

    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_auto_link", True)
    monkeypatch.setattr(get_settings(), "source_research_provider", "curated")
    monkeypatch.setattr(
        get_settings(),
        "source_curated_catalog",
        json.dumps(
            [
                {
                    "id": "py-docs",
                    "title": "Python official documentation",
                    "sourceType": "official_documentation",
                    "canonicalUrl": "https://docs.python.org/3/",
                    "publisher": "Python Software Foundation",
                    "publicationDate": "2025-06-01",
                    "version": "3.13",
                    "licenseInfo": "PSF License",
                    "language": "en",
                    "tags": "python",
                }
            ]
        ),
    )
    await register(client)
    course_id = await create_course(client)
    for i in range(5):
        r = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 200
    assert (
        await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    ).status_code == 202

    import asyncio

    for _ in range(100):
        gen = await client.get(f"/v1/courses/{course_id}/generation")
        if gen.json()["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(0.05)
    assert gen.json()["status"] == "ready"

    # Curated + metadata_verified ⇒ nguồn được link trước khi sinh bài.
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(SourceResearchRun).where(
                    SourceResearchRun.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_mock is False
    assert rows[0].status is SourceResearchStatus.completed

    linked = await client.get(f"/v1/courses/{course_id}/sources")
    assert linked.json()["total"] == 1

    detail = await client.get(f"/v1/courses/{course_id}")
    lesson_id = detail.json()["units"][0]["lessons"][0]["id"]
    lesson = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    # Chưa ingest nội dung ⇒ vẫn general_ai_knowledge (không tô hồng grounding).
    assert lesson["grounding"] == "general_ai_knowledge"
    assert lesson["citations"]

async def test_failed_run_is_retried_without_duplicate_row(client, monkeypatch):
    import app.services.source_research_service as research_service
    from app.agents.source_research.adapters.base import ResearchDiscoveryAdapter

    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)

    class _Broken(ResearchDiscoveryAdapter):
        name = "broken"
        deterministic = False
        is_mock = False

        async def search(self, query, *, max_results):
            raise RuntimeError("boom")

        async def metadata(self, external_id):
            return None

    monkeypatch.setattr(research_service, "resolve_adapter", lambda _s: _Broken())
    first = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert first.json()["status"] == "failed"
    run_id = first.json()["researchRunId"]

    # Adapter sửa xong ⇒ retry dùng LẠI đúng row, không sinh run thứ hai.
    monkeypatch.setattr(research_service, "resolve_adapter", lambda _s: __import__(
        "app.agents.source_research.adapters.mock", fromlist=["MockResearchDiscoveryAdapter"]
    ).MockResearchDiscoveryAdapter())
    second = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert second.status_code == 201, second.text
    # Adapter khác ⇒ fingerprint khác ⇒ run mới là hợp lý (kết quả khác nguồn gốc).
    assert second.json()["researchRunId"] != run_id

    third = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert third.json()["researchRunId"] == second.json()["researchRunId"]
    assert third.json()["reused"] is True

async def test_web_provider_is_rejected_with_structured_503(client, monkeypatch):
    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_provider", "web")
    await register(client)
    course_id = await create_course(client)
    r = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "SOURCE_RESEARCH_NOT_CONFIGURED"
    # Không lộ chi tiết cấu hình/stacktrace.
    assert "SourceDiscovery" not in r.text


async def test_unknown_provider_is_rejected(client, monkeypatch):
    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_provider", "totally-unknown")
    await register(client)
    course_id = await create_course(client)
    r = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "SOURCE_RESEARCH_NOT_CONFIGURED"


async def test_request_body_cannot_override_identity_or_course(client, monkeypatch):
    enable_research(monkeypatch)
    await register(client)
    course_id = await create_course(client)
    for payload in (
        {"courseId": str(uuid.uuid4())},
        {"ownerId": str(uuid.uuid4())},
        {"maxSources": 0},
        {"maxSources": 21},
        {"learningGoals": [f"g{i}" for i in range(9)]},
    ):
        r = await client.post(
            f"/v1/courses/{course_id}/research-runs", json=payload, headers=csrf_headers(client)
        )
        assert r.status_code == 422, f"{payload} -> {r.status_code} {r.text}"


async def test_accept_rejects_other_users_run(client, monkeypatch):
    import json as _json

    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_provider", "curated")
    monkeypatch.setattr(
        get_settings(),
        "source_curated_catalog",
        _json.dumps(
            [
                {
                    "id": "py-docs",
                    "title": "Python official documentation",
                    "sourceType": "official_documentation",
                    "canonicalUrl": "https://docs.python.org/3/",
                    "publisher": "Python Software Foundation",
                    "publicationDate": "2025-06-01",
                    "version": "3.13",
                    "language": "en",
                    "tags": "python",
                }
            ]
        ),
    )
    await register(client)
    course_a = await create_course(client)
    run = await client.post(
        f"/v1/courses/{course_a}/research-runs", json={}, headers=csrf_headers(client)
    )
    run_id = run.json()["researchRunId"]

    await register(client)  # user B
    course_b = await create_course(client)
    denied = await client.post(
        f"/v1/courses/{course_b}/research-runs/{run_id}/accept",
        headers=csrf_headers(client),
    )
    assert denied.status_code == 404

async def test_total_timeout_becomes_failed_run_not_hang(client, monkeypatch):
    import app.services.source_research_service as research_service
    from app.agents.source_research.adapters.base import ResearchDiscoveryAdapter

    enable_research(monkeypatch)
    monkeypatch.setattr(get_settings(), "source_research_timeout_seconds", 0.05)
    await register(client)
    course_id = await create_course(client)

    class _Slow(ResearchDiscoveryAdapter):
        name = "slow"
        deterministic = False
        is_mock = False

        async def search(self, query, *, max_results):
            import asyncio

            await asyncio.sleep(1.0)
            return []

        async def metadata(self, external_id):
            return None

    monkeypatch.setattr(research_service, "resolve_adapter", lambda _s: _Slow())
    r = await client.post(
        f"/v1/courses/{course_id}/research-runs", json={}, headers=csrf_headers(client)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "SOURCE_RESEARCH_TIMEOUT"
    assert body["error"]["retryable"] is True
    assert body["insufficientEvidence"] is True
