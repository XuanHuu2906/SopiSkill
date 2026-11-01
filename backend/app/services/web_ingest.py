"""P4.2 — ingest nguồn web/arXiv thành `SourceDocument` có provenance.

Luồng:
  1. `rights_confirmed` BẮT BUỘC (API đã chặn 422), lưu `rights_confirmed_at`.
  2. Fetch qua `url_fetcher` (allowlist + chống SSRF + robots + trần tài nguyên).
     arXiv: metadata Atom (defusedxml) + PDF qua cùng cổng.
  3. Ghi blob vào private storage (cùng `storage.py` của P4.0) với key ngẫu nhiên:
       - web  : JSON `{kind: web_text, version, text, sections, ...}` đã trích;
       - arxiv: bytes PDF.
  4. Tạo `SourceDocument` idempotent theo `(source, content_hash, pipeline)`.
     Với web, `content_hash` = hash(final_url + text) ⇒ fetch lại nội dung y hệt
     không tạo document/chunk trùng.
  5. Worker đọc blob theo `origin`, chunk bằng đúng pipeline của P4.0 (web dùng
     section provenance từ HTML) rồi `finish_ready` như cũ ⇒ embedding/RAG P4.1
     hoạt động không cần sửa gì.

Không log URL đầy đủ, không log nội dung tài liệu.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import Source, SourceDocument, SourceDocumentOrigin, SourceDocumentStatus
from app.services import arxiv_service, html_extract, ingest, storage as storage_module, url_fetcher

logger = logging.getLogger(__name__)

WEB_BLOB_KIND = "web_text"
WEB_BLOB_VERSION = 1

RIGHTS_CONFIRMATION_STATEMENT = (
    "Người dùng xác nhận có quyền sử dụng và ingest nội dung nguồn này cho mục đích học tập."
)


class WebIngestError(Exception):
    """Lỗi ingest web/arXiv, mã ổn định; có thể wrap lỗi fetch/extract."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass
class _PreparedContent:
    origin: SourceDocumentOrigin
    origin_url: str
    origin_meta: dict
    blob: bytes
    mime: str
    byte_size: int
    page_count: int
    content_hash: str
    title: str | None
    # Metadata để điền vào `Source` khi còn TRỐNG (không ghi đè dữ liệu người
    # dùng đã nhập). `None` = không có dữ liệu đáng tin.
    source_patch: dict = field(default_factory=dict)


def _require_rights(user_confirmed_rights: bool) -> None:
    if not user_confirmed_rights:
        raise WebIngestError(
            "USER_RIGHTS_NOT_CONFIRMED",
            "Bạn phải xác nhận có quyền sử dụng nội dung nguồn trước khi ingest.",
        )


def _as_web_error(exc: Exception) -> WebIngestError:
    if isinstance(exc, WebIngestError):
        return exc
    if isinstance(exc, url_fetcher.WebFetchError):
        return WebIngestError(exc.code, exc.message, retryable=exc.retryable)
    if isinstance(exc, arxiv_service.ArxivError):
        return WebIngestError(exc.code, exc.message, retryable=exc.retryable)
    if isinstance(exc, html_extract.HtmlExtractionError):
        return WebIngestError(exc.code, str(exc), retryable=False)
    return WebIngestError("WEB_INGEST_FAILED", "Không ingest được nguồn từ URL.")


