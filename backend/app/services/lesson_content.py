"""Public/private lesson content contract + deterministic server-side grading.

Nguyên tắc (P1.1):
  - DB `lessons.content` là **private**: chứa answer key, thứ tự đúng, cặp ghép đúng.
  - API `GET /v1/lessons/{id}` chỉ trả **public blocks** — không có answer key.
  - `order`/`match` không dùng thứ tự mảng làm lời giải: public gửi danh sách item
    đã shuffle ổn định kèm id; client trả về id, server tự dựng lại đáp án từ
    private content.
  - **Seed shuffle là HMAC có khoá server** (`LESSON_SHUFFLE_SECRET`, fallback
    `JWT_SECRET`). Trước P6.1 seed là sha256(lessonId:version:blockIndex) — cả ba
    thành phần đều công khai (lessonId nằm trong URL) nên client tự dựng lại được
    hoán vị và suy ra đáp án. Khoá không rời server nên không tái lập được.
  - Grading deterministic, không nhận bất kỳ cờ `correct` nào từ client.
"""

import hashlib
import hmac
import logging
import random
import uuid

from app.core.config import get_settings
from app.schemas.schemas import AttemptAnswer

logger = logging.getLogger(__name__)

# Chỉ dùng khi chạy dev/test không cấu hình secret. Production mà thiếu secret thì
# `_shuffle_key()` raise thay vì âm thầm rơi về khoá công khai (tức là lộ đáp án).
_DEV_INSECURE_KEY = "sopiskill-dev-insecure-shuffle-key"

_key_cache: tuple[str, bytes] | None = None


def reset_shuffle_key_cache() -> None:
    """Xoá cache khoá — dùng cho test đổi env."""
    global _key_cache
    _key_cache = None


def _shuffle_key() -> bytes:
    """Khoá HMAC server-side cho seed shuffle. KHÔNG bao giờ trả về client."""
    global _key_cache
    settings = get_settings()
    raw = (settings.lesson_shuffle_secret or settings.jwt_secret or "").strip()
    if not raw:
        if settings.env == "production":
            raise RuntimeError(
                "LESSON_SHUFFLE_SECRET (hoặc JWT_SECRET) chưa cấu hình: không thể "
                "tạo shuffle không đoán được ở production."
            )
        raw = _DEV_INSECURE_KEY
        logger.warning(
            "lesson shuffle dùng khoá dev không bảo mật — đặt LESSON_SHUFFLE_SECRET "
            "trước khi chạy production"
        )
    if _key_cache is not None and _key_cache[0] == raw:
        return _key_cache[1]
    key = raw.encode("utf-8")
    _key_cache = (raw, key)
    return key


