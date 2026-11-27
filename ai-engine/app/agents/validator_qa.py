"""2-Tier Lesson Validator QA (DEC-023) with canonical 6-code `content_flags` taxonomy.

Canonical 6 `content_flags` codes:
  - `figure_mismatch`  : invalid/mismatched figure layout or figure+image mutual exclusion conflict.
  - `unanswerable`     : missing premise (overly brief teach block) or empty prompt/answers.
  - `ambiguous`        : duplicate MC options or under-specified short-answer criteria.
  - `weak_distractors` : answer leaked inside blank stem or word bank lacking distractors.
  - `wrong_answer`     : out-of-bounds answer index or invalid answer structure.
  - `other`            : general Tier-2 LLM QA warning or structural issue.

Tier 1 (mandatory deterministic): runs always at 0 cost.
Tier 2 (opt-in LLM QA pass): runs when `VALIDATOR_LLM_ENABLED=true` OR Tier 1 raised warnings
(only for non-mock providers, never incurring cost in Mock/CI mode).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.figure_validator import validate_teach_media_and_figure
from app.agents.providers import LLMProvider
from app.agents.validation import validate_lesson_payload

logger = logging.getLogger(__name__)

CONTENT_FLAG_CODES: frozenset[str] = frozenset(
    {
        "figure_mismatch",
        "unanswerable",
        "ambiguous",
        "weak_distractors",
        "wrong_answer",
        "other",
    }
)


@dataclass
class QaReport:
    blocking_errors: list[str] = field(default_factory=list)
    content_flags: list[dict[str, Any]] = field(default_factory=list)
    estimated_minutes: int = 5


def _flag(
    *,
    block_index: int | None,
    code: str,
    details: str,
    rule: str,
    severity: str = "warning",
) -> dict[str, Any]:
    safe_code = code if code in CONTENT_FLAG_CODES else "other"
    return {
        "blockIndex": block_index,
        "source": "validator",
        "code": safe_code,
        "severity": severity,
        "rule": rule,
        "details": details[:300],
    }


def run_static_qa(lesson: dict[str, Any]) -> QaReport:
    blocking = validate_lesson_payload(lesson)
    flags: list[dict[str, Any]] = []
    blocks = lesson.get("blocks") or []

    total_words = 0
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            flags.append(
                _flag(
                    block_index=idx,
                    code="other",
                    rule="BLOCK_NOT_OBJECT",
                    severity="error",
                    details=f"Block {idx} is not an object.",
                )
            )
            continue

        btype = block.get("type")
        if btype == "teach":
            paras = block.get("paragraphs") or []
            word_cnt = sum(len(str(p).split()) for p in paras)
            total_words += word_cnt
            if word_cnt < 10:
                flags.append(
                    _flag(
                        block_index=idx,
                        code="unanswerable",
                        rule="TEACH_TOO_BRIEF",
                        details=f"Teach block {idx} has only {word_cnt} words; premise too brief.",
                    )
                )
            has_fig = isinstance(block.get("figure"), dict)
            has_img = isinstance(block.get("image"), dict)
            if has_fig and has_img:
                flags.append(
                    _flag(
                        block_index=idx,
                        code="figure_mismatch",
                        rule="FIGURE_IMAGE_CONFLICT",
                        severity="error",
                        details=f"Teach block {idx} has both figure and image.",
                    )
                )
            elif has_fig:
                fig_errs = validate_teach_media_and_figure(block, idx)
                if fig_errs:
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="figure_mismatch",
                            rule="FIGURE_SCHEMA_INVALID",
                            severity="error",
                            details="; ".join(fig_errs),
                        )
                    )
        elif btype == "mc":
            opts_raw = block.get("options") or []
            opts = [str(o).strip().casefold() for o in opts_raw]
            if len(opts) < 2:
                flags.append(
                    _flag(
                        block_index=idx,
                        code="weak_distractors",
                        rule="MC_TOO_FEW_OPTIONS",
                        severity="error",
                        details=f"MC block {idx} has fewer than 2 options.",
                    )
                )
            elif len(set(opts)) != len(opts):
                flags.append(
                    _flag(
                        block_index=idx,
                        code="ambiguous",
                        rule="MC_DUPLICATE_OPTIONS",
                        details=f"MC block {idx} contains duplicate option text.",
                    )
                )
            ans_idx = block.get("answerIndex")
            if not isinstance(ans_idx, int) or isinstance(ans_idx, bool) or ans_idx < 0 or ans_idx >= len(opts):
                flags.append(
                    _flag(
                        block_index=idx,
                        code="wrong_answer",
                        rule="MC_ANSWER_INDEX_OUT_OF_BOUNDS",
                        severity="error",
                        details=f"MC block {idx} has invalid answerIndex={ans_idx}.",
                    )
                )
            total_words += 20
        elif btype == "blank":
            sentence = str(block.get("sentence") or "").casefold()
            if isinstance(block.get("answers"), list):
                answers = [str(a).strip() for a in block.get("answers") or []]
                bank = [str(w).strip() for w in block.get("bank") or []]
                if not answers or any(not a for a in answers):
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="unanswerable",
                            rule="MULTI_BLANK_EMPTY_ANSWER",
                            severity="error",
                            details=f"Multi-blank block {idx} has empty answers.",
                        )
                    )
                if len(bank) <= len(answers):
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="weak_distractors",
                            rule="MULTI_BLANK_NO_DISTRACTOR",
                            details=f"Multi-blank block {idx} word bank needs at least 1 distractor.",
                        )
                    )
                missing_in_bank = [a for a in answers if a not in bank]
                if missing_in_bank:
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="wrong_answer",
                            rule="MULTI_BLANK_ANSWER_NOT_IN_BANK",
                            severity="error",
                            details=f"Multi-blank block {idx} answers missing from bank: {missing_in_bank}.",
                        )
                    )
            else:
                answer = str(block.get("answer") or "").strip().casefold()
                if not answer:
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="unanswerable",
                            rule="BLANK_EMPTY_ANSWER",
                            severity="error",
                            details=f"Blank block {idx} has empty answer.",
                        )
                    )
                elif len(answer) >= 4 and answer in sentence:
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="weak_distractors",
                            rule="BLANK_ANSWER_LEAKED_IN_STEM",
                            details=f"Blank block {idx} contains answer text inside sentence.",
                        )
                    )
            total_words += 15
        elif btype == "short":
            accepted = block.get("acceptedAnswers") or []
            if not accepted:
                flags.append(
                    _flag(
                        block_index=idx,
                        code="ambiguous",
                        rule="SHORT_NO_ACCEPTED_ANSWERS",
                        severity="error",
                        details=f"Short block {idx} has no acceptedAnswers.",
                    )
                )
            total_words += 20
        elif btype == "speed":
            items = block.get("items") or []
            for item_i, item in enumerate(items):
                choices = item.get("choices") if isinstance(item, dict) else None
                aidx = item.get("answerIndex") if isinstance(item, dict) else None
                if not isinstance(choices, list) or not isinstance(aidx, int) or aidx < 0 or aidx >= len(choices):
                    flags.append(
                        _flag(
                            block_index=idx,
                            code="wrong_answer",
                            rule="SPEED_ANSWER_OUT_OF_BOUNDS",
                            severity="error",
                            details=f"Speed block {idx} item {item_i} has invalid answerIndex.",
                        )
                    )
            total_words += 20
        else:
            total_words += 20

    # Estimate 3-15 minutes based on block count & reading volume
    est = max(3, min(15, round(len(blocks) * 0.7 + total_words / 160)))
    return QaReport(blocking_errors=blocking, content_flags=flags, estimated_minutes=est)


def verify_and_strip_ungrounded_block_citations(
    lesson: dict[str, Any],
    *,
    source_excerpts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Phase L5 Tier-1 Deterministic Locator Verification.

    Validates every `block.cite` on `teach` blocks strictly against the set of
    `(anchor, chunkId, pageNumber, sourceId)` returned by `read_source` in this session.
    Strips any hallucinated/ungrounded `cite` deterministically and returns warning flags.
    """
    blocks = lesson.get("blocks") if isinstance(lesson.get("blocks"), list) else []
    if not blocks:
        return []

    valid_anchors: set[str] = set()
    valid_chunk_ids: set[str] = set()
    valid_source_ids: set[str] = set()
    for ex in source_excerpts or []:
        if not isinstance(ex, dict):
            continue
        for key in ("anchor", "sectionAnchor"):
            val = str(ex.get(key) or "").strip()
            if val:
                valid_anchors.add(val)
        cid = str(ex.get("chunkId") or "").strip()
        if cid:
            valid_chunk_ids.add(cid)
        sid = str(ex.get("sourceId") or "").strip()
        if sid:
            valid_source_ids.add(sid)

    flags: list[dict[str, Any]] = []
    for idx, blk in enumerate(blocks):
        if not isinstance(blk, dict) or blk.get("type") != "teach":
            continue
        cite = blk.get("cite")
        if cite is None:
            continue
        if not isinstance(cite, dict):
            blk.pop("cite", None)
            flags.append(
                _flag(
                    block_index=idx,
                    code="other",
                    rule="CITATION_LOCATOR_INVALID",
                    details=f"Removed malformed cite object on teach block {idx}.",
                )
            )
            continue

        c_anchor = str(cite.get("anchor") or cite.get("sectionAnchor") or "").strip()
        c_chunk = str(cite.get("chunkId") or "").strip()
        c_source = str(cite.get("sourceId") or "").strip()

        verified = False
        if c_chunk and c_chunk in valid_chunk_ids:
            verified = True
        elif c_anchor and c_anchor in valid_anchors:
            verified = True
        elif not c_chunk and not c_anchor and c_source and c_source in valid_source_ids:
            verified = True

        # If source_id was explicitly provided, it MUST also match observed sources when we have source_ids
        if verified and c_source and valid_source_ids and c_source not in valid_source_ids:
            verified = False

        if not verified:
            blk.pop("cite", None)
            flags.append(
                _flag(
                    block_index=idx,
                    code="other",
                    rule="CITATION_LOCATOR_UNVERIFIED",
                    details=(
                        f"Stripped unverified cite (anchor={c_anchor!r}, chunkId={c_chunk!r}) "
                        f"on teach block {idx}: locator was not returned by read_source."
                    ),
                )
            )
    return flags


