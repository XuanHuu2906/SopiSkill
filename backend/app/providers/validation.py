"""Semantic validation cho structured output của LLM (P2.0).

Pydantic chỉ kiểm tra hình thức. Các rule dưới đây kiểm tra *nghĩa*: đúng số câu
phỏng vấn, đáp án nằm trong bounds, không rỗng, không trùng lặp vô nghĩa.
Vi phạm ⇒ `SchemaInvalidError` (không retry tự động, tránh đốt tiền).
"""

from app.providers.base import SchemaInvalidError
from app.schemas.schemas import LessonContent, ProposalPayload

INTERVIEW_QUESTIONS_COUNT = 5
MAX_UNITS = 6
MAX_LESSONS_PER_UNIT = 12


BLANK_MARKERS = ("____", "___", "[...]", "...", "…")
BLANK_FILL = "____"


def _has_blank_marker(sentence: str) -> bool:
    return any(marker in sentence for marker in BLANK_MARKERS)


def _mask_answer_in_sentence(sentence: str, answer: str) -> str:
    """Thay lần xuất hiện đầu tiên của đáp án bằng chỗ trống.

    So khớp không phân biệt hoa/thường và bỏ qua khác biệt khoảng trắng; giữ
    nguyên phần còn lại của câu để không phá ngữ pháp.
    """
    if not sentence or not answer:
        return sentence
    if _has_blank_marker(sentence):
        # Đã có chỗ trống: chỉ cần đảm bảo đáp án không nằm ngoài chỗ trống.
        masked = _replace_ci(sentence, answer, BLANK_FILL)
        return masked if masked != sentence else sentence

    masked = _replace_ci(sentence, answer, BLANK_FILL)
    if masked != sentence:
        return masked
    return sentence


def _replace_ci(text: str, needle: str, replacement: str) -> str:
    """Thay thế không phân biệt hoa/thường, an toàn với ký tự đặc biệt."""
    import re

    needle = needle.strip()
    if not needle:
        return text
    pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", re.IGNORECASE)
    return pattern.sub(replacement, text, count=1)


