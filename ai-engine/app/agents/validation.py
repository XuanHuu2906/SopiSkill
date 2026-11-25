"""Deterministic completeness lint & quiz structure validator (Wave 2 + P1-QUIZ-BLANK)."""

from __future__ import annotations

import re
from typing import Any

BLANK_SLOT_COUNT = 1
_TRAILING_DANGLING_CHARS = (",", "=", "(", "[", "{", "\\", "+", "-")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_UNCLOSED_BACKTICK_RE = re.compile(r"(?<!`)`(?!`)")


class ValidationFailure(ValueError):
    """Raised when generated lesson or proposal fails deterministic integrity checks."""


def _brackets_balanced(snippet: str) -> bool:
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
    stripped = (text or "").strip()
    if not stripped:
        return None
    if stripped.count("```") % 2 != 0:
        return f"{label}: truncated content (unclosed ``` code fence)."
    without_fences = stripped.replace("```", "")
    if len(_UNCLOSED_BACKTICK_RE.findall(without_fences)) % 2 != 0:
        return f"{label}: truncated content (unclosed inline ` code)."
    for match in _INLINE_CODE_RE.finditer(without_fences):
        code_span = match.group(1).strip()
        if any(c in code_span for c in "([{}])") and not _brackets_balanced(code_span):
            return f"{label}: truncated code span (unbalanced brackets/quotes)."
    if stripped.endswith(_TRAILING_DANGLING_CHARS) and not stripped.endswith("--"):
        return f"{label}: dangling trailing token '{stripped[-1]}'."
    return None


def count_blank_slots(sentence: str) -> int:
    strict = len(re.findall(r"_{3,}", sentence)) + sentence.count("[...]")
    if strict:
        return strict
    return len(re.findall(r"…", sentence)) + len(re.findall(r"(?<!\.)\.\.\.(?!\.)", sentence))


def validate_lesson_payload(lesson: dict[str, Any]) -> list[str]:
    """Validate generated lesson blocks for completeness and quiz invariants.

    Returns a list of deterministic error messages (empty list == valid).
    """
    errors: list[str] = []
    title = str(lesson.get("title") or "").strip()
    if not title:
        errors.append("Lesson missing title.")
    else:
        err = check_text_completeness(title, "lesson.title")
        if err:
            errors.append(err)

    blocks = lesson.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        errors.append("Lesson missing blocks list.")
        return errors

    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            errors.append(f"block[{idx}]: must be an object.")
            continue
        btype = block.get("type")
        if btype == "teach":
            paragraphs = block.get("paragraphs") or []
            if not paragraphs:
                errors.append(f"block[{idx}] (teach): empty paragraphs.")
            for p_idx, para in enumerate(paragraphs):
                err = check_text_completeness(str(para), f"block[{idx}].paragraphs[{p_idx}]")
                if err:
                    errors.append(err)
        elif btype == "mc":
            options = block.get("options") or []
            ans_idx = block.get("answerIndex")
            if not isinstance(options, list) or len(options) < 2:
                errors.append(f"block[{idx}] (mc): requires at least 2 options.")
            if not isinstance(ans_idx, int) or isinstance(ans_idx, bool) or not (0 <= ans_idx < len(options)):
                errors.append(f"block[{idx}] (mc): answerIndex out of bounds.")
            err = check_text_completeness(str(block.get("question") or ""), f"block[{idx}].question")
            if err:
                errors.append(err)
        elif btype == "blank":
            sentence = str(block.get("sentence") or "")
            answer = str(block.get("answer") or "").strip()
            slots = count_blank_slots(sentence)
            if slots != BLANK_SLOT_COUNT:
                errors.append(f"block[{idx}] (blank): expected exactly {BLANK_SLOT_COUNT} blank slot, got {slots}.")
            if not answer:
                errors.append(f"block[{idx}] (blank): empty answer.")
            err = check_text_completeness(sentence, f"block[{idx}].sentence")
            if err:
                errors.append(err)
        elif btype == "order":
            items = block.get("items") or []
            if not isinstance(items, list) or len(items) < 2:
                errors.append(f"block[{idx}] (order): requires at least 2 items.")
        elif btype == "match":
            pairs = block.get("pairs") or []
            if not isinstance(pairs, list) or len(pairs) < 2:
                errors.append(f"block[{idx}] (match): requires at least 2 pairs.")
        elif btype == "short":
            accepted = block.get("acceptedAnswers") or []
            if not isinstance(accepted, list) or not any(str(a).strip() for a in accepted):
                errors.append(f"block[{idx}] (short): requires non-empty acceptedAnswers.")
            err = check_text_completeness(str(block.get("question") or ""), f"block[{idx}].question")
            if err:
                errors.append(err)
        else:
            errors.append(f"block[{idx}]: unknown block type {btype!r}.")

    return errors
