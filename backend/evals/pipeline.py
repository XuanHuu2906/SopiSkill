"""P2.2 eval pipeline — chạy dataset qua provider, chấm rubric, thu usage/cost.

Mọi kết quả đều ghi rõ **cái gì đã chạy**: `provider`, `model`, `promptVersion`,
`usedLlm`, `judge.status`. Mock được ghi là mock; judge không chạy được thì ghi
`not_run` chứ không tạo điểm giả.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import LLMProvider
from app.providers.usage import collect_usage
from app.schemas.schemas import LessonContent, ProposalPayload
from app.services import pedagogy
from evals.dataset import EvalCase
from evals.judges import JudgeResult, judge_course
from evals.rubric import evaluate_course

EVAL_VERSION = "p2.2-v1"


@dataclass
class CaseResult:
    id: str
    topic: str
    language: str
    level: str
    ambiguity: str
    provider: str
    model: str
    interview_ok: bool = False
    proposal_ok: bool = False
    curriculum_ok: bool = False
    lessons_total: int = 0
    lessons_ok: int = 0
    lesson_failures: list[str] = field(default_factory=list)
    rubric: dict = field(default_factory=dict)
    judge: dict | None = None
    usage: dict = field(default_factory=dict)
    latency_seconds: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return (
            self.interview_ok
            and self.proposal_ok
            and self.curriculum_ok
            and self.error is None
            and bool(self.rubric.get("passed"))
        )
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "language": self.language,
            "level": self.level,
            "ambiguity": self.ambiguity,
            "provider": self.provider,
            "model": self.model,
            "interviewOk": self.interview_ok,
            "proposalOk": self.proposal_ok,
            "curriculumOk": self.curriculum_ok,
            "lessonsTotal": self.lessons_total,
            "lessonsOk": self.lessons_ok,
            "lessonFailures": self.lesson_failures,
            "rubric": self.rubric,
            "judge": self.judge,
            "usage": self.usage,
            "latencySeconds": self.latency_seconds,
            "error": self.error,
            "passed": self.passed,
        }


async def run_case(
    provider: LLMProvider,
    case: EvalCase,
    *,
    model: str,
    run_judge: bool = False,
) -> CaseResult:
    result = CaseResult(
        id=case.id,
        topic=case.topic,
        language=case.language,
        level=case.level,
        ambiguity=case.ambiguity,
        provider=provider.name,
        model=model,
    )
    started = time.perf_counter()
    proposal_payload: ProposalPayload | None = None
    lessons: list[LessonContent] = []

    with collect_usage() as usage:
        try:
            questions = await provider.generate_interview_questions(case.topic)
            result.interview_ok = len(questions) == 5

            proposal_payload = await provider.generate_proposal(
                case.topic, questions, list(case.answers)
            )
            proposal_payload.learnerProfile = pedagogy.extract_learner_profile(
                questions, list(case.answers)
            )
            proposal_payload = pedagogy.normalize_curriculum(proposal_payload)
            pedagogy.validate_curriculum(proposal_payload)
            result.proposal_ok = True
            result.curriculum_ok = True

            titles = pedagogy.lesson_order(proposal_payload)
            result.lessons_total = len(titles)
            previous: list[str] = []
            for unit in proposal_payload.units:
                for title in unit.lessonTitles:
                    try:
                        lesson = await provider.generate_lesson(
                            case.topic, proposal_payload, unit.title, title, previous
                        )
                    except Exception as exc:  # noqa: BLE001 — ghi từng bài lỗi
                        result.lesson_failures.append(
                            f"{title}: {type(exc).__name__}: {str(exc)[:160]}"
                        )
                        continue
                    lessons.append(lesson)
                    result.lessons_ok += 1
                    previous.append(lesson.title)
        except Exception as exc:  # noqa: BLE001
            result.error = f"{type(exc).__name__}: {str(exc)[:300]}"

        result.usage = usage.summary(_pricing())

    result.latency_seconds = round(time.perf_counter() - started, 2)

    if proposal_payload is not None:
        result.rubric = evaluate_course(
            proposal=proposal_payload,
            lessons=lessons,
            language=case.language,
            expected_lessons=result.lessons_total,
            min_quiz_per_lesson=case.min_quiz_per_lesson,
        ).to_dict()

        if run_judge:
            # Judge chạy trong collector riêng để usage của judge không trộn với
            # usage sinh nội dung (báo cáo phải tách được chi phí hai phần).
            with collect_usage() as judge_usage_collector:
                judge: JudgeResult = await judge_course(
                    provider,
                    topic=case.topic,
                    language=case.language,
                    level=case.level,
                    proposal=proposal_payload.model_dump(),
                    lessons=[lesson.model_dump() for lesson in lessons],
                    model=model,
                )
                judge_usage = judge_usage_collector.summary(_pricing())
            result.judge = judge.to_dict()
            result.usage["judge"] = {
                "calls": judge_usage["calls"],
                "promptTokens": judge_usage["promptTokens"],
                "completionTokens": judge_usage["completionTokens"],
                "costEstimateUsd": judge_usage["costEstimateUsd"],
                "costKnown": judge_usage["costKnown"],
            }
    else:
        result.rubric = {
            "passed": False,
            "criteria": [],
            "metrics": {},
            "note": "Không có proposal ⇒ không chấm rubric.",
        }

    return result


def _pricing() -> dict:
    from app.core.config import get_settings
    from app.providers.usage import parse_pricing

    return parse_pricing(get_settings().llm_pricing_json)


def summary(results: list[CaseResult]) -> dict[str, Any]:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    usable_usage = [r.usage for r in results if isinstance(r.usage, dict)]
    judge_scored = [
        r for r in results if r.judge and r.judge.get("status") == "scored"
    ]
    judge_avgs = [
        r.judge["averageScore"]
        for r in judge_scored
        if r.judge.get("averageScore") is not None
    ]
    costs = [
        u.get("costEstimateUsd") for u in usable_usage if u.get("costEstimateUsd") is not None
    ]
    return {
        "topics": total,
        "passed": passed,
        "passRate": round(passed / total, 4) if total else 0.0,
        "llmCalls": sum(u.get("calls", 0) or 0 for u in usable_usage),
        "promptTokens": sum(u.get("promptTokens", 0) or 0 for u in usable_usage),
        "completionTokens": sum(
            u.get("completionTokens", 0) or 0 for u in usable_usage
        ),
        "costEstimateUsd": round(sum(costs), 6) if costs else None,
        "costKnown": len(costs) == len(usable_usage) and bool(usable_usage),
        "judge": {
            "requested": any(r.judge is not None for r in results),
            "scored": len(judge_scored),
            "notRun": sum(
                1 for r in results if r.judge and r.judge.get("status") == "not_run"
            ),
            "averageScore": round(sum(judge_avgs) / len(judge_avgs), 2)
            if judge_avgs
            else None,
        },
    }
