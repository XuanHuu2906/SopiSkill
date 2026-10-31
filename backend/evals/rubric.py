"""P2.2 rubric — deterministic metrics (không phải "AI chính xác").

Phân tầng rõ ràng như master plan §P2.2.3:

  1. **deterministic** (module này): schema/lint/DAG/trùng lặp/quiz bám bài/độ
     dài/ngôn ngữ/answer-key nhất quán. Chạy được offline, không tốn tiền, lặp
     lại được. Đây là tầng duy nhất được dùng để **fail gate**.
  2. **human rubric** (`HUMAN_RUBRIC`): chất lượng sư phạm/factual. Cần người
     chấm; eval ghi `not_run` cho tới khi có người chấm thật.
  3. **llm-as-judge** (`judges.py`): chỉ là *tín hiệu tham khảo*, có metadata và
     không được coi là ground truth.

Rubric deterministic trả `CriterionResult` cho từng tiêu chí + tổng pass/fail.
Mọi ngưỡng đều ghi trong `THRESHOLDS` và là **PROPOSAL** cần hiệu chỉnh theo dữ
liệu thật.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.schemas.schemas import LessonContent, ProposalPayload

Severity = Literal["error", "warning"]

# Ngưỡng gate — PROPOSAL, cần hiệu chỉnh theo kết quả đo thật (ghi trong docs).
THRESHOLDS = {
    # 1.0 = 100% bài học phải qua lint (schema/teach+quiz/không lặp).
    "lessonPassRate": 1.0,
    # Tỉ lệ bài có ít nhất 1 câu hỏi khác teach.
    "quizPerLesson": 1.0,
    # Tỉ lệ block dạy học tối thiểu để không "toàn câu hỏi". Lint đã bắt buộc
    # >=1 teach/bài; ratio chỉ là cảnh báo (mock hợp lệ có 1 teach + 5 quiz = 0.17).
    "minTeachRatio": 0.15,
    # Độ dài trung bình mỗi đoạn teach (ký tự) — chặn bài rỗng/quá ngắn.
    "minAvgTeachChars": 60,
    # Trùng tiêu đề bài học trong cùng course (đã chặn ở proposal validation).
    "maxDuplicateTitleRatio": 0.0,
    # Tỉ lệ câu hỏi trùng nguyên văn giữa các bài (dấu hiệu nhồi template).
    "maxCrossLessonDuplicateQuestionRatio": 0.35,
    # Quiz phải bám tiêu đề/skill của bài: ít nhất 1 từ khoá nội dung của bài
    # xuất hiện trong câu hỏi/đoạn giảng của chính bài đó.
    "minLessonQuizAlignment": 1.0,
}

HUMAN_RUBRIC: tuple[tuple[dict, ...], str, str] = (
    (
        {
            "id": "objective_clarity",
            "label": "Mục tiêu rõ ràng, đo được",
            "scale": "0-4",
        },
        {
            "id": "level_fit",
            "label": "Đúng mức người học (không quá cao/thấp)",
            "scale": "0-4",
        },
        {
            "id": "structural_logic",
            "label": "Cấu trúc unit/bài có logic, prerequisite hợp lý",
            "scale": "0-4",
        },
        {
            "id": "example_correctness",
            "label": "Ví dụ đúng chuyên môn, không gây hiểu sai",
            "scale": "0-4",
        },
        {
            "id": "quiz_alignment",
            "label": "Quiz bám nội dung và kiểm tra đúng mục tiêu",
            "scale": "0-4",
        },
        {
            "id": "answer_consistency",
            "label": "Đáp án nhất quán với phần giảng",
            "scale": "0-4",
        },
        {
            "id": "repetition",
            "label": "Không lặp nội dung vô nghĩa",
            "scale": "0-4",
        },
        {
            "id": "language_quality",
            "label": "Ngôn ngữ tự nhiên, đúng ngôn ngữ yêu cầu",
            "scale": "0-4",
        },
        {
            "id": "safety",
            "label": "Không độc hại/không nội dung nhạy cảm không phù hợp",
            "scale": "0-4",
        },
    ),
    "4 = rất tốt, 3 = tốt, 2 = tạm được, 1 = kém, 0 = không đạt. "
    "Người chấm phải là người thật (hoặc domain reviewer); KHÔNG dùng điểm của "
    "LLM-as-judge thay cho mục này.",
    (
        "Chấm trên payload proposal + toàn bộ lesson sinh ra. Không chấm dựa "
        "trên việc hệ thống có trả JSON hợp lệ."
    ),
)


@dataclass
class CriterionResult:
    id: str
    passed: bool
    severity: Severity
    detail: str
    value: float | None = None


@dataclass
class RubricReport:
    criteria: list[CriterionResult] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.criteria if c.severity == "error")

    @property
    def warnings(self) -> list[CriterionResult]:
        return [c for c in self.criteria if not c.passed and c.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "criteria": [
                {
                    "id": c.id,
                    "passed": c.passed,
                    "severity": c.severity,
                    "detail": c.detail,
                    "value": c.value,
                }
                for c in self.criteria
            ],
            "metrics": self.metrics,
        }


_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ỹ_]+", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD_RE.findall(text or "") if len(w) > 2}


def _norm(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _block_text(block: dict) -> str:
    btype = block.get("type")
    parts: list[str] = []
    if btype == "teach":
        parts.extend(block.get("paragraphs") or [])
        parts.append(block.get("title") or "")
    elif btype in ("mc", "short"):
        parts.append(block.get("question") or "")
    elif btype == "blank":
        parts.append(block.get("sentence") or "")
    elif btype in ("order", "match"):
        parts.append(block.get("prompt") or "")
    return " ".join(p for p in parts if p)


def _question_text(block: dict) -> str:
    btype = block.get("type")
    if btype in ("mc", "short"):
        return block.get("question") or ""
    if btype == "blank":
        return block.get("sentence") or ""
    if btype in ("order", "match"):
        return block.get("prompt") or ""
    return ""


def _validate_lesson_shape(lesson: LessonContent) -> list[str]:
    """Gọi lại semantic lint của provider — nguồn sự thật duy nhất về hình dạng."""
    from app.providers.base import SchemaInvalidError
    from app.providers.validation import validate_lesson

    try:
        validate_lesson(lesson)
    except SchemaInvalidError as exc:
        return [str(exc)]
    return []


def evaluate_course(
    *,
    proposal: ProposalPayload,
    lessons: list[LessonContent],
    language: str,
    expected_lessons: int,
    min_quiz_per_lesson: int = 1,
) -> RubricReport:
    """Chấm các tiêu chí deterministic cho 1 course sinh ra.

    `lessons` phải là nội dung đã sinh (kể cả bài lỗi được bỏ qua ở caller).
    """
    report = RubricReport()
    blocks_per_lesson = [lesson.model_dump()["blocks"] for lesson in lessons]
    all_blocks = [b for blocks in blocks_per_lesson for b in blocks]

    # 1. Schema/lint từng bài (đây là cổng cứng).
    lint_errors: list[str] = []
    for lesson in lessons:
        lint_errors.extend(_validate_lesson_shape(lesson))
    lessons_ok = len(lessons) - len(lint_errors) if lint_errors else len(lessons)
    lesson_pass_rate = (lessons_ok / expected_lessons) if expected_lessons else 0.0
    report.metrics["lessonPassRate"] = round(lesson_pass_rate, 4)
    report.criteria.append(
        CriterionResult(
            id="lessonPassRate",
            passed=not lint_errors and lesson_pass_rate >= THRESHOLDS["lessonPassRate"],
            severity="error",
            detail="; ".join(lint_errors[:3])[:300] or "mọi bài học qua lint",
            value=round(lesson_pass_rate, 4),
        )
    )

    # 2. Mỗi bài phải có >= min_quiz_per_lesson câu hỏi (không phải teach).
    quiz_deficit = [
        i
        for i, blocks in enumerate(blocks_per_lesson)
        if sum(1 for b in blocks if b.get("type") != "teach") < min_quiz_per_lesson
    ]
    report.criteria.append(
        CriterionResult(
            id="quizPerLesson",
            passed=not quiz_deficit,
            severity="error",
            detail=f"bài thiếu quiz: {quiz_deficit[:5]}",
            value=len(quiz_deficit) / max(1, len(blocks_per_lesson)),
        )
    )

    # 3. Tỉ lệ block teach (không toàn câu hỏi, không toàn lý thuyết).
    teach_ratio = (
        sum(1 for b in all_blocks if b.get("type") == "teach") / len(all_blocks)
        if all_blocks
        else 0.0
    )
    report.metrics["teachRatio"] = round(teach_ratio, 4)
    report.criteria.append(
        CriterionResult(
            id="minTeachRatio",
            passed=teach_ratio >= THRESHOLDS["minTeachRatio"],
            severity="warning",
            detail=f"teachRatio={teach_ratio:.2f}",
            value=round(teach_ratio, 4),
        )
    )

    # 4. Độ dài trung bình đoạn teach — chặn nội dung rỗng.
    paragraphs = [
        p
        for b in all_blocks
        if b.get("type") == "teach"
        for p in (b.get("paragraphs") or [])
        if isinstance(p, str) and p.strip()
    ]
    avg_chars = (
        sum(len(p) for p in paragraphs) / len(paragraphs) if paragraphs else 0.0
    )
    report.metrics["avgTeachChars"] = round(avg_chars, 2)
    report.criteria.append(
        CriterionResult(
            id="minAvgTeachChars",
            passed=avg_chars >= THRESHOLDS["minAvgTeachChars"],
            severity="error",
            detail=f"avgTeachChars={avg_chars:.0f}",
            value=round(avg_chars, 2),
        )
    )

    # 5. Không trùng tiêu đề bài học.
    titles = [lesson.title for lesson in lessons]
    dup_titles = len(titles) - len({_norm(t) for t in titles})
    report.metrics["duplicateTitleRatio"] = round(
        dup_titles / max(1, len(titles)), 4
    )
    report.criteria.append(
        CriterionResult(
            id="duplicateTitleRatio",
            passed=(dup_titles / max(1, len(titles)))
            <= THRESHOLDS["maxDuplicateTitleRatio"],
            severity="error",
            detail=f"duplicateTitles={dup_titles}",
            value=round(dup_titles / max(1, len(titles)), 4),
        )
    )

    # 6. Cross-lesson repetition — câu hỏi lặp giữa các bài.
    questions = [
        _norm(_question_text(b)) for blocks in blocks_per_lesson for b in blocks if _question_text(b)
    ]
    questions = [q for q in questions if q]
    dup_questions = len(questions) - len(set(questions))
    dup_ratio = dup_questions / max(1, len(questions))
    report.metrics["crossLessonDuplicateQuestionRatio"] = round(dup_ratio, 4)
    report.criteria.append(
        CriterionResult(
            id="crossLessonDuplicateQuestionRatio",
            passed=dup_ratio <= THRESHOLDS["maxCrossLessonDuplicateQuestionRatio"],
            severity="warning",
            detail=f"duplicateQuestions={dup_questions}/{len(questions)}",
            value=round(dup_ratio, 4),
        )
    )

    # 7. Quiz bám bài: câu hỏi/giảng của bài phải chứa ít nhất một từ khoá lấy từ
    #    tiêu đề bài (hoặc skill outcome). Thuần từ vựng, không hiểu ngữ nghĩa.
    misaligned: list[str] = []
    for lesson in lessons:
        keywords = _words(lesson.title)
        if not keywords:
            continue
        lesson_text = " ".join(
            _block_text(b) for b in lesson.model_dump()["blocks"]
        ).casefold()
        if not any(k in lesson_text for k in keywords):
            misaligned.append(lesson.title)
    alignment = 1 - len(misaligned) / max(1, len(lessons))
    report.metrics["lessonQuizAlignment"] = round(alignment, 4)
    report.criteria.append(
        CriterionResult(
            id="lessonQuizAlignment",
            passed=alignment >= THRESHOLDS["minLessonQuizAlignment"],
            severity="warning",
            detail=f"misaligned={misaligned[:3]}",
            value=round(alignment, 4),
        )
    )

    # 8. Proposal khớp số bài thực sinh (không thiếu bài im lặng).
    report.metrics["expectedLessons"] = expected_lessons
    report.metrics["generatedLessons"] = len(lessons)
    report.criteria.append(
        CriterionResult(
            id="lessonCount",
            passed=len(lessons) == expected_lessons,
            severity="error",
            detail=f"generated={len(lessons)}/{expected_lessons}",
            value=len(lessons) / max(1, expected_lessons),
        )
    )

    # 9. Ngôn ngữ: với case tiếng Việt, phải còn dấu tiếng Việt trong nội dung.
    if language == "vi":
        vietnamese = re.compile(r"[ăâđêôơưàáảãạằắẳẵặèéẻẽẹìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.I)
        sample = " ".join(_block_text(b) for b in all_blocks)
        has_vi = bool(vietnamese.search(sample))
        report.criteria.append(
            CriterionResult(
                id="language",
                passed=has_vi,
                severity="warning",
                detail="có dấu tiếng Việt" if has_vi else "thiếu dấu tiếng Việt",
                value=1.0 if has_vi else 0.0,
            )
        )

    return report
