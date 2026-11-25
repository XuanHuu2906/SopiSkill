"""Unit tests for ai-worker-llm & ai-worker-ingest handlers and HMAC-signed callbacks."""

from __future__ import annotations

import json

import httpx

from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings
from app.core.internal_auth import (
    HEADER_CORRELATION,
    HEADER_SERVICE_AUTH,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    verify_internal_headers,
)
from app.db.session import dispose_engine, ensure_sqlite_tables, get_session_factory
from app.rag.repository import RagRepository
from app.rag.storage import MemorySourceStorage
from app.workers.worker_ingest import handle_ingest_job
from app.workers.worker_llm import handle_llm_job


def _make_recording_callback(cfg: Settings):
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
        assert failure is None, f"Callback HMAC verification failed: {failure}"
        recorded.append(
            {
                "path": request.url.path,
                "correlation_id": request.headers.get(HEADER_CORRELATION),
                "body": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(200, json={"accepted": True, "duplicate": False})

    client = CoreApiCallbackClient(settings=cfg, transport=httpx.MockTransport(handler))
    return client, recorded


async def test_worker_llm_generates_validated_lessons_and_sends_signed_callback():
    cfg = Settings(
        llm_provider="mock",
        core_api_url="http://core-api.test",
        internal_service_token="tok-123",
        internal_hmac_secret="sec-456",
    )
    cb_client, recorded = _make_recording_callback(cfg)

    msg = {
        "jobId": "job_42",
        "idempotencyKey": "idem_42",
        "jobType": "generate_course",
        "ownerId": "usr_1",
        "courseId": "crs_1",
        "correlationId": "cor_llm_42",
        "payload": {
            "topic": "Docker Basics",
            "language": "en",
            "units": [{"title": "Foundations", "lessonTitles": ["What is a container?"]}],
        },
    }
    res = await handle_llm_job(msg, callback_client=cb_client, settings=cfg)
    assert res["status"] == "completed"
    assert len(res["result"]["lessons"]) == 1
    assert len(recorded) == 1
    assert recorded[0]["path"] == "/internal/jobs/job_42/complete"
    assert recorded[0]["correlation_id"] == "cor_llm_42"


async def test_worker_ingest_chunks_raw_text_and_handles_ssrf_failure(tmp_path, monkeypatch):
    db_file = tmp_path / "ingest_worker.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_file}",
        core_api_url="http://core-api.test",
        internal_service_token="tok-123",
        internal_hmac_secret="sec-456",
        web_ingest_enabled=False,
    )
    await dispose_engine()
    await ensure_sqlite_tables()
    cb_client, recorded = _make_recording_callback(cfg)
    repo = RagRepository(settings=cfg)

    async with get_session_factory()() as db:
        ok_res = await handle_ingest_job(
            {
                "sourceId": "src_100",
                "documentId": "doc_100",
                "idempotencyKey": "idem_src_100",
                "ownerId": "usr_1",
                "courseId": "crs_1",
                "sourceKind": "raw_text",
                "sourceTitle": "Kubernetes Guide",
                "rawText": "Kubernetes Pods share networking and storage across containers.",
                "correlationId": "cor_ing_100",
            },
            db=db,
            rag_repo=repo,
            callback_client=cb_client,
            settings=cfg,
            storage=MemorySourceStorage(),
        )
        assert ok_res["status"] == "ready"
        assert ok_res["chunkCount"] == 1
        assert recorded[-1]["path"] == "/internal/sources/src_100/complete"

        # Blocked SSRF web_url -> failed callback with WEB_INGEST_DISABLED
        fail_res = await handle_ingest_job(
            {
                "sourceId": "src_101",
                "documentId": "doc_101",
                "idempotencyKey": "idem_src_101",
                "ownerId": "usr_1",
                "courseId": "crs_1",
                "sourceKind": "web_url",
                "url": "https://169.254.169.254/latest/meta-data/",
                "correlationId": "cor_ing_101",
            },
            db=db,
            rag_repo=repo,
            callback_client=cb_client,
            settings=cfg,
            storage=MemorySourceStorage(),
        )
        assert fail_res["status"] == "failed"
        assert fail_res["errorCode"] == "WEB_INGEST_DISABLED"

    await dispose_engine()
