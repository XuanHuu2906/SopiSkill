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
"""

from __future__ import annotations

import logging
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
        return (
            CitationValidationStatus.unverified,
            ["Đã có nội dung nguồn nhưng P3.0 chưa có chunk store để đối chiếu locator."],
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
