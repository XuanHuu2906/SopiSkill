"""P2.2 — eval dataset, rubric, judge contract và regression (offline, không tốn tiền).

Không chạy provider thật ở đây. Provider thật dùng `evals.runner` có --yes.
"""

import httpx
import pytest

from app.providers.base import ProviderConfigError
from app.providers.mock_provider import MockProvider
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.schemas.schemas import LessonContent, ProposalPayload
from evals.dataset import EVAL_CASES, dataset_summary, get_cases
from evals.judges import JUDGE_PROMPT_VERSION, judge_course
from evals.pipeline import run_case, summary
from evals.regression import compare_reports
from evals.rubric import HUMAN_RUBRIC, THRESHOLDS, evaluate_course


def _proposal() -> ProposalPayload:
    return ProposalPayload.model_validate(
        {
            "name": "Course",
            "objective": "Học được điều gì đó hữu ích.",
            "units": [
                {"title": "Nền tảng", "blurb": "a", "lessonTitles": ["Giới thiệu Python", "Biến"]},
                {"title": "Thực hành", "blurb": "b", "lessonTitles": ["Vòng lặp", "Hàm"]},
            ],
            "outcomes": ["Giải thích được Python", "Viết được hàm"],
        }
    )


def _lesson(title: str, *, quiz: bool = True) -> LessonContent:
    blocks = [
        {
            "type": "teach",
            "title": title,
            "paragraphs": [
                f"Bài {title} giải thích khái niệm cốt lõi bằng ví dụ chạy được và cảnh báo lỗi phổ biến.",
            ],
        }
    ]
    if quiz:
        blocks.append(
            {
                "type": "mc",
                "question": f"Câu hỏi kiểm tra kiến thức trong bài {title}?",
                "options": [f"Đáp án đúng về {title}", "Sai 1", "Sai 2"],
                "answerIndex": 0,
            }
        )
    return LessonContent.model_validate({"title": title, "blocks": blocks})


# ---------- dataset ----------


def test_dataset_has_at_least_ten_varied_topics():
    summary_data = dataset_summary()
    assert summary_data["topics"] >= 10
    assert {"vi", "en"} <= set(summary_data["languages"])
    assert {"beginner", "intermediate", "advanced"} <= set(summary_data["levels"])
    assert "ambiguous" in summary_data["ambiguity"]


def test_dataset_cases_have_five_answers_and_unique_ids():
    ids = [c.id for c in EVAL_CASES]
    assert len(ids) == len(set(ids))
    for case in EVAL_CASES:
        assert len(case.answers) == 5, case.id
        assert case.topic.strip()
        assert case.min_lessons <= case.max_lessons


def test_get_cases_rejects_unknown_id():
    with pytest.raises(ValueError):
        get_cases(ids=["does-not-exist"])


# ---------- rubric ----------


def test_rubric_passes_clean_course():
    lessons = [_lesson(t) for t in ("Giới thiệu Python", "Biến", "Vòng lặp", "Hàm")]
    report = evaluate_course(
        proposal=_proposal(),
        lessons=lessons,
        language="vi",
        expected_lessons=4,
    )
    assert report.passed, report.to_dict()


def test_rubric_fails_when_lesson_missing_quiz():
    lessons = [_lesson(t, quiz=(i != 2)) for i, t in enumerate(("Giới thiệu Python", "Biến", "Vòng lặp", "Hàm"))]
    report = evaluate_course(
        proposal=_proposal(), lessons=lessons, language="vi", expected_lessons=4
    )
    failed = {c.id for c in report.criteria if not c.passed}
    assert "quizPerLesson" in failed
    assert not report.passed


def test_rubric_fails_when_expected_lesson_missing():
    lessons = [_lesson("Giới thiệu Python")]
    report = evaluate_course(
        proposal=_proposal(), lessons=lessons, language="vi", expected_lessons=4
    )
    assert not report.passed
    assert report.metrics["generatedLessons"] == 1


def test_rubric_flags_empty_teach_paragraphs():
    lesson = LessonContent.model_validate(
        {
            "title": "Hàm",
            "blocks": [
                {"type": "teach", "title": "Hàm", "paragraphs": ["Hàm."]},
                {"type": "mc", "question": "Hàm là gì?", "options": ["a", "b"], "answerIndex": 0},
            ],
        }
    )
    report = evaluate_course(
        proposal=_proposal(), lessons=[lesson], language="vi", expected_lessons=1
    )
    failed = {c.id for c in report.criteria if not c.passed}
    # excerpt ngắn vẫn qua lint nhưng bị bắt bởi độ dài trung bình
    assert "minAvgTeachChars" in failed


def test_rubric_warns_on_cross_lesson_duplicate_questions():
    lessons = [_lesson("Giới thiệu Python") for _ in range(4)]
    report = evaluate_course(
        proposal=_proposal(), lessons=lessons, language="vi", expected_lessons=4
    )
    warnings = {c.id: c for c in report.criteria if c.severity == "warning"}
    assert warnings["crossLessonDuplicateQuestionRatio"].passed is False


