"""2-Tier Lesson Validator QA (Phase 3 / DEC-023).

Tier 1 (mandatory deterministic):
  - Blocking errors: completeness lint, single-blank count, invalid MC answerIndex bounds.
  - Non-blocking warnings recorded to `core.content_flags`: duplicate MC options,
    answer leakage in blank/MC stem, overly brief teach block.

Tier 2 (opt-in LLM QA pass):
  - Runs when `VALIDATOR_LLM_ENABLED=true` OR Tier 1 raised warnings (only for real LLM providers,
    never incurring cost in Mock/CI mode).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.providers import LLMProvider
from app.agents.validation import validate_lesson_payload

logger = logging.getLogger(__name__)


@dataclass
class QaReport:
    blocking_errors: list[str] = field(default_factory=list)
    content_flags: list[dict[str, Any]] = field(default_factory=list)
    estimated_minutes: int = 5


def run_static_qa(lesson: dict[str, Any]) -> QaReport:
    blocking = validate_lesson_payload(lesson)
    flags: list[dict[str, Any]] = []
    blocks = lesson.get("blocks") or []

    total_words = 0
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "teach":
            paras = block.get("paragraphs") or []
            word_cnt = sum(len(str(p).split()) for p in paras)
            total_words += word_cnt
            if word_cnt < 10:
                flags.append(
                    {
                        "blockIndex": idx,
                        "source": "validator",
                        "code": "TEACH_TOO_BRIEF",
                        "severity": "warning",
                        "details": f"Teach block {idx} has only {word_cnt} words.",
                    }
                )
        elif btype == "mc":
            opts = [str(o).strip().casefold() for o in (block.get("options") or [])]
            if len(set(opts)) != len(opts):
                flags.append(
                    {
                        "blockIndex": idx,
                        "source": "validator",
                        "code": "MC_DUPLICATE_OPTIONS",
                        "severity": "warning",
                        "details": f"MC block {idx} contains duplicate option text.",
                    }
                )
            total_words += 20
        elif btype == "blank":
            sentence = str(block.get("sentence") or "").casefold()
            answer = str(block.get("answer") or "").strip().casefold()
            if answer and len(answer) >= 4 and answer in sentence:
                flags.append(
                    {
                        "blockIndex": idx,
                        "source": "validator",
                        "code": "BLANK_ANSWER_LEAKED_IN_STEM",
                        "severity": "warning",
                        "details": f"Blank block {idx} contains answer text inside sentence.",
                    }
                )
            total_words += 15
        else:
            total_words += 20

    # Estimate 4-12 minutes based on block count & reading volume
    est = max(3, min(15, round(len(blocks) * 0.7 + total_words / 160)))
    return QaReport(blocking_errors=blocking, content_flags=flags, estimated_minutes=est)


async def run_two_tier_validator(
    lesson: dict[str, Any],
    *,
    provider: LLMProvider,
    llm_qa_enabled: bool = False,
) -> QaReport:
    report = run_static_qa(lesson)
    if report.blocking_errors:
        return report

    # Tier 2 LLM QA pass (opt-in flag or warning escalation on real provider; 0 cost in mock mode)
    if (llm_qa_enabled or report.content_flags) and provider.name != "mock":
        try:
            verdict, _usage = await provider.grade_short_dispute(
                language="en",
                prompt="Audit this lesson JSON for factual contradictions or ambiguous quiz questions.",
                learner_answer=str(lesson.get("title") or ""),
                accepted_answers=["clear and accurate"],
                rubric="Return got_it if no critical quality issues, else not_yet with concise feedback.",
            )
            if not verdict.get("correct", True):
                report.content_flags.append(
                    {
                        "blockIndex": None,
                        "source": "validator",
                        "code": "LLM_QA_REVIEW_FLAG",
                        "severity": "warning",
                        "details": str(verdict.get("feedback") or "Flagged by Tier-2 LLM QA pass.")[:300],
                    }
                )
        except Exception as exc:  # noqa: BLE001 — Tier 2 QA is advisory, never blocks valid lesson
            logger.warning("tier2_llm_qa_skipped error_type=%s", type(exc).__name__)
    return report
