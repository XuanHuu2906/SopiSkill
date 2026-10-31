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
        assert payload["max_tokens"] == _provider(handler).max_tokens_by_kind["proposal"]
        assert payload["max_tokens"] <= 6000
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


# ---------- P2.1 — prompt version, learner profile & curriculum ----------


def _valid_curriculum_proposal() -> dict:
    data = json.loads(json.dumps(VALID_PROPOSAL))
    titles = [t for unit in data["units"] for t in unit["lessonTitles"]]
    data["skills"] = [
        {"id": f"s{i}", "title": t, "lesson": t, "bloomLevel": "understand", "outcome": f"Hiểu {t}"}
        for i, t in enumerate(titles)
    ]
    data["prerequisites"] = [
        [f"s{i}", f"s{i + 1}"] for i in range(len(titles) - 1)
    ]
    return data


async def test_prompt_version_is_p30_with_p21_curriculum():
    from app.providers import openai_compatible_provider as adapter

    assert adapter.PROMPT_VERSION == "p3.0-v1"
    assert "1)" in adapter.INTERVIEW_SYSTEM and "5)" in adapter.INTERVIEW_SYSTEM
    assert "prerequisites" in adapter.PROPOSAL_SYSTEM
    assert "mục tiêu của bài" in adapter.LESSON_SYSTEM
    # P3.0 — model bị cấm tự tạo citation/URL/sourceId.
    assert "sourceId" in adapter.LESSON_SYSTEM
    assert "không tự tạo URL" in adapter.LESSON_SYSTEM


async def test_interview_prompt_covers_five_facets_and_forbids_sensitive_data():
    from app.providers import openai_compatible_provider as adapter

    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["system"] = json.loads(request.content)["messages"][0]["content"]
        return _chat_response(VALID_INTERVIEW)

    await _provider(handler).generate_interview_questions("Python")
    system = seen["system"]
    for facet in ("trình độ", "mục tiêu", "thời gian", "phong cách", "rộng/sâu"):
        assert facet in system
    assert "nhạy cảm" in system


async def test_proposal_prompt_includes_server_derived_profile():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return _chat_response(_valid_curriculum_proposal())

    payload = await _provider(handler).generate_proposal(
        "Python",
        [f"q{i}" for i in range(5)],
        [
            "Mình chưa từng học",
            "Muốn làm web app",
            "3 giờ mỗi tuần",
            "Thích thực hành",
            "Muốn đi sâu",
        ],
    )
    assert "Hồ sơ tóm tắt" in seen["user"]
    assert "beginner" in seen["user"]
    assert "180" in seen["user"]
    assert len(payload.skills) == sum(len(u.lessonTitles) for u in payload.units)


async def test_lesson_prompt_passes_skill_and_prerequisite_context():
    seen = {}
    proposal = ProposalPayload(**_valid_curriculum_proposal())

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["user"] = json.loads(request.content)["messages"][1]["content"]
        return _chat_response(VALID_LESSON)

    await _provider(handler).generate_lesson(
        "Python", proposal, "Nền tảng", "Kiểu dữ liệu", ["Biến"]
    )
    assert "Kỹ năng:" in seen["user"]
    assert "Bloom:" in seen["user"]
    assert "Kỹ năng tiên quyết: Biến" in seen["user"]


async def test_proposal_cycle_from_llm_is_rejected():
    bad = _valid_curriculum_proposal()
    bad["prerequisites"] = [["s0", "s1"], ["s1", "s2"], ["s2", "s0"]]

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError, match="chu trình"):
        await _provider(handler).generate_proposal("x", ["q"] * 5, ["a"] * 5)


async def test_proposal_missing_curriculum_is_filled_not_failed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(VALID_PROPOSAL)

    payload = await _provider(handler).generate_proposal("x", ["q"] * 5, ["a"] * 5)
    titles = [t for u in payload.units for t in u.lessonTitles]
    assert [s.lesson for s in payload.skills] == titles


async def test_lesson_with_duplicate_questions_from_llm_is_rejected():
    bad = json.loads(json.dumps(VALID_LESSON))
    bad["blocks"][4]["prompt"] = bad["blocks"][1]["question"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(bad)

    with pytest.raises(SchemaInvalidError, match="lặp"):
        await _provider(handler).generate_lesson(
            "x", ProposalPayload(**VALID_PROPOSAL), "u", "l", []
        )


# ---------- P2.1 — token budget theo loại call ----------


async def test_max_tokens_is_per_call_kind():
    seen: dict[str, int] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        kind = "proposal" if "prerequisites" in system else "lesson" if "block" in system else "interview"
        seen[kind] = body["max_tokens"]
        if kind == "interview":
            return _chat_response(VALID_INTERVIEW)
        if kind == "proposal":
            return _chat_response(_valid_curriculum_proposal())
        return _chat_response(VALID_LESSON)

    provider = _provider(handler)
    await provider.generate_interview_questions("Python")
    await provider.generate_proposal("Python", ["q"] * 5, ["a"] * 5)
    await provider.generate_lesson(
        "Python", ProposalPayload(**_valid_curriculum_proposal()), "u", "l", []
    )

    kinds = provider.max_tokens_by_kind
    assert kinds["interview"] < kinds["lesson"] < kinds["proposal"]
    assert seen == kinds


async def test_budget_check_uses_call_specific_limit():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(VALID_INTERVIEW)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1000},
            },
        )

    provider = _provider(handler)
    assert provider.max_tokens_by_kind["interview"] < 1000
    with pytest.raises(ProviderBudgetError):
        await provider.generate_interview_questions("x")


