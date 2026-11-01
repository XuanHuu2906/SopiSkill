"""Source Registry API (P3.0) + PDF ingestion (P4.0).

Authorization:
  - Mọi endpoint yêu cầu identity đã xác thực.
  - Nguồn private chỉ chủ sở hữu truy cập; truy cập trái quyền trả 404 (không xác
    nhận sự tồn tại).
  - Course phải thuộc user (dùng `course_service.get_owned_course`).
  - Discovery chỉ trả candidate; không tự đăng ký nguồn và không tự đánh dấu verified.
  - Upload PDF: stream có trần byte, kiểm tra magic, không tin extension/Content-Type;
    file lưu private storage với object key ngẫu nhiên do server sinh.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.csrf import verify_csrf
from app.core.limits import rate_limit
from app.db.session import get_db
from app.models import (
    CourseSource,
    SourceChunk,
    SourceDocument,
    SourceDocumentStatus,
    User,
)
from app.schemas.schemas import (
    CourseSourceListOut,
    CourseSourceOut,
    RagChunkOut,
    RagSearchOut,
    RagSearchRequest,
    SourceCreateRequest,
    SourceDiscoveryOut,
    SourceDocumentListOut,
    SourceDocumentOut,
    SourceEvaluationOut,
    SourceIngestConfigOut,
    SourceLinkRequest,
    SourceListOut,
    SourceOut,
    WebDocumentRequest,
)
from app.services import (
    course_service,
    ingest,
    source_discovery,
    source_evaluation,
    source_service,
    storage,
    url_fetcher,
    web_ingest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["sources"])

# Đọc upload theo khối để trần byte có hiệu lực TRƯỚC khi nạp cả file vào RAM.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


def _document_out(document: SourceDocument, *, chunk_count: int = 0, preview: str | None = None) -> SourceDocumentOut:
    return SourceDocumentOut(
        id=f"doc_{document.id}",
        sourceId=f"src_{document.source_id}",
        status=document.status.value,
        origin=document.origin.value if document.origin else "upload",
        originUrl=document.origin_url,
        mime=document.mime,
        byteSize=document.byte_size,
        pageCount=document.page_count,
        pipelineVersion=document.pipeline_version,
        originalFilename=document.original_filename,
        chunkCount=chunk_count,
        preview=preview,
        error=document.error,
        attempts=document.attempts_count,
        rightsConfirmed=document.rights_confirmed_at is not None,
        ingestedAt=document.ingested_at.isoformat() if document.ingested_at else None,
        createdAt=document.created_at.isoformat() if document.created_at else None,
    )



@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "source_create", limit=30, window_seconds=60)
    source, _created = await source_service.create_source(db, user.id, body)
    return source_service.to_source_out(source)


@router.get("/sources", response_model=SourceListOut)
async def list_sources(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await source_service.list_accessible_sources(db, user.id, limit=limit, offset=offset)


# Khai báo TRƯỚC `/sources/{source_id}` để không bị route động "nuốt" mất.
@router.get("/sources/discover", response_model=SourceDiscoveryOut)
async def discover_sources(
    request: Request,
    topic: str = Query(min_length=1, max_length=200),
    adapter: str | None = Query(default=None, max_length=32),
    user: User = Depends(get_current_user),
):
    # Không gọi network: adapter mặc định là curated/mock; `web` bị từ chối rõ ràng.
    rate_limit(request, "source_discover", limit=30, window_seconds=60)
    try:
        resolved = source_discovery.get_discovery_adapter(adapter)
        items = await resolved.search_sources(topic, context={"userId": str(user.id)})
    except source_discovery.SourceDiscoveryConfigError as exc:
        # Cấu hình/khả năng chưa có ⇒ 503 có mã lỗi, không lộ chi tiết nội bộ.
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": "Tính năng tìm nguồn này chưa được cấu hình hoặc chưa hỗ trợ.",
            },
        ) from exc
    return SourceDiscoveryOut(
        adapter=resolved.name,
        query=topic,
        deterministic=resolved.deterministic,
        isMock=resolved.is_mock,
        items=items,
        notice=(
            "Kết quả MOCK, không phải tìm kiếm thật và không được xem là nguồn đã xác minh."
            if resolved.is_mock
            else "Ứng viên chưa phải nguồn đã đăng ký; cần bạn xác nhận trước khi liên kết."
        ),
    )


@router.get("/sources/ingest-config", response_model=SourceIngestConfigOut)
async def ingest_config(
    user: User = Depends(get_current_user),
) -> SourceIngestConfigOut:
    """Cấu hình công khai cho UI (không lộ endpoint/credential storage)."""
    settings = get_settings()
    return SourceIngestConfigOut(
        ingestEnabled=settings.source_ingest_enabled,
        storageConfigured=settings.source_storage_configured,
        maxPdfBytes=settings.source_max_pdf_bytes,
        maxPdfPages=settings.source_max_pdf_pages,
        pipelineVersion=settings.source_pipeline_version,
        embeddingEnabled=settings.embedding_enabled,
        embeddingConfigured=settings.embedding_configured,
        embeddingProvider=settings.embedding_provider,
        embeddingModel=settings.embedding_model,
        embeddingDimension=settings.embedding_dimension,
        ragEnabled=settings.rag_active,
        webEnabled=settings.web_ingest_active,
        webAllowedHostCount=len(settings.web_allowed_hosts),
        webMaxFetchBytes=settings.web_max_fetch_bytes,
        webRespectRobots=settings.web_ingest_respect_robots,
        arxivEnabled=(
            settings.web_ingest_active
            and url_fetcher.host_allowed(settings.arxiv_pdf_host, settings.web_allowed_hosts)
            and url_fetcher.host_allowed(settings.arxiv_api_host, settings.web_allowed_hosts)
        ),
    )


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    return source_service.to_source_out(source)


@router.get("/sources/{source_id}/evaluation", response_model=SourceEvaluationOut)
async def evaluate_source(
    source_id: str,
    topic: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    has_content = await ingest.source_has_content(db, source.id)
    result = source_evaluation.evaluate_source(
        source, topics=[topic] if topic else [], has_content=has_content
    )
    payload = result.to_dict()
    return SourceEvaluationOut(
        sourceId=f"src_{source.id}",
        criteria=payload["criteria"],
        knownWeight=payload["knownWeight"],
        totalWeight=payload["totalWeight"],
        weightedScore=payload["weightedScore"],
        verdict=payload["verdict"],
        suggestedVerificationStatus=payload["suggestedVerificationStatus"],
        limitations=payload["limitations"],
        evaluator=payload["evaluator"],
    )


@router.post("/courses/{course_id}/sources", response_model=CourseSourceOut, status_code=201)
async def link_course_source(
    course_id: str,
    body: SourceLinkRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    verify_csrf(request)
    rate_limit(request, "course_source_link", limit=60, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)
    source = await source_service.get_accessible_source(db, body.sourceId, user.id)
    has_content = await ingest.source_has_content(db, source.id)
    evaluation = source_evaluation.evaluate_source(
        source, topics=[course.topic], has_content=has_content
    ).to_dict()
    link, source, _created = await source_service.link_source_to_course(
        db, course, user.id, body.sourceId, evaluation=evaluation
    )
    return CourseSourceOut(
        courseId=f"crs_{course.id}",
        source=source_service.to_source_out(source),
        evaluation=link.evaluation,
        linkedAt=link.created_at.isoformat() if link.created_at else None,
    )


@router.get("/courses/{course_id}/sources", response_model=CourseSourceListOut)
async def list_course_sources(
    course_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await course_service.get_owned_course(db, course_id, user.id)
    rows = await source_service.list_course_sources(db, course.id, user.id)
    items = [
        CourseSourceOut(
            courseId=f"crs_{course.id}",
            source=source_service.to_source_out(source),
            evaluation=link.evaluation,
            linkedAt=link.created_at.isoformat() if link.created_at else None,
        )
        for link, source in rows
    ]
    has_sources = len(items) > 0
    source_ids = [source.id for _link, source in rows]
    ingested_ids = await _ready_source_ids(db, source_ids)
    content_ingested = len(ingested_ids) > 0
    # `groundingAvailable` nói về việc SINH BÀI HỌC từ excerpt nguồn (generation
    # grounding) — P4.1 chỉ mở retrieval/citation trong tutor, không đổi grounding
    # của lesson. Vì vậy vẫn False, và notice nói rõ RAG đang bật hay tắt.
    settings = get_settings()
    if content_ingested and settings.rag_active:
        notice = (
            "Đã có nội dung nguồn được trích xuất và tìm kiếm tài liệu (RAG) đang bật. "
            "Trợ giảng có thể trả lời kèm trích dẫn đã xác minh VỊ TRÍ chunk (chưa "
            "chứng minh từng câu). Bài học vẫn dựa trên kiến thức chung của AI."
        )
    elif content_ingested:
        notice = (
            "Đã có nội dung nguồn được trích xuất nhưng tìm kiếm tài liệu (RAG) đang "
            "TẮT hoặc embedding chưa cấu hình hợp lệ, nên trợ giảng chưa dùng nguồn này."
        )
    elif has_sources:
        notice = (
            "Nguồn đã liên kết nhưng chưa ingest nội dung: bài học vẫn dựa trên kiến thức "
            "chung của AI và citation sẽ ở trạng thái chưa xác minh."
        )
    else:
        notice = "Khóa học chưa liên kết nguồn nào; nội dung bài học là kiến thức chung của AI."
    return CourseSourceListOut(
        items=items,
        total=len(items),
        groundingAvailable=False,
        contentIngested=content_ingested,
        notice=notice,
    )


async def _ready_source_ids(db: AsyncSession, source_ids: list) -> set:
    """Source đã có ít nhất một chunk từ document `ready` (owner đã được lọc ở trên)."""
    if not source_ids:
        return set()
    rows = await db.execute(
        select(SourceDocument.source_id)
        .where(
            SourceDocument.source_id.in_(source_ids),
            SourceDocument.status == SourceDocumentStatus.ready,
        )
        .distinct()
    )
    return set(rows.scalars().all())


# ---------- P4.0 — PDF ingestion ----------


async def _read_upload_limited(file: UploadFile, limit: int) -> bytes:
    """Đọc streaming tới `limit` byte; vượt ⇒ 413, không nạp phần còn lại."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "PDF_TOO_LARGE",
                    "message": f"PDF vượt giới hạn {limit} bytes.",
                },
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _ingest_http_error(exc: ingest.IngestError) -> HTTPException:
    status_code = 404 if exc.code == "SOURCE_DOCUMENT_NOT_FOUND" else 422
    return HTTPException(status_code=status_code, detail=exc.to_error())


