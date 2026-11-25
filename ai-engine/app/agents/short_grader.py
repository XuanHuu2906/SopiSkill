"""Short-answer grader: exact match + diacritic-folded semantic rubric + bounded LLM dispute."""

from __future__ import annotations

import re
import unicodedata

from app.agents.providers import LLMProvider, ProviderConfigError, ProviderTransientError
from app.schemas.internal import GradeShortRequest, GradeShortResponse, LlmUsageOut

_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def _fold_tokens(text: str) -> list[str]:
    raw = (text or "").strip().lower().replace("đ", "d")
    nfkd = unicodedata.normalize("NFKD", raw)
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    cleaned = _NON_WORD_RE.sub(" ", no_accents)
    return [tok for tok in cleaned.split() if tok]


async def grade_short_answer(
    req: GradeShortRequest,
    provider: LLMProvider,
) -> GradeShortResponse:
    learner_raw = req.learnerAnswer.strip()
    if not learner_raw:
        return GradeShortResponse(
            correct=False,
            verdict="not_yet",
            keyPoints=[],
            feedback="Answer is empty." if req.language == "en" else "Câu trả lời đang để trống.",
            method="exact",
            usage=LlmUsageOut(provider=provider.name, model=provider.model),
        )

    ans_tokens = _fold_tokens(learner_raw)
    ans_joined = " ".join(ans_tokens)
    ans_set = set(ans_tokens)

    # 1. Exact folded match
    for candidate in req.acceptedAnswers:
        cand_tokens = _fold_tokens(candidate)
        if cand_tokens and " ".join(cand_tokens) == ans_joined:
            return GradeShortResponse(
                correct=True,
                verdict="got_it",
                keyPoints=[candidate.strip()],
                feedback="Exact match!" if req.language == "en" else "Chính xác!",
                method="exact",
                usage=LlmUsageOut(provider=provider.name, model=provider.model),
            )

    # 2. Deterministic keyword rubric (recall >= 0.8, precision >= 0.5 for >=2-token answers)
    best_recall = 0.0
    for candidate in req.acceptedAnswers:
        cand_tokens = _fold_tokens(candidate)
        if len(cand_tokens) < 2 or not ans_set:
            continue
        cand_set = set(cand_tokens)
        overlap = len(cand_set & ans_set)
        recall = overlap / len(cand_set)
        precision = overlap / len(ans_set)
        best_recall = max(best_recall, recall)
        if recall >= 0.8 and precision >= 0.5:
            return GradeShortResponse(
                correct=True,
                verdict="got_it",
                keyPoints=[candidate.strip()],
                feedback=(
                    "Correct — matches key rubric concepts."
                    if req.language == "en"
                    else "Chính xác — câu trả lời khớp với ý chính theo tiêu chí chấm."
                ),
                method="semantic_rubric",
                usage=LlmUsageOut(provider=provider.name, model=provider.model),
            )

    # 3. Optional bounded LLM dispute re-check (prompt-injection delimited inside provider)
    if req.dispute:
        try:
            verdict_data, usage = await provider.grade_short_dispute(
                language=req.language,
                prompt=req.prompt,
                learner_answer=learner_raw,
                accepted_answers=req.acceptedAnswers,
                rubric=req.rubric,
            )
            correct = bool(verdict_data.get("correct", False))
            verdict = verdict_data.get("verdict")
            if verdict not in ("got_it", "almost", "not_yet"):
                verdict = "got_it" if correct else "not_yet"
            key_points = [str(kp) for kp in (verdict_data.get("keyPoints") or [])[:5]]
            feedback = str(
                verdict_data.get("feedback")
                or ("Reviewed against rubric." if req.language == "en" else "Đã chấm lại theo tiêu chí.")
            )
            return GradeShortResponse(
                correct=correct,
                verdict=verdict,
                keyPoints=key_points,
                feedback=feedback,
                method="llm_dispute",
                usage=usage,
            )
        except (ProviderConfigError, ProviderTransientError, ValueError):
            return GradeShortResponse(
                correct=False,
                verdict="almost" if best_recall >= 0.5 else "not_yet",
                keyPoints=[],
                feedback=(
                    "Could not reach AI reviewer; deterministic verdict preserved."
                    if req.language == "en"
                    else "Không thể gọi chấm lại AI lúc này; giữ kết quả đối chiếu tiêu chí."
                ),
                method="fallback",
                usage=LlmUsageOut(provider=provider.name, model=provider.model),
            )

    verdict = "almost" if best_recall >= 0.5 else "not_yet"
    return GradeShortResponse(
        correct=False,
        verdict=verdict,
        keyPoints=[],
        feedback=(
            "Close — include the core key term."
            if (verdict == "almost" and req.language == "en")
            else "Gần đúng — hãy bổ sung thêm ý cốt lõi."
            if verdict == "almost"
            else "Does not match rubric yet."
            if req.language == "en"
            else "Chưa khớp đáp án mẫu theo tiêu chí."
        ),
        method="semantic_rubric",
        usage=LlmUsageOut(provider=provider.name, model=provider.model),
    )