async def test_usage_is_logged_even_when_budget_is_exceeded(caplog):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(VALID_INTERVIEW)}}],
                "usage": {"prompt_tokens": 77, "completion_tokens": 999_999},
            },
        )

    with caplog.at_level(logging.INFO):
        with pytest.raises(ProviderBudgetError):
            await _provider(handler).generate_interview_questions("x")

    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "prompt_tokens=77" in joined, "request đã tốn tiền vẫn phải có log usage"


# ---------- P2.1 — budget dựa trên truncation, không phải tổng token ----------


def _response_with_usage(completion_tokens: int, finish_reason: str | None, content=None):
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": json.dumps(content or VALID_INTERVIEW)},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": completion_tokens},
    }
    return httpx.Response(200, json=body)


async def test_complete_output_at_token_cap_is_not_budget_error():
    """Model reasoning tính reasoning tokens vào completion_tokens.

    `finish_reason=stop` nghĩa là output xong → không được báo vượt budget chỉ vì
    con số token chạm trần (đây là false positive đã gặp với eval thật).
    """
    limit = _provider(lambda r: None).max_tokens_by_kind["interview"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return _response_with_usage(limit, "stop")

    questions = await _provider(handler).generate_interview_questions("x")
    assert len(questions) == 5


async def test_truncated_output_escalates_budget_once_then_succeeds(monkeypatch):
    """Bị cắt ở trần cấu hình → leo thang 1 lần (bounded) rồi dùng output hoàn chỉnh."""
    calls: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested = json.loads(request.content)["max_tokens"]
        calls.append(requested)
        if len(calls) == 1:
            return _response_with_usage(requested, "length")
        return _response_with_usage(100, "stop")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    questions = await _provider(handler).generate_interview_questions("x")
    assert len(questions) == 5
    assert len(calls) == 2
    assert calls[1] > calls[0], "lần 2 phải có ngân sách cao hơn"


async def test_permanently_truncated_output_fails_bounded(monkeypatch):
    """Vẫn bị cắt sau khi leo thang → báo lỗi, số request bị chặn (không đốt tiền)."""
    calls: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested = json.loads(request.content)["max_tokens"]
        calls.append(requested)
        return _response_with_usage(requested, "length")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.providers.openai_compatible_provider.asyncio.sleep", no_sleep)
    provider = _provider(handler)
    with pytest.raises(ProviderBudgetError):
        await provider.generate_interview_questions("x")
    assert len(calls) <= provider.max_retries + 1
    assert calls[-1] <= provider.max_tokens_by_kind["interview"] * 2


async def test_unknown_finish_reason_at_cap_is_treated_as_truncated():
    limit = _provider(lambda r: None).max_tokens_by_kind["interview"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return _response_with_usage(limit, None)

    with pytest.raises(ProviderBudgetError):
        await _provider(handler).generate_interview_questions("x")


# ---------- P2.1 — bounded schema repair ----------


async def test_schema_failure_is_repaired_with_second_request():
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        calls.append(user)
        if len(calls) == 1:
            return _chat_response({"questions": ["chỉ một câu?"]})
        return _chat_response(VALID_INTERVIEW)

    monkeypatch_provider = _provider(handler)
    assert monkeypatch_provider.max_schema_retries == 1
    questions = await monkeypatch_provider.generate_interview_questions("Python")
    assert len(questions) == 5
    assert len(calls) == 2
    assert "KHÔNG hợp lệ" in calls[1], "request sửa phải nói rõ lỗi trước đó"


async def test_schema_repair_is_bounded(monkeypatch):
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _chat_response({"questions": ["một câu?"]})

    provider = _provider(handler)
    provider.max_schema_retries = 1
    with pytest.raises(SchemaInvalidError):
        await provider.generate_interview_questions("x")
    assert calls["n"] == 2  # 1 lần + 1 lần sửa, không hơn


async def test_schema_repair_can_be_disabled():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _chat_response({"questions": ["một câu?"]})

    provider = _provider(handler)
    provider.max_schema_retries = 0
    with pytest.raises(SchemaInvalidError):
        await provider.generate_interview_questions("x")
    assert calls["n"] == 1
