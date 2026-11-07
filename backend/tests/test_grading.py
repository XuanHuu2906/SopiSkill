"""Unit tests cho grading deterministic + public/private contract (P1.1) — không dùng LLM."""

import uuid

import pytest

from app.schemas.schemas import AttemptAnswer
from app.services.lesson_content import (
    grade_attempt,
    grade_mc,
    is_completed,
    public_block,
    public_blocks,
)

LESSON_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
VERSION = 1

MC = {"type": "mc", "question": "q", "options": ["a", "b", "c"], "answerIndex": 1}
BLANK = {"type": "blank", "sentence": "s", "answer": "Python"}
ORDER = {"type": "order", "prompt": "p", "items": ["đọc", "làm", "kiểm"]}
MATCH = {"type": "match", "prompt": "p", "pairs": [["A", "1"], ["B", "2"]]}
SHORT = {"type": "short", "question": "q", "acceptedAnswers": ["python", "Python "]}


def _match_answer() -> dict[int, int]:
    """Đáp án đúng dạng id public (tính từ public blocks, không đọc key)."""
    pub = public_block(LESSON_ID, VERSION, 1, MATCH)
    left = {item["text"]: item["id"] for item in pub["lefts"]}
    right = {item["text"]: item["id"] for item in pub["rights"]}
    return {left[a]: right[b] for a, b in MATCH["pairs"]}


def _grade(block: dict, answer, index: int = 0):
    results, correct, total = grade_attempt(
        LESSON_ID, VERSION, [{"type": "teach", "title": "t", "paragraphs": ["x"]}, block],
        [AttemptAnswer(index=1, answer=answer)],
    )
    assert total == 1
    return results[0]["correct"]


def _public_order_ids() -> list[int]:
    pub = public_block(LESSON_ID, VERSION, 1, ORDER)
    return [item["id"] for item in pub["items"]]


def test_mc_correct_and_wrong():
    assert _grade(MC, 1) is True
    assert _grade(MC, 0) is False
    assert _grade(MC, "1") is False  # chỉ chấp nhận int, không nhận chuỗi từ client
    assert _grade(MC, None) is False
    # bool là int ở Python → grader từ chối trực tiếp (Pydantic smart-union có thể
    # coerce true→1 nên kiểm tra ở tầng grader, không qua AttemptAnswer).
    assert grade_mc(MC, True) is False


def test_blank_normalized():
    assert _grade(BLANK, " python ") is True
    assert _grade(BLANK, "PYTHON") is True
    assert _grade(BLANK, "Java") is False
    assert _grade(BLANK, 123) is False


def test_short_normalized():
    assert _grade(SHORT, " Python ") is True
    assert _grade(SHORT, "ruby") is False


def test_order_uses_public_ids_not_array_order():
    pub = public_block(LESSON_ID, VERSION, 1, ORDER)
    ids_by_text = {item["text"]: item["id"] for item in pub["items"]}

    correct_ids = [ids_by_text[text] for text in ORDER["items"]]
    assert _grade(ORDER, correct_ids) is True

    wrong_ids = list(reversed(correct_ids))
    assert _grade(ORDER, wrong_ids) is False

    # Gửi array index gốc [0,1,2] của private content KHÔNG còn là đáp án đúng.
    assert _grade(ORDER, [0, 1, 2]) is (correct_ids == [0, 1, 2])

    # Index trùng/ngoài bounds bị từ chối.
    assert _grade(ORDER, [correct_ids[0]] * 3) is False
    assert _grade(ORDER, [0, 1, 99]) is False


def test_match_uses_public_ids_not_pairs_order():
    pub = public_block(LESSON_ID, VERSION, 1, MATCH)
    left_id_by_text = {item["text"]: item["id"] for item in pub["lefts"]}
    right_id_by_text = {item["text"]: item["id"] for item in pub["rights"]}

    correct = {
        left_id_by_text["A"]: right_id_by_text["1"],
        left_id_by_text["B"]: right_id_by_text["2"],
    }
    assert _grade(MATCH, correct) is True

    swapped = {
        left_id_by_text["A"]: right_id_by_text["2"],
        left_id_by_text["B"]: right_id_by_text["1"],
    }
    assert _grade(MATCH, swapped) is False

    # Thiếu cặp / text thay vì id đều sai.
    assert _grade(MATCH, {left_id_by_text["A"]: right_id_by_text["1"]}) is False
    assert _grade(MATCH, {"A": "1", "B": "2"}) is False
    assert _grade(MATCH, "not a mapping") is False


def test_teach_block_skipped():
    results, correct, total = grade_attempt(
        LESSON_ID, VERSION, [{"type": "teach", "title": "t", "paragraphs": ["x"]}, MC],
        [AttemptAnswer(index=1, answer=1)],
    )
    assert total == 1
    assert correct == 1
    assert results[0]["index"] == 1
    assert results[0]["solution"]["answerIndex"] == 1