_WEB_STATUS_BY_CODE = {
    "WEB_INGEST_DISABLED": status.HTTP_503_SERVICE_UNAVAILABLE,
    "WEB_ALLOWLIST_EMPTY": status.HTTP_503_SERVICE_UNAVAILABLE,
    "STORAGE_NOT_CONFIGURED": status.HTTP_503_SERVICE_UNAVAILABLE,
    "STORAGE_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    "ARXIV_HOST_NOT_ALLOWED": status.HTTP_503_SERVICE_UNAVAILABLE,
    "USER_RIGHTS_NOT_CONFIRMED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WEB_REQUEST_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WEB_HOST_NOT_ALLOWED": status.HTTP_403_FORBIDDEN,
    "WEB_HTTPS_REQUIRED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WEB_SCHEME_NOT_ALLOWED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WEB_PORT_NOT_ALLOWED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WEB_BLOCKED_ADDRESS": status.HTTP_403_FORBIDDEN,
    "WEB_ROBOTS_DENIED": status.HTTP_403_FORBIDDEN,
    "WEB_ROBOTS_UNVERIFIABLE": status.HTTP_403_FORBIDDEN,
    "WEB_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
    "WEB_RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
    "WEB_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
    "WEB_UPSTREAM_ERROR": status.HTTP_502_BAD_GATEWAY,
}


