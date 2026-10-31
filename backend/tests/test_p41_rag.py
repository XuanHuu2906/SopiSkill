"""P4.1 — embedding + hybrid retrieval + citation verification.

Chạy offline (SQLite in-memory, embedding hashing). **Không** phải bằng chứng
chất lượng semantic retrieval: hashing embedding là baseline lexical/subword, và
test chỉ chứng minh pipeline/contract đúng, không chứng minh "hiểu ngữ nghĩa".

Bao phủ:
  R01 Embedding deterministic, đúng dimension, chuẩn hoá L2, khác văn bản khác.
  R02 Đổi spec ⇒ không dùng lại vector cũ (không trộn vector).
  R03 Provider thật thiếu cấu hình ⇒ `EMBEDDING_NOT_CONFIGURED` (không fallback).
  R04 Lexical retrieval tìm đúng chunk chứa từ khoá; tiếng Việt có dấu.
  R05 Vector retrieval khớp câu không dấu/cùng chủ đề.
  R06 RRF hợp nhất: chunk xuất hiện ở cả hai ranker xếp trên chunk chỉ một.
  R07 Ownership: user B không truy xuất được chunk của user A.
  R08 Source không liên kết course ⇒ không vào scope.
  R09 Weak query ⇒ insufficientEvidence, không trả đoạn ngẫu nhiên.
  R10 Citation: id bịa bị loại; id hợp lệ ⇒ locator_verified + evidenceSupported=False.
  R11 `evidenceSupported` luôn False (không tự nâng lên evidence_supported).
  R12 API search: CSRF, RAG tắt ⇒ 503, sourceIds ngoài scope bị giao.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    CourseSource,
    Source,
    SourceChunk,
    SourceChunkEmbedding,
    SourceDocument,
    SourceDocumentStatus,
    SourceVisibility,
    User,
)
from app.services import (
    citation_service,
    embedding_service,
    rag_service,
    retrieval_service,
)

from .pdf_fixtures import pdf_with_heading_pages

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def register(client) -> uuid.UUID:
    email = f"p41-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    me = await client.get("/v1/auth/me")
    raw = me.json()["id"].removeprefix("usr_")
    return uuid.UUID(raw)


async def create_source(client, title: str, *, visibility: str = "private") -> str:
    r = await client.post(
        "/v1/sources",
        json={
            "sourceType": "user_document",
            "title": title,
            "visibility": visibility,
            "language": "vi",
            "version": "1.0",
        },
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def upload_text_source(client, source_id: str, data: bytes | None = None) -> dict:
    r = await client.post(
        f"/v1/sources/{source_id}/document",
        files={"file": ("doc.pdf", data or pdf_with_heading_pages(), "application/pdf")},
        headers=csrf_headers(client),
    )
    assert r.status_code == 202, r.text
    return r.json()


async def make_course(client) -> str:
    r = await client.post(
        "/v1/courses",
        json={"topic": "RAG test", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def link_source(client, course_id: str, source_id: str) -> None:
    r = await client.post(
        f"/v1/courses/{course_id}/sources",
        json={"sourceId": source_id},
        headers=csrf_headers(client),
    )
    assert r.status_code in (200, 201), r.text


async def seed_chunks(
    *,
    source_id: uuid.UUID,
    owner_id: uuid.UUID,
    title: str,
    texts: list[str],
    embed: bool = True,
    document_status=SourceDocumentStatus.ready,
) -> list[uuid.UUID]:
    """Ghi source + document + chunks trực tiếp (không qua upload)."""
    async with SessionLocal() as db:
        source = await db.get(Source, source_id)
        if source is None:
            source = Source(
                id=source_id,
                source_type="user_document",
                title=title,
                owner_id=owner_id,
                visibility=SourceVisibility.private,
                dedupe_key=f"test-{source_id}",
                version="1.0",
            )
            db.add(source)
            await db.flush()
        document = SourceDocument(
            source_id=source_id,
            content_hash=uuid.uuid4().hex * 2,
            pipeline_version="p4.0-v1",
            storage_key=f"sources/{source_id}/{uuid.uuid4().hex}",
            status=document_status,
        )
        db.add(document)
        await db.flush()

        chunk_ids: list[uuid.UUID] = []
        chunks = []
        for index, text in enumerate(texts):
            chunk = SourceChunk(
                document_id=document.id,
                source_id=source_id,
                chunk_index=index,
                page_number=index + 1,
                char_start=0,
                char_end=len(text),
                section_anchor=f"Mục {index + 1}",
                text=text,
                text_hash=embedding_service.hashlib.sha256(text.encode()).hexdigest(),
            )
            db.add(chunk)
            chunks.append(chunk)
            chunk_ids.append(chunk.id)
        await db.flush()
        if embed:
            written = await embedding_service.embed_chunks(db, chunks)
            assert written == len(chunks)
        await db.commit()
        return chunk_ids


async def link_course_source_raw(course_id: uuid.UUID, source_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        db.add(CourseSource(course_id=course_id, source_id=source_id))
        await db.commit()


@pytest.fixture(autouse=True)
def _rag_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rag_enabled", True)
    monkeypatch.setattr(settings, "embedding_enabled", True)
    monkeypatch.setattr(settings, "embedding_provider", "hashing")
    monkeypatch.setattr(settings, "embedding_model", "hashing-ngram-v1")
    monkeypatch.setattr(settings, "embedding_dimension", 256)
    monkeypatch.setattr(settings, "embedding_version", "v1")
    monkeypatch.setattr(settings, "rag_min_similarity", 0.05)


# ---------- R01: embedding properties ----------


async def test_hashing_embedding_is_deterministic_and_normalized():
    first = embedding_service.hashing_embed("vòng lặp for trong Python", dimension=256)
    second = embedding_service.hashing_embed("vòng lặp for trong Python", dimension=256)
    assert first == second
    assert len(first) == 256
    norm = sum(value * value for value in first) ** 0.5
    assert abs(norm - 1.0) < 1e-6

    other = embedding_service.hashing_embed("cấu trúc dữ liệu cây nhị phân", dimension=256)
    assert other != first
    assert embedding_service.cosine_similarity(first, other) < 0.9


async def test_hashing_embedding_matches_without_diacritics():
    with_marks = embedding_service.hashing_embed("lập trình hướng đối tượng", dimension=256)
    without = embedding_service.hashing_embed("lap trinh huong doi tuong", dimension=256)
    assert embedding_service.cosine_similarity(with_marks, without) > 0.95


async def test_spec_mismatch_does_not_reuse_old_vectors(monkeypatch):
    owner = uuid.uuid4()
    source_id = uuid.uuid4()
    await seed_chunks(
        source_id=source_id,
        owner_id=owner,
        title="Spec test",
        texts=["Đoạn văn về thuật toán sắp xếp nhanh."],
    )

    async with SessionLocal() as db:
        before = await embedding_service.embedding_coverage(db, source_id=source_id)
        assert before["pending"] == 0

        # Đổi version ⇒ spec khác ⇒ vector cũ KHÔNG được coi là hợp lệ.
        settings = get_settings()
        monkeypatch.setattr(settings, "embedding_version", "v2")
        after = await embedding_service.embedding_coverage(db, source_id=source_id)
        assert after["pending"] == before["total"]
        assert after["embedded"] == 0

        # Backfill spec mới tạo row riêng, row cũ vẫn còn (không ghi đè).
        chunks = await embedding_service.chunks_missing_embedding(db, source_id=source_id)
        assert len(chunks) == before["total"]
        await embedding_service.embed_chunks(db, chunks)
        await db.commit()

        rows = (
            await db.execute(
                select(SourceChunkEmbedding.version).where(
                    SourceChunkEmbedding.source_id == source_id
                )
            )
        ).scalars().all()
        assert set(rows) == {"v1", "v2"}


async def test_real_provider_without_config_fails_fast(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "openai_compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")

    assert settings.embedding_configured is False
    with pytest.raises(embedding_service.EmbeddingNotConfigured):
        embedding_service.get_embedding_provider()

    # Không được âm thầm rơi về hashing.
    assert settings.rag_active is False


async def test_unknown_provider_is_rejected(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "mystery-embed")
    with pytest.raises(embedding_service.EmbeddingNotConfigured):
        embedding_service.get_embedding_provider()


# ---------- R04-R09: retrieval ----------


async def _setup_course_with_source(client) -> tuple[uuid.UUID, str, uuid.UUID]:
    owner_id = await register(client)
    course_id = await make_course(client)
    source_id = await create_source(client, "Tài liệu RAG")
    await upload_text_source(client, source_id)
    await link_source(client, course_id, source_id)
    raw_course = uuid.UUID(course_id.removeprefix("crs_"))
    raw_source = uuid.UUID(source_id.removeprefix("src_"))
    return owner_id, course_id, raw_source


async def test_lexical_retrieval_finds_vietnamese_chunk(client):
    owner_id, course_id, source_id = await _setup_course_with_source(client)

    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="Python variables and data types",
        )
    assert result.items, result.reason
    assert result.insufficient_evidence is False
    assert result.lexical_hits >= 1
    assert all(item.source_id == source_id for item in result.items)


async def test_vector_retrieval_matches_without_diacritics(client):
    owner_id = await register(client)
    course_id = await make_course(client)
    source_id = uuid.uuid4()
    await seed_chunks(
        source_id=source_id,
        owner_id=owner_id,
        title="Cấu trúc dữ liệu",
        texts=[
            "Ngăn xếp hoạt động theo nguyên tắc vào sau ra trước.",
            "Hàng đợi hoạt động theo nguyên tắc vào trước ra trước.",
            "Cây nhị phân tìm kiếm giữ thứ tự khoá.",
        ],
    )
    await link_course_source_raw(uuid.UUID(course_id.removeprefix("crs_")), source_id)

    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="hang doi vao truoc ra truoc",
        )
    assert result.items
    assert "Hàng đợi" in result.items[0].text


async def test_rrf_ranks_dual_ranker_hit_first(client):
    owner_id = await register(client)
    course_id = await make_course(client)
    source_a = uuid.uuid4()
    await seed_chunks(
        source_id=source_a,
        owner_id=owner_id,
        title="Nguồn A",
        texts=[
            "Đệ quy là kỹ thuật hàm tự gọi chính nó với bài toán nhỏ hơn.",
            "Màu sắc và bố cục trang trí không liên quan.",
        ],
    )
    await link_course_source_raw(uuid.UUID(course_id.removeprefix("crs_")), source_a)

    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="đệ quy hàm tự gọi",
        )
    assert result.items
    top = result.items[0]
    assert "Đệ quy" in top.text
    assert top.lexical_rank is not None
    assert top.vector_rank is not None


async def test_cross_user_chunks_are_never_retrieved(client):
    owner_a = await register(client)
    course_id = await make_course(client)
    source_a = uuid.uuid4()
    await seed_chunks(
        source_id=source_a,
        owner_id=owner_a,
        title="Nguồn riêng A",
        texts=["Bí mật của người dùng A về mật mã học lượng tử."],
    )
    await link_course_source_raw(uuid.UUID(course_id.removeprefix("crs_")), source_a)

    owner_b = await register(client)
    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_b,
            query="mật mã học lượng tử",
        )
    assert result.items == []
    assert result.insufficient_evidence is True
    assert result.reason in ("NO_SCOPED_CONTENT", "NO_MATCH")


async def test_unlinked_source_is_out_of_scope(client):
    owner_id = await register(client)
    course_id = await make_course(client)
    unlinked = uuid.uuid4()
    await seed_chunks(
        source_id=unlinked,
        owner_id=owner_id,
        title="Nguồn chưa liên kết",
        texts=["Nội dung chưa được liên kết với khóa học nào cả."],
    )

    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="nội dung chưa liên kết",
        )
    assert result.items == []
    assert result.reason == "NO_SCOPED_CONTENT"


async def test_non_ready_document_is_out_of_scope(client):
    owner_id = await register(client)
    course_id = await make_course(client)
    source_id = uuid.uuid4()
    await seed_chunks(
        source_id=source_id,
        owner_id=owner_id,
        title="Đang xử lý",
        texts=["Tài liệu còn đang trích xuất, chưa được coi là nguồn."],
        document_status=SourceDocumentStatus.extracting,
    )
    await link_course_source_raw(uuid.UUID(course_id.removeprefix("crs_")), source_id)

    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="trích xuất",
        )
    assert result.items == []


async def test_weak_query_reports_insufficient_evidence(client):
    owner_id, course_id, _source_id = await _setup_course_with_source(client)
    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="zzz qqq xxx",
        )
    assert result.insufficient_evidence is True
    assert result.items == []


# ---------- R10-R11: citation verification ----------


async def test_citation_validator_drops_invented_ids_and_never_claims_evidence():
    retrieved = [
        retrieval_service.RetrievedChunk(
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page_number=3,
            char_start=10,
            char_end=40,
            section_anchor="Mục 1",
            text_hash="abc",
            text="Đoạn nguồn thật về vòng lặp.",
            source_title="Tài liệu",
            source_version="1.0",
            source_type="user_document",
        )
    ]
    answer = (
        f"Như tài liệu nói [chk_{retrieved[0].chunk_id}]. "
        f"Còn điều này tôi bịa [chk_{uuid.uuid4()}]."
    )
    verified, rejected = citation_service.verify_answer_citations(
        answer, retrieved=retrieved, max_citations=5
    )
    assert len(verified) == 1
    assert verified[0]["chunkId"] == f"chk_{retrieved[0].chunk_id}"
    assert verified[0]["pageNumber"] == 3
    assert verified[0]["validationStatus"] == "locator_verified"
    # P4.1: xác minh vị trí KHÔNG đồng nghĩa claim được chứng minh.
    assert verified[0]["evidenceSupported"] is False
    assert len(rejected) == 1


async def test_rag_verify_gives_no_citations_when_no_retrieval():
    verified, pointers, rejected = rag_service.verify_answer(
        "Câu trả lời tự do không có nguồn.", None
    )
    assert verified == [] and pointers == [] and rejected == []

    empty = retrieval_service.RetrievalResult(items=[], insufficient_evidence=True)
    verified, pointers, rejected = rag_service.verify_answer(
        f"Bịa [chk_{uuid.uuid4()}]", empty
    )
    assert verified == [] and pointers == [] and rejected == []


async def test_rag_system_prompt_marks_context_untrusted(client):
    owner_id, course_id, _source_id = await _setup_course_with_source(client)
    async with SessionLocal() as db:
        result = await retrieval_service.retrieve(
            db,
            course_id=uuid.UUID(course_id.removeprefix("crs_")),
            user_id=owner_id,
            query="Python variables",
        )
    assert result.items
    system, allowlist = rag_service.build_system_with_rag("BASE PROMPT", result, max_chars=2000)
    assert "BASE PROMPT" in system
    assert "<<<NGUON_BAT_DAU>>>" in system
    assert "DỮ LIỆU KHÔNG TIN CẬY" in system
    assert allowlist == sorted(result.allowed_chunk_ids)
    # Id chunk trong allowlist phải xuất hiện trong prompt để model trích đúng.
    assert f"chk_{allowlist[0]}" in system


async def test_rag_system_prompt_says_insufficient_without_chunks():
    empty = retrieval_service.RetrievalResult(items=[], insufficient_evidence=True)
    system, allowlist = rag_service.build_system_with_rag("BASE", empty)
    assert allowlist == []
    assert "chưa đủ căn cứ" in system
    assert "<<<NGUON_BAT_DAU>>>" not in system


# ---------- R12: API ----------


async def test_search_api_requires_csrf_and_rag_enabled(client, monkeypatch):
    await register(client)
    course_id = await make_course(client)
    payload = {"query": "bất kỳ"}

    r = await client.post(f"/v1/courses/{course_id}/sources/search", json=payload)
    assert r.status_code == 403

    settings = get_settings()
    monkeypatch.setattr(settings, "rag_enabled", False)
    r = await client.post(
        f"/v1/courses/{course_id}/sources/search",
        json=payload,
        headers=csrf_headers(client),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "RAG_NOT_ENABLED"


async def test_search_api_returns_provenance_and_narrows_scope(client):
    owner_id, course_id, source_id = await _setup_course_with_source(client)
    r = await client.post(
        f"/v1/courses/{course_id}/sources/search",
        json={"query": "Python variables data types"},
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["insufficientEvidence"] is False
    assert body["items"]
    item = body["items"][0]
    assert item["chunkId"].startswith("chk_")
    assert item["sourceId"] == f"src_{source_id}"
    assert item["pageNumber"] >= 1
    assert item["textHash"]
    assert body["embeddingSpec"].startswith("hashing/")

    # sourceIds ngoài phạm vi ⇒ giao rỗng, không lộ dữ liệu.
    other = await create_source(client, "Nguồn khác")
    r2 = await client.post(
        f"/v1/courses/{course_id}/sources/search",
        json={"query": "Python variables data types", "sourceIds": [other]},
        headers=csrf_headers(client),
    )
    assert r2.status_code == 200
    assert r2.json()["items"] == []
    assert r2.json()["insufficientEvidence"] is True


async def test_search_api_cross_user_course_is_404(client):
    await register(client)
    owner_course = await make_course(client)
    _owner_id, _course_id, _source_id = await _setup_course_with_source(client)

    # User mới (cookie đã đổi) không được dùng course của người khác.
    await register(client)
    r = await client.post(
        f"/v1/courses/{owner_course}/sources/search",
        json={"query": "Python"},
        headers=csrf_headers(client),
    )
    assert r.status_code == 404


async def test_ingest_config_exposes_embedding_state_without_secrets(client):
    await register(client)
    r = await client.get("/v1/sources/ingest-config")
    assert r.status_code == 200
    body = r.json()
    assert body["embeddingProvider"] == "hashing"
    assert body["embeddingDimension"] == 256
    assert "apiKey" not in body
    assert "baseUrl" not in body


# ---------- R13: allowlist phải khớp nội dung prompt thật ----------


async def test_allowlist_only_contains_chunks_visible_in_prompt():
    """Bug hồi quy: id bị cắt do ngân sách không được nằm trong allowlist.

    Nếu allowlist rộng hơn prompt, model được "cấp quyền" trích đoạn nó chưa hề
    đọc ⇒ server có thể xác nhận citation không dựa trên ngữ cảnh thực.
    """
    items = [
        retrieval_service.RetrievedChunk(
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page_number=index + 1,
            char_start=0,
            char_end=100,
            section_anchor=None,
            text_hash=f"h{index}",
            text="nội dung " * 120,
            source_title="Tài liệu dài",
            source_version="1.0",
            source_type="user_document",
        )
        for index in range(5)
    ]
    section, included = retrieval_service.build_context_section_with_ids(
        items, max_chars=400
    )
    assert included, "phải có ít nhất một đoạn vừa ngân sách"
    assert len(included) < len(items), "ngân sách nhỏ phải cắt bớt đoạn"
    for chunk_id in included:
        assert f"chk_{chunk_id}" in section
    excluded = {item.chunk_id for item in items} - set(included)
    for chunk_id in excluded:
        assert f"chk_{chunk_id}" not in section


async def test_rag_service_narrows_result_items_to_prompted_chunks():
    items = [
        retrieval_service.RetrievedChunk(
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            page_number=index + 1,
            char_start=0,
            char_end=100,
            section_anchor=None,
            text_hash=f"h{index}",
            text="nội dung " * 120,
            source_title="Tài liệu dài",
            source_version="1.0",
            source_type="user_document",
        )
        for index in range(5)
    ]
    result = retrieval_service.RetrievalResult(
        items=items, insufficient_evidence=False
    )
    _system, allowlist = rag_service.build_system_with_rag("BASE", result, max_chars=400)
    assert set(allowlist) == {item.chunk_id for item in result.items}
    assert len(allowlist) < len(items)

    # Verify chỉ chấp nhận id còn lại sau khi prompt đã cắt.
    dropped = items[0].chunk_id if items[0].chunk_id not in allowlist else None
    if dropped is not None:
        verified, _pointers, rejected = rag_service.verify_answer(
            f"theo [chk_{dropped}]", result
        )
        assert verified == []
        assert dropped in rejected


# ---------- R14: notice trung thực theo trạng thái RAG ----------


async def test_course_source_notice_reflects_rag_state(client, monkeypatch):
    owner_id, course_id, _source_id = await _setup_course_with_source(client)

    monkeypatch.setattr(get_settings(), "rag_enabled", True)
    r = await client.get(f"/v1/courses/{course_id}/sources")
    assert r.status_code == 200
    body = r.json()
    assert body["contentIngested"] is True
    # Grounding của lesson KHÔNG đổi ở P4.1 — chỉ tutor dùng nguồn.
    assert body["groundingAvailable"] is False
    assert "chứng minh từng câu" in (body["notice"] or "")

    monkeypatch.setattr(get_settings(), "rag_enabled", False)
    r2 = await client.get(f"/v1/courses/{course_id}/sources")
    body2 = r2.json()
    assert "TẮT" in (body2["notice"] or "")
    assert body2["groundingAvailable"] is False
