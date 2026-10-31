"""P3.0 — Source Registry, Evidence contract & Source-First integration.

Bao phủ acceptance:
  AC01 Source metadata lưu/đọc đúng.
  AC02 Một course liên kết nhiều nguồn.
  AC03 Nguồn private được kiểm tra ownership ở server (user B bị 404).
  AC04 Citation không trỏ tới source không tồn tại / locator bịa.
  AC05 Citation KHÔNG tự thành verified khi không có bằng chứng.
  AC06 Duplicate/invalid/unauthorized.
  AC07 Discovery mock deterministic, không network.
  AC08/AC09 Course cũ + flow generation/quiz không bị phá.
"""

import asyncio
import uuid

import pytest

from app.models import LessonCitation, LessonGrounding, Source, SourceVerificationStatus
from app.schemas.schemas import SourceCandidateOut, SourceCreateRequest
from app.services import citation_service, source_discovery, source_evaluation, source_service
from app.services import source_context

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict:
    token = client.cookies.get("csrf_token") or ""
    return {"X-CSRF-Token": token}


async def register(client) -> str:
    email = f"p30-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def create_source(client, **overrides) -> dict:
    body = {
        "sourceType": "official_documentation",
        "title": overrides.pop("title", f"Tài liệu {uuid.uuid4().hex[:6]}"),
        "canonicalUrl": overrides.pop("canonicalUrl", "https://docs.example.com/guide"),
        "publisher": overrides.pop("publisher", "Example Org"),
        "author": overrides.pop("author", "Example Author"),
        "publicationDate": overrides.pop("publicationDate", "2025-01-15"),
        "language": overrides.pop("language", "en"),
        "version": overrides.pop("version", "1.2"),
        "visibility": overrides.pop("visibility", "private"),
        "licenseInfo": overrides.pop("licenseInfo", "CC BY 4.0"),
    }
    body.update(overrides)
    r = await client.post("/v1/sources", json=body, headers=csrf_headers(client))
    assert r.status_code == 201, r.text
    return r.json()


async def create_course(client, topic="Python cho người mới") -> str:
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def finish_interview(client, course_id: str) -> None:
    for i in range(5):
        r = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=csrf_headers(client),
        )
        assert r.status_code == 200, r.text


# ---------- AC01: metadata round-trip ----------