def _seed(lesson_id: uuid.UUID | str, content_version: int, block_index: int) -> int:
    """Seed = HMAC-SHA256(khoá server, lessonId:version:blockIndex).

    Khoá nằm server-side nên client **không** tái lập được hoán vị, dù biết đủ
    lessonId/version/blockIndex.
    """
    message = f"{lesson_id}:{content_version}:{block_index}".encode("utf-8")
    digest = hmac.new(_shuffle_key(), message, hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big")


def _shuffled(items: list, lesson_id: uuid.UUID | str, content_version: int, block_index: int) -> list:
    """Shuffle ổn định và **không bao giờ** trả về đúng thứ tự gốc (khi len > 1)."""
    if len(items) < 2:
        return list(items)
    # PRNG tất định theo seed HMAC có khoá server (xem `_seed`). Bản thân PRNG
    # không phải CSPRNG nhưng khoá bí mật mới là thứ bảo vệ hoán vị, nên B311 là
    # false positive ở đây.
    rng = random.Random(_seed(lesson_id, content_version, block_index))  # nosec B311
    work = list(items)
    for _ in range(8):
        rng.shuffle(work)
        if work != list(items):
            return work
    # Fallback xác định: đảo vòng để chắc chắn khác bản gốc.
    return list(items)[1:] + list(items)[:1]


# ---------- public projection ----------


def public_block(
    lesson_id: uuid.UUID | str, content_version: int, block_index: int, block: dict
) -> dict:
    """Trả block đã loại bỏ answer key. Không mutate block gốc."""
    btype = block.get("type")

    if btype == "teach":
        return {
            "type": "teach",
            "title": block.get("title", ""),
            "paragraphs": list(block.get("paragraphs", [])),
        }

    if btype == "mc":
        return {
            "type": "mc",
            "question": block.get("question", ""),
            "options": list(block.get("options", [])),
        }

    if btype == "blank":
        return {"type": "blank", "sentence": block.get("sentence", "")}

    if btype == "short":
        return {"type": "short", "question": block.get("question", "")}

    if btype == "order":
        shuffled = _shuffled(list(block.get("items", [])), lesson_id, content_version, block_index)
        return {
            "type": "order",
            "prompt": block.get("prompt", ""),
            "items": [{"id": i, "text": text} for i, text in enumerate(shuffled)],
        }

    if btype == "match":
        lefts = [pair[0] for pair in block.get("pairs", [])]
        rights = [pair[1] for pair in block.get("pairs", [])]
        shuffled_rights = _shuffled(rights, lesson_id, content_version, block_index)
        return {
            "type": "match",
            "prompt": block.get("prompt", ""),
            "lefts": [{"id": i, "text": text} for i, text in enumerate(lefts)],
            "rights": [{"id": i, "text": text} for i, text in enumerate(shuffled_rights)],
        }

    # Unknown block type (legacy/dữ liệu lạ): chỉ trả type, không trả field ẩn.
    return {"type": btype}


def public_blocks(
    lesson_id: uuid.UUID | str, content_version: int, blocks: list[dict] | None
) -> list[dict]:
    return [
        public_block(lesson_id, content_version, i, b)
        for i, b in enumerate(blocks or [])
    ]


# ---------- grading ----------


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_text(value)
    return str(value).strip()


def _as_index_list(answer) -> list[int] | None:
    if not isinstance(answer, list):
        return None
    out: list[int] = []
    for item in answer:
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        out.append(item)
    return out


def grade_mc(block: dict, answer) -> bool:
    if isinstance(answer, bool) or not isinstance(answer, int):
        return False
    try:
        return answer == int(block["answerIndex"])
    except (TypeError, ValueError, KeyError):
        return False


def grade_blank(block: dict, answer) -> bool:
    if not isinstance(answer, str):
        return False
    return _norm(answer) == _norm(block.get("answer", ""))


def grade_short(block: dict, answer) -> bool:
    if not isinstance(answer, str):
        return False
    accepted = [_norm(a) for a in block.get("acceptedAnswers", [])]
    return _norm(answer) in accepted


def grade_order(
    block: dict, answer, lesson_id: uuid.UUID | str, content_version: int, block_index: int
) -> bool:
    """answer = danh sách public item id (đã shuffle); so với thứ tự đúng trong private."""
    ids = _as_index_list(answer)
    if ids is None:
        return False
    correct_items = list(block.get("items", []))
    shuffled = _shuffled(correct_items, lesson_id, content_version, block_index)
    if len(ids) != len(shuffled):
        return False
    if len(set(ids)) != len(ids) or any(i < 0 or i >= len(shuffled) for i in ids):
        return False
    picked = [shuffled[i] for i in ids]
    return [_norm(x) for x in picked] == [_norm(x) for x in correct_items]


def grade_match(
    block: dict, answer, lesson_id: uuid.UUID | str, content_version: int, block_index: int
) -> bool:
    """answer = {leftId: rightId} dùng id public; so với cặp đúng trong private."""
    if not isinstance(answer, dict) or not answer:
        return False
    pairs = block.get("pairs", [])
    lefts = [pair[0] for pair in pairs]
    rights = [pair[1] for pair in pairs]
    shuffled_rights = _shuffled(rights, lesson_id, content_version, block_index)
    mapping = {_norm(left): _norm(right) for left, right in pairs}

    seen_lefts: set[int] = set()
    for raw_left, raw_right in answer.items():
        try:
            left_id = int(raw_left)
            right_id = int(raw_right)
        except (TypeError, ValueError):
            return False
        if left_id in seen_lefts or left_id < 0 or left_id >= len(lefts):
            return False
        if right_id < 0 or right_id >= len(shuffled_rights):
            return False
        seen_lefts.add(left_id)
        if mapping.get(_norm(lefts[left_id])) != _norm(shuffled_rights[right_id]):
            return False
    return len(seen_lefts) == len(lefts)


GRADERS = {"mc": grade_mc, "blank": grade_blank, "short": grade_short}


def _is_correct(
    block: dict, answer, lesson_id: uuid.UUID | str, content_version: int, block_index: int
) -> bool:
    btype = block.get("type")
    if btype == "order":
        return grade_order(block, answer, lesson_id, content_version, block_index)
    if btype == "match":
        return grade_match(block, answer, lesson_id, content_version, block_index)
    grader = GRADERS.get(btype)
    return bool(grader(block, answer)) if grader else False


def solution_for(block: dict, lesson_id: uuid.UUID | str, content_version: int, block_index: int) -> dict:
    """Đáp án trả **sau khi nộp** (post-submit policy). Không dùng trước submission."""
    btype = block.get("type")
    if btype == "mc":
        options = list(block.get("options", []))
        idx = int(block.get("answerIndex", -1))
        return {"answerIndex": idx, "answerText": options[idx] if 0 <= idx < len(options) else None}
    if btype == "blank":
        return {"answer": block.get("answer", "")}
    if btype == "short":
        return {"acceptedAnswers": list(block.get("acceptedAnswers", []))}
    if btype == "order":
        return {"order": list(block.get("items", []))}
    if btype == "match":
        return {"pairs": [list(pair) for pair in block.get("pairs", [])]}
    return {}


def grade_attempt(
    lesson_id: uuid.UUID | str,
    content_version: int,
    blocks: list[dict],
    answers: list[AttemptAnswer],
) -> tuple[list[dict], int, int]:
    """Chấm batch từ private blocks. Trả (results, correct, total).

    results[i] = {index, type, correct, solution} — solution chỉ dùng để trả sau
    khi nộp; route quyết định có đưa ra ngoài hay không.
    """
    results: list[dict] = []
    correct = 0
    total = 0
    answer_by_index = {a.index: a for a in answers}
    for idx, block in enumerate(blocks):
        btype = block.get("type", "")
        if btype == "teach":
            continue
        total += 1
        ans = answer_by_index.get(idx)
        ok = _is_correct(block, ans.answer if ans else None, lesson_id, content_version, idx)
        if ok:
            correct += 1
        results.append(
            {
                "index": idx,
                "type": btype,
                "correct": ok,
                "solution": solution_for(block, lesson_id, content_version, idx),
            }
        )
    return results, correct, total


# ---------- completion policy ----------

COMPLETION_THRESHOLD_PERCENT = 80


def is_completed(correct: int, total: int) -> bool:
    """PROPOSAL: lesson completed khi attempt đạt >=80% trên contentVersion hiện hành."""
    if total <= 0:
        return False
    return correct * 100 >= total * COMPLETION_THRESHOLD_PERCENT
