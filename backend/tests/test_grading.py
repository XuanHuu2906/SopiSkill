"""Unit tests cho grading deterministic — không dùng LLM."""

from app.schemas.schemas import AttemptAnswer
from app.services.grading_service import grade_attempt, grade_block

MC = {"type": "mc", "question": "q", "options": ["a", "b", "c"], "answerIndex": 1}
BLANK = {"type": "blank", "sentence": "s", "answer": "Python"}
ORDER = {"type": "order", "prompt": "p", "items": ["đọc", "làm", "kiểm"]}
MATCH = {"type": "match", "prompt": "p", "pairs": [["A", "1"], ["B", "2"]]}
SHORT = {"type": "short", "question": "q", "acceptedAnswers": ["python", "Python "]}


def test_mc_correct_and_wrong():
    assert grade_block(MC, AttemptAnswer(index=0, answer=1)) is True
    assert grade_block(MC, AttemptAnswer(index=0, answer=0)) is False
    assert grade_block(MC, AttemptAnswer(index=0, answer="1")) is True  # chuỗi số vẫn chấm được
    assert grade_block(MC, AttemptAnswer(index=0, answer=None)) is False


def test_blank_normalized():
    assert grade_block(BLANK, AttemptAnswer(index=0, answer=" python ")) is True
    assert grade_block(BLANK, AttemptAnswer(index=0, answer="PYTHON")) is True
    assert grade_block(BLANK, AttemptAnswer(index=0, answer="Java")) is False


def test_order_exact_sequence():
    assert grade_block(ORDER, AttemptAnswer(index=0, answer=["đọc", "làm", "kiểm"])) is True
    assert grade_block(ORDER, AttemptAnswer(index=0, answer=["làm", "đọc", "kiểm"])) is False
    assert grade_block(ORDER, AttemptAnswer(index=0, answer=[0, 1, 2])) is True  # index mode
    assert grade_block(ORDER, AttemptAnswer(index=0, answer=[1, 0, 2])) is False


def test_match_pairs():
    assert grade_block(MATCH, AttemptAnswer(index=0, answer={"A": "1", "B": "2"})) is True
    assert grade_block(MATCH, AttemptAnswer(index=0, answer={"A": "2", "B": "1"})) is False
    assert grade_block(MATCH, AttemptAnswer(index=0, answer=[["A", "1"], ["B", "2"]])) is True
    assert grade_block(MATCH, AttemptAnswer(index=0, answer={"A": "1"})) is False  # thiếu B
    assert grade_block(MATCH, AttemptAnswer(index=0, answer="not a mapping")) is False


def test_short_normalized():
    assert grade_block(SHORT, AttemptAnswer(index=0, answer=" Python ")) is True
    assert grade_block(SHORT, AttemptAnswer(index=0, answer="ruby")) is False


def test_teach_block_skipped():
    blocks = [{"type": "teach", "title": "t", "paragraphs": ["x"]}, MC]
    results, correct, total = grade_attempt(
        blocks, [AttemptAnswer(index=1, answer=1)]
    )
    assert total == 1  # teach không tính điểm
    assert correct == 1
    assert results[0]["index"] == 1


def test_unknown_type_is_wrong():
    assert grade_block({"type": "mystery"}, AttemptAnswer(index=0, answer=1)) is False