def _canonical_url_for_storage(url: str) -> str:
    """Bỏ fragment + userinfo đã bị chặn; giữ query vì có thể xác định nội dung."""
    parts = url_fetcher.urlsplit(url)
    return url_fetcher.urlunsplit(
        (parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


async def prepare_web(
    url: str,
    *,
    settings: Settings | None = None,
    transport=None,
) -> _PreparedContent:
    cfg = settings or get_settings()
    resource = await url_fetcher.fetch_resource(url, kind="html", settings=cfg, transport=transport)
    html = url_fetcher.decode_html(resource.data, resource.content_type_header)
    extraction = html_extract.sanitize_extract(
        html, base_url=resource.final_url, max_chars=cfg.web_max_extracted_chars
    )
    if not extraction.text.strip():
        raise WebIngestError(
            "WEB_NO_EXTRACTABLE_TEXT",
            "Trang không có văn bản dùng được (có thể là JavaScript-only).",
        )

    canonical = _canonical_url_for_storage(resource.final_url)
    blob_payload = {
        "kind": WEB_BLOB_KIND,
        "version": WEB_BLOB_VERSION,
        "text": extraction.text,
        "title": extraction.title,
        "finalUrl": canonical,
        "requestedUrl": _canonical_url_for_storage(resource.requested_url),
        "retrievedAt": resource.retrieved_at.isoformat(),
        "sections": [
            {
                "heading": section.heading,
                "level": section.level,
                "charStart": section.char_start,
                "charEnd": section.char_end,
                "anchorId": section.anchor_id,
            }
            for section in extraction.sections
        ],
    }
    blob = json.dumps(blob_payload, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(
        (canonical + "\n" + extraction.text).encode("utf-8")
    ).hexdigest()
    return _PreparedContent(
        origin=SourceDocumentOrigin.web,
        origin_url=canonical,
        origin_meta={
            "requestedUrl": blob_payload["requestedUrl"],
            "finalUrl": canonical,
            "redirectChain": list(resource.redirect_chain),
            "httpStatus": resource.http_status,
            "contentType": resource.media_type,
            "title": extraction.title,
            "chars": extraction.char_count,
            "sectionCount": len(extraction.sections),
        },
        blob=blob,
        mime="application/vnd.sopiskill.web-text+json",
        byte_size=len(blob),
        page_count=1,
        content_hash=digest,
        title=extraction.title,
        source_patch={},
    )


async def prepare_arxiv(
    arxiv_id: str,
    *,
    settings: Settings | None = None,
    transport=None,
) -> _PreparedContent:
    cfg = settings or get_settings()
    paper = await arxiv_service.fetch_metadata(arxiv_id, settings=cfg, transport=transport)
    resource = await arxiv_service.fetch_pdf(paper.arxiv_id, settings=cfg, transport=transport)
    digest = hashlib.sha256(
        (paper.abs_url + "\n" + ingest.content_hash(resource.data)).encode("utf-8")
    ).hexdigest()
    # Đếm trang bằng đúng parser P4.0 để lỗi PDF hiện ra NGAY (không đợi worker).
    try:
        page_count = ingest.check_limits(
            resource.data,
            max_bytes=cfg.web_max_fetch_bytes,
            max_pages=cfg.source_max_pdf_pages,
        )
    except ingest.IngestError as exc:
        raise WebIngestError(exc.code, exc.message, retryable=exc.retryable) from exc

    return _PreparedContent(
        origin=SourceDocumentOrigin.arxiv,
        origin_url=_canonical_url_for_storage(paper.abs_url),
        origin_meta={
            "arxivId": paper.arxiv_id,
            "version": paper.version,
            "published": paper.published,
            "updated": paper.updated,
            "authors": paper.authors,
            "categories": paper.categories,
            "title": paper.title,
            "pdfUrl": paper.pdf_url,
            "httpStatus": resource.http_status,
            "redirectChain": list(resource.redirect_chain),
        },
        blob=resource.data,
        mime="application/pdf",
        byte_size=len(resource.data),
        page_count=page_count,
        content_hash=digest,
        title=paper.title,
        source_patch={
            "canonical_url": paper.abs_url,
            "version": paper.version,
            "publisher": "arXiv",
            "author": (", ".join(paper.authors[:5]) if paper.authors else None),
            "retrieved_at": datetime.now(UTC),
        },
    )


async def register_web_document(
    db: AsyncSession,
    source: Source,
    *,
    url: str | None = None,
    arxiv_id: str | None = None,
    user_confirmed_rights: bool,
    settings: Settings | None = None,
    transport=None,
) -> tuple[SourceDocument, bool]:
    """Fetch + lưu blob + tạo document (idempotent). Trả `(document, created)`."""
    _require_rights(user_confirmed_rights)
    cfg = settings or get_settings()
    if not cfg.web_ingest_enabled:
        raise WebIngestError(
            "WEB_INGEST_DISABLED", "Tính năng tải nội dung từ URL đang tắt trên server."
        )
    if not storage_module.storage_configured():
        raise storage_module.StorageNotConfigured(
            "Kho lưu trữ nguồn chưa được cấu hình trên server."
        )

    if bool(url) == bool(arxiv_id):
        raise WebIngestError(
            "WEB_REQUEST_INVALID", "Chọn đúng một trong hai: URL hoặc ID arXiv."
        )

    try:
        prepared = (
            await prepare_arxiv(arxiv_id, settings=cfg, transport=transport)
            if arxiv_id
            else await prepare_web(url or "", settings=cfg, transport=transport)
        )
    except Exception as exc:  # noqa: BLE001 — chuẩn hoá mã lỗi cho API/worker
        raise _as_web_error(exc) from exc

    pipeline = cfg.web_pipeline_version

    existing = (
        await db.execute(
            select(SourceDocument).where(
                SourceDocument.source_id == source.id,
                SourceDocument.content_hash == prepared.content_hash,
                SourceDocument.pipeline_version == pipeline,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    store = ingest._get_storage()
    key = storage_module.build_object_key(source.id)
    try:
        store.put(key, prepared.blob, content_type=prepared.mime)
    except storage_module.StorageError as exc:
        raise WebIngestError("STORAGE_UNAVAILABLE", "Kho lưu trữ tạm thời không sẵn sàng.", retryable=True) from exc

    document = SourceDocument(
        source_id=source.id,
        content_hash=prepared.content_hash,
        mime=prepared.mime,
        byte_size=prepared.byte_size,
        page_count=prepared.page_count,
        pipeline_version=pipeline,
        status=SourceDocumentStatus.queued,
        origin=prepared.origin,
        origin_url=prepared.origin_url,
        origin_meta=prepared.origin_meta,
        rights_confirmed_at=datetime.now(UTC),
        original_filename=(prepared.title or prepared.origin_url)[:120],
        storage_key=key,
        max_attempts=cfg.source_ingest_max_attempts,
    )
    db.add(document)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        try:
            store.delete(key)
        except storage_module.StorageError:
            logger.warning("web ingest duplicate blob cleanup failed source_id=%s", source.id)
        found = (
            await db.execute(
                select(SourceDocument).where(
                    SourceDocument.source_id == source.id,
                    SourceDocument.content_hash == prepared.content_hash,
                    SourceDocument.pipeline_version == pipeline,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise
        return found, False

    await db.refresh(document)
    changed = False
    if source.content_hash != prepared.content_hash:
        source.content_hash = prepared.content_hash
        changed = True
    # Metadata nguồn: CHỈ điền chỗ còn trống. Không ghi đè dữ liệu người dùng đã
    # nhập, và không suy ra `verification_status` từ việc fetch thành công.
    for attr, value in prepared.source_patch.items():
        if value is None:
            continue
        if getattr(source, attr, None) in (None, ""):
            setattr(source, attr, value)
            changed = True
    if changed:
        await db.commit()
        await db.refresh(document)

    logger.info(
        "web source document queued document_id=%s source_id=%s origin=%s bytes=%s",
        document.id,
        source.id,
        prepared.origin.value,
        prepared.byte_size,
    )
    return document, True


# ---------- worker-side parsing ----------


def parse_web_extraction(data: bytes) -> html_extract.HtmlExtraction:
    """Đọc blob JSON web-text; sai định dạng/lạc hậu ⇒ lỗi rõ, không đoán."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ingest.IngestError(
            "WEB_BLOB_INVALID", "Dữ liệu tài liệu web bị hỏng.", retryable=False
        ) from exc
    if not isinstance(payload, dict) or payload.get("kind") != WEB_BLOB_KIND:
        raise ingest.IngestError(
            "WEB_BLOB_INVALID", "Loại dữ liệu tài liệu web không được hỗ trợ."
        )
    if payload.get("version") != WEB_BLOB_VERSION:
        raise ingest.IngestError(
            "WEB_BLOB_VERSION_UNSUPPORTED",
            "Phiên bản dữ liệu tài liệu web không được hỗ trợ.",
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ingest.IngestError("WEB_NO_EXTRACTABLE_TEXT", "Tài liệu web không có văn bản.")

    sections: list[html_extract.HtmlSection] = []
    raw_sections = payload.get("sections") or []
    if isinstance(raw_sections, list):
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            heading = item.get("heading")
            if not isinstance(heading, str) or not heading.strip():
                continue
            try:
                start = int(item.get("charStart", 0))
                end = int(item.get("charEnd", 0))
                level = int(item.get("level", 1))
            except (TypeError, ValueError):
                continue
            anchor = item.get("anchorId")
            sections.append(
                html_extract.HtmlSection(
                    heading=heading.strip()[:120],
                    level=max(1, min(level, 6)),
                    char_start=max(0, min(start, len(text))),
                    char_end=max(0, min(end, len(text))),
                    anchor_id=anchor if isinstance(anchor, str) else None,
                )
            )
    return html_extract.HtmlExtraction(
        title=payload.get("title") if isinstance(payload.get("title"), str) else None,
        text=text,
        sections=sections,
        links=[],
    )


def chunk_web_extraction(
    extraction: html_extract.HtmlExtraction,
    *,
    target_chars: int | None = None,
) -> list[ingest.ChunkDraft]:
    """Chunk văn bản web theo section, giữ offset tuyệt đối + heading làm anchor.

    Không overlap; phủ kín toàn bộ text (section không phủ hết thì phần trống
    được gom vào section kế tiếp / section tổng) ⇒ citation không rơi vào vùng
    không có chunk.
    """
    cfg = get_settings()
    target = max(200, target_chars or cfg.source_chunk_target_chars)
    text = extraction.text
    if not text.strip():
        return []

    spans: list[tuple[int, int, str | None]] = []
    cursor = 0
    for section in sorted(extraction.sections, key=lambda s: s.char_start):
        start = max(cursor, min(section.char_start, len(text)))
        end = max(start, min(section.char_end, len(text)))
        if end <= start:
            continue
        if start > cursor:
            spans.append((cursor, start, None))
        spans.append((start, end, section.heading))
        cursor = end
    if cursor < len(text):
        spans.append((cursor, len(text), None))

    drafts: list[ingest.ChunkDraft] = []
    for start, end, heading in spans:
        cursor = start
        while cursor < end:
            limit = min(cursor + target, end)
            if limit < end:
                window = text[cursor:limit]
                cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
                if cut > target // 2:
                    limit = cursor + cut + 1
            body = text[cursor:limit]
            if " ".join(body.split()):
                drafts.append(
                    ingest.ChunkDraft(
                        page_number=1,
                        char_start=cursor,
                        char_end=limit,
                        section_anchor=heading,
                        text=body,
                    )
                )
            cursor = limit
    return drafts


def build_extracted_pages(extraction: html_extract.HtmlExtraction) -> list[ingest.ExtractedPage]:
    return [ingest.ExtractedPage(page_number=1, text=extraction.text)]


def storage_key_prefix(source_id: uuid.UUID) -> str:
    return f"sources/{source_id}/"
