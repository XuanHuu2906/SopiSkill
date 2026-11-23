"""Glossary service (Wave 4 / P1-GLOSSARY) — thuật ngữ khóa học rút từ `teach` blocks.

Bảo mật:
  - CHỈ đọc `teach` blocks (tiêu đề + đoạn giảng). TUYỆT ĐỐI không đọc các block câu hỏi
    (`mc`, `blank`, `short`, `order`, `match`) để không bao giờ rò answer key vào glossary.
  - Mọi truy vấn đều scope theo `course_id` đã qua kiểm ownership ở API.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CourseGlossaryTerm, Lesson

# Mẫu thuật ngữ phổ biến trong đoạn giảng: **Thuật ngữ**: định nghĩa... hoặc `term` — định nghĩa...
_BOLD_DEF_RE = re.compile(
    r"\*\*([^*]{2,64})\*\*\s*(?:\([^)]{1,40}\))?\s*(?::|—|–|\s-\s|là\s+|is\s+)",
    re.IGNORECASE,
)
_CODE_DEF_RE = re.compile(
    r"`([^`]{2,48})`\s*(?:\([^)]{1,40}\))?\s*(?::|—|–|\s-\s|là\s+|is\s+)",
    re.IGNORECASE,
)
# Token inline tường minh: [[termKey|Hiển thị]] (hoặc [[Term]])
_INLINE_TOKEN_RE = re.compile(r"\[\[([a-zA-Z0-9_-]{2,64})(?:\|([^\]]{1,80}))?\]\]")


def normalize_term_key(term: str) -> str:
    """Chuẩn hóa thuật ngữ thành ASCII slug ổn định (unique trong một course)."""
    raw = (term or "").strip()
    nfkd = unicodedata.normalize("NFKD", raw.replace("đ", "d").replace("Đ", "D"))
    ascii_only = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only.lower()).strip("_")
    return slug[:80] or "term"


def _first_sentence(text: str, max_chars: int = 240) -> str:
    clean = " ".join((text or "").replace("**", "").split())
    if not clean:
        return ""
    match = re.search(r"([.!?])(?:\s|$)", clean)
    if match and match.end() >= 25:
        sentence = clean[: match.end()].strip()
    else:
        sentence = clean
    return sentence[:max_chars].strip()


def extract_terms_from_lesson(
    lesson_title: str, blocks: list[dict] | None, *, max_terms: int = 6
) -> list[dict]:
    """Rút trích danh sách thuật ngữ an toàn từ `teach` blocks của một bài học.

    Không bao giờ đụng block câu hỏi (chống rò đáp án).
    """
    seen_keys: set[str] = set()
    extracted: list[dict] = []

    def _add(term: str, definition: str, example: str | None = None, key_override: str | None = None):
        if len(extracted) >= max_terms:
            return
        clean_term = " ".join((term or "").split()).strip(" :—–-.,")
        clean_def = " ".join((definition or "").replace("**", "").split()).strip()
        if len(clean_term) < 2 or len(clean_term) > 90 or len(clean_def) < 12:
            return
        key = normalize_term_key(key_override or clean_term)
        if key in seen_keys:
            return
        seen_keys.add(key)
        extracted.append(
            {
                "termKey": key,
                "term": clean_term,
                "definition": clean_def[:320],
                "example": (" ".join(example.split())[:220] if example else None),
            }
        )

    teach_blocks = [b for b in (blocks or []) if isinstance(b, dict) and b.get("type") == "teach"]

    for block in teach_blocks:
        paragraphs = [str(p) for p in (block.get("paragraphs") or []) if str(p).strip()]
        for para in paragraphs:
            # 1. Token inline [[termKey|Term]]
            for match in _INLINE_TOKEN_RE.finditer(para):
                raw_key, display = match.group(1), match.group(2)
                _add(display or raw_key, _first_sentence(para), key_override=raw_key)

            # 2. Bold term definition: **Term**: ...
            for pattern in (_BOLD_DEF_RE, _CODE_DEF_RE):
                for match in pattern.finditer(para):
                    term = match.group(1)
                    tail = para[match.start() :]
                    _add(term, _first_sentence(tail))

    # 3. Fallback đảm bảo mỗi bài học có ít nhất 1 thuật ngữ cốt lõi từ tiêu đề teach block / bài học
    if not extracted and teach_blocks:
        for block in teach_blocks[:2]:
            title = str(block.get("title") or lesson_title or "").strip()
            paragraphs = [str(p) for p in (block.get("paragraphs") or []) if str(p).strip()]
            if not paragraphs:
                continue
            definition = _first_sentence(paragraphs[0])
            example = _first_sentence(paragraphs[1], 180) if len(paragraphs) > 1 else None
            _add(title, definition, example=example)

    return extracted


async def upsert_lesson_glossary(
    db: AsyncSession,
    course_id: uuid.UUID,
    lesson_id: uuid.UUID,
    lesson_title: str,
    blocks: list[dict] | None,
) -> int:
    """Rút trích và upsert thuật ngữ cho một bài học (idempotent theo course_id + term_key)."""
    terms = extract_terms_from_lesson(lesson_title, blocks)
    if not terms:
        return 0

    existing_rows = (
        await db.execute(
            select(CourseGlossaryTerm).where(CourseGlossaryTerm.course_id == course_id)
        )
    ).scalars().all()
    by_key = {row.term_key: row for row in existing_rows}

    count = 0
    for item in terms:
        row = by_key.get(item["termKey"])
        if row is None:
            row = CourseGlossaryTerm(
                course_id=course_id,
                lesson_id=lesson_id,
                term_key=item["termKey"],
                term=item["term"],
                definition=item["definition"],
                example=item["example"],
            )
            db.add(row)
            by_key[item["termKey"]] = row
        else:
            row.term = item["term"]
            row.definition = item["definition"]
            if item["example"] is not None:
                row.example = item["example"]
            if row.lesson_id is None:
                row.lesson_id = lesson_id
        count += 1

    await db.flush()
    return count


async def list_course_glossary(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    lesson_id: uuid.UUID | None = None,
) -> list[dict]:
    """Trả danh sách thuật ngữ của khóa học (tùy chọn lọc theo 1 lesson)."""
    stmt = (
        select(CourseGlossaryTerm, Lesson.title)
        .outerjoin(Lesson, Lesson.id == CourseGlossaryTerm.lesson_id)
        .where(CourseGlossaryTerm.course_id == course_id)
        .order_by(CourseGlossaryTerm.created_at.asc(), CourseGlossaryTerm.term.asc())
    )
    if lesson_id is not None:
        stmt = stmt.where(CourseGlossaryTerm.lesson_id == lesson_id)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": f"trm_{term.id}",
            "termKey": term.term_key,
            "term": term.term,
            "definition": term.definition,
            "example": term.example,
            "lessonId": f"lsn_{term.lesson_id}" if term.lesson_id else None,
            "lessonTitle": lesson_title,
        }
        for term, lesson_title in rows
    ]