def _norm(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def validate_interview_questions(questions: list[str]) -> list[str]:
    if len(questions) != INTERVIEW_QUESTIONS_COUNT:
        raise SchemaInvalidError(
            f"Cần đúng {INTERVIEW_QUESTIONS_COUNT} câu phỏng vấn, nhận {len(questions)}."
        )
    cleaned: list[str] = []
    for question in questions:
        if not isinstance(question, str) or not question.strip():
            raise SchemaInvalidError("Câu phỏng vấn rỗng.")
        if len(question) > 400:
            raise SchemaInvalidError("Câu phỏng vấn quá dài (>400 ký tự).")
        cleaned.append(question.strip())
    if len({_norm(q) for q in cleaned}) != len(cleaned):
        raise SchemaInvalidError("Câu phỏng vấn bị trùng.")
    return cleaned


def validate_proposal(payload: ProposalPayload) -> ProposalPayload:
    if not payload.name.strip() or not payload.objective.strip():
        raise SchemaInvalidError("Proposal thiếu tên hoặc mục tiêu.")

    if len(payload.units) > MAX_UNITS:
        raise SchemaInvalidError(f"Quá nhiều unit ({len(payload.units)} > {MAX_UNITS}).")

    seen_unit_titles: set[str] = set()
    total_lessons = 0
    for unit in payload.units:
        if not unit.title.strip():
            raise SchemaInvalidError("Unit không có tiêu đề.")
        key = _norm(unit.title)
        if key in seen_unit_titles:
            raise SchemaInvalidError(f"Unit trùng tiêu đề: '{unit.title}'.")
        seen_unit_titles.add(key)
        if len(unit.lessonTitles) > MAX_LESSONS_PER_UNIT:
            raise SchemaInvalidError(f"Unit '{unit.title}' có quá nhiều bài.")
        for title in unit.lessonTitles:
            if not title.strip():
                raise SchemaInvalidError(f"Unit '{unit.title}' có bài học không tên.")
        total_lessons += len(unit.lessonTitles)

    seen_titles: set[str] = set()
    for unit in payload.units:
        for title in unit.lessonTitles:
            key = _norm(title)
            if key in seen_titles:
                raise SchemaInvalidError(f"Bài học trùng tiêu đề: '{title}'.")
            seen_titles.add(key)

    if total_lessons == 0:
        raise SchemaInvalidError("Proposal không có bài học nào.")
    if not payload.outcomes or all(not o.strip() for o in payload.outcomes):
        raise SchemaInvalidError("Proposal thiếu learning outcome.")

    # P2.1 — lộ trình phải là DAG acyclic và phủ đủ mọi bài học.
    from app.services import pedagogy

    payload = pedagogy.normalize_curriculum(payload)
    return pedagogy.validate_curriculum(payload)


def _validate_block(block, index: int) -> None:
    btype = block.type

    if btype == "teach":
        if not block.title.strip():
            raise SchemaInvalidError(f"Block {index}: teach thiếu tiêu đề.")
        if not any(p.strip() for p in block.paragraphs):
            raise SchemaInvalidError(f"Block {index}: teach không có nội dung.")
        return

    if btype == "mc":
        options = [o.strip() for o in block.options]
        if any(not o for o in options):
            raise SchemaInvalidError(f"Block {index}: mc có option rỗng.")
        if len({_norm(o) for o in options}) != len(options):
            raise SchemaInvalidError(f"Block {index}: mc có option trùng.")
        if not (0 <= block.answerIndex < len(options)):
            raise SchemaInvalidError(
                f"Block {index}: answerIndex {block.answerIndex} ngoài [0, {len(options) - 1}]."
            )
        return

    if btype == "blank":
        answer = block.answer.strip()
        if not answer:
            raise SchemaInvalidError(f"Block {index}: blank thiếu đáp án.")
        # Repair thay vì fail: nếu đáp án xuất hiện trong câu thì thay chỗ đó bằng
        # chỗ trống. Fail ở đây sẽ đốt thêm request LLM mà không cải thiện nội dung.
        block.sentence = _mask_answer_in_sentence(block.sentence, answer)
        if not _has_blank_marker(block.sentence):
            # Không có marker và đáp án cũng không nằm trong câu → không rõ chỗ điền.
            raise SchemaInvalidError(
                f"Block {index}: câu blank không có chỗ trống (____ / [...])."
            )
        return

    if btype == "order":
        items = [i.strip() for i in block.items]
        if any(not i for i in items):
            raise SchemaInvalidError(f"Block {index}: order có item rỗng.")
        if len({_norm(i) for i in items}) != len(items):
            raise SchemaInvalidError(f"Block {index}: order có item trùng.")
        return

    if btype == "match":
        lefts = [p[0].strip() for p in block.pairs]
        rights = [p[1].strip() for p in block.pairs]
        if any(not x for x in lefts + rights):
            raise SchemaInvalidError(f"Block {index}: match có cặp rỗng.")
        if len({_norm(x) for x in lefts}) != len(lefts):
            raise SchemaInvalidError(f"Block {index}: match có left trùng.")
        return

    if btype == "short":
        accepted = [a.strip() for a in block.acceptedAnswers]
        if any(not a for a in accepted):
            raise SchemaInvalidError(f"Block {index}: short có đáp án rỗng.")
        return


def _block_question(block) -> str:
    if block.type in ("mc", "short"):
        return block.question
    if block.type == "blank":
        return block.sentence
    if block.type in ("order", "match"):
        return block.prompt
    return ""


def validate_lesson(content: LessonContent) -> LessonContent:
    if not content.title.strip():
        raise SchemaInvalidError("Bài học không có tiêu đề.")
    if not content.blocks:
        raise SchemaInvalidError("Bài học không có block nào.")
    if not any(block.type == "teach" for block in content.blocks):
        raise SchemaInvalidError("Bài học thiếu block 'teach' (không có nội dung giảng).")
    if not any(block.type != "teach" for block in content.blocks):
        raise SchemaInvalidError("Bài học không có câu hỏi kiểm tra nào.")
    for index, block in enumerate(content.blocks):
        _validate_block(block, index)

    # P2.1 — chống bài học "độn" bằng câu hỏi lặp (LLM hay lặp khi thiếu ngữ cảnh).
    seen_questions: set[str] = set()
    for index, block in enumerate(content.blocks):
        question = _block_question(block)
        if not question.strip():
            continue
        key = _norm(question)
        if key in seen_questions:
            raise SchemaInvalidError(f"Block {index}: câu hỏi bị lặp trong cùng bài học.")
        seen_questions.add(key)

    # Không lặp y nguyên toàn bộ đoạn giảng (dấu hiệu model nhồi nội dung).
    paragraphs = [
        _norm(p)
        for block in content.blocks
        if block.type == "teach"
        for p in block.paragraphs
        if len(_norm(p)) >= 40
    ]
    if len(set(paragraphs)) != len(paragraphs):
        raise SchemaInvalidError("Bài học có đoạn giảng bị lặp nguyên văn.")
    return content
