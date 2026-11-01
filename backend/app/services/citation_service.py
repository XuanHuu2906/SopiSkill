"""Citation & Evidence contract (P3.0) — kiểm tra locator, không tự "verified".

Bốn mức KHÁC NHAU, không được gộp:
  1. Metadata verified      — nguồn (title/publisher/version) đã được review.
  2. Locator verified       — chunk/page/section được cite CÓ THẬT trong nguồn.
  3. Evidence supports claim— đoạn evidence thực sự chống lưng cho câu trong bài.
  4. Claim corroborated     — claim được nguồn ĐỘC LẬP khác xác nhận.

P3.0 chỉ có metadata nguồn (chưa ingest nội dung), vì vậy:
  - Không có bảng chunk/page ⇒ locator không thể verify ⇒ status `unavailable`.
  - Không có so khớp ngữ nghĩa ⇒ KHÔNG BAO GIỜ tự đặt `evidence_supported`.
  - Model KHÔNG được cấp `sourceId`: citation chỉ do server tạo từ nguồn đã liên
    kết, nên không thể bịa source id từ output LLM.

P4.0 thêm chunk store nhưng CHƯA có retrieval/locator: có nội dung đã ingest chỉ
làm citation chuyển từ `unavailable` sang `unverified` (kèm lý do thật), tuyệt
đối không nhảy lên `locator_verified`/`evidence_supported`.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CitationValidationStatus,
    Course,
    Lesson,
    LessonCitation,
    Source,
    SourceVisibility,
)
from app.schemas.schemas import CitationOut

logger = logging.getLogger(__name__)

MAX_CITATIONS_PER_LESSON = 12


class CitationContractError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})


def _normalize_locator(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def validate_citation_locator(
    source: Source,
    *,
    source_version: str | None = None,
    chunk_id: str | None = None,
    page_number: int | None = None,
    section_anchor: str | None = None,
    evidence_text: str | None = None,
    has_ingested_content: bool = False,
) -> tuple[CitationValidationStatus, list[str]]:
    """Trả (status, lý do). Không mutate nguồn, không gọi LLM, không đoán.

    Quy tắc:
      - source_version lệch bản hiện tại ⇒ `source_changed` (citation cũ không âm
        thầm trỏ sang phiên bản mới).
      - Có locator nhưng nguồn chưa ingest nội dung ⇒ `unavailable`.
      - Có locator + đã ingest: P3.0 chưa có chunk store để so ⇒ `unverified`
        kèm lý do "chưa đối chiếu locator"; nâng lên `locator_verified` chỉ khi
        có hàm kiểm tra thực (P4).
      - Không có locator ⇒ `unverified` (evidence text một mình không chứng minh).
      - Tuyệt đối không trả `evidence_supported`/`corroborated`.
    """
    reasons: list[str] = []

    if page_number is not None and page_number < 1:
        return CitationValidationStatus.rejected, ["pageNumber phải >= 1."]

    version = _normalize_locator(source_version)
    if version is not None and source.version is not None and version != source.version:
        return (
            CitationValidationStatus.source_changed,
            [f"Citation trỏ version '{version}' nhưng nguồn hiện tại là '{source.version}'."],
        )

    has_locator = any(
        _normalize_locator(v) is not None
        for v in (chunk_id, section_anchor)
    ) or page_number is not None

    if has_locator and not has_ingested_content:
        return (
            CitationValidationStatus.unavailable,
            ["Nguồn chưa ingest nội dung ⇒ chưa thể xác minh chunk/page/anchor."],
        )

    if has_locator and has_ingested_content:
        # P4.0 ĐÃ có chunk store, nhưng citation vẫn chưa được đối chiếu với chunk
        # nào (list_lesson_citations tạo citation từ registry, không từ retrieval).
        # Vì vậy CHỈ `unverified` — nâng lên `locator_verified` đòi hỏi kiểm tra thật
        # rằng chunk/page/anchor tồn tại và thuộc nguồn (P4.1).
        return (
            CitationValidationStatus.unverified,
            [
                "Nguồn đã có nội dung ingest, nhưng citation này chưa được đối chiếu "
                "với chunk cụ thể ⇒ chưa phải locator_verified."
            ],
        )

    reasons.append("Không có locator (chunk/page/anchor) ⇒ không thể xác minh vị trí.")
    if evidence_text:
        reasons.append("evidenceText không được đối chiếu với nguồn ở P3.0.")
    return CitationValidationStatus.unverified, reasons


async def replace_lesson_citations(
    db: AsyncSession,
    lesson: Lesson,
    course: Course,
    sources: list[Source],
    *,
    evidence_by_source: dict[uuid.UUID, str] | None = None,
    has_ingested_content: bool = False,
) -> list[LessonCitation]:
    """Tạo lại citation cho bài học từ danh sách nguồn đã liên kết (server-side).

    Server tự chọn nguồn & snapshot version; không có input citation từ client hay
    LLM. `evidence_by_source` chỉ chứa đoạn text THẬT lấy từ nguồn đã ingest (P4);
    ở P3.0 mặc định rỗng ⇒ mọi citation là `unverified`/`unavailable`.
    """
    await db.execute(delete(LessonCitation).where(LessonCitation.lesson_id == lesson.id))

    citations: list[LessonCitation] = []
    for source in sources[:MAX_CITATIONS_PER_LESSON]:
        evidence = (evidence_by_source or {}).get(source.id)
        status_value, _reasons = validate_citation_locator(
            source,
            source_version=source.version,
            evidence_text=evidence,
            has_ingested_content=has_ingested_content,
        )
        citation = LessonCitation(
            lesson_id=lesson.id,
            source_id=source.id,
            source_version=source.version,
            chunk_id=None,
            page_number=None,
            section_anchor=None,
            evidence_text=evidence,
            validation_status=status_value,
        )
        db.add(citation)
        citations.append(citation)

    return citations


async def list_lesson_citations(
    db: AsyncSession, lesson: Lesson, user_id: uuid.UUID
) -> list[tuple[LessonCitation, Source]]:
    """Citation của bài học, chỉ kèm nguồn user hiện tại còn quyền xem."""
    rows = (
        await db.execute(
            select(LessonCitation, Source)
            .join(Source, Source.id == LessonCitation.source_id)
            .where(
                LessonCitation.lesson_id == lesson.id,
                (Source.visibility == SourceVisibility.public) | (Source.owner_id == user_id),
            )
            .order_by(LessonCitation.created_at.asc())
        )
    ).all()
    return [(citation, source) for citation, source in rows]


def to_citation_out(citation: LessonCitation, source: Source) -> CitationOut:
    return CitationOut(
        citationId=f"cit_{citation.id}",
        sourceId=f"src_{source.id}",
        sourceVersion=citation.source_version,
        chunkId=citation.chunk_id,
        pageNumber=citation.page_number,
        sectionAnchor=citation.section_anchor,
        evidenceText=citation.evidence_text,
        validationStatus=citation.validation_status.value,
        sourceTitle=source.title,
        sourceUrl=source.canonical_url,
        sourceVerificationStatus=source.verification_status.value,
    )


# ---------------------------------------------------------------------------
# P4.1 — citation verification cho câu trả lời tutor dựa trên retrieval
# ---------------------------------------------------------------------------

# Model chỉ được trích `[chk_<uuid>]`. Chấp nhận biến thể có/không ngoặc vuông,
# và id trần chk_... để không phụ thuộc định dạng quá chặt.
_CITATION_PATTERN = re.compile(
    r"\[?(chk_([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}))\]?"
)

MAX_VERIFIED_CITATIONS = 8


def extract_citation_ids(answer: str) -> list[uuid.UUID]:
    """Id chunk model đã nêu trong câu trả lời, theo thứ tự xuất hiện, đã dedupe."""
    seen: list[uuid.UUID] = []
    for match in _CITATION_PATTERN.finditer(answer or ""):
        try:
            chunk_uuid = uuid.UUID(match.group(2))
        except ValueError:
            continue
        if chunk_uuid not in seen:
            seen.append(chunk_uuid)
    return seen


def verify_answer_citations(
    answer: str,
    *,
    retrieved: list,
    max_citations: int = MAX_VERIFIED_CITATIONS,
) -> tuple[list[dict], list[uuid.UUID]]:
    """Đối chiếu id model nêu với ĐÚNG danh sách retrieval của request này.

    Trả `(citations, rejected_ids)`:

      - `citations`: mỗi dict chứa chunkId/sourceId/page/offset/textHash + đoạn
        trích THẬT lấy từ chunk đã retrieve; status `locator_verified` vì vị trí
        đã đối chiếu được (KHÔNG hàm ý claim được chứng minh).
      - `rejected_ids`: id model bịa hoặc ngoài allowlist — chỉ dùng để log/eval,
        không bao giờ trả về client và không bao giờ làm hỏng câu trả lời.

    Không truy vấn DB: danh sách `retrieved` đã bị scope theo owner/course ở
    `retrieval_service`, nên id ngoài danh sách đó không thể là dữ liệu hợp lệ.
    """
    allowed = {item.chunk_id: item for item in retrieved}
    citations: list[dict] = []
    rejected: list[uuid.UUID] = []

    for chunk_id in extract_citation_ids(answer):
        item = allowed.get(chunk_id)
        if item is None:
            rejected.append(chunk_id)
            continue
        if len(citations) >= max(1, max_citations):
            rejected.append(chunk_id)
            continue
        citations.append(
            {
                "chunkId": f"chk_{item.chunk_id}",
                "sourceId": f"src_{item.source_id}",
                "documentId": f"doc_{item.document_id}",
                "pageNumber": item.page_number,
                "charStart": item.char_start,
                "charEnd": item.char_end,
                "sectionAnchor": item.section_anchor,
                "textHash": item.text_hash,
                "sourceTitle": item.source_title,
                # P4.2 — URL gốc cho tài liệu web/arXiv (None cho PDF upload).
                "sourceUrl": getattr(item, "source_url", None),
                "sourceVersion": item.source_version,
                "evidenceText": item.text[:600],
                "validationStatus": CitationValidationStatus.locator_verified.value,
                # P4.1: đã xác minh VỊ TRÍ, chưa xác minh claim ⇒ luôn False ở đây.
                "evidenceSupported": False,
            }
        )

    return citations, rejected


def unverified_source_pointers(retrieved: list, *, max_items: int = 5) -> list[dict]:
    """Nguồn đã truy xuất nhưng model KHÔNG trích — hiển thị riêng, không verified.

    Dùng khi câu trả lời không có citation hợp lệ: UI cần thấy "đã tìm thấy đoạn
    này nhưng chưa được dẫn" thay vì im lặng hoặc tô hồng.
    """
    pointers: list[dict] = []
    for item in retrieved[: max(0, max_items)]:
        pointers.append(
            {
                "chunkId": f"chk_{item.chunk_id}",
                "sourceId": f"src_{item.source_id}",
                "sourceTitle": item.source_title,
                "sourceUrl": getattr(item, "source_url", None),
                "pageNumber": item.page_number,
                "sectionAnchor": item.section_anchor,
                "validationStatus": CitationValidationStatus.unverified.value,
                "evidenceSupported": False,
            }
        )
    return pointers