def _web_http_error(exc: web_ingest.WebIngestError) -> HTTPException:
    code = exc.code
    if code in _WEB_STATUS_BY_CODE:
        status_code = _WEB_STATUS_BY_CODE[code]
    elif code.startswith(("URL_", "ARXIV_ID_INVALID", "ARXIV_ID_EMPTY")):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif code == "ARXIV_NOT_FOUND":
        status_code = status.HTTP_404_NOT_FOUND
    elif code.startswith("ARXIV_"):
        status_code = status.HTTP_502_BAD_GATEWAY
    elif code.startswith("WEB_"):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=status_code, detail=exc.to_error())


async def _document_chunk_count(db: AsyncSession, document_id) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(SourceChunk)
                .where(SourceChunk.document_id == document_id)
            )
        ).scalar_one()
    )


@router.post(
    "/sources/{source_id}/document", response_model=SourceDocumentOut, status_code=202
)
async def upload_source_document(
    source_id: str,
    request: Request,
    file: UploadFile = File(..., description="PDF có quyền sử dụng"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload PDF (stream, giới hạn size/magic/page) và xếp hàng ingest bất đồng bộ."""
    verify_csrf(request)
    rate_limit(request, "source_upload", limit=10, window_seconds=60)

    settings = get_settings()
    if not settings.source_ingest_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "SOURCE_INGEST_DISABLED", "message": "Tính năng ingest nguồn đang tắt."},
        )
    if not storage.storage_configured():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_NOT_CONFIGURED",
                "message": "Kho lưu trữ nguồn chưa được cấu hình trên server.",
            },
        )

    # Nguồn phải thuộc user (public source không cho upload — tránh ghi đè dữ liệu chung).
    source = await source_service.get_owned_source(db, source_id, user.id)

    try:
        data = await _read_upload_limited(file, settings.source_max_pdf_bytes)
        document, created = await ingest.register_document(
            db, source, data=data, filename=file.filename, content_type=file.content_type
        )
    except storage.StorageNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_NOT_CONFIGURED", "message": "Kho lưu trữ nguồn chưa được cấu hình."},
        ) from exc
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "Kho lưu trữ tạm thời không sẵn sàng."},
        ) from exc
    except ingest.IngestError as exc:
        raise _ingest_http_error(exc) from exc
    finally:
        await file.close()

    chunk_count = (
        await db.execute(
            select(func.count())
            .select_from(SourceChunk)
            .where(SourceChunk.document_id == document.id)
        )
    ).scalar_one()
    needs_ingest = created and document.status == SourceDocumentStatus.queued
    if (
        not created
        and document.status == SourceDocumentStatus.failed
        and document.attempts_count < document.max_attempts
    ):
        # Người dùng upload lại đúng bytes sau khi lỗi = yêu cầu thử lại có chủ ý.
        # Chỉ retry khi còn lượt; nếu đã cạn thì phải xóa và tạo document mới.
        document.status = SourceDocumentStatus.queued
        document.error = None
        document.error_code = None
        document.dispatched_at = None
        await db.commit()
        needs_ingest = True

    if needs_ingest:
        # Dispatch chỉ khi document MỚI (hoặc retry có chủ ý); upload trùng đã
        # `ready` không chạy lại ingest.
        from app.worker import ingest as ingest_worker

        await ingest_worker.dispatch_document(db, document.id)
        await db.refresh(document)
        # Chạy inline (dev/test) hoặc worker đã xong rất nhanh ⇒ đọc lại số chunk
        # thật thay vì trả 0 trong khi document đã `ready`.
        chunk_count = (
            await db.execute(
                select(func.count())
                .select_from(SourceChunk)
                .where(SourceChunk.document_id == document.id)
            )
        ).scalar_one()

    return _document_out(document, chunk_count=int(chunk_count))


@router.post(
    "/sources/{source_id}/web-document",
    response_model=SourceDocumentOut,
    status_code=202,
)
async def ingest_web_document(
    source_id: str,
    body: WebDocumentRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch URL/arXiv và xếp hàng ingest (P4.2).

    Bảo mật: CSRF + rate limit + nguồn private thuộc user; URL phải qua allowlist
    và chống SSRF của `url_fetcher`. `userConfirmedRights` đã được validate ở
    schema (thiếu ⇒ 422 trước khi có bất kỳ request outbound nào).
    """
    verify_csrf(request)
    rate_limit(request, "source_web_ingest", limit=5, window_seconds=60)

    settings = get_settings()
    if not settings.web_ingest_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "WEB_INGEST_DISABLED",
                "message": "Tính năng tải nội dung từ URL đang tắt trên server.",
            },
        )
    if not storage.storage_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "STORAGE_NOT_CONFIGURED",
                "message": "Kho lưu trữ nguồn chưa được cấu hình trên server.",
            },
        )

    source = await source_service.get_owned_source(db, source_id, user.id)

    try:
        document, _created = await web_ingest.register_web_document(
            db,
            source,
            url=body.url,
            arxiv_id=body.arxivId,
            user_confirmed_rights=body.userConfirmedRights,
        )
    except storage.StorageNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "STORAGE_NOT_CONFIGURED",
                "message": "Kho lưu trữ nguồn chưa được cấu hình.",
            },
        ) from exc
    except web_ingest.WebIngestError as exc:
        raise _web_http_error(exc) from exc

    # Chỉ dispatch khi document còn `queued`; fetch lại nội dung y hệt (đã ready)
    # không được chạy lại pipeline.
    if document.status == SourceDocumentStatus.queued:
        from app.worker import ingest as ingest_worker

        await ingest_worker.dispatch_document(db, document.id)
        await db.refresh(document)

    chunk_count = await _document_chunk_count(db, document.id)
    return _document_out(document, chunk_count=chunk_count)


