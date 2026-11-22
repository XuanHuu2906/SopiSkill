"""Semantic validation cho structured output của LLM (P2.0).

Pydantic chỉ kiểm tra hình thức. Các rule dưới đây kiểm tra *nghĩa*: đúng số câu
phỏng vấn, đáp án nằm trong bounds, không rỗng, không trùng lặp vô nghĩa.
Vi phạm ⇒ `SchemaInvalidError` (không retry tự động, tránh đốt tiền).
"""

import re

from app.providers.base import SchemaInvalidError
from app.schemas.schemas import LessonContent, ProposalPayload

INTERVIEW_QUESTIONS_COUNT = 5
MAX_UNITS = 6
MAX_LESSONS_PER_UNIT = 12


BLANK_MARKERS = ("____", "___", "[...]", "...", "…")
BLANK_FILL = "____"

# Hợp đồng quiz hiện tại chỉ hỗ trợ ĐÚNG MỘT chỗ trống với MỘT đáp án:
#   - `BlankBlock` có một trường `answer: str` (không có `blanks[]`)
#   - `grade_blank` so nguyên chuỗi đã chuẩn hoá với `block["answer"]`
#   - frontend render đúng một <input> và gửi một chuỗi
#   - `public_block` chỉ gửi `sentence`, không gửi đáp án
# Vì vậy câu 2+ chỗ trống là *không thể trả lời*, phải từ chối thay vì lưu `ready`.
BLANK_SLOT_COUNT = 1


def _has_blank_marker(sentence: str) -> bool:
    return any(marker in sentence for marker in BLANK_MARKERS)


def _count_blank_slots(sentence: str) -> int:
    """Đếm số chỗ trống theo marker rõ ràng trước, chỉ đoán mờ khi không có marker rõ.

    `_` (3+) và `[...]` là marker do prompt sinh ra. `...` / `…` chỉ được tính khi
    câu không có marker rõ — trong dữ liệu thật `...` xuất hiện như cú pháp code
    (`conn.execute(...)`) chứ không phải chỗ trống.
    """
    strict = len(re.findall(r"_{3,}", sentence)) + sentence.count("[...]")
    if strict:
        return strict
    return len(re.findall(r"…", sentence)) + len(re.findall(r"(?<!\.)\.\.\.(?!\.)", sentence))


def _mask_answer_in_sentence(sentence: str, answer: str) -> str:
    """Thay lần xuất hiện đầu tiên của đáp án bằng chỗ trống.

    So khớp không phân biệt hoa/thường và bỏ qua khác biệt khoảng trắng; giữ
    nguyên phần còn lại của câu để không phá ngữ pháp.
    """
    if not sentence or not answer:
        return sentence
    if _has_blank_marker(sentence):
        # Đã có chỗ trống: KHÔNG tạo thêm chỗ trống thứ hai. Che đáp án đang lộ ở
        # đây sẽ biến câu 1 chỗ trống thành 2 chỗ trống và làm câu không trả lời được.
        return sentence
    return _replace_ci(sentence, answer, BLANK_FILL)


def _replace_ci(text: str, needle: str, replacement: str) -> str:
    """Thay thế không phân biệt hoa/thường, an toàn với ký tự đặc biệt."""
    needle = needle.strip()
    if not needle:
        return text
    pattern = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", re.IGNORECASE)
    return pattern.sub(replacement, text, count=1)


def _norm(text: str) -> str:
    return " ".join(text.strip().casefold().split())


# Các dấu hiệu cắt cụt giữa chừng thường gặp khi LLM chạm trần token (P1-CONTENT-TRUNC).
_TRAILING_DANGLING_CHARS = (",", "=", "(", "[", "{", "\\", "+", "-")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_UNCLOSED_BACKTICK_RE = re.compile(r"(?<!`)`(?!`)")


