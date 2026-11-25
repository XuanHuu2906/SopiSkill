"""Live Phase Gate 1 integration tests on Docker `pgvector/pgvector:pg16` + Redis 7 + `ai-api`.

Automatically skipped when PGVECTOR_TEST_URL / REDIS_TEST_URL are not set; executed during
Phase Gate 1 against `deploy/docker-compose.yml`.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.internal_auth import sign_internal_headers
from app.rag.repository import ChunkInput, RagRepository
from app.workers.streams import RedisStreamWorker, enqueue_stream_job

AI_ENGINE_DIR = Path(__file__).resolve().parents[1]
PGVECTOR_TEST_URL = os.environ.get("PGVECTOR_TEST_URL", "").strip()
REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "").strip()
AI_API_LIVE_URL = os.environ.get("AI_API_LIVE_URL", "").strip()


@pytest.mark.skipif(not PGVECTOR_TEST_URL, reason="PGVECTOR_TEST_URL not configured")
async def test_live_pgvector_alembic_schema_and_hybrid_rag_rrf():
    # 1. Verify Alembic migration roundtrip on `rag` schema (`rag.alembic_version`)
    env = {**os.environ, "DATABASE_URL": PGVECTOR_TEST_URL}
    for args in (["upgrade", "head"], ["downgrade", "base"], ["upgrade", "head"]):
        proc = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(AI_ENGINE_DIR),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"alembic {args} failed: {proc.stderr}"

    engine = create_async_engine(PGVECTOR_TEST_URL, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = RagRepository(settings=Settings(database_url=PGVECTOR_TEST_URL))

    owner_a = f"usr_live_{uuid.uuid4().hex[:8]}"
    owner_b = f"usr_other_{uuid.uuid4().hex[:8]}"
    course_id = f"crs_live_{uuid.uuid4().hex[:8]}"

    try:
        async with factory() as db:
            # Verify `rag.alembic_version`, vector extension, GIN FTS & HNSW vector indexes exist
            ext = (await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))).scalar()
            assert ext == "vector"
            ver = (await db.execute(text("SELECT version_num FROM rag.alembic_version"))).scalar()
            assert ver == "0001_init_rag_schema"
            indexes = {
                row[0]
                for row in (
                    await db.execute(
                        text("SELECT indexname FROM pg_indexes WHERE schemaname = 'rag' AND tablename = 'document_chunks'")
                    )
                ).all()
            }
            assert "ix_rag_chunks_tsv_gin" in indexes
            assert "ix_rag_chunks_embedding_hnsw" in indexes

            # Seed chunks for Owner A and Owner B
            await repo.replace_document_chunks(
                db,
                owner_id=owner_a,
                course_id=course_id,
                source_id="src_pg",
                document_id="doc_pg",
                source_title="PostgreSQL MVCC Paper",
                chunks=[
                    ChunkInput(
                        chunk_index=0,
                        content="PostgreSQL MVCC allows readers never to block writers using tuple snapshots.",
                        page_number=4,
                        section_anchor="sec-mvcc",
                    ),
                    ChunkInput(
                        chunk_index=1,
                        content="Bananas and oranges are common tropical fruits used in smoothies.",
                        page_number=9,
                        section_anchor="sec-fruit",
                    ),
                ],
            )
            await repo.replace_document_chunks(
                db,
                owner_id=owner_b,
                course_id=course_id,
                source_id="src_secret",
                document_id="doc_secret",
                source_title="Tenant B Secret",
                chunks=[
                    ChunkInput(
                        chunk_index=0,
                        content="PostgreSQL MVCC secret tenant B tuple snapshot internal leak test.",
                        page_number=1,
                        section_anchor="sec-leak",
                    ),
                ],
            )

            mode, hits = await repo.search(
                db,
                owner_id=owner_a,
                course_id=course_id,
                query="PostgreSQL MVCC tuple snapshots",
                top_k=5,
            )
            assert mode == "hybrid_rrf"
            assert len(hits) >= 1
            assert hits[0].sourceId == "src_pg"
            assert hits[0].pageNumber == 4
            assert hits[0].sectionAnchor == "sec-mvcc"
            assert all(h.sourceId != "src_secret" for h in hits), "Cross-tenant leak detected!"

            deleted_a = await repo.delete_by_user(db, owner_a)
            deleted_b = await repo.delete_by_user(db, owner_b)
            assert deleted_a == 2
            assert deleted_b == 1
    finally:
        await engine.dispose()


@pytest.mark.skipif(not REDIS_TEST_URL, reason="REDIS_TEST_URL not configured")
async def test_live_redis_streams_xreadgroup_xautoclaim_and_dlq():
    redis = Redis.from_url(REDIS_TEST_URL)
    suffix = uuid.uuid4().hex[:8]
    stream_key = f"test:queue:ai:llm:{suffix}"
    dlq_key = f"test:queue:ai:llm:dlq:{suffix}"
    group_name = f"test-group-{suffix}"
    handled: list[str] = []

    async def ok_handler(msg: dict) -> None:
        handled.append(str(msg["jobId"]))

    try:
        worker_a = RedisStreamWorker(
            redis=redis,
            stream_key=stream_key,
            group_name=group_name,
            dlq_key=dlq_key,
            consumer_name="consumer-dead",
            handler=ok_handler,
            claim_idle_ms=40,
            max_retries=2,
            block_ms=100,
        )
        await worker_a.ensure_group()
        await enqueue_stream_job(redis, stream_key, {"jobId": "job_recover_1", "attempt": 1})

        # Simulate Consumer A reading via XREADGROUP and crashing BEFORE XACK
        raw_read = await redis.xreadgroup(
            groupname=group_name,
            consumername="consumer-dead",
            streams={stream_key: ">"},
            count=1,
            block=200,
        )
        assert len(raw_read) == 1
        assert handled == []

        # Wait past idle threshold; Consumer B reclaims with XAUTOCLAIM and completes it
        await asyncio.sleep(0.08)
        worker_b = RedisStreamWorker(
            redis=redis,
            stream_key=stream_key,
            group_name=group_name,
            dlq_key=dlq_key,
            consumer_name="consumer-healthy",
            handler=ok_handler,
            claim_idle_ms=40,
            max_retries=2,
            block_ms=100,
        )
        reclaimed = await worker_b.reclaim_stale(count=5)
        assert reclaimed == 1
        assert handled == ["job_recover_1"]

        # Verify heartbeat & pending count == 0
        await worker_b.write_heartbeat()
        hb = await redis.get(f"worker:heartbeat:{group_name}:consumer-healthy")
        assert hb == b"alive"
        pending = await redis.xpending(stream_key, group_name)
        assert pending["pending"] == 0

        # Verify DLQ routing after max_retries exhaustion
        async def always_fail(_msg: dict) -> None:
            raise RuntimeError("boom")

        worker_dlq = RedisStreamWorker(
            redis=redis,
            stream_key=stream_key,
            group_name=group_name,
            dlq_key=dlq_key,
            consumer_name="consumer-dlq",
            handler=always_fail,
            claim_idle_ms=40,
            max_retries=1,
            block_ms=100,
        )
        await enqueue_stream_job(redis, stream_key, {"jobId": "job_poison", "attempt": 1})
        await worker_dlq.poll_once(count=5)
        dlq_len = await redis.xlen(dlq_key)
        assert dlq_len == 1
    finally:
        await redis.delete(stream_key, dlq_key, f"worker:heartbeat:{group_name}:consumer-healthy")
        await redis.aclose()


@pytest.mark.skipif(not AI_API_LIVE_URL, reason="AI_API_LIVE_URL not configured")
async def test_live_ai_api_container_ready_and_401_enforcement():
    cfg = Settings()
    async with httpx.AsyncClient(base_url=AI_API_LIVE_URL, timeout=10.0, trust_env=False) as client:
        r_ready = await client.get("/ready")
        assert r_ready.status_code == 200
        assert r_ready.json()["status"] == "ready"
        assert r_ready.json()["checks"]["database"] == "ok"
        assert r_ready.json()["checks"]["redis"] == "ok"

        payload = {"courseId": "crs_live", "topic": "Kubernetes", "language": "en"}
        r_unauth = await client.post("/internal/interview/questions", json=payload)
        assert r_unauth.status_code == 401

        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = sign_internal_headers(
            method="POST",
            path_with_query="/internal/interview/questions",
            raw_body=raw,
            settings=cfg,
        )
        headers["Content-Type"] = "application/json"
        r_ok = await client.post("/internal/interview/questions", content=raw, headers=headers)
        assert r_ok.status_code == 200
        assert len(r_ok.json()["questions"]) == 5
