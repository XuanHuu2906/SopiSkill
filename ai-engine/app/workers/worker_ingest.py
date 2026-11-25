"""`ai-worker-ingest`: Redis Streams consumer on `queue:ai:ingest` (PDF/Web/arXiv/OCR -> `rag.document_chunks` -> callback)."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings, get_settings
from app.db.session import dispose_engine, ensure_sqlite_tables, get_session_factory
from app.rag.extractor import (
    ExtractionError,
    chunk_text_with_provenance,
    extract_arxiv_atom_text,
    extract_html_text,
    extract_pdf_pages,
)
from app.rag.repository import RagRepository
from app.rag.storage import get_source_storage
from app.rag.url_fetcher import WebFetchError, fetch_url_safe
from app.workers.streams import RedisStreamWorker, default_consumer_name

logger = logging.getLogger(__name__)


async def handle_ingest_job(
    message: dict[str, Any],
    *,
    db: AsyncSession | None = None,
    rag_repo: RagRepository | None = None,
    callback_client: CoreApiCallbackClient | None = None,
    settings: Settings | None = None,
    storage=None,
) -> dict[str, Any]:
    """Extract, chunk, embed into `rag.document_chunks`, and notify `core-api` via signed callback."""
    cfg = settings or get_settings()
    repo = rag_repo or RagRepository(settings=cfg)
    cb = callback_client or CoreApiCallbackClient(settings=cfg)
    store = storage or get_source_storage(cfg)

    source_id = str(message["sourceId"])
    document_id = str(message["documentId"])
    idempotency_key = str(message["idempotencyKey"])
    owner_id = str(message["ownerId"])
    course_id = message.get("courseId")
    source_kind = str(message["sourceKind"])
    source_title = message.get("sourceTitle")
    correlation_id = str(message.get("correlationId") or f"cor_{source_id}")

    async def _run_with_session(session: AsyncSession) -> dict[str, Any]:
        try:
            pages: list[tuple[int | None, str | None, str]] = []
            pipeline_version = "pypdf-v1"
            resolved_title = source_title

            if source_kind == "raw_text":
                raw_text = str(message.get("rawText") or "").strip()
                if not raw_text:
                    raise ExtractionError("SOURCE_EMPTY", "Raw text source is empty.")
                pages = [(1, "section-1", raw_text)]
                pipeline_version = "raw-text-v1"
            elif source_kind == "pdf_s3":
                storage_key = str(message.get("storageKey") or "")
                if not storage_key:
                    raise ExtractionError("STORAGE_KEY_MISSING", "Missing storageKey for pdf_s3 ingest.")
                raw_bytes = await store.get_bytes(storage_key)
                extracted = extract_pdf_pages(
                    raw_bytes,
                    ocr_enabled=bool(message.get("ocrEnabled", False)),
                    settings=cfg,
                )
                pages = [(p, f"p{p}", txt) for p, txt in extracted]
            elif source_kind in {"web_url", "arxiv_url"}:
                url = str(message.get("url") or "")
                fetched = await fetch_url_safe(url, settings=cfg)
                if source_kind == "arxiv_url" or "xml" in fetched.media_type:
                    txt, arxiv_title = extract_arxiv_atom_text(fetched.data)
                    resolved_title = resolved_title or arxiv_title
                    pages = [(1, "abstract", txt)]
                    pipeline_version = "arxiv-atom-v1"
                else:
                    txt, sections = extract_html_text(fetched.data)
                    anchor = sections[0][0] if sections else "body"
                    pages = [(1, anchor, txt)]
                    pipeline_version = "html-v1"
            else:
                raise ExtractionError("UNSUPPORTED_SOURCE_KIND", f"Unsupported sourceKind: {source_kind!r}")

            chunks = chunk_text_with_provenance(pages)
            if not chunks:
                raise ExtractionError("NO_EXTRACTABLE_TEXT", "Document produced 0 text chunks.")

            inserted = await repo.replace_document_chunks(
                session,
                owner_id=owner_id,
                course_id=course_id,
                source_id=source_id,
                document_id=document_id,
                source_title=resolved_title,
                chunks=chunks,
            )
            word_count = sum(len(c.content.split()) for c in chunks)
            callback_payload = {
                "sourceId": source_id,
                "documentId": document_id,
                "idempotencyKey": idempotency_key,
                "status": "ready",
                "chunkCount": inserted,
                "wordCount": word_count,
                "pipelineVersion": pipeline_version,
                "brief": None,
                "errorCode": None,
                "errorMessage": None,
            }
        except (ExtractionError, WebFetchError) as exc:
            callback_payload = {
                "sourceId": source_id,
                "documentId": document_id,
                "idempotencyKey": idempotency_key,
                "status": "failed",
                "chunkCount": 0,
                "errorCode": exc.code,
                "errorMessage": exc.message,
            }
        except Exception as exc:  # noqa: BLE001
            callback_payload = {
                "sourceId": source_id,
                "documentId": document_id,
                "idempotencyKey": idempotency_key,
                "status": "failed",
                "chunkCount": 0,
                "errorCode": "INGEST_FAILED",
                "errorMessage": f"{type(exc).__name__}: {str(exc)[:240]}",
            }

        await cb.post_callback(
            f"/internal/sources/{source_id}/complete",
            callback_payload,
            correlation_id=correlation_id,
        )
        return callback_payload

    if db is not None:
        return await _run_with_session(db)

    factory = get_session_factory()
    async with factory() as session:
        return await _run_with_session(session)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = get_settings()
    await ensure_sqlite_tables()
    redis = Redis.from_url(cfg.redis_url)
    worker = RedisStreamWorker(
        redis=redis,
        stream_key=cfg.stream_ingest_key,
        group_name=cfg.stream_ingest_group,
        dlq_key=cfg.stream_ingest_dlq_key,
        consumer_name=default_consumer_name("ai-worker-ingest"),
        handler=handle_ingest_job,
        claim_idle_ms=cfg.stream_claim_idle_ms,
        max_retries=cfg.stream_max_retries,
        block_ms=cfg.stream_block_ms,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run_forever()
    finally:
        await redis.aclose()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
