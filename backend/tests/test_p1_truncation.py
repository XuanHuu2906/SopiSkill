"""Tests cho P1-CONTENT-TRUNC: bắt mọi finish_reason='length', compact retry và completeness lint."""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import ProviderBudgetError, SchemaInvalidError
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.providers.validation import (
    check_lesson_completeness,
    check_text_completeness,
    validate_lesson,
)
from app.schemas.schemas import (
    CurriculumSkill,
    LessonContent,
    ProposalPayload,
    ProposalUnit,
)
from evals.rubric import evaluate_course


def _sample_proposal() -> ProposalPayload:
    return ProposalPayload(
        name="Python Basics",
        objective="Learn Python lists and loops.",
        units=[
            ProposalUnit(title="Unit 1", blurb="Basics", lessonTitles=["Lists"]),
            ProposalUnit(title="Unit 2", blurb="Loops", lessonTitles=["For loops"]),
        ],
        outcomes=["Use lists", "Write loops"],
        skills=[
            CurriculumSkill(id="s1", title="Lists", lesson="Lists", bloomLevel="apply", outcome="Use lists"),
            CurriculumSkill(id="s2", title="For loops", lesson="For loops", bloomLevel="apply", outcome="Write loops"),
        ],
        prerequisites=[("s1", "s2")],
    )


def _valid_lesson_dict() -> dict:
    return {
        "title": "Lists",
        "blocks": [
            {
                "type": "teach",
                "title": "Python Lists",
                "paragraphs": [
                    "A list stores ordered items such as `diem = [7, 8, 9]`.",
                    "You can append new elements with `diem.append(10)`.",
                ],
            },
            {
                "type": "mc",
                "question": "Which method adds an item to the end of a Python list?",
                "options": ["append()", "delete()", "split()"],
                "answerIndex": 0,
            },
        ],
    }


@pytest.mark.parametrize(
    "bad_text",
    [
        "Ví dụ danh sách: `diem = [7, 8,`",
        "```python\nx = [1, 2, 3]\nprint(x)",
        "Hàm `sum(a, b` dùng để tính tổng.",
        "Giá trị biến được gán như sau: x =",
        "Các bước gồm đọc dữ liệu, xử lý,",
        "Đoạn code `print('hello` bị cắt giữa chừng.",
    ],
)
def test_completeness_lint_catches_real_truncation_patterns(bad_text: str):
    assert check_text_completeness(bad_text, "test") is not None


@pytest.mark.parametrize(
    "good_text",
    [
        "Danh sách lưu các phần tử có thứ tự, ví dụ `diem = [7, 8, 9]`.",
        "```python\nx = [1, 2, 3]\nprint(x)\n```",
        "p99 latency 200ms nghĩa là 1% request vượt ngưỡng 200ms.",
        "Điền vào chỗ trống: Hàm ____ dùng để tính độ dài danh sách.",
        "Use `SELECT id, name FROM users WHERE active = 1;` to filter active rows.",
    ],
)
def test_completeness_lint_accepts_complete_text(good_text: str):
    assert check_text_completeness(good_text, "test") is None


def test_validate_lesson_rejects_truncated_paragraph():
    data = _valid_lesson_dict()
    data["blocks"][0]["paragraphs"][0] = "Ví dụ mảng bị cắt giữa chừng: `diem = [7, 8,`"
    lesson = LessonContent.model_validate(data)
    with pytest.raises(SchemaInvalidError, match="cắt cụt"):
        validate_lesson(lesson)


def test_eval_rubric_fails_completeness_on_truncated_lesson():
    data = _valid_lesson_dict()
    data["blocks"][0]["paragraphs"][0] = "Code bị cắt: `items = [1, 2,`"
    truncated_lesson = LessonContent.model_validate(data)
    report = evaluate_course(
        proposal=_sample_proposal(),
        lessons=[truncated_lesson],
        language="vi",
        expected_lessons=1,
    )
    comp = next(c for c in report.criteria if c.id == "completeness")
    assert comp.passed is False
    assert comp.severity == "error"
    assert report.metrics["truncatedLessons"] >= 1
    assert report.passed is False


@pytest.mark.asyncio
async def test_finish_reason_length_without_usage_triggers_compact_retry_and_succeeds():
    """Ngay cả khi provider KHÔNG trả usage (hoặc completion_tokens < max_tokens),
    finish_reason='length' vẫn bị coi là cắt cụt và kích hoạt 1 lần compact retry."""
    seen_requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_requests.append(body)
        if len(seen_requests) == 1:
            # Không trả `usage` nhưng finish_reason='length' — bug cũ sẽ bỏ lọt!
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": json.dumps(_valid_lesson_dict())},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(_valid_lesson_dict())},
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 450},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    lesson = await provider.generate_lesson(
        "Python", _sample_proposal(), "Unit 1", "Lists", [], language="en"
    )
    assert lesson.title == "Lists"
    assert len(seen_requests) == 2
    assert seen_requests[1]["max_tokens"] > seen_requests[0]["max_tokens"]
    assert "SHORTER, 100% COMPLETE" in seen_requests[1]["messages"][1]["content"]
    assert check_lesson_completeness(lesson) == []


@pytest.mark.asyncio
async def test_persistent_length_truncation_raises_budget_error_never_returns():
    """Nếu cả lượt compact retry vẫn finish_reason='length' → raise ProviderBudgetError."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"title":"Lists","blocks":[]}'},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 2000},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderBudgetError):
        await provider.generate_lesson(
            "Python", _sample_proposal(), "Unit 1", "Lists", [], language="en"
        )
    # Tối đa 2 lời gọi (1 gốc + 1 compact escalation), không lặp vô hạn.
    assert calls == 2