async def test_create_source_persists_metadata_and_is_unverified(client):
    await register(client)
    created = await create_source(client, title="Python Language Reference")

    r = await client.get(f"/v1/sources/{created['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Python Language Reference"
    assert body["canonicalUrl"] == "https://docs.example.com/guide"
    assert body["publisher"] == "Example Org"
    assert body["version"] == "1.2"
    assert body["publicationDate"].startswith("2025-01-15")
    # URL hợp lệ KHÔNG được suy ra là verified.
    assert body["verificationStatus"] == SourceVerificationStatus.unverified.value
    assert body["ownerId"].startswith("usr_")


async def test_duplicate_source_reuses_existing_record(client):
    await register(client)
    first = await create_source(client, title="Dup Source", canonicalUrl="https://dup.example.com/x")
    second = await create_source(client, title="Dup Source", canonicalUrl="https://dup.example.com/x")
    assert first["id"] == second["id"]

    r = await client.get("/v1/sources?limit=50&offset=0")
    matches = [s for s in r.json()["items"] if s["title"] == "Dup Source"]
    assert len(matches) == 1


async def test_public_source_is_reusable_across_users(client):
    await register(client)
    public = await create_source(client, visibility="public", title="Shared Public Doc")
    assert public["ownerId"] is None

    await register(client)  # user B
    r = await client.get(f"/v1/sources/{public['id']}")
    assert r.status_code == 200
    assert r.json()["visibility"] == "public"

    # B tạo lại cùng public source → trả đúng bản ghi đó (dedupe toàn cục).
    again = await create_source(client, visibility="public", title="Shared Public Doc")
    assert again["id"] == public["id"]


# ---------- AC06: invalid input ----------


async def test_reject_invalid_source_input(client):
    await register(client)
    headers = csrf_headers(client)
    cases = [
        {"sourceType": "official_documentation", "title": "", "canonicalUrl": None},
        {"sourceType": "not_a_type", "title": "x", "canonicalUrl": None},
        {"sourceType": "webpage", "title": "x", "canonicalUrl": "javascript:alert(1)"},
        {"sourceType": "webpage", "title": "x", "canonicalUrl": "ftp://example.com/f"},
        {"sourceType": "webpage", "title": "x", "canonicalUrl": "https://exa mple.com"},
        {"sourceType": "webpage", "title": "x", "unexpectedField": "nope"},
    ]
    for body in cases:
        r = await client.post("/v1/sources", json=body, headers=headers)
        assert r.status_code == 422, f"{body} -> {r.status_code} {r.text}"


async def test_create_source_requires_csrf_and_auth(client):
    await register(client)
    r = await client.post(
        "/v1/sources",
        json={"sourceType": "webpage", "title": "no csrf"},
    )
    assert r.status_code == 403


# ---------- AC03: authorization ----------


async def test_private_source_is_invisible_to_other_user(client):
    await register(client)
    private = await create_source(client, title="Private Notes", canonicalUrl="https://private.example.com/a")

    await register(client)  # user B
    assert (await client.get(f"/v1/sources/{private['id']}")).status_code == 404
    assert (await client.get(f"/v1/sources/{private['id']}/evaluation")).status_code == 404
    listing = await client.get("/v1/sources?limit=50&offset=0")
    assert all(s["id"] != private["id"] for s in listing.json()["items"])


async def test_user_cannot_link_other_users_private_source(client):
    await register(client)  # A
    private = await create_source(client, title="A Private")
    course_a = await create_course(client)

    await register(client)  # B
    course_b = await create_course(client)
    r = await client.post(
        f"/v1/courses/{course_b}/sources",
        json={"sourceId": private["id"]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 404

    # B cũng không gắn được nguồn vào course của A (course ownership chặn trước).
    r2 = await client.post(
        f"/v1/courses/{course_a}/sources",
        json={"sourceId": private["id"]},
        headers=csrf_headers(client),
    )
    assert r2.status_code == 404


async def test_other_user_cannot_read_course_sources(client):
    await register(client)
    public = await create_source(client, visibility="public", title="Public For A")
    course_id = await create_course(client)
    await client.post(
        f"/v1/courses/{course_id}/sources",
        json={"sourceId": public["id"]},
        headers=csrf_headers(client),
    )
    assert (await client.get(f"/v1/courses/{course_id}/sources")).status_code == 200

    await register(client)  # B
    assert (await client.get(f"/v1/courses/{course_id}/sources")).status_code == 404


async def test_reject_nonexistent_source_link(client):
    await register(client)
    course_id = await create_course(client)
    for bogus in ("src_" + str(uuid.uuid4()), "not-a-uuid", ""):
        r = await client.post(
            f"/v1/courses/{course_id}/sources",
            json={"sourceId": bogus or "x"},
            headers=csrf_headers(client),
        )
        assert r.status_code in (404, 422), f"{bogus} -> {r.status_code}"


# ---------- AC02: many sources per course ----------


async def test_course_links_multiple_sources_idempotently(client):
    await register(client)
    course_id = await create_course(client)
    sources = [
        await create_source(client, title=f"Src {i}", canonicalUrl=f"https://ex.com/{i}")
        for i in range(3)
    ]
    for source in sources:
        r = await client.post(
            f"/v1/courses/{course_id}/sources",
            json={"sourceId": source["id"]},
            headers=csrf_headers(client),
        )
        assert r.status_code == 201, r.text

    # Link lại cùng nguồn không tạo thêm liên kết.
    r = await client.post(
        f"/v1/courses/{course_id}/sources",
        json={"sourceId": sources[0]["id"]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201

    listing = await client.get(f"/v1/courses/{course_id}/sources")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert {item["source"]["id"] for item in body["items"]} == {s["id"] for s in sources}
    # P3.0 chưa ingest ⇒ không được quảng cáo grounding.
    assert body["groundingAvailable"] is False
    assert body["contentIngested"] is False
    assert body["notice"]


# ---------- AC07: deterministic mock discovery, no network ----------


async def test_mock_discovery_is_deterministic_and_flagged(client):
    await register(client)
    r1 = await client.get("/v1/sources/discover?topic=python&adapter=mock")
    r2 = await client.get("/v1/sources/discover?topic=python&adapter=mock")
    assert r1.status_code == 200 and r2.status_code == 200
    first, second = r1.json(), r2.json()
    assert first["isMock"] is True and first["deterministic"] is True
    assert first["items"] == second["items"]
    assert first["items"], "mock discovery phải trả candidate"
    assert "MOCK" in first["notice"]
    for item in first["items"]:
        assert item["isMock"] is True
        assert item["externalId"].startswith("mock-")


async def test_network_discovery_adapter_is_refused(client):
    await register(client)
    r = await client.get("/v1/sources/discover?topic=python&adapter=web")
    assert r.status_code == 503
    body = r.json()
    assert body["detail"]["code"] == "SOURCE_DISCOVERY_NOT_CONFIGURED"
    # Không được lộ stacktrace/chi tiết cấu hình.
    assert "SourceDiscoveryConfigError" not in r.text


async def test_curated_adapter_filters_by_keyword_without_network():
    import json

    catalog = json.dumps(
        [
            {"id": "doc-1", "title": "Python official docs", "sourceType": "official_documentation",
             "canonicalUrl": "https://docs.python.org/3/", "publisher": "Python Software Foundation"},
            {"id": "doc-2", "title": "Rust book", "sourceType": "official_documentation",
             "canonicalUrl": "https://doc.rust-lang.org/book/", "publisher": "Rust Team"},
        ]
    )
    adapter = source_discovery.CuratedCatalogAdapter(catalog_json=catalog)
    items = await adapter.search_sources("python")
    assert [i.externalId for i in items] == ["doc-1"]
    assert items[0].isMock is False

    meta = await adapter.get_source_metadata("doc-2")
    assert meta is not None and meta.title == "Rust book"


async def test_mock_discovery_adapter_hits_no_network(monkeypatch):
    """Nếu adapter chạm network thì test phải fail ngay."""
    import socket

    def _boom(*args, **kwargs):
        raise AssertionError("Mock discovery không được mở socket")

    monkeypatch.setattr(socket, "socket", _boom)
    adapter = source_discovery.MockDiscoveryAdapter()
    items = await adapter.search_sources("distributed systems")
    assert len(items) == 3
    assert all(i.isMock for i in items)


# ---------- Source evaluation ----------


async def test_evaluation_marks_missing_data_unknown(client):
    await register(client)
    sparse = await create_source(
        client,
        title="Mystery Doc",
        canonicalUrl=None,
        publisher=None,
        author=None,
        publicationDate=None,
        language=None,
        version=None,
        licenseInfo=None,
    )
    r = await client.get(f"/v1/sources/{sparse['id']}/evaluation")
    assert r.status_code == 200
    body = r.json()
    by_key = {c["key"]: c for c in body["criteria"]}
    assert by_key["freshness"]["status"] == "unknown"
    assert by_key["freshness"]["score"] is None
    assert by_key["consistency"]["status"] == "unknown"
    assert by_key["licensing"]["status"] == "unknown"
    assert body["verdict"] == "insufficient_metadata"
    assert body["weightedScore"] is None
    # Không tự đề xuất metadata_verified khi thiếu dữ liệu.
    assert body["suggestedVerificationStatus"] != "metadata_verified"


async def test_evaluation_never_claims_content_correctness(client):
    await register(client)
    full = await create_source(client, title="Python docs", publicationDate="2026-01-01")
    r = await client.get(f"/v1/sources/{full['id']}/evaluation?topic=python")
    body = r.json()
    assert body["evaluator"]["kind"] == "deterministic_metadata"
    # Không có bất kỳ tín hiệu "nội dung đúng".
    allowed = {"pending_review", "metadata_verified"}
    assert body["suggestedVerificationStatus"] in allowed
    assert any("KHÔNG phải độ đúng nội dung" in note for note in body["limitations"])


async def test_restrictive_license_blocks_metadata_verified(client):
    await register(client)
    src = await create_source(
        client,
        title="Restricted Content",
        publicationDate="2026-01-01",
        licenseInfo="All rights reserved",
    )
    r = await client.get(f"/v1/sources/{src['id']}/evaluation?topic=restricted")
    body = r.json()
    assert body["verdict"] == "weak"
    assert body["suggestedVerificationStatus"] == "pending_review"


def _source_stub(**overrides) -> Source:
    values = {
        "id": uuid.uuid4(),
        "source_type": source_service.SourceType.webpage,
        "title": "Stub",
        "canonical_url": "https://example.com/x",
        "author": None,
        "publisher": "Example",
        "publication_date": None,
        "source_updated_at": None,
        "retrieved_at": None,
        "language": "en",
        "version": "1",
        "owner_id": None,
        "visibility": source_service.SourceVisibility.public,
        "license_info": "CC BY 4.0",
        "content_hash": None,
        "verification_status": SourceVerificationStatus.unverified,
    }
    values.update(overrides)
    return Source(**values)


async def test_evaluation_freshness_and_consistency_paths():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 6, 1, tzinfo=UTC)
    fresh = _source_stub(source_updated_at=now - timedelta(days=10))
    ev = source_evaluation.evaluate_source(fresh, topics=["stub"], now=now, has_conflicts=False)
    by_key = {c.key: c for c in ev.criteria}
    assert by_key["freshness"].status == "strong"
    assert by_key["consistency"].status == "strong"

    stale = _source_stub(source_updated_at=now - timedelta(days=5000))
    ev2 = source_evaluation.evaluate_source(stale, topics=["stub"], now=now, has_conflicts=True)
    by_key2 = {c.key: c for c in ev2.criteria}
    assert by_key2["freshness"].status == "weak"
    assert by_key2["consistency"].status == "penalized"


# ---------- AC04 / AC05: citation contract ----------


async def test_citation_locator_cannot_be_verified_without_content():
    source = _source_stub(version="2")
    status_value, reasons = citation_service.validate_citation_locator(
        source, source_version="2", chunk_id="c-1", page_number=3, has_ingested_content=False
    )
    assert status_value.value == "unavailable"
    assert reasons

    status_none, _ = citation_service.validate_citation_locator(source, source_version="2")
    assert status_none.value == "unverified"

    changed, changed_reasons = citation_service.validate_citation_locator(
        source, source_version="1"
    )
    assert changed.value == "source_changed"
    assert "version" in changed_reasons[0].lower()

    invalid_page, _ = citation_service.validate_citation_locator(source, page_number=0)
    assert invalid_page.value == "rejected"


async def test_citation_never_self_reports_evidence_supported():
    source = _source_stub()
    status_value, _ = citation_service.validate_citation_locator(
        source,
        chunk_id="c-1",
        evidence_text="đoạn văn do model bịa",
        has_ingested_content=True,
    )
    assert status_value.value not in ("evidence_supported", "corroborated")


async def test_lesson_citations_are_created_unverified_from_linked_sources(client):
    await register(client)
    course_id = await create_course(client)
    source = await create_source(client, title="Linked Doc")
    await client.post(
        f"/v1/courses/{course_id}/sources",
        json={"sourceId": source["id"]},
        headers=csrf_headers(client),
    )
    await finish_interview(client, course_id)
    approve = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert approve.status_code == 202

    for _ in range(100):
        await asyncio.sleep(0.05)
        gen = await client.get(f"/v1/courses/{course_id}/generation")
        if gen.json()["status"] in ("ready", "failed"):
            break
    assert gen.json()["status"] == "ready"

    detail = await client.get(f"/v1/courses/{course_id}")
    lesson_id = detail.json()["units"][0]["lessons"][0]["id"]
    lesson = await client.get(f"/v1/lessons/{lesson_id}")
    assert lesson.status_code == 200
    body = lesson.json()

    # P3.0 chưa ingest ⇒ bài học KHÔNG được gắn nhãn source_grounded.
    assert body["grounding"] == LessonGrounding.general_ai_knowledge.value
    assert body["evidenceNotice"]
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["sourceId"] == source["id"]
    assert citation["validationStatus"] == "unverified"
    assert citation["chunkId"] is None and citation["pageNumber"] is None
    assert citation["sourceVersion"] == "1.2"


async def test_lesson_without_sources_has_no_citations_and_is_flagged(client):
    await register(client)
    course_id = await create_course(client)
    await finish_interview(client, course_id)
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    for _ in range(100):
        await asyncio.sleep(0.05)
        gen = await client.get(f"/v1/courses/{course_id}/generation")
        if gen.json()["status"] in ("ready", "failed"):
            break
    assert gen.json()["status"] == "ready"

    detail = await client.get(f"/v1/courses/{course_id}")
    lesson_id = detail.json()["units"][0]["lessons"][0]["id"]
    body = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    assert body["citations"] == []
    assert body["grounding"] == LessonGrounding.general_ai_knowledge.value
    assert "chưa có nguồn" in body["evidenceNotice"]


async def test_citation_rows_never_reference_missing_source(client):
    """Bảo vệ ở tầng dữ liệu: mọi citation phải có source tồn tại (FK)."""
    await register(client)
    course_id = await create_course(client)
    source = await create_source(client, title="FK Doc")
    await client.post(
        f"/v1/courses/{course_id}/sources",
        json={"sourceId": source["id"]},
        headers=csrf_headers(client),
    )
    await finish_interview(client, course_id)
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    for _ in range(100):
        await asyncio.sleep(0.05)
        gen = await client.get(f"/v1/courses/{course_id}/generation")
        if gen.json()["status"] in ("ready", "failed"):
            break

    from sqlalchemy import select

    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        rows = (await db.execute(select(LessonCitation))).scalars().all()
        source_ids = {
            row[0] for row in (await db.execute(select(Source.id))).all()
        }
    assert rows, "phải có citation được ghi cho course có nguồn"
    assert all(row.source_id in source_ids for row in rows)
    assert all(
        row.validation_status.value in ("unverified", "unavailable")
        for row in rows
    )


# ---------- source context helpers ----------


async def test_source_context_marks_grounding_only_with_real_excerpt():
    class FakeSource:
        id = uuid.uuid4()
        title = "Doc"
        publisher = "Pub"
        canonical_url = "https://example.com"
        version = "1"
        verification_status = SourceVerificationStatus.unverified

    linked = [(None, FakeSource())]
    metadata_only = source_context.build_source_context(linked)
    assert metadata_only[0].excerpt is None
    assert source_context.lesson_grounding(metadata_only) is LessonGrounding.general_ai_knowledge

    with_excerpt = source_context.build_source_context(
        linked, excerpt_provider=lambda _s: "Đoạn nội dung thật từ nguồn."
    )
    assert with_excerpt[0].excerpt == "Đoạn nội dung thật từ nguồn."
    assert source_context.lesson_grounding(with_excerpt) is LessonGrounding.source_grounded


async def test_source_create_request_rejects_non_http_url():
    with pytest.raises(ValueError):
        SourceCreateRequest(sourceType="webpage", title="x", canonicalUrl="ftp://x")
    with pytest.raises(ValueError):
        SourceCreateRequest(sourceType="webpage", title="x", canonicalUrl="https://a\nb")


async def test_source_candidate_model_flags_mock():
    candidate = SourceCandidateOut(
        adapter="mock",
        externalId="mock-1",
        sourceType="webpage",
        title="t",
        canonicalUrl=None,
        author=None,
        publisher=None,
        publicationDate=None,
        language=None,
        version=None,
        licenseInfo=None,
        deterministic=True,
        isMock=True,
    )
    assert candidate.isMock is True
