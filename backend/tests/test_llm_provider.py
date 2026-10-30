"""P2.0 — OpenAI-compatible adapter với mocked HTTP (không gọi mạng, không tốn tiền).

Bao phủ: output hợp lệ, JSON hỏng, schema sai, semantic sai, 429 (+ retry-after),
5xx, timeout, auth, budget, retry bounded, redaction log, fail-fast config.
"""

import json
import logging

import httpx
import pytest

from app.providers import (
    MockProvider,
    ProviderAuthError,
    ProviderBudgetError,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    SchemaInvalidError,
    get_provider,
)
from app.providers.base import LLMProvider
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.schemas.schemas import LessonContent, ProposalPayload, ProposalUnit


VALID_PROPOSAL = {
    "name": "Python căn bản",
    "objective": "Nắm cú pháp và viết được script nhỏ.",
    "units": [
        {"title": "Nền tảng", "blurb": "Cú pháp", "lessonTitles": ["Biến", "Kiểu dữ liệu"]},
        {"title": "Thực hành", "blurb": "Bài tập", "lessonTitles": ["Vòng lặp", "Hàm"]},
    ],
    "outcomes": ["Viết được script CLI", "Giải thích được kiểu dữ liệu"],
}

VALID_LESSON = {
    "title": "Biến trong Python",
    "blocks": [
        {"type": "teach", "title": "Biến", "paragraphs": ["Biến lưu giá trị."]},
        {"type": "mc", "question": "Cách khai báo?", "options": ["x = 1", "int x", "var x"], "answerIndex": 0},
        {"type": "blank", "sentence": "Từ khóa tạo hàm là ____ .", "answer": "def"},
        {"type": "order", "prompt": "Sắp xếp", "items": ["Khai báo", "Gán", "In"]},
        {"type": "match", "prompt": "Ghép", "pairs": [["int", "số nguyên"], ["str", "chuỗi"]]},
        {"type": "short", "question": "Học gì?", "acceptedAnswers": ["python"]},
    ],
}

VALID_INTERVIEW = {"questions": ["q1?", "q2?", "q3?", "q4?", "q5?"]}


def _provider(handler, **kwargs) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleProvider(
        api_key="sk-test-not-real",
        base_url="https://llm.test/v1",
        model="test-model",
        transport=transport,
        **kwargs,
    )


def _chat_response(content: dict | str, status: int = 200, headers: dict | None = None):
    body = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        status,
        headers=headers or {},
        json={
            "choices": [{"message": {"role": "assistant", "content": body}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 128},
        },
    )


# ---------- success paths ----------


async def test_interview_valid_output():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-not-real"
        return _chat_response(VALID_INTERVIEW)

    questions = await _provider(handler).generate_interview_questions("Python")
    assert len(questions) == 5


async def test_proposal_valid_output():
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert 0 < payload["max_tokens"] <= 2000
        return _chat_response(VALID_PROPOSAL)

    payload = await _provider(handler).generate_proposal("Python", ["q"] * 5, ["a"] * 5)
    assert isinstance(payload, ProposalPayload)
    assert len(payload.units) == 2


async def test_lesson_valid_output():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(VALID_LESSON)

    content = await _provider(handler).generate_lesson(
        "Python",
        ProposalPayload(**VALID_PROPOSAL),
        "Nền tảng",
        "Biến",
        [],
    )
    assert isinstance(content, LessonContent)
    assert {b.type for b in content.blocks} == {"teach", "mc", "blank", "order", "match", "short"}


async def test_json_fenced_output_is_accepted():
    fenced = "```json\n" + json.dumps(VALID_INTERVIEW) + "\n```"

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(fenced)

    assert len(await _provider(handler).generate_interview_questions("x")) == 5


# ---------- schema / semantic failures ----------


async def test_malformed_json_raises_schema_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("not json at all")

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_interview_questions("x")


async def test_non_object_json_raises_schema_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response("[1,2,3]")

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_interview_questions("x")


async def test_wrong_question_count_is_semantic_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"questions": ["q1?", "q2?"]})

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_interview_questions("x")


async def test_duplicate_questions_rejected():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response({"questions": ["q?", "q?", "a", "b", "c"]})

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_interview_questions("x")


