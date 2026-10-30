"""Grading service — chấm deterministic trên backend, KHÔNG dùng LLM."""

from app.schemas.schemas import AttemptAnswer


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _norm_answer(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_text(value)
    return str(value).strip()


def grade_mc(block: dict, answer) -> bool:
    try:
        return int(answer) == int(block["answerIndex"])
    except (TypeError, ValueError, KeyError):
        return False


def grade_blank(block: dict, answer) -> bool:
    return _norm_answer(answer if isinstance(answer, str) else "") == _norm_answer(block.get("answer", ""))


def grade_order(block: dict, answer) -> bool:
    """answer: list các chuỗi theo thứ tự người dùng sắp, hoặc list index."""
    items = block.get("items", [])
    if not isinstance(answer, list) or len(answer) != len(items):
        return False
    normalized_items = [_norm_answer(i) for i in items]
    answer_norm = [_norm_answer(a) if isinstance(a, str) else "" for a in answer]
    # chấp nhận cả回答 dạng index
    try:
        if all(isinstance(a, int) for a in answer):
            return list(answer) == list(range(len(items)))
    except Exception:
        pass
    return answer_norm == normalized_items


def grade_match(block: dict, answer) -> bool:
    """answer: dict left->right (hoặc list [left, right] pairs)."""
    pairs = block.get("pairs", [])
    lefts = [_norm_answer(p[0]) for p in pairs]
    rights = [_norm_answer(p[1]) for p in pairs]
    mapping = dict(zip(lefts, rights))

    if isinstance(answer, dict):
        user_map = {_norm_answer(k): _norm_answer(v) for k, v in answer.items()}
    elif isinstance(answer, list):
        try:
            user_map = {_norm_answer(p[0]): _norm_answer(p[1]) for p in answer}
        except (TypeError, IndexError):
            return False
    else:
        return False

    if set(user_map.keys()) != set(lefts):
        return False
    return all(mapping.get(k) == v for k, v in user_map.items())


def grade_short(block: dict, answer) -> bool:
    accepted = [_norm_answer(a) for a in block.get("acceptedAnswers", [])]
    return _norm_answer(answer if isinstance(answer, str) else "") in accepted


GRADERS = {
    "mc": grade_mc,
    "blank": grade_blank,
    "order": grade_order,
    "match": grade_match,
    "short": grade_short,
}


def grade_block(block: dict, answer: AttemptAnswer) -> bool:
    grader = GRADERS.get(block.get("type"))
    if grader is None:
        return False
    return bool(grader(block, answer.answer))


def grade_attempt(blocks: list[dict], answers: list[AttemptAnswer]) -> tuple[list[dict], int, int]:
    """Chấm batch. Trả về (results, correct, total). Chỉ chấm block type có grader."""
    results = []
    correct = 0
    total = 0
    answer_by_index = {a.index: a for a in answers}
    for idx, block in enumerate(blocks):
        btype = block.get("type", "")
        if btype == "teach":
            continue
        ans = answer_by_index.get(idx)
        ok = grade_block(block, ans) if ans is not None else False
        total += 1
        if ok:
            correct += 1
        results.append({"index": idx, "type": btype, "correct": ok})
    return results, correct, total