@router.get("/sources/{source_id}/documents", response_model=SourceDocumentListOut)
async def list_source_documents(
    source_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    documents = await ingest.list_documents_for_source(db, source.id)

    chunk_counts = dict(
        (
            await db.execute(
                select(SourceChunk.document_id, func.count())
                .where(SourceChunk.source_id == source.id)
                .group_by(SourceChunk.document_id)
            )
        ).all()
    )
    items = [
        _document_out(document, chunk_count=int(chunk_counts.get(document.id, 0)))
        for document in documents
    ]
    ready = any(document.status == SourceDocumentStatus.ready for document in documents)
    return SourceDocumentListOut(
        sourceId=f"src_{source.id}",
        items=items,
        total=len(items),
        contentIngested=ready,
        notice=(
            None
            if ready
            else "Chưa có nội dung nào được trích xuất từ nguồn này."
        ),
    )


@router.get("/sources/{source_id}/documents/{document_id}", response_model=SourceDocumentOut)
async def get_source_document(
    source_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    source = await source_service.get_accessible_source(db, source_id, user.id)
    document, doc_source = await ingest.get_owned_document(db, document_id, user.id)
    if doc_source.id != source.id:
        raise HTTPException(
            status_code=404,
            detail={"code": "SOURCE_DOCUMENT_NOT_FOUND", "message": "Tài liệu không thuộc nguồn này."},
        )

    chunk_count = (
        await db.execute(
            select(func.count()).select_from(SourceChunk).where(SourceChunk.document_id == document.id)
        )
    ).scalar_one()
    preview = None
    if document.status == SourceDocumentStatus.ready:
        first_chunk = (
            await db.execute(
                select(SourceChunk)
                .where(SourceChunk.document_id == document.id)
                .order_by(SourceChunk.chunk_index)
                .limit(1)
            )
        ).scalar_one_or_none()
        if first_chunk is not None:
            preview = ingest.normalize_preview(first_chunk.text)
    return _document_out(document, chunk_count=int(chunk_count), preview=preview)


@router.delete("/sources/{source_id}/documents/{document_id}", status_code=204)
async def delete_source_document(
    source_id: str,
    document_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Xóa tài liệu đã ingest (chunk đi theo cascade) + dọn object storage."""
    verify_csrf(request)
    rate_limit(request, "source_document_delete", limit=30, window_seconds=60)
    source = await source_service.get_owned_source(db, source_id, user.id)
    document, doc_source = await ingest.get_owned_document(db, document_id, user.id)
    if doc_source.id != source.id:
        raise HTTPException(
            status_code=404,
            detail={"code": "SOURCE_DOCUMENT_NOT_FOUND", "message": "Tài liệu không thuộc nguồn này."},
        )

    storage_key = document.storage_key
    # SQLite không bật FK cascade mặc định ⇒ xóa chunk tường minh (PostgreSQL
    # cascade cũng vẫn đúng, xóa hai lần không sai).
    from sqlalchemy import delete as sa_delete

    await db.execute(sa_delete(SourceChunk).where(SourceChunk.document_id == document.id))
    await db.delete(document)
    await db.commit()
    if storage.storage_configured():
        try:
            storage.get_storage().delete(storage_key)
        except storage.StorageError:
            logger.warning("source document object delete failed source_id=%s", source.id)
    # Source không còn nội dung ⇒ `content_hash` cũ không còn đúng.
    remaining = await ingest.latest_document(db, source.id)
    if remaining is None and source.content_hash is not None:
        source.content_hash = None
        await db.commit()
    return None


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Xóa nguồn private của chính user cùng document/chunk + object storage.

    Không xóa nguồn public (dùng chung) và không cho xóa nguồn của người khác
    (404 — không xác nhận sự tồn tại).
    """
    verify_csrf(request)
    rate_limit(request, "source_delete", limit=30, window_seconds=60)
    source = await source_service.get_owned_source(db, source_id, user.id)

    await ingest.delete_source_documents(db, source)

    links = (
        await db.execute(select(CourseSource).where(CourseSource.source_id == source.id))
    ).scalars().all()
    for link in links:
        await db.delete(link)
    await db.commit()

    from sqlalchemy import delete as sa_delete

    from app.models import LessonCitation

    await db.execute(
        sa_delete(LessonCitation).where(LessonCitation.source_id == source.id)
    )
    await db.delete(source)
    await db.commit()
    logger.info("source deleted source_id=%s", source.id)
    return None


# ---------- P4.1 — hybrid retrieval (course-scoped) ----------


@router.post("/courses/{course_id}/sources/search", response_model=RagSearchOut)
async def search_course_sources(
    course_id: str,
    body: RagSearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tìm đoạn tài liệu liên quan trong phạm vi khóa học (lexical+vector+RRF).

    Bảo mật: `course_id` phải thuộc user; `sourceIds` chỉ thu hẹp phạm vi và bị
    giao với các nguồn đã liên kết — không thể dùng để đọc nguồn của người khác.
    Không gọi LLM; không trả về chunk ngoài scope.
    """
    from app.services import rag_service, retrieval_service, source_service

    verify_csrf(request)
    rate_limit(request, "rag_search", limit=60, window_seconds=60)
    course = await course_service.get_owned_course(db, course_id, user.id)

    settings = get_settings()
    if not settings.rag_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "RAG_NOT_ENABLED",
                "message": "Tìm kiếm tài liệu (RAG) chưa được bật trên hệ thống này.",
            },
        )
    if not settings.embedding_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "EMBEDDING_NOT_CONFIGURED",
                "message": "Embedding chưa được cấu hình hợp lệ trên server.",
            },
        )

    linked = await source_service.list_course_sources(db, course.id, user.id)
    linked_ids = {source.id for _link, source in linked}
    requested: list = []
    for raw in body.sourceIds:
        source_uuid = source_service.parse_source_id(raw)
        if source_uuid is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_SOURCE_ID", "message": f"sourceId không hợp lệ: {raw[:40]}"},
            )
        requested.append(source_uuid)
    # Giao với nguồn đã liên kết: client KHÔNG mở rộng được phạm vi truy vấn.
    scope_ids = [sid for sid in requested if sid in linked_ids] if requested else None
    if requested and not scope_ids:
        return RagSearchOut(
            query=body.query,
            embeddingSpec="",
            items=[],
            total=0,
            insufficientEvidence=True,
            notice="Không có nguồn nào trong danh sách thuộc khóa học này.",
        )

    result = await retrieval_service.retrieve(
        db,
        course_id=course.id,
        user_id=user.id,
        query=body.query,
        source_ids=scope_ids,
        top_k=body.topK,
    )

    items = [
        RagChunkOut(
            chunkId=f"chk_{item.chunk_id}",
            sourceId=f"src_{item.source_id}",
            documentId=f"doc_{item.document_id}",
            pageNumber=item.page_number,
            charStart=item.char_start,
            charEnd=item.char_end,
            sectionAnchor=item.section_anchor,
            textHash=item.text_hash,
            sourceTitle=item.source_title,
            sourceVersion=item.source_version,
            sourceUrl=item.source_url,
            snippet=item.text[:400],
            lexicalRank=item.lexical_rank,
            vectorRank=item.vector_rank,
            similarity=round(item.similarity, 6) if item.vector_rank else None,
            rrfScore=round(item.rrf_score, 8),
        )
        for item in result.items
    ]
    notice = None
    if result.insufficient_evidence:
        notice = (
            "Không tìm thấy đoạn tài liệu nào đủ liên quan trong phạm vi khóa học. "
            "Đây là 'chưa đủ thông tin từ tài liệu', không phải khẳng định chủ đề không tồn tại."
        )
    return RagSearchOut(
        query=result.query,
        embeddingSpec=result.spec,
        items=items,
        total=len(items),
        insufficientEvidence=result.insufficient_evidence,
        notice=notice,
    )