async def test_proposal_duplicate_lesson_titles_rejected():
    bad = {**VALID_PROPOSAL}
    bad["units"] = [
        {"title": "U1", "blurb": "", "lessonTitles": ["Giống nhau"]},
        {"title": "U2", "blurb": "", "lessonTitles": ["Giống nhau"]},
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_proposal("x", ["q"] * 5, ["a"] * 5)


async def test_lesson_answer_index_out_of_bounds_rejected():
    bad = json.loads(json.dumps(VALID_LESSON))
    bad["blocks"][1]["answerIndex"] = 9

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_lesson(
            "x", ProposalPayload(**VALID_PROPOSAL), "u", "l", []
        )


async def test_lesson_without_teach_block_rejected():
    bad = {"title": "t", "blocks": [VALID_LESSON["blocks"][1]]}

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_lesson(
            "x", ProposalPayload(**VALID_PROPOSAL), "u", "l", []
        )


async def test_blank_answer_leaked_in_sentence_is_masked_not_rejected():
    """LLM hay trả câu đã chứa đáp án → server tự thay bằng chỗ trống (không đốt thêm request)."""
    leaked = json.loads(json.dumps(VALID_LESSON))
    leaked["blocks"][2]["sentence"] = "Từ khóa tạo hàm là def ."

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(leaked)

    content = await _provider(handler).generate_lesson(
        "x", ProposalPayload(**VALID_PROPOSAL), "u", "l", []
    )
    blank = next(b for b in content.blocks if b.type == "blank")
    assert blank.answer == "def"
    assert "def" not in blank.sentence
    assert "____" in blank.sentence


async def test_blank_without_marker_or_answer_in_sentence_rejected():
    bad = json.loads(json.dumps(VALID_LESSON))
    bad["blocks"][2]["sentence"] = "Câu này không có chỗ trống và không chứa đáp án."
    bad["blocks"][2]["answer"] = "def"

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError):
        await _provider(handler).generate_lesson(
            "x", ProposalPayload(**VALID_PROPOSAL), "u", "l", []
        )


# ---------- transport failures ----------


async def test_429_with_retry_after_is_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return _chat_response(VALID_INTERVIEW)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    questions = await _provider(handler).generate_interview_questions("x")
    assert len(questions) == 5
    assert calls["n"] == 2


async def test_429_exhausts_retries(monkeypatch):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "0"})

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    provider = _provider(handler)
    with pytest.raises(ProviderRateLimitError):
        await provider.generate_interview_questions("x")
    assert calls["n"] == provider.max_retries + 1  # 1 lần gọi + N retry


async def test_5xx_retried_bounded(monkeypatch):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    provider = _provider(handler)
    with pytest.raises(ProviderTransientError):
        await provider.generate_interview_questions("x")
    assert calls["n"] == provider.max_retries + 1


async def test_timeout_maps_to_provider_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ProviderTimeoutError):
        await _provider(handler).generate_interview_questions("x")


async def test_connection_error_is_transient(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    with pytest.raises(ProviderTransientError):
        await _provider(handler).generate_interview_questions("x")


async def test_auth_error_not_retried():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401)

    with pytest.raises(ProviderAuthError):
        await _provider(handler).generate_interview_questions("x")
    assert calls["n"] == 1  # không retry key sai


async def test_400_maps_to_schema_invalid_without_leaking_body():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "secret-internal-detail"})

    with pytest.raises(SchemaInvalidError) as info:
        await _provider(handler).generate_interview_questions("x")
    assert "secret-internal-detail" not in str(info.value)


async def test_budget_exceeded_when_hitting_token_cap():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(VALID_INTERVIEW)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2000},
            },
        )

    with pytest.raises(ProviderBudgetError):
        await _provider(handler).generate_interview_questions("x")


async def test_empty_content_is_transient():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    with pytest.raises(ProviderTransientError):
        await _provider(handler).generate_interview_questions("x")


# ---------- config fail-fast ----------


def test_missing_key_fails_fast():
    with pytest.raises(ProviderConfigError) as info:
        OpenAICompatibleProvider(api_key="", base_url="https://x/v1", model="m")
    assert info.value.code == "PROVIDER_NOT_CONFIGURED"
    assert info.value.retryable is False


def test_missing_model_or_base_url_fails_fast():
    with pytest.raises(ProviderConfigError):
        OpenAICompatibleProvider(api_key="k", base_url="", model="m")
    with pytest.raises(ProviderConfigError):
        OpenAICompatibleProvider(api_key="k", base_url="https://x/v1", model="")


def test_unknown_provider_is_not_mock(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "totally-unknown")
    with pytest.raises(ProviderConfigError):
        get_provider()


def test_mock_provider_is_explicit_choice():
    assert isinstance(MockProvider(), LLMProvider)


# ---------- log redaction ----------


async def test_logs_do_not_contain_key_or_prompt(caplog):
    secret = "sk-live-SUPER-SECRET"
    prompt_marker = "NỘI-DUNG-RIÊNG-CỦA-NGƯỜI-HỌC"

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(VALID_INTERVIEW)

    provider = OpenAICompatibleProvider(
        api_key=secret,
        base_url="https://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO):
        await provider.generate_interview_questions(prompt_marker)

    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert prompt_marker not in joined
    assert "test-model" in joined  # metadata hữu ích vẫn được log


async def test_input_is_truncated_to_configured_limit():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen["user"] = body["messages"][1]["content"]
        return _chat_response(VALID_INTERVIEW)

    from app.core.config import get_settings

    provider = _provider(handler)
    provider.max_input_chars = 50
    await provider.generate_interview_questions("x" * 500)
    assert len(seen["user"]) <= 50
