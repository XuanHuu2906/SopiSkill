"""PDF ingestion service (P4.0) — validate, extract text, chunk, provenance.

Nguyên tắc:
  - **Không tin client**: extension/Content-Type không chứng minh gì. Chỉ chấp nhận
    file bắt đầu bằng magic `%PDF-`; page count/size bị giới hạn cứng; file mã
    hoá/corrupt bị từ chối với mã lỗi ổn định.
  - **Không OCR** ở P4.0. PDF scan (không có text layer) ⇒ trạng thái `no_text`,
    không bịa nội dung và không đánh dấu `ready`.
  - **Provenance thật**: mỗi chunk giữ `page_number` + offset ký tự trong text
    của trang + `text_hash`. Không overlap giữa chunk để citation không mơ hồ.
  - **Idempotent** theo `(source_id, content_hash, pipeline_version)`: retry không
    tạo document/chunk trùng; chunk được thay thế theo `document_id` trong một
    transaction.
  - **Không log nội dung**: log chỉ id/kích thước/số trang/mã lỗi.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Source, SourceChunk, SourceDocument, SourceDocumentStatus, SourceVisibility
from app.services import storage as storage_module

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
UNTRUSTED_OPEN = "<<<NGUON_BAT_DAU>>>"
UNTRUSTED_CLOSE = "<<<NGUON_KET_THUC>>>"


class IngestError(Exception):
    """Lỗi ingest có mã ổn định + thông điệp an toàn cho người dùng."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass
class ExtractedPage:
    page_number: int
    text: str


@dataclass
class ChunkDraft:
    page_number: int
    char_start: int
    char_end: int
    section_anchor: str | None
    text: str


@dataclass
class ExtractionResult:
    page_count: int
    pages: list[ExtractedPage]

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


# ---------- validation ----------


def validate_pdf_header(data: bytes) -> None:
    if not data:
        raise IngestError("EMPTY_FILE", "File rỗng.")
    head = data[:1024].lstrip(b"\xef\xbb\xbf \r\n\t")
    if not head.startswith(PDF_MAGIC):
        raise IngestError(
            "INVALID_PDF_MIME",
            "File không phải PDF hợp lệ (thiếu chữ ký %PDF-).",
        )