async def run_two_tier_validator(
    lesson: dict[str, Any],
    *,
    provider: LLMProvider,
    llm_qa_enabled: bool = False,
    source_excerpts: list[dict[str, Any]] | None = None,
) -> QaReport:
    report = run_static_qa(lesson)
    if source_excerpts is not None:
        stripped = verify_and_strip_ungrounded_block_citations(lesson, source_excerpts=source_excerpts)
        if stripped:
            logger.warning("tier1_stripped_unverified_citations count=%d", len(stripped))
    if report.blocking_errors:
        return report

    # Tier 2 LLM QA pass: native `flag_question` (6 codes) / `approve_lesson` tools on real provider (0 cost in mock mode)
    if (llm_qa_enabled or report.content_flags) and provider.name != "mock":
        try:
            tool_reviewer = getattr(provider, "review_lesson_with_tools", None)
            if callable(tool_reviewer):
                review_kwargs: dict[str, Any] = {
                    "lesson": lesson,
                    "static_flags": report.content_flags,
                    "language": "en",
                }
                if source_excerpts:
                    review_kwargs["source_excerpts"] = source_excerpts
                raw_flags, approved, _usage = await tool_reviewer(**review_kwargs)
                blocks = lesson.get("blocks") if isinstance(lesson.get("blocks"), list) else []
                existing_keys = {(f.get("blockIndex"), f.get("code")) for f in report.content_flags}
                for item in raw_flags:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("code") or "other")
                    if code not in CONTENT_FLAG_CODES:
                        code = "other"
                    b_idx = item.get("blockIndex")
                    safe_idx = b_idx if isinstance(b_idx, int) and 0 <= b_idx < len(blocks) else None
                    details = str(item.get("details") or "Flagged by Validator QA Agent.")[:400]
                    if (safe_idx, code) not in existing_keys:
                        existing_keys.add((safe_idx, code))
                        report.content_flags.append(
                            _flag(
                                block_index=safe_idx,
                                code=code,
                                rule="LLM_QA_FLAG_QUESTION",
                                details=details,
                            )
                        )
                if approved and not raw_flags:
                    logger.debug("tier2_llm_qa_approved title=%s", str(lesson.get("title") or "")[:80])
            else:
                verdict, _usage = await provider.grade_short_dispute(
                    language="en",
                    prompt="Audit this lesson JSON for factual contradictions, wrong answers, or ambiguous quiz questions.",
                    learner_answer=str(lesson.get("title") or ""),
                    accepted_answers=["clear and accurate"],
                    rubric="Return got_it if no critical quality issues, else not_yet with concise feedback.",
                )
                if not verdict.get("correct", True):
                    fb = str(verdict.get("feedback") or "Flagged by Tier-2 LLM QA pass.")
                    inferred_code = "wrong_answer" if "wrong" in fb.lower() else "other"
                    report.content_flags.append(
                        _flag(
                            block_index=None,
                            code=inferred_code,
                            rule="LLM_QA_REVIEW_FLAG",
                            details=fb,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — Tier 2 QA is advisory, never blocks valid lesson
            logger.warning("tier2_llm_qa_skipped error_type=%s", type(exc).__name__)
    return report