def test_rubric_thresholds_are_serialisable_contract():
    assert 0 <= THRESHOLDS["lessonPassRate"] <= 1
    assert set(THRESHOLDS) >= {"lessonPassRate", "quizPerLesson", "minAvgTeachChars"}
    criteria, scale, note = HUMAN_RUBRIC
    assert len(criteria) >= 5
    assert "0" in scale and "4" in scale
    assert note


# ---------- judge ----------


async def test_mock_provider_cannot_judge_and_does_not_fake_scores():
    result = await judge_course(
        MockProvider(),
        topic="Python",
        language="vi",
        level="beginner",
        proposal={"name": "x"},
        lessons=[{"title": "y"}],
    )
    assert result.status == "not_run"
    assert result.usedLlm is False
    assert result.averageScore is None
    assert result.scores == {}
    data = result.to_dict()
    assert data["promptVersion"] == JUDGE_PROMPT_VERSION
    assert "ground truth" in data["disclaimer"]


async def test_judge_parses_scores_and_ignores_out_of_range():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"scores": {"objective_clarity": 3, "level_fit": 99, "made_up": 4, "safety": null}, "notes": ["ok"]}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="sk-test",
        base_url="https://llm.test/v1",
        model="judge-model",
        transport=httpx.MockTransport(handler),
    )
    result = await judge_course(
        provider,
        topic="Python",
        language="vi",
        level="beginner",
        proposal={"name": "x"},
        lessons=[{"title": "y"}],
    )
    assert result.status == "scored"
    assert result.usedLlm is True
    assert result.scores["objective_clarity"] == 3.0
    assert result.scores["level_fit"] is None  # ngoài 0..4 ⇒ không nhận
    assert "made_up" not in result.scores
    assert result.averageScore == 3.0


async def test_judge_without_request_json_support_is_not_run():
    class NoJudgeProvider(MockProvider):
        name = "no-judge"

    result = await judge_course(
        NoJudgeProvider(),
        topic="t",
        language="vi",
        level="beginner",
        proposal={},
        lessons=[],
    )
    # MockProvider kế thừa base → ProviderConfigError ⇒ not_run (không bịa điểm)
    assert result.status == "not_run"
    assert isinstance(ProviderConfigError(), ProviderConfigError)


# ---------- pipeline ----------


async def test_pipeline_mock_run_is_deterministic_and_labels_mock():
    case = get_cases(ids=["vi-beginner-python"])[0]
    result = await run_case(MockProvider(), case, model="mock")
    assert result.provider == "mock"
    assert result.model == "mock"
    assert result.passed
    assert result.lessons_ok == result.lessons_total == 4
    assert result.usage["costEstimateUsd"] is None  # chưa cấu hình giá
    assert result.judge is None


async def test_pipeline_summary_counts_only_deterministic_pass():
    cases = get_cases(limit=3)
    results = [await run_case(MockProvider(), c, model="mock") for c in cases]
    totals = summary(results)
    assert totals["topics"] == 3
    assert totals["passed"] == 3
    assert totals["costKnown"] is False
    assert totals["judge"]["requested"] is False


# ---------- regression ----------


def _report(provider: str, prompt: str, topics: list[tuple[str, bool]], judge_avg=None):
    return {
        "provider": provider,
        "model": "m",
        "promptVersion": prompt,
        "topics": [{"id": i, "passed": p} for i, p in topics],
        "totals": {
            "topics": len(topics),
            "passed": sum(1 for _, p in topics if p),
            "passRate": sum(1 for _, p in topics if p) / len(topics),
            "judge": {"averageScore": judge_avg},
        },
    }


def test_regression_identical_reports_pass():
    report = _report("mock", "p1", [("a", True), ("b", True)])
    result = compare_reports(report, report)
    assert result.comparable
    assert result.passed


def test_regression_detects_major_drop():
    base = _report("openai", "p1", [(str(i), True) for i in range(10)])
    cand = _report("openai", "p1", [(str(i), i < 7) for i in range(10)])
    result = compare_reports(base, cand)
    assert result.comparable
    assert not result.passed
    assert result.deltas["passRateDrop"] == pytest.approx(0.3)
    assert len(result.deltas["newFailures"]) == 3


def test_regression_detects_judge_average_drop():
    base = _report("openai", "p1", [("a", True)], judge_avg=3.6)
    cand = _report("openai", "p1", [("a", True)], judge_avg=2.4)
    result = compare_reports(base, cand)
    assert not result.passed


def test_regression_marks_incomparable_and_does_not_fail():
    base = _report("mock", "p1", [("a", True), ("b", True)])
    cand = _report("openai", "p1", [("a", False), ("b", False)])
    result = compare_reports(base, cand)
    assert not result.comparable
    assert result.passed  # không kết luận regression giữa 2 provider khác nhau
