"""Phase 3 tests: Source Brief hard-schema, 2-tier Validator QA, structured interview chips,
Lesson-1-First progressive callbacks, and source brief callback payload."""

from __future__ import annotations

import json

import httpx

from app.agents.providers import MockProvider
from app.agents.validator_qa import run_two_tier_validator
from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings
from app.core.internal_auth import (
    HEADER_SERVICE_AUTH,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    verify_internal_headers,
)
from app.db.session import dispose_engine, ensure_sqlite_tables, get_session_factory
from app.rag.brief_builder import build_source_brief
from app.rag.repository import ChunkInput, RagRepository
from app.rag.storage import MemorySourceStorage
from app.workers.worker_ingest import handle_ingest_job
from app.workers.worker_llm import handle_llm_job


def _recording_client(cfg: Settings):
    recorded: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        failure = verify_internal_headers(
            token=request.headers.get(HEADER_SERVICE_AUTH),
            timestamp_raw=request.headers.get(HEADER_TIMESTAMP),
            signature=request.headers.get(HEADER_SIGNATURE),
            method=request.method,
            path_with_query=request.url.path,
            raw_body=request.content,
            settings=cfg,
        )
        assert failure is None, f"HMAC failed: {failure}"
        recorded.append(
            {
                "path": request.url.path,
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(200, json={"accepted": True, "duplicate": False})

    return CoreApiCallbackClient(settings=cfg, transport=httpx.MockTransport(handler)), recorded


def test_build_source_brief_enforces_hard_schema_bounds():
    chunks = [
        ChunkInput(
            chunk_index=0,
            page_number=1,
            section_anchor="sec-transformer",
            content=(
                "Self-Attention computes weighted representations across every token in parallel. "
                "Prerequisites: basic linear algebra and matrix multiplication for Q, K, V matrices."
            ),
        ),
        ChunkInput(
            chunk_index=1,
            page_number=2,
            section_anchor="sec-scaled-dot",
            content=(
                "Using Q, K, V matrices, attention scales dot products by sqrt(d_k) to stabilize gradients. "
                "Multi-Head Attention projects queries and keys into multiple subspaces."
            ),
        ),
    ]
    out = build_source_brief(
        title="Attention Is All You Need",
        chunks=chunks,
        headings=[("sec-transformer", "Transformer Architecture"), ("sec-scaled-dot", "Scaled Dot-Product Attention")],
    )
    brief = out["brief"]
    assert isinstance(brief["what"], str) and len(brief["what"]) > 10
    assert 1 <= len(brief["claims"]) <= 10
    assert len(brief["notation"]) <= 20
    assert len(brief["assumes"]) <= 10
    assert 1 <= len(brief["sections"]) <= 40
    for sec in brief["sections"]:
        assert set(sec.keys()) == {"anchor", "heading", "gist"}
        assert sec["anchor"]
    assert out["wordCount"] > 20
    assert out["durationMinutes"] >= 1
    assert out["suggestedTopic"]


async def test_two_tier_validator_flags_warnings_and_passes_clean_lesson():
    provider = MockProvider()
    clean_lesson, _usage = await provider.generate_lesson(
        topic="Graph Algorithms",
        unit_title="Shortest Paths",
        lesson_title="Dijkstra Algorithm",
        language="en",
        learner_profile={},
    )
    res_clean = await run_two_tier_validator(clean_lesson, provider=provider, llm_qa_enabled=False)
    assert res_clean.blocking_errors == []
    assert res_clean.estimated_minutes >= 3

    # Now inject a brief teach block + duplicate MC options -> static warnings recorded as contentFlags
    noisy_lesson = {
        "title": "Noisy Lesson",
        "blocks": [
            {"type": "teach", "heading": "Hi", "paragraphs": ["Too short"]},
            {
                "type": "mc",
                "prompt": "Pick one",
                "options": ["Same", "Same"],
                "answerIndex": 0,
                "explanation": "Because.",
            },
        ],
    }
    res_noisy = await run_two_tier_validator(noisy_lesson, provider=provider, llm_qa_enabled=False)
    codes = {f["code"] for f in res_noisy.content_flags}
    assert "TEACH_TOO_BRIEF" in codes
    assert "MC_DUPLICATE_OPTIONS" in codes


async def test_mock_provider_structured_interview_chips_vi_and_en():
    provider = MockProvider()
    for lang, expected_q1 in [("en", "Have you worked with"), ("vi", "Bạn đã từng tiếp xúc")]:
        qs, _usage = await provider.generate_interview_questions("Linear Algebra", lang)
        assert len(qs) == 5
        assert expected_q1 in qs[0].prompt
        kinds = {q.kind for q in qs}
        assert "single" in kinds and "multi" in kinds
        for q in qs:
            assert 2 <= len(q.choices) <= 6


async def test_worker_llm_emits_progressive_lesson_ready_callbacks_with_lesson_ids():
    cfg = Settings(
        llm_provider="mock",
        core_api_url="http://core-api.test",
        internal_service_token="tok-123",
        internal_hmac_secret="sec-456",
    )
    cb_client, recorded = _recording_client(cfg)
    msg = {
        "jobId": "job_p3_1",
        "idempotencyKey": "idem_p3_1",
        "jobType": "generate_course",
        "ownerId": "usr_1",
        "courseId": "crs_p3_1",
        "correlationId": "cor_p3_1",
        "payload": {
            "topic": "Distributed Consensus",
            "language": "en",
            "lessonIds": ["lsn_1", "lsn_2"],
            "units": [
                {"title": "Foundations", "lessonTitles": ["Raft Leader Election", "Log Replication"]}
            ],
        },
    }
    res = await handle_llm_job(msg, callback_client=cb_client, settings=cfg)
    assert res["status"] == "completed"
    paths = [r["path"] for r in recorded]
    assert paths == [
        "/internal/jobs/job_p3_1/lesson-ready",
        "/internal/jobs/job_p3_1/lesson-ready",
        "/internal/jobs/job_p3_1/complete",
    ]
    assert recorded[0]["body"]["lessonId"] == "lsn_1"
    assert recorded[0]["body"]["lessonOrder"] == 0
    assert recorded[0]["body"]["estimatedMinutes"] >= 1
    assert recorded[1]["body"]["lessonId"] == "lsn_2"
    assert recorded[1]["body"]["lessonOrder"] == 1


async def test_worker_ingest_sends_structured_source_brief(tmp_path, monkeypatch):
    db_file = tmp_path / "p3_ingest.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file}",
        core_api_url="http://core-api.test",
        internal_service_token="tok-123",
        internal_hmac_secret="sec-456",
    )
    await dispose_engine()
    await ensure_sqlite_tables()
    cb_client, recorded = _recording_client(cfg)
    repo = RagRepository(settings=cfg)

    async with get_session_factory()() as db:
        res = await handle_ingest_job(
            {
                "sourceId": "src_p3",
                "documentId": "doc_p3",
                "idempotencyKey": "idem_src_p3",
                "ownerId": "usr_1",
                "sourceKind": "raw_text",
                "sourceTitle": "Vector Databases Overview",
                "rawText": (
                    "1. HNSW Indexes\n"
                    "Hierarchical Navigable Small World graphs enable fast approximate nearest neighbor search.\n"
                    "2. Hybrid Retrieval\n"
                    "Combining BM25 lexical matching with cosine vector search via RRF improves recall."
                ),
                "correlationId": "cor_p3_ing",
            },
            db=db,
            rag_repo=repo,
            callback_client=cb_client,
            settings=cfg,
            storage=MemorySourceStorage(),
        )
        assert res["status"] == "ready"
        assert len(recorded) == 1
        cb = recorded[0]["body"]
        assert cb["brief"]["what"]
        assert len(cb["brief"]["claims"]) >= 1
        assert cb["wordCount"] > 10
        assert cb["durationMinutes"] >= 1
        assert cb["suggestedTopic"] == "Vector Databases Overview"

    await dispose_engine()