def _brackets_balanced(snippet: str) -> bool:
    """Kiểm tra ngoặc (), [], {} cân bằng trong đoạn code ngắn (bỏ qua chuỗi trong nháy)."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    in_quote: str | None = None
    escaped = False
    for ch in snippet:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_quote is not None:
            escaped = True
            continue
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
            continue
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return not stack and in_quote is None


def check_text_completeness(text: str, label: str) -> str | None:
    """Lint deterministic phát hiện văn bản/đoạn code bị cắt cụt giữa chừng.

    Trả thông điệp lỗi nếu có dấu hiệu cắt cụt rõ ràng, ngược lại trả None.
    Thiết kế cẩn trọng để tránh false positive trên văn bản tiếng Việt/Anh bình thường.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    # 1. Fenced code block chưa đóng (số lượng ``` lẻ).
    if stripped.count("```") % 2 != 0:
        return f"{label}: nội dung bị cắt cụt (khối code ``` chưa đóng)."
    # 2. Dấu backtick inline lẻ (bỏ qua các khối ``` đã kiểm ở trên).
    without_fences = stripped.replace("```", "")
    if len(_UNCLOSED_BACKTICK_RE.findall(without_fences)) % 2 != 0:
        return f"{label}: nội dung bị cắt cụt (inline code ` chưa đóng)."
    # 3. Ngoặc chưa đóng bên trong inline code span (vd: `diem = [7, 8,`).
    for match in _INLINE_CODE_RE.finditer(without_fences):
        code_span = match.group(1).strip()
        if any(c in code_span for c in "([{}])") and not _brackets_balanced(code_span):
            return f"{label}: đoạn code bị cắt cụt (ngoặc/chuỗi chưa đóng)."
    # 4. Ký tự treo rõ ràng ở cuối câu/đoạn (vd: kết thúc bằng dấu `,`, `=`, `(`, `[`, `{`).
    if stripped.endswith(_TRAILING_DANGLING_CHARS) and not stripped.endswith("--"):
        return f"{label}: nội dung kết thúc lơ lửng ('{stripped[-1]}'), nghi bị cắt cụt."
    return None


def check_lesson_completeness(content: LessonContent) -> list[str]:
    """Trả danh sách lỗi cắt cụt trên toàn bộ blocks của một bài học."""
    errors: list[str] = []
    title_err = check_text_completeness(content.title, "Tiêu đề bài học")
    if title_err:
        errors.append(title_err)
    for index, block in enumerate(content.blocks):
        btype = block.type
        if btype == "teach":
            for p_idx, paragraph in enumerate(block.paragraphs):
                err = check_text_completeness(
                    paragraph, f"Block {index} (teach đoạn {p_idx})"
                )
                if err:
                    errors.append(err)
        elif btype == "mc":
            err = check_text_completeness(block.question, f"Block {index} (mc question)")
            if err:
                errors.append(err)
            for o_idx, option in enumerate(block.options):
                o_err = check_text_completeness(
                    option, f"Block {index} (mc option {o_idx})"
                )
                if o_err:
                    errors.append(o_err)
        elif btype == "blank":
            err = check_text_completeness(block.sentence, f"Block {index} (blank)")
            if err:
                errors.append(err)
        elif btype == "order":
            err = check_text_completeness(block.prompt, f"Block {index} (order)")
            if err:
                errors.append(err)
        elif btype == "match":
            err = check_text_completeness(block.prompt, f"Block {index} (match)")
            if err:
                errors.append(err)
        elif btype == "short":
            err = check_text_completeness(block.question, f"Block {index} (short)")
            if err:
                errors.append(err)
    return errors


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
        slots = _count_blank_slots(block.sentence)
        if slots != BLANK_SLOT_COUNT:
            # 0 chỗ trống → không rõ điền vào đâu; 2+ chỗ trống → hợp đồng hiện tại
            # chỉ có một `answer`/một input nên câu không thể trả lời trọn vẹn.
            raise SchemaInvalidError(
                f"Block {index}: câu blank phải có đúng {BLANK_SLOT_COUNT} chỗ trống "
                f"(____ / [...]), nhận {slots}."
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

    # P1-CONTENT-TRUNC — chặn bài học có đoạn giảng/code/câu hỏi bị cắt dở.
    truncation_errors = check_lesson_completeness(content)
    if truncation_errors:
        raise SchemaInvalidError(truncation_errors[0])
    return content