def test_unknown_type_is_wrong():
    assert _grade({"type": "mystery"}, 1) is False


def test_public_blocks_never_leak_answer_key():
    blocks = [MC, BLANK, ORDER, MATCH, SHORT]
    pub = public_blocks(LESSON_ID, VERSION, blocks)

    for block in pub:
        assert "answerIndex" not in block
        assert "answer" not in block
        assert "acceptedAnswers" not in block
        assert "pairs" not in block

    # order items và match right sides đã được shuffle, không trùng thứ tự gốc.
    assert [item["text"] for item in pub[2]["items"]] != ORDER["items"]
    assert [item["text"] for item in pub[3]["rights"]] != ["1", "2"]
    # lefts giữ thứ tự (không phải lời giải), rights mới là phần cần ghép.
    assert [item["text"] for item in pub[3]["lefts"]] == ["A", "B"]


def test_public_projection_is_deterministic():
    first = public_blocks(LESSON_ID, VERSION, [ORDER, MATCH])
    second = public_blocks(LESSON_ID, VERSION, [ORDER, MATCH])
    assert first == second

    # Seed khác version chỉ cần tạo projection hợp lệ; không assert nó *phải* khác
    # (với 2 phần tử, hai hoán vị có thể trùng nhau một cách hợp lệ).
    other_version = public_blocks(LESSON_ID, VERSION + 1, [MATCH])
    assert sorted(item["text"] for item in other_version[0]["rights"]) == ["1", "2"]


def test_public_projection_does_not_mutate_private_block():
    import copy

    original = copy.deepcopy(MATCH)
    public_block(LESSON_ID, VERSION, 1, MATCH)
    assert MATCH == original


def test_completion_threshold_policy():
    assert is_completed(5, 5) is True
    assert is_completed(4, 5) is True  # 80%
    assert is_completed(3, 5) is False  # 60%
    assert is_completed(0, 0) is False



# ---------- P6.1: shuffle seed must depend on a server-only secret ----------


def _legacy_seed(lesson_id, version: int, index: int) -> int:
    """Công thức seed CŨ: mọi thành phần đều công khai ⇒ client tái lập được."""
    import hashlib

    raw = f"{lesson_id}:{version}:{index}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def test_shuffle_seed_is_keyed_and_not_reproducible_from_public_data():
    """Trước P6.1, seed = sha256("<lessonId>:<version>:<blockIndex>").

    lessonId nằm trong URL, version/index trong payload ⇒ học viên dựng lại đúng
    hoán vị và suy ra đáp án `order`/`match`. Nay seed là HMAC(key server, msg)
    nên không tái lập được nếu không có khoá.
    """
    from app.services.lesson_content import _seed

    inputs = [(LESSON_ID, VERSION + (i // 3), i) for i in range(24)]
    assert all(_seed(*args) != _legacy_seed(*args) for args in inputs)

    # Ổn định khi cùng khoá — nếu không, public projection mỗi lần một khác.
    assert {_seed(*args) for args in inputs} == {_seed(*args) for args in inputs}


def test_shuffle_seed_changes_when_server_secret_changes(monkeypatch):
    from app.core.config import get_settings
    from app.services import lesson_content

    def seeded() -> list[int]:
        get_settings.cache_clear()
        lesson_content.reset_shuffle_key_cache()
        return [_seed(LESSON_ID, VERSION, i) for i in range(16)]

    from app.services.lesson_content import _seed

    monkeypatch.setenv("LESSON_SHUFFLE_SECRET", "secret-one")
    first = seeded()
    monkeypatch.setenv("LESSON_SHUFFLE_SECRET", "secret-two")
    second = seeded()

    assert first != second
    # Đổi khoá KHÔNG được đổi đáp án đúng, chỉ đổi mapping hiển thị.
    ids = {
        item["text"]: item["id"]
        for item in public_block(LESSON_ID, VERSION, 1, ORDER)["items"]
    }
    assert _grade(ORDER, [ids[text] for text in ORDER["items"]]) is True
    assert _grade(MATCH, _match_answer()) is True


def test_production_without_any_secret_refuses_to_shuffle(monkeypatch):
    """Production thiếu secret phải lỗi rõ ràng, KHÔNG rơi về khoá dev công khai."""
    from app.core.config import get_settings
    from app.services import lesson_content

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("LESSON_SHUFFLE_SECRET", "")
    monkeypatch.setenv("JWT_SECRET", "")
    get_settings.cache_clear()
    lesson_content.reset_shuffle_key_cache()
    try:
        with pytest.raises(RuntimeError, match="LESSON_SHUFFLE_SECRET"):
            public_block(LESSON_ID, VERSION, 1, ORDER)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        lesson_content.reset_shuffle_key_cache()
