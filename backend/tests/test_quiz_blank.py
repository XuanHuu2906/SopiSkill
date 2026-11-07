"""P1-QUIZ-BLANK — một blank block chỉ được có đúng một chỗ trống, một đáp án.

Hợp đồng hiện tại chỉ hỗ trợ một chỗ trống: frontend render đúng một <input>
(`lesson/[lessonId]/page.tsx`), `grade_blank` so nguyên chuỗi với `block["answer"]`,
và public projection chỉ gửi `sentence`. Vì vậy câu có 2 chỗ trống nhưng 1 đáp án
là **không thể trả lời** — validator phải từ chối thay vì lưu thành `ready`.

Các test dưới đây chạy hoàn toàn offline, không gọi provider/không tốn phí.
"""

import pytest
from pydantic import ValidationError

from app.providers import MockProvider, SchemaInvalidError
from app.providers.validation import validate_lesson
from app.schemas.schemas import LessonContent
from app.services.lesson_content import grade_blank, public_block

LESSON_ID = "11111111-1111-1111-1111-111111111111"

TEACH = {"type": "teach", "title": "T", "paragraphs": ["Đoạn giảng có nội dung."]}


def _lesson(*blocks: dict) -> LessonContent:
    return LessonContent.model_validate({"title": "Bài", "blocks": [TEACH, *blocks]})


def _blank(sentence: str, answer: str = "while") -> dict:
    return {"type": "blank", "sentence": sentence, "answer": answer}


def _slots(sentence: str) -> int:
    """Đếm chỗ trống theo cùng quy tắc validator: ưu tiên marker rõ ràng."""
    import re

    strict = len(re.findall(r"_{3,}", sentence)) + sentence.count("[...]")
    if strict:
        return strict
    fuzzy = len(re.findall(r"…", sentence)) + len(re.findall(r"(?<!\.)\.\.\.(?!\.)", sentence))
    return fuzzy


# ---------- blank: số chỗ trống ----------


def test_blank_with_one_gap_is_accepted():
    content = _lesson(_blank("Ta dùng vòng lặp ____ khi chưa biết số lần."))
    assert validate_lesson(content) is content


def test_blank_with_two_gaps_and_one_answer_is_rejected():
    """Lỗi thực tế: 7/333 block blank đã sinh có 2 chỗ trống, chỉ 1 đáp án."""
    content = _lesson(
        _blank("Ta dùng vòng lặp ____, ví dụ: ____ tong < 10: tong += 1.")
    )
    with pytest.raises(SchemaInvalidError, match="chỗ trống"):
        validate_lesson(content)


def test_blank_with_two_bracket_gaps_is_rejected():
    content = _lesson(_blank("[...] là ánh xạ URL tới hàm; [...] quyết định hàm nào."))
    with pytest.raises(SchemaInvalidError, match="chỗ trống"):
        validate_lesson(content)


def test_blank_with_zero_gaps_is_rejected():
    """Không có marker và đáp án không nằm trong câu ⇒ không biết điền vào đâu."""
    content = _lesson(_blank("Ta dùng vòng lặp khi chưa biết số lần.", answer="while"))
    with pytest.raises(SchemaInvalidError, match="chỗ trống"):
        validate_lesson(content)


def test_blank_repair_does_not_create_a_second_gap():
    """Masking đáp án vào câu đã có sẵn chỗ trống từng tạo ra chỗ trống thứ hai."""
    content = _lesson(_blank("Python là gì? Điền: ____", answer="Python"))
    validate_lesson(content)
    assert _slots(content.blocks[1].sentence) == 1


def test_blank_repair_fills_missing_gap_when_answer_is_in_sentence():
    content = _lesson(_blank("Từ khóa tạo hàm là def.", answer="def"))
    validate_lesson(content)
    assert _slots(content.blocks[1].sentence) == 1
    assert "def" not in content.blocks[1].sentence


def test_blank_with_empty_answer_is_rejected():
    content = _lesson({"type": "blank", "sentence": "Điền: ____", "answer": "   "})
    with pytest.raises(SchemaInvalidError, match="thiếu đáp án"):
        validate_lesson(content)


# ---------- short: acceptedAnswers ----------


def test_short_with_empty_accepted_answers_is_rejected():
    with pytest.raises(ValidationError):
        _lesson({"type": "short", "question": "Học gì?", "acceptedAnswers": []})


def test_short_missing_accepted_answers_is_rejected():
    with pytest.raises(ValidationError):
        _lesson({"type": "short", "question": "Học gì?"})


def test_short_with_blank_only_answer_is_rejected():
    content = _lesson({"type": "short", "question": "Học gì?", "acceptedAnswers": ["  "]})
    with pytest.raises(SchemaInvalidError, match="đáp án rỗng"):
        validate_lesson(content)


# ---------- malformed input ----------


def test_blank_sentence_must_be_string():
    with pytest.raises(ValidationError):
        _lesson({"type": "blank", "sentence": None, "answer": "x"})


def test_blank_answer_must_be_string():
    with pytest.raises(ValidationError):
        _lesson({"type": "blank", "sentence": "Điền: ____", "answer": 5})


# ---------- public projection + grading consistency ----------


def test_single_gap_public_block_hides_answer_and_grades():
    block = dict(_blank("Ta dùng vòng lặp ____ khi chưa biết số lần."))
    pub = public_block(LESSON_ID, 1, 1, block)
    assert pub == {"type": "blank", "sentence": block["sentence"]}
    assert "answer" not in pub
    assert grade_blank(block, " while ") is True
    assert grade_blank(block, "for") is False


@pytest.mark.asyncio
async def test_mock_provider_emits_exactly_one_gap_per_blank():
    """Lint offline trên toàn bộ 10 topic eval của suite P2.1 (mock, không tốn phí)."""
    from tests.test_p21_pedagogy import EVAL_TOPICS

    provider = MockProvider()
    for topic in EVAL_TOPICS:
        questions = await provider.generate_interview_questions(topic)
        answers = ["Chưa từng học", "Áp dụng vào dự án", "3 giờ mỗi tuần",
                   "Thích thực hành", "Muốn đi sâu"]
        proposal = await provider.generate_proposal(topic, questions, answers)
        for unit in proposal.units:
            for title in unit.lessonTitles:
                content = await provider.generate_lesson(
                    topic, proposal, unit.title, title, []
                )
                for block in content.blocks:
                    if block.type == "blank":
                        assert _slots(block.sentence) == 1, (topic, title, block.sentence)
