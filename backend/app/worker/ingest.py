"""Ingest worker (P4.0) — claim, extract, chunk, persist; bounded retry.

Luồng giống `worker/generation.py` (P1.2) nhưng cho tài liệu nguồn:
  1. `claim_document` nguyên tử (queued → extracting + lease).
  2. Đọc bytes từ private storage (server-side key, không lấy từ client).
  3. `extract_pages` → `chunk_pages` (text-only; PDF scan ⇒ `no_text`).
  4. `finish_ready` ghi chunk + trạng thái trong một transaction.
  5. Lỗi tạm thời → requeue bounded; lỗi dữ liệu (corrupt/encrypted/no text)
     → `failed` với mã ổn định, KHÔNG retry vô ích.

Không log nội dung tài liệu. Development/test có `SOURCE_INGEST_INLINE_BLOCKING`
để chạy đồng bộ (SQLite dùng chung một connection).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.models import SourceDocument, SourceDocumentOrigin, SourceDocumentStatus

logger = logging.getLogger(__name__)

_settings = get_settings()

_celery_app = None
_use_celery = False

if _settings.redis_url:
    try:
        from app.worker.celery_app import celery_app as _configured_app

        if _configured_app is not None:
            _celery_app = _configured_app
            _use_celery = True
    except Exception:  # pragma: no cover — thiếu celery/redis không được làm sập app
        _celery_app = None
        _use_celery = False


def get_celery_app():
    return _celery_app


TASK_NAME = "app.worker.ingest.run_ingest_task"


async def _run_ingest_async(document_id: str) -> None:
    """Thân task ingest — engine riêng vì mỗi `asyncio.run` có event loop mới."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.session import engine as app_engine

    settings = get_settings()
    engine = (
        app_engine
        if settings.database_url.startswith("sqlite")
        else create_async_engine(settings.database_url, pool_pre_ping=True)
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        await _ingest(Session, document_id)
    finally:
        if engine is not app_engine:
            await engine.dispose()


async def _ingest(Session, document_id: str) -> None:
    from app.services import ingest as ingest_service
    from app.services import storage as storage_module

    try:
        did = uuid.UUID(document_id)
    except (ValueError, TypeError):
        return

    async with Session() as db:
        document = await ingest_service.claim_document(db, did)
        if document is None:
            logger.info("ingest not claimed (done/running/exhausted) document_id=%s", did)
            return

        source_id = document.source_id
        storage_key = document.storage_key
        origin = document.origin

        try:
            if not await ingest_service.renew_lease(db, did):
                logger.info("ingest lease lost document_id=%s", did)
                return

            data = await asyncio.to_thread(_read_object, storage_key)

            if origin != SourceDocumentOrigin.upload:
                # P4.2 — web blob (JSON đã trích) hoặc PDF arXiv: KHÔNG chạy lại
                # `check_limits` của PDF upload, và web không đi qua `pypdf`.
                await _ingest_fetched(db, document, origin=origin, data=data)
                return

            page_count = ingest_service.check_limits(data)
            document.page_count = page_count
            await db.commit()

            if not await ingest_service.renew_lease(db, did):
                logger.info("ingest lease lost document_id=%s", did)
                return

            try:
                extraction = await asyncio.to_thread(ingest_service.extract_pages, data)
            except ingest_service.IngestError as exc:
                if exc.code == "NO_EXTRACTABLE_TEXT":
                    await ingest_service.finish_no_text(db, document)
                    logger.info("ingest no_text document_id=%s source_id=%s", did, source_id)
                    return
                raise

            drafts = ingest_service.chunk_pages(extraction.pages)
            if not drafts:
                await ingest_service.finish_no_text(db, document)
                logger.info("ingest no_chunks document_id=%s source_id=%s", did, source_id)
                return

            await ingest_service.finish_ready(db, document, extraction.pages, drafts)
            logger.info(
                "ingest ready document_id=%s source_id=%s pages=%s chunks=%s",
                did,
                source_id,
                len(extraction.pages),
                len(drafts),
            )
            # P4.1 — tạo embedding cho chunk vừa ghi. Best-effort: lỗi embedding
            # KHÔNG được biến document thành `failed`, vì nội dung đã ingest xong
            # và reconciler sẽ backfill sau.
            from app.services import rag_service

            await rag_service.embed_after_ingest(db, source_id)
        except storage_module.StorageNotFound:
            await db.rollback()
            await ingest_service.fail_document(
                db,
                did,
                ingest_service.IngestError(
                    "STORAGE_OBJECT_MISSING", "Bản gốc không còn trong kho lưu trữ.", retryable=False
                ),
            )
            logger.warning("ingest storage object missing document_id=%s", did)
        except storage_module.StorageError as exc:
            await db.rollback()
            outcome = await ingest_service.fail_document(
                db,
                did,
                ingest_service.IngestError("STORAGE_UNAVAILABLE", exc.code, retryable=True),
            )
            logger.warning(
                "ingest storage error document_id=%s code=%s outcome=%s", did, exc.code, outcome
            )
        except ingest_service.IngestError as exc:
            await db.rollback()
            outcome = await ingest_service.fail_document(db, did, exc)
            logger.warning(
                "ingest rejected document_id=%s code=%s outcome=%s", did, exc.code, outcome
            )
        except Exception as exc:  # noqa: BLE001 — lỗi lạ phải phân loại rồi dừng
            await db.rollback()
            outcome = await ingest_service.fail_document(
                db,
                did,
                ingest_service.IngestError("INGEST_FAILED", type(exc).__name__, retryable=True),
            )
            logger.warning(
                "ingest failed document_id=%s error=%s outcome=%s", did, type(exc).__name__, outcome
            )


def _read_object(key: str) -> bytes:
    from app.services import storage as storage_module

    return storage_module.get_storage().get(key)


async def _ingest_fetched(
    db, document: SourceDocument, *, origin: SourceDocumentOrigin, data: bytes
) -> None:
    """Ingest document đến từ web/arXiv (P4.2) — dùng chung chunk/embedding P4.0/1.

    Web: blob là JSON text đã sanitize ⇒ chunk theo section provenance, không
    overlap. arXiv: blob là PDF bytes ⇒ dùng đúng `extract_pages`/`chunk_pages`
    của P4.0 (provenance theo page thật).
    """
    from app.services import ingest as ingest_service
    from app.services import rag_service, web_ingest

    if origin == SourceDocumentOrigin.web:
        extraction = web_ingest.parse_web_extraction(data)
        drafts = web_ingest.chunk_web_extraction(extraction)
        if not drafts:
            await ingest_service.finish_no_text(db, document)
            logger.info(
                "ingest web no_chunks document_id=%s source_id=%s", document.id, document.source_id
            )
            return
        pages = web_ingest.build_extracted_pages(extraction)
        await ingest_service.finish_ready(db, document, pages, drafts)
        logger.info(
            "ingest web ready document_id=%s source_id=%s chars=%s chunks=%s",
            document.id,
            document.source_id,
            extraction.char_count,
            len(drafts),
        )
        await rag_service.embed_after_ingest(db, document.source_id)
        return

    # arXiv (và mọi origin PDF fetched trong tương lai).
    page_count = ingest_service.check_limits(
        data,
        max_bytes=get_settings().web_max_fetch_bytes,
        max_pages=get_settings().source_max_pdf_pages,
    )
    document.page_count = page_count
    await db.commit()

    if not await ingest_service.renew_lease(db, document.id):
        logger.info("ingest lease lost document_id=%s", document.id)
        return

    try:
        extraction = await asyncio.to_thread(ingest_service.extract_pages, data)
    except ingest_service.IngestError as exc:
        if exc.code == "NO_EXTRACTABLE_TEXT":
            await ingest_service.finish_no_text(db, document)
            logger.info(
                "ingest arxiv no_text document_id=%s source_id=%s",
                document.id,
                document.source_id,
            )
            return
        raise

    drafts = ingest_service.chunk_pages(extraction.pages)
    if not drafts:
        await ingest_service.finish_no_text(db, document)
        logger.info(
            "ingest arxiv no_chunks document_id=%s source_id=%s",
            document.id,
            document.source_id,
        )
        return

    await ingest_service.finish_ready(db, document, extraction.pages, drafts)
    logger.info(
        "ingest arxiv ready document_id=%s source_id=%s pages=%s chunks=%s",
        document.id,
        document.source_id,
        len(extraction.pages),
        len(drafts),
    )
    await rag_service.embed_after_ingest(db, document.source_id)


async def dispatch_document(db, document_id: uuid.UUID, countdown: int = 0) -> bool:
    """Gửi ingest sang broker (hoặc chạy inline khi dev/test không có broker)."""
    from sqlalchemy import update

    settings = get_settings()
    app = get_celery_app()
    if app is None:
        if not settings.source_ingest_enabled:
            return False
        await _mark_dispatched(db, document_id)
        if countdown > 0:
            return True
        if settings.generation_inline_blocking:
            await _run_inline(document_id)
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            await _run_inline(document_id)
            return True
        loop.create_task(_run_inline(document_id))
        return True

    try:
        await asyncio.wait_for(
            asyncio.to_thread(app.send_task, TASK_NAME, args=[str(document_id)], countdown=countdown),
            timeout=settings.generation_dispatch_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — broker down phải chịu được
        logger.warning(
            "ingest dispatch failed document_id=%s code=%s", document_id, type(exc).__name__
        )
        await db.execute(
            update(SourceDocument)
            .where(SourceDocument.id == document_id, SourceDocument.dispatched_at.is_(None))
            .values(dispatch_attempts=SourceDocument.dispatch_attempts + 1)
        )
        await db.commit()
        return False

    await _mark_dispatched(db, document_id)
    return True


async def _mark_dispatched(db, document_id: uuid.UUID) -> None:
    from sqlalchemy import update

    await db.execute(
        update(SourceDocument)
        .where(SourceDocument.id == document_id)
        .values(dispatched_at=datetime.now(UTC), dispatch_attempts=SourceDocument.dispatch_attempts + 1)
    )
    await db.commit()


async def _run_inline(document_id: uuid.UUID) -> None:
    try:
        await _run_ingest_async(str(document_id))
    except Exception:  # pragma: no cover — task nền không được làm sập request
        logger.exception("inline ingest crashed document_id=%s", document_id)


async def recover_stuck_documents(db, limit: int = 20) -> list[uuid.UUID]:
    """Reconciler cho ingest: lease hết hạn hoặc chưa dispatch (outbox).

    Chỉ requeue document `queued` chưa dispatch quá grace, hoặc `extracting` có
    lease hết hạn. Không đụng `ready`/`no_text`/`failed`.
    """
    from datetime import timedelta

    from sqlalchemy import or_, select

    settings = get_settings()
    now = datetime.now(UTC)
    grace = timedelta(seconds=settings.generation_dispatch_grace_seconds)

    rows = await db.execute(
        select(SourceDocument)
        .where(
            or_(
                (SourceDocument.status == SourceDocumentStatus.queued)
                & SourceDocument.dispatched_at.is_(None)
                & (SourceDocument.created_at < now - grace),
                (SourceDocument.status == SourceDocumentStatus.extracting)
                & or_(
                    SourceDocument.lease_expires_at.is_(None),
                    SourceDocument.lease_expires_at < now,
                ),
            )
        )
        .order_by(SourceDocument.created_at)
        .limit(limit)
    )
    documents = list(rows.scalars().all())

    recovered: list[uuid.UUID] = []
    for document in documents:
        if document.status == SourceDocumentStatus.extracting:
            # Lease hết hạn mà không ai heartbeat ⇒ trả về queued để claim lại.
            document.status = SourceDocumentStatus.queued
            document.lease_expires_at = None
            document.dispatched_at = None
            await db.commit()
        if document.attempts_count >= document.max_attempts:
            document.status = SourceDocumentStatus.failed
            document.error_code = "INGEST_ATTEMPTS_EXHAUSTED"
            document.error = {
                "code": "INGEST_ATTEMPTS_EXHAUSTED",
                "message": "Ingest thất bại quá số lần cho phép.",
                "retryable": False,
            }
            document.lease_expires_at = None
            await db.commit()
            continue
        await dispatch_document(db, document.id)
        recovered.append(document.id)
    return recovered


async def _run_reconcile_async(limit: int = 20) -> list[str]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.session import engine as app_engine

    settings = get_settings()
    engine = (
        app_engine
        if settings.database_url.startswith("sqlite")
        else create_async_engine(settings.database_url, pool_pre_ping=True)
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            recovered = await recover_stuck_documents(db, limit=limit)
            if recovered:
                logger.info("ingest reconciler recovered count=%s", len(recovered))
            return [str(document_id) for document_id in recovered]
    finally:
        if engine is not app_engine:
            await engine.dispose()


def reconcile_now(limit: int = 10) -> list[uuid.UUID]:
    return [uuid.UUID(x) for x in asyncio.run(_run_reconcile_async(limit))]


if _use_celery and _celery_app is not None:

    @_celery_app.task(name=TASK_NAME, bind=True, max_retries=0)
    def run_ingest_task(self, document_id: str):  # noqa: ANN001
        asyncio.run(_run_ingest_async(document_id))

    @_celery_app.task(name="app.worker.ingest.reconcile_ingest", bind=True, max_retries=0)
    def reconcile_ingest(self, limit: int = 10):  # noqa: ANN001
        return asyncio.run(_run_reconcile_async(limit))


async def backfill_embeddings(db, limit: int | None = None) -> int:
    """Backfill embedding cho chunk còn thiếu/stale (P4.1). Idempotent.

    Chạy trên beat để bắt kịp: ingest xong khi embedding tạm lỗi, hoặc admin đổi
    `EMBEDDING_MODEL/VERSION` (spec mới ⇒ mọi chunk trở thành "missing").
    """
    from app.core.config import get_settings as _get_settings
    from app.services import embedding_service

    settings = _get_settings()
    if not settings.embedding_enabled:
        return 0
    total = 0
    cap = max(1, int(limit or settings.embedding_reconcile_limit or 200))
    while total < cap:
        chunks = await embedding_service.chunks_missing_embedding(
            db, limit=min(200, cap - total)
        )
        if not chunks:
            break
        written = await embedding_service.embed_chunks(db, chunks)
        await db.commit()
        total += written
        if written == 0:
            break
    if total:
        logger.info("embed backfill written=%s", total)
    return total


async def _run_embed_reconcile_async(limit: int | None = None) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.session import engine as app_engine

    settings = get_settings()
    engine = (
        app_engine
        if settings.database_url.startswith("sqlite")
        else create_async_engine(settings.database_url, pool_pre_ping=True)
    )
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            return await backfill_embeddings(db, limit=limit)
    finally:
        if engine is not app_engine:
            await engine.dispose()


if _use_celery and _celery_app is not None:

    @_celery_app.task(name="app.worker.ingest.reconcile_embeddings", bind=True, max_retries=0)
    def reconcile_embeddings(self, limit: int = 200):  # noqa: ANN001
        return asyncio.run(_run_embed_reconcile_async(limit))
