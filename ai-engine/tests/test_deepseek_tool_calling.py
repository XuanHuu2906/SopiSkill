"""Tests for official `openai` SDK (`AsyncOpenAI`) native Function Calling (`tools` / `tool_calls`)
configured for DeepSeek (`LLM_PROVIDER=deepseek`, `https://api.deepseek.com/v1`, `deepseek-chat`).

100% offline / zero API spend via `httpx.MockTransport` — verifies exact wire payloads sent by
`AsyncOpenAI` and end-to-end tool execution in both Sopi Tutor and Lesson Generator + Refiner.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.lesson_generator import generate_lesson_with_qa_loop
from app.agents.providers import (
    OpenAICompatibleProvider,
    ProviderConfigError,
    get_llm_provider,
)
from app.agents.tutor_agent import stream_tutor_turn
from app.core.config import Settings
from app.rag.repository import RagRepository
from app.schemas.internal import TutorLessonContext, TutorStreamInternalRequest


def _chat_completion_tool_resp(
    *,
    call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    model: str = "deepseek-chat",
) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "created": 1732500000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
    }


def _chat_completion_json_resp(content_obj: dict[str, Any], model: str = "deepseek-chat") -> dict[str, Any]:
    return {
        "id": "chatcmpl-json-1",
        "object": "chat.completion",
        "created": 1732500000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content_obj, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 90, "completion_tokens": 60, "total_tokens": 150},
    }


def test_deepseek_provider_preset_defaults_and_fail_fast():
    # Missing API key -> fail-fast
    with pytest.raises(ProviderConfigError):
        get_llm_provider(Settings(llm_provider="deepseek", llm_api_key=""))

    # Valid API key -> automatically defaults to DeepSeek base_url & deepseek-chat
    p = get_llm_provider(Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek"))
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.name == "deepseek"
    assert p.model == "deepseek-chat"
    assert p._base_url == "https://api.deepseek.com/v1"


async def test_deepseek_sdk_lesson_generator_multi_turn_tool_calls_and_refiner():
    captured_requests: list[dict[str, Any]] = []
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        assert str(request.url) == "https://api.deepseek.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test-deepseek"
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append(body)

        # Turn 1: DeepSeek invokes native tool `read_source`
        if call_idx == 1:
            assert body["model"] == "deepseek-chat"
            tool_names = [t["function"]["name"] for t in body["tools"]]
            assert tool_names == ["read_source", "save_lesson"]
            return httpx.Response(
                200,
                json=_chat_completion_tool_resp(
                    call_id="call_rs_1",
                    tool_name="read_source",
                    arguments={"anchor": "sec-btree", "query": "B-Tree pages"},
                ),
            )

        # Turn 2: Verify SDK sent `assistant.tool_calls` + `role=tool` with exact `tool_call_id` -> DeepSeek calls `save_lesson` (with an ambiguous duplicate MC option so Refiner runs!)
        if call_idx == 2:
            roles = [m["role"] for m in body["messages"]]
            assert roles == ["system", "user", "assistant", "tool"]
            assert body["messages"][3]["tool_call_id"] == "call_rs_1"
            assert "B-Tree pages minimize disk I/O" in body["messages"][3]["content"]
            return httpx.Response(
                200,
                json=_chat_completion_tool_resp(
                    call_id="call_sl_2",
                    tool_name="save_lesson",
                    arguments={
                        "lesson": {
                            "title": "B-Tree Indexing",
                            "blocks": [
                                {
                                    "type": "teach",
                                    "title": "Why B-Trees?",
                                    "paragraphs": [
                                        "B-Tree pages keep keys sorted and pack hundreds of pointers per page to minimize disk I/O."
                                    ],
                                },
                                {
                                    "type": "mc",
                                    "question": "Why do databases use B-Trees?",
                                    "options": ["Minimize disk I/O", "Minimize disk I/O", "Disable caching"],
                                    "answerIndex": 0,
                                },
                            ],
                        }
                    },
                ),
            )

        # Call 3: Tier-2 Validator QA native tools (`flag_question` / `approve_lesson`)
        if call_idx == 3:
            qa_tools = [t["function"]["name"] for t in body["tools"]]
            assert qa_tools == ["flag_question", "approve_lesson"]
            return httpx.Response(
                200,
                json=_chat_completion_tool_resp(
                    call_id="call_qa_3",
                    tool_name="flag_question",
                    arguments={
                        "blockIndex": 1,
                        "code": "ambiguous",
                        "details": "Duplicate options in MC block 1 must be distinct.",
                    },
                ),
            )

        # Call 4: Refiner pass fixes the `ambiguous` flag cleanly
        return httpx.Response(
            200,
            json=_chat_completion_json_resp(
                {
                    "title": "B-Tree Indexing",
                    "blocks": [
                        {
                            "type": "teach",
                            "title": "Why B-Trees?",
                            "paragraphs": [
                                "B-Tree pages keep keys sorted and pack hundreds of pointers per page to minimize disk I/O."
                            ],
                        },
                        {
                            "type": "mc",
                            "question": "Why do databases use B-Trees?",
                            "options": ["Minimize disk I/O", "Store unsorted blobs", "Disable caching"],
                            "answerIndex": 0,
                        },
                    ],
                }
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    res = await generate_lesson_with_qa_loop(
        topic="Database Internals",
        unit_title="Storage",
        lesson_title="B-Tree Indexing",
        language="en",
        learner_profile={"currentLevel": "intermediate"},
        provider=provider,
        source_brief={
            "what": "Database storage internals.",
            "sections": [
                {
                    "anchor": "sec-btree",
                    "heading": "B-Tree Pages",
                    "gist": "B-Tree pages minimize disk I/O by using high branching factors.",
                }
            ],
        },
        max_turns=6,
        max_refine_rounds=2,
    )

    assert res.tools_called == ["read_source", "save_lesson"]
    assert res.turns_used == 2
    assert res.refine_rounds == 1
    assert res.qa.blocking_errors == []
    assert res.qa.content_flags == []
    assert "ambiguous" in res.resolved_flag_codes
    assert len(captured_requests) == 4
    assert captured_requests[3]["response_format"] == {"type": "json_object"}


async def test_deepseek_sdk_sopi_tutor_native_tool_calls_and_streaming():
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        body = json.loads(request.content.decode("utf-8"))

        # Call 1: Native tool selection via `tools` JSON schema -> DeepSeek calls `regenerate_unit`
        if call_idx == 1:
            assert body.get("stream") is not True
            sent_tools = {t["function"]["name"] for t in body["tools"]}
            assert {"read_lesson", "explain_deeper", "read_source", "flag_question", "revise_proposal", "regenerate_unit"} == sent_tools
            return httpx.Response(
                200,
                json=_chat_completion_tool_resp(
                    call_id="call_tutor_1",
                    tool_name="regenerate_unit",
                    arguments={
                        "direction": "more_practical",
                        "notes": "Add concrete SQL query plan labs before theory.",
                    },
                ),
            )

        # Call 2: Native streaming SSE reply from DeepSeek
        sse_chunks = (
            'data: {"id":"cmpl-1","object":"chat.completion.chunk","created":1732500000,"model":"deepseek-chat","choices":[{"index":0,"delta":{"role":"assistant","content":"I prepared "},"finish_reason":null}]}\n\n'
            'data: {"id":"cmpl-1","object":"chat.completion.chunk","created":1732500000,"model":"deepseek-chat","choices":[{"index":0,"delta":{"content":"a practical preview."},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_chunks.encode("utf-8"),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    req = TutorStreamInternalRequest(
        courseId="crs_1",
        threadId="thr_1",
        messageId="msg_1",
        ownerId="usr_1",
        language="en",
        userMessage="Can we make this unit way more hands-on?",
        entryPoint="tab",
        allowedTools=["read_lesson", "explain_deeper", "read_source", "flag_question", "revise_proposal", "regenerate_unit"],
        lessonContext=TutorLessonContext(
            lessonId="lsn_1",
            lessonTitle="Query Plans",
            activeBlockIndex=0,
            publicBlocks=[{"type": "teach", "title": "EXPLAIN", "paragraphs": ["Inspect query plans."]}],
        ),
        unitContext={"unitId": "unt_1", "unitTitle": "SQL Performance"},
    )

    frames = []
    async for raw in stream_tutor_turn(req, provider=provider, rag_repo=RagRepository(settings=cfg), db=None):
        frames.append(raw)

    joined = "".join(frames)
    assert "event: tool\n" in joined
    assert '"name":"regenerate_unit"' in joined
    assert "event: tool_effect\n" in joined
    assert '"direction":"more_practical"' in joined
    assert "Add concrete SQL query plan labs before theory." in joined
    assert "I prepared " in joined and "a practical preview." in joined
    assert "event: done\n" in joined


async def test_deepseek_sdk_rejects_unallowed_tool_and_falls_back_safely():
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            # Model tries to call `regenerate_unit` even though only `read_lesson` is allowed!
            return httpx.Response(
                200,
                json=_chat_completion_tool_resp(
                    call_id="call_bad",
                    tool_name="regenerate_unit",
                    arguments={"direction": "easier", "notes": "Unauthorized"},
                ),
            )
        sse_chunks = (
            'data: {"id":"cmpl-2","object":"chat.completion.chunk","created":1732500000,"model":"deepseek-chat","choices":[{"index":0,"delta":{"role":"assistant","content":"Safe reply."},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_chunks.encode("utf-8"))

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    req = TutorStreamInternalRequest(
        courseId="crs_1",
        threadId="thr_1",
        messageId="msg_2",
        ownerId="usr_1",
        language="en",
        userMessage="Summarize this lesson",
        allowedTools=["read_lesson"],
        lessonContext=TutorLessonContext(
            lessonId="lsn_1",
            lessonTitle="Intro",
            activeBlockIndex=0,
            publicBlocks=[{"type": "teach", "title": "Intro", "paragraphs": ["Basics."]}],
        ),
    )

    frames = []
    async for raw in stream_tutor_turn(req, provider=provider, rag_repo=RagRepository(settings=cfg), db=None):
        frames.append(raw)

    joined = "".join(frames)
    assert '"name":"read_lesson"' in joined
    assert "event: tool_effect\n" not in joined
    assert "Safe reply." in joined


async def test_deepseek_lesson_without_source_omits_read_source_and_detects_truncation():
    from app.agents.providers import ProviderTransientError

    seen_bodies: list[dict[str, Any]] = []

    def handler_no_source(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_bodies.append(body)
        return httpx.Response(
            200,
            json=_chat_completion_tool_resp(
                call_id="call_save_only",
                tool_name="save_lesson",
                arguments={
                    "lesson": {
                        "title": "Binary Tree Overview",
                        "blocks": [
                            {
                                "type": "teach",
                                "title": "What is a Binary Tree?",
                                "paragraphs": [
                                    "A binary tree stores hierarchical nodes where each parent points to at most a left child and right child."
                                ],
                            },
                            {
                                "type": "mc",
                                "question": "At most how many children does each node in a binary tree have?",
                                "options": ["One", "Two", "Four"],
                                "answerIndex": 1,
                            },
                        ],
                    }
                },
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler_no_source))
    res = await generate_lesson_with_qa_loop(
        topic="Binary Tree",
        unit_title="Foundations",
        lesson_title="What is a Binary Tree?",
        language="vi",
        learner_profile={"currentLevel": "beginner"},
        provider=provider,
        source_brief=None,
        source_reader=None,
        max_turns=6,
    )
    assert res.turns_used == 1
    assert res.tools_called == ["save_lesson"]
    assert res.qa.blocking_errors == []
    assert seen_bodies[0]["tool_choice"] == {"type": "function", "function": {"name": "save_lesson"}}
    assert seen_bodies[0]["max_tokens"] == 8000

    def handler_truncated(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-trunc",
                "object": "chat.completion",
                "created": 1732500000,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_trunc",
                                    "type": "function",
                                    "function": {"name": "save_lesson", "arguments": '{"lesson": {"title": "Cut'},
                                }
                            ],
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {"prompt_tokens": 200, "completion_tokens": 8000, "total_tokens": 8200},
            },
        )

    provider_trunc = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler_truncated))
    with pytest.raises(ProviderTransientError, match="finish_reason=length"):
        await generate_lesson_with_qa_loop(
            topic="Binary Tree",
            unit_title="Foundations",
            lesson_title="What is a Binary Tree?",
            language="vi",
            learner_profile={"currentLevel": "beginner"},
            provider=provider_trunc,
            source_brief=None,
            source_reader=None,
            max_turns=6,
        )