def _open_reader(data: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except PdfReadError as exc:
        raise IngestError("CORRUPT_PDF", "PDF bị hỏng hoặc không đọc được.") from exc
    except Exception as exc:  # noqa: BLE001 — parser lỗi lạ cũng phải fail an toàn
        raise IngestError("CORRUPT_PDF", "PDF bị hỏng hoặc không đọc được.") from exc

    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception:  # noqa: BLE001
            unlocked = 0
        if not unlocked:
            raise IngestError(
                "ENCRYPTED_PDF",
                "PDF được bảo vệ bằng mật khẩu; hãy upload bản không mã hoá.",
            )
    return reader


def check_limits(data: bytes, *, max_bytes: int | None = None, max_pages: int | None = None) -> int:
    """Kiểm tra size + header + page count. Trả page count. Không trích text."""
    settings = get_settings()
    max_bytes = max_bytes if max_bytes is not None else settings.source_max_pdf_bytes
    max_pages = max_pages if max_pages is not None else settings.source_max_pdf_pages

    if len(data) > max_bytes:
        raise IngestError(
            "PDF_TOO_LARGE", f"PDF vượt giới hạn {max_bytes} bytes."
        )
    validate_pdf_header(data)
    reader = _open_reader(data)
    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise IngestError("CORRUPT_PDF", "PDF bị hỏng hoặc không đọc được.") from exc
    if page_count == 0:
        raise IngestError("EMPTY_PDF", "PDF không có trang nào.")
    if page_count > max_pages:
        raise IngestError(
            "TOO_MANY_PAGES", f"PDF có {page_count} trang, vượt giới hạn {max_pages}."
        )
    return page_count


# ---------- extraction ----------


def extract_pages(data: bytes) -> ExtractionResult:
    """Trích text theo trang (native text layer). Không OCR, không sửa nội dung."""
    reader = _open_reader(data)
    pages: list[ExtractedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — một trang lỗi không làm hỏng cả tài liệu
            raw = ""
        pages.append(ExtractedPage(page_number=index, text=raw))

    result = ExtractionResult(page_count=len(pages), pages=pages)
    if not result.has_text:
        raise IngestError(
            "NO_EXTRACTABLE_TEXT",
            "PDF không có lớp text (có thể là bản scan). OCR chưa được bật ở giai đoạn này.",
        )
    return result


# ---------- chunking ----------

_HEADING_MAX_CHARS = 80
_HEADING_MAX_WORDS = 12


def _looks_like_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > _HEADING_MAX_CHARS:
        return False
    if len(text.split()) > _HEADING_MAX_WORDS:
        return False
    if text.endswith((".", ",", ";", "!", "?")):
        return False
    return any(ch.isalpha() for ch in text)


@dataclass
class _Block:
    start: int
    end: int
    heading: str | None


def _split_blocks(page_text: str) -> list[_Block]:
    """Chia trang thành block theo dòng trống, giữ offset chính xác trong page text."""
    blocks: list[_Block] = []
    offset = 0
    current_start: int | None = None
    current_lines: list[str] = []
    heading: str | None = None

    def flush(end_offset: int) -> None:
        nonlocal current_start, current_lines, heading
        if current_start is not None and current_lines:
            blocks.append(_Block(current_start, end_offset, heading))
        current_start = None
        current_lines = []
        heading = None

    for line in page_text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            flush(offset)
        else:
            if current_start is None:
                current_start = offset
                if _looks_like_heading(stripped):
                    heading = stripped[:_HEADING_MAX_CHARS]
            current_lines.append(line)
        offset += len(line)
    flush(offset)
    return blocks


def _normalize(text: str) -> str:
    return " ".join(text.split())


def chunk_pages(
    pages: list[ExtractedPage],
    *,
    target_chars: int | None = None,
    min_chars: int | None = None,
) -> list[ChunkDraft]:
    """Chunk theo trang, không overlap, giữ heading gần nhất làm `section_anchor`."""
    settings = get_settings()
    target = max(200, target_chars or settings.source_chunk_target_chars)
    minimum = max(0, min_chars if min_chars is not None else settings.source_chunk_min_chars)
    hard_limit = target * 2

    drafts: list[ChunkDraft] = []
    for page in pages:
        if not page.text.strip():
            continue
        blocks = _split_blocks(page.text)
        if not blocks:
            continue

        pending: list[_Block] = []
        pending_len = 0
        anchor: str | None = None

        def emit() -> None:
            nonlocal pending, pending_len, anchor
            if not pending:
                return
            start = pending[0].start
            end = pending[-1].end
            raw = page.text[start:end]
            if _normalize(raw):
                drafts.append(
                    ChunkDraft(
                        page_number=page.page_number,
                        char_start=start,
                        char_end=end,
                        section_anchor=anchor,
                        text=raw,
                    )
                )
            pending = []
            pending_len = 0
            anchor = None

        for block in blocks:
            block_len = block.end - block.start
            if anchor is None and block.heading:
                anchor = block.heading
            # Block quá dài một mình: cắt theo dòng để chunk không vượt hard limit.
            if block_len > hard_limit:
                emit()
                for span_start, span_end in _split_long_block(
                    page.text, block.start, block.end, target
                ):
                    if _normalize(page.text[span_start:span_end]):
                        drafts.append(
                            ChunkDraft(
                                page_number=page.page_number,
                                char_start=span_start,
                                char_end=span_end,
                                section_anchor=block.heading,
                                text=page.text[span_start:span_end],
                            )
                        )
                continue

            if pending and pending_len + block_len > target:
                emit()
            if anchor is None and block.heading:
                anchor = block.heading
            pending.append(block)
            pending_len += block_len
            if pending_len >= target:
                emit()

        if pending:
            emit()

    return _merge_tiny_chunks(drafts, pages=pages, minimum=minimum)


def _split_long_block(
    page_text: str, start: int, end: int, target: int
) -> list[tuple[int, int]]:
    """Cắt một block quá dài thành span ≤ ~target, ưu tiên ranh giới dòng/câu.

    Trả danh sách `(start, end)` là offset tuyệt đối trong text của trang; các span
    không overlap và nối lại phủ đúng [start, end).
    """
    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        limit = min(cursor + target, end)
        if limit < end:
            window = page_text[cursor:limit]
            # Ưu tiên xuống dòng, rồi tới khoảng trắng để không cắt giữa từ.
            cut = window.rfind("\n")
            if cut < target // 2:
                cut = max(window.rfind(" "), window.rfind("\t"))
            if cut > 0:
                limit = cursor + cut + 1
        spans.append((cursor, limit))
        cursor = limit
    return spans


def _merge_tiny_chunks(
    drafts: list[ChunkDraft], *, pages: list[ExtractedPage], minimum: int
) -> list[ChunkDraft]:
    """Gộp chunk quá ngắn vào chunk liền trước CÙNG TRANG (không gộp xuyên trang).

    Tránh chunk 1–2 dòng gây citation mơ hồ; offset của chunk gộp vẫn liên tục
    trong text của trang (lấy lại đúng substring, không nối chuỗi thủ công).
    """
    page_text_by_number = {page.page_number: page.text for page in pages}
    merged: list[ChunkDraft] = []
    for draft in drafts:
        if (
            merged
            and len(_normalize(draft.text)) < minimum
            and merged[-1].page_number == draft.page_number
        ):
            previous = merged[-1]
            start = min(previous.char_start, draft.char_start)
            end = max(previous.char_end, draft.char_end)
            page_text = page_text_by_number[previous.page_number]
            merged[-1] = ChunkDraft(
                page_number=previous.page_number,
                char_start=start,
                char_end=end,
                section_anchor=previous.section_anchor,
                text=page_text[start:end],
            )
            continue
        merged.append(draft)
    return merged


def text_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wrap_untrusted(text: str) -> str:
    """Bọc nội dung nguồn như dữ liệu KHÔNG tin cậy (P4.1 dùng khi đưa vào prompt)."""
    return f"{UNTRUSTED_OPEN}\n{text}\n{UNTRUSTED_CLOSE}"


# ---------- persistence ----------


def _get_storage() -> storage_module.Storage:
    """Indirection để test patch được storage (không gọi network trong pytest)."""
    return storage_module.get_storage()


async def get_owned_document(
    db: AsyncSession, document_id: str, user_id: uuid.UUID
) -> tuple[SourceDocument, Source]:
    """Document + source, chỉ khi source thuộc user hoặc public. Sai ⇒ 404."""
    raw = (document_id or "").strip()
    for prefix in ("doc_",):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    try:
        did = uuid.UUID(raw)
    except (ValueError, TypeError):
        raise _document_not_found() from None

    row = (
        await db.execute(
            select(SourceDocument, Source)
            .join(Source, Source.id == SourceDocument.source_id)
            .where(
                SourceDocument.id == did,
                (Source.visibility == SourceVisibility.public) | (Source.owner_id == user_id),
            )
        )
    ).first()
    if row is None:
        raise _document_not_found()
    return row[0], row[1]


def _document_not_found() -> IngestError:
    return IngestError("SOURCE_DOCUMENT_NOT_FOUND", "Tài liệu không tồn tại hoặc không thuộc quyền của bạn.")


async def list_documents_for_source(
    db: AsyncSession, source_id: uuid.UUID
) -> list[SourceDocument]:
    rows = (
        await db.execute(
            select(SourceDocument)
            .where(SourceDocument.source_id == source_id)
            .order_by(SourceDocument.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def source_has_content(db: AsyncSession, source_id: uuid.UUID) -> bool:
    """True nếu nguồn có ít nhất một document `ready` (có chunk text thật).

    Chỉ dùng để đánh giá mức dữ liệu hiện có; KHÔNG dùng để chuyển citation sang
    `locator_verified` — việc đó cần retrieval/đối chiếu locator (P4.1).
    """
    row = (
        await db.execute(
            select(SourceDocument.id)
            .where(
                SourceDocument.source_id == source_id,
                SourceDocument.status == SourceDocumentStatus.ready,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def latest_document(db: AsyncSession, source_id: uuid.UUID) -> SourceDocument | None:
    return (
        await db.execute(
            select(SourceDocument)
            .where(SourceDocument.source_id == source_id)
            .order_by(SourceDocument.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def register_document(
    db: AsyncSession,
    source: Source,
    *,
    data: bytes,
    filename: str | None,
    content_type: str | None = None,
) -> tuple[SourceDocument, bool]:
    """Lưu file vào private storage + tạo document row (idempotent theo hash).

    Trả `(document, created)`. Upload trùng bytes/pipeline trả document cũ và
    xóa object vừa ghi để không để rác trong storage.
    """
    settings = get_settings()
    if not storage_module.storage_configured():
        raise storage_module.StorageNotConfigured(
            "Kho lưu trữ nguồn chưa được cấu hình trên server."
        )

    page_count = check_limits(
        data,
        max_bytes=settings.source_max_pdf_bytes,
        max_pages=settings.source_max_pdf_pages,
    )
    digest = content_hash(data)
    pipeline = settings.source_pipeline_version

    existing = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.source_id == source.id,
                SourceDocument.content_hash == digest,
                SourceDocument.pipeline_version == pipeline,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    store = _get_storage()
    key = storage_module.build_object_key(source.id)
    safe_name = storage_module.sanitize_filename(filename)
    # MIME ghi vào storage luôn là PDF: đây là kết quả sau khi đã xác minh magic,
    # không phải Content-Type client gửi.
    store.put(key, data, content_type="application/pdf")

    document = SourceDocument(
        source_id=source.id,
        content_hash=digest,
        mime="application/pdf",
        byte_size=len(data),
        page_count=page_count,
        pipeline_version=pipeline,
        status=SourceDocumentStatus.queued,
        original_filename=safe_name,
        storage_key=key,
        max_attempts=settings.source_ingest_max_attempts,
    )
    db.add(document)
    try:
        await db.commit()
    except IntegrityError:
        # Race: request khác đã tạo cùng (source, hash, pipeline).
        await db.rollback()
        store.delete(key)
        found = (
            await db.execute(
                select(SourceDocument).where(
                    SourceDocument.source_id == source.id,
                    SourceDocument.content_hash == digest,
                    SourceDocument.pipeline_version == pipeline,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise
        return found, False

    await db.refresh(document)
    # `content_hash` trên source là móc nối P3.0 → P4: chỉ cập nhật khi có nội
    # dung thật, không suy ra verification status.
    if source.content_hash != digest:
        source.content_hash = digest
        await db.commit()
        await db.refresh(document)

    logger.info(
        "source document queued document_id=%s source_id=%s bytes=%s pages=%s",
        document.id,
        source.id,
        len(data),
        page_count,
    )
    return document, True


# ---------- worker state machine ----------


def _lease_deadline(seconds: int | None = None) -> datetime:
    settings = get_settings()
    return datetime.now(UTC) + timedelta(
        seconds=seconds if seconds is not None else settings.source_ingest_lease_seconds
    )


async def claim_document(db: AsyncSession, document_id: uuid.UUID) -> SourceDocument | None:
    """Claim nguyên tử: chỉ một worker giữ một document tại một thời điểm."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(SourceDocument)
        .where(
            SourceDocument.id == document_id,
            SourceDocument.status.in_((SourceDocumentStatus.queued,)),
            SourceDocument.attempts_count < SourceDocument.max_attempts,
        )
        .values(
            status=SourceDocumentStatus.extracting,
            lease_expires_at=_lease_deadline(),
            heartbeat_at=now,
            attempts_count=SourceDocument.attempts_count + 1,
            dispatched_at=datetime.now(UTC),
        )
        .returning(SourceDocument.id)
    )
    claimed = result.scalar_one_or_none()
    if claimed is None:
        await db.rollback()
        return None
    await db.commit()
    return (
        await db.execute(select(SourceDocument).where(SourceDocument.id == claimed))
    ).scalar_one()


async def renew_lease(db: AsyncSession, document_id: uuid.UUID) -> bool:
    result = await db.execute(
        update(SourceDocument)
        .where(
            SourceDocument.id == document_id,
            SourceDocument.status == SourceDocumentStatus.extracting,
        )
        .values(heartbeat_at=datetime.now(UTC), lease_expires_at=_lease_deadline())
        .returning(SourceDocument.id)
    )
    return result.scalar_one_or_none() is not None


async def finish_ready(
    db: AsyncSession,
    document: SourceDocument,
    pages: list[ExtractedPage],
    drafts: list[ChunkDraft],
) -> None:
    """Ghi chunks + trạng thái ready trong một transaction (idempotent theo doc)."""
    # Retry/ingest lại cùng document ⇒ thay chunk cũ, không nhân bản.
    await db.execute(delete(SourceChunk).where(SourceChunk.document_id == document.id))
    for index, draft in enumerate(drafts):
        db.add(
            SourceChunk(
                document_id=document.id,
                source_id=document.source_id,
                chunk_index=index,
                page_number=draft.page_number,
                char_start=draft.char_start,
                char_end=draft.char_end,
                section_anchor=draft.section_anchor,
                text=draft.text,
                text_hash=text_hash(draft.text),
            )
        )
    document.status = SourceDocumentStatus.ready
    document.page_count = len(pages)
    document.error_code = None
    document.error = None
    document.lease_expires_at = None
    document.heartbeat_at = datetime.now(UTC)
    document.ingested_at = datetime.now(UTC)
    await db.commit()


async def finish_no_text(db: AsyncSession, document: SourceDocument) -> None:
    await db.execute(delete(SourceChunk).where(SourceChunk.document_id == document.id))
    document.status = SourceDocumentStatus.no_text
    document.error_code = "NO_EXTRACTABLE_TEXT"
    document.error = {
        "code": "NO_EXTRACTABLE_TEXT",
        "message": "PDF không có lớp text (có thể là bản scan). OCR chưa được bật.",
        "retryable": False,
    }
    document.lease_expires_at = None
    document.heartbeat_at = datetime.now(UTC)
    await db.commit()


async def fail_document(
    db: AsyncSession, document: SourceDocument | uuid.UUID, error: IngestError | BaseException
) -> str:
    """Phân loại lỗi → requeue (bounded) hoặc failed. Trả 'queued'|'failed'."""
    doc = document
    if isinstance(doc, uuid.UUID):
        doc = (
            await db.execute(select(SourceDocument).where(SourceDocument.id == doc))
        ).scalar_one_or_none()
        if doc is None:
            return "failed"

    if isinstance(error, IngestError):
        code, message, retryable = error.code, error.message, error.retryable
    else:
        code = "INGEST_FAILED"
        message = type(error).__name__
        retryable = True

    if retryable and doc.attempts_count < doc.max_attempts:
        doc.status = SourceDocumentStatus.queued
        doc.lease_expires_at = None
        doc.heartbeat_at = None
        doc.dispatched_at = None
        doc.error_code = code
        doc.error = {"code": code, "message": message, "retryable": True}
        await db.commit()
        return "queued"

    doc.status = SourceDocumentStatus.failed
    doc.error_code = code
    doc.error = {"code": code, "message": message, "retryable": False}
    doc.lease_expires_at = None
    doc.heartbeat_at = datetime.now(UTC)
    await db.commit()
    return "failed"


async def delete_source_documents(db: AsyncSession, source: Source) -> int:
    """Xóa document/chunk của nguồn + object storage (best-effort). Trả số document."""
    documents = await list_documents_for_source(db, source.id)
    if not documents:
        return 0
    await db.execute(delete(SourceChunk).where(SourceChunk.source_id == source.id))
    await db.execute(delete(SourceDocument).where(SourceDocument.source_id == source.id))
    await db.commit()

    if storage_module.storage_configured():
        try:
            _get_storage().delete_prefix(f"sources/{source.id}/")
        except storage_module.StorageError as exc:
            logger.warning(
                "source storage cleanup failed source_id=%s code=%s", source.id, exc.code
            )
    logger.info("source documents deleted source_id=%s count=%s", source.id, len(documents))
    return len(documents)


# ---------- quality helpers cho API ----------


_WS = re.compile(r"\s+")


def normalize_preview(text: str, limit: int = 200) -> str:
    """Preview ngắn cho API — chỉ dùng cho hiển thị, không phải bằng chứng."""
    return _WS.sub(" ", text).strip()[:limit]
