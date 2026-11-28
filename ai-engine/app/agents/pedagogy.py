"""Deterministic, negation-aware learner profile extraction (ported from Wave 2 pedagogy.py)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

from app.schemas.internal import InterviewAnswerItem, LearnerProfileOut

_LEVEL_BEGINNER = (
    "chưa biết", "chưa từng", "chưa tiếp xúc", "mới bắt đầu", "mới học",
    "người mới", "cơ bản", "từ đầu", "con số 0", "chưa nắm", "làm quen từ đầu",
    "beginner", "from scratch", "chưa có kinh nghiệm",
    "zero", "no experience", "never used", "new to", "just starting",
    "complete beginner", "absolute beginner", "novice", "basic knowledge",
    "basics only", "introductory",
)
_LEVEL_INTERMEDIATE = (
    "đã biết", "đã học qua", "đã học", "đã từng", "đã viết", "đã làm", "đã dùng",
    "đã quen", "từng cài đặt", "từng áp dụng", "áp dụng thực tế", "biết sơ qua", "làm quen sơ",
    "2 năm", "3 năm", "trung bình", "intermediate", "có chút kinh nghiệm",
    "biết sơ", "some experience", "familiar with", "comfortable with",
    "working knowledge", "used it before", "work with", "work in",
    "use it at work", "regularly use", "solid foundation", "mid-level",
    "1-2 years", "2 years", "3 years", "can write", "read a lot about",
)
_LEVEL_ADVANCED = (
    "nâng cao", "chuyên sâu", "thành thạo", "khá vững", "tối ưu", "advanced", "expert",
    "đã có kinh nghiệm", "nhiều năm", "senior", "years of experience",
    "5+ years", "production", "proficient", "deeply familiar",
    "deep experience", "architect", "staff engineer", "principal",
    "lead engineer", "mastery", "seasoned",
)

_STYLE_HANDS_ON = (
    "thực hành", "làm ví dụ", "ví dụ thực tế", "hands-on", "coding",
    "thực chiến", "bài tập", "examples", "exercises", "practice",
)
_STYLE_THEORY = ("lý thuyết", "đọc hiểu", "theory", "giải thích", "conceptual")
_STYLE_PROJECT = ("dự án", "project", "sản phẩm", "ứng dụng thật", "real-world")
_STYLE_VISUAL = (
    "video", "hình ảnh", "sơ đồ", "đồ thị", "trực quan", "minh hoạ",
    "minh họa", "diagrams", "charts", "visual",
)

_DEPTH_OVERVIEW = ("phủ rộng", "tổng quan", "tổng quan nhanh", "bao quát", "rộng", "overview", "broad", "high-level", "survey")
_DEPTH_DEEP = (
    "đi sâu", "hiểu sâu", "chuyên sâu", "chi tiết", "bản chất", "cơ chế bên trong", "deep", "deep dive",
    "in-depth", "thorough", "comprehensive", "nâng cao",
)

_TIME_UNIT_MINUTES = {
    "phut": 1, "mins": 1, "min": 1,
    "gio": 60, "tieng": 60, "hours": 60, "hour": 60, "hrs": 60, "hr": 60, "h": 60,
}

_TIME_UNIT_PATTERN = re.compile(
    r"(?<![0-9a-z])(\d+(?:[.,]\d+)?)\s*(?:-|–|den|to)?\s*(\d+(?:[.,]\d+)?)?\s*"
    r"(phut|gio|tieng|mins|min|hours|hour|hrs|hr|h)(?![a-z])"
)

_NEGATION_RE = re.compile(
    r"(?:^|[\s,.;:()\-/])(?:not|no|without|avoid|khong|chua can|khong can)\s+(?:\w+\s+){0,3}$"
)


def fold_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", (text or "").casefold())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("đ", "d").split())


@lru_cache(maxsize=256)
def _fold_needle(needle: str) -> str:
    return fold_text(needle)


def contains_any(text: str, needles: tuple[str, ...], *, ignore_negated: bool = False) -> bool:
    folded = fold_text(text)
    for needle in needles:
        target = _fold_needle(needle)
        if not target:
            continue
        start = folded.find(target)
        while start != -1:
            end = start + len(target)
            before = folded[start - 1] if start > 0 else ""
            after = folded[end] if end < len(folded) else ""
            if not (before and before.isalpha()) and not (after and after.isalpha()):
                if ignore_negated:
                    prefix = folded[max(0, start - 32) : start]
                    if _NEGATION_RE.search(prefix):
                        start = folded.find(target, start + 1)
                        continue
                return True
            start = folded.find(target, start + 1)
    return False


def parse_weekly_minutes(text: str) -> int | None:
    match = _TIME_UNIT_PATTERN.search(fold_text(text))
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    unit = match.group(3)
    minutes = int(round(amount * _TIME_UNIT_MINUTES.get(unit, 60)))
    return max(15, min(minutes, 40 * 60))


def extract_learner_profile(
    answers: list[InterviewAnswerItem],
    *,
    onboarding_profile: dict[str, Any] | None = None,
) -> LearnerProfileOut:
    combined = " ".join(item.answer for item in answers if item.answer)

    # Negation-aware level inference (Wave 2 fix preserved).
    if contains_any(combined, _LEVEL_ADVANCED, ignore_negated=True):
        level = "advanced"
    elif contains_any(combined, _LEVEL_INTERMEDIATE, ignore_negated=True):
        level = "intermediate"
    elif contains_any(combined, _LEVEL_BEGINNER, ignore_negated=False):
        level = "beginner"
    else:
        level = "beginner"

    if contains_any(combined, _DEPTH_DEEP, ignore_negated=True):
        depth = "deep"
    elif contains_any(combined, _DEPTH_OVERVIEW, ignore_negated=True):
        depth = "overview"
    else:
        depth = "practical"

    styles: list[str] = []
    if contains_any(combined, _STYLE_HANDS_ON, ignore_negated=True):
        styles.append("hands_on")
    if contains_any(combined, _STYLE_VISUAL, ignore_negated=True):
        styles.append("visual")
    if contains_any(combined, _STYLE_PROJECT, ignore_negated=True):
        styles.append("project")
    if contains_any(combined, _STYLE_THEORY, ignore_negated=True):
        styles.append("theory")

    if not styles and onboarding_profile:
        raw_styles = onboarding_profile.get("learningStyles")
        if isinstance(raw_styles, list):
            styles = [str(s).strip() for s in raw_styles if str(s).strip()][:4]

    if not styles:
        styles = ["hands_on"]

    weekly_minutes = parse_weekly_minutes(combined)
    goal = answers[1].answer.strip()[:240] if len(answers) > 1 and answers[1].answer.strip() else None

    return LearnerProfileOut(
        currentLevel=level,
        depth=depth,
        preferredStyles=styles,
        weeklyMinutes=weekly_minutes,
        goal=goal,
    )
