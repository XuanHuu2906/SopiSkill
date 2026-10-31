"""Source context assembly (P3.0) — pure, deterministic, honest labelling.

Vai trò: dựng `SourceContextEntry` gửi cho provider và quyết định `LessonGrounding`
cho bài học. Hàm thuần để test dễ và để worker không tự diễn giải metadata.

Quy tắc trung thực (quan trọng hơn "trông có vẻ grounded"):
  - `source_grounded` CHỈ khi có ít nhất một nguồn cung cấp **đoạn bằng chứng thật**
    (excerpt lấy từ nội dung đã ingest). Metadata (title/publisher/URL) không đủ.
  - P3.0 chưa có ingestion ⇒ `excerpt_provider` trả None ⇒ mọi bài học là
    `general_ai_knowledge` dù course có nguồn liên kết. Citation vẫn được ghi để
    truy vết nhưng luôn `unverified`/`unavailable`.
  - Không suy ra excerpt từ title/LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from app.models import CourseSource, LessonGrounding, Source
from app.schemas.schemas import SourceContextEntry

MAX_CONTEXT_SOURCES = 8


def clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    clean = " ".join(str(text).split())
    return clean[:limit] if clean else None


def build_source_context(
    linked: Iterable[tuple[CourseSource, Source]],
    *,
    excerpt_provider: Callable[[Source], str | None] | None = None,
    max_sources: int = MAX_CONTEXT_SOURCES,
) -> list[SourceContextEntry]:
    """Metadata-only context. `excerpt_provider` là điểm nối P4 (RAG chunk → excerpt)."""
    entries: list[SourceContextEntry] = []
    for _link, source in list(linked)[:max_sources]:
        excerpt = excerpt_provider(source) if excerpt_provider else None
        entries.append(
            SourceContextEntry(
                sourceId=f"src_{source.id}",
                title=clip(source.title, 200) or source.title[:200],
                publisher=clip(source.publisher, 120),
                canonicalUrl=source.canonical_url,
                sourceVersion=source.version,
                verificationStatus=source.verification_status.value,
                excerpt=clip(excerpt, 1200) if excerpt else None,
            )
        )
    return entries


def lesson_grounding(context: list[SourceContextEntry] | None) -> LessonGrounding:
    """`source_grounded` chỉ khi thật sự có đoạn nguồn; metadata đơn thuần không đủ."""
    if context and any(entry.excerpt for entry in context):
        return LessonGrounding.source_grounded
    return LessonGrounding.general_ai_knowledge


def grounding_notice(grounding: LessonGrounding, has_linked_sources: bool) -> str | None:
    """Thông báo hiển thị cho người học — không tô hồng trạng thái."""
    if grounding is LessonGrounding.source_grounded:
        return None
    if has_linked_sources:
        return (
            "Bài học dựa trên kiến thức chung của AI. Khóa học có nguồn tham khảo đã liên kết "
            "nhưng chưa được đối chiếu nội dung, nên các câu trong bài chưa được xác minh."
        )
    return (
        "Bài học dựa trên kiến thức chung của AI, chưa có nguồn tài liệu được xác minh."
    )
