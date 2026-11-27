"""Offline zero-cost tests for the full 8-Agent DeepSeek OpenAI SDK Tool-Calling architecture.

Exercises real `openai.AsyncOpenAI` via `httpx.MockTransport` (0đ spend, no network):
  - Agent #1 Source Research (`search_sources`, `inspect_source`, `commit_sources` + SSRF/junk filter + API endpoint)
  - Agent #2 Source Brief (`save_brief` 1-turn + anchor grounding + hard schema bounds)
  - Agent #3 Interview & Planner (`read_source_brief`, `save_proposal` + worker_llm integration)
  - Agent #4 Lesson Generator optional `generate_image` gating
  - Agent #5 Validator / QA (`flag_question` 6 canonical codes + `approve_lesson` -> Refiner -> approve)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.lesson_generator import generate_lesson_with_qa_loop
from app.agents.planner_agent import generate_proposal_with_tools
from app.agents.providers import OpenAICompatibleProvider
from app.agents.source_research_agent import (
    SourceResearchMaxTurnsError,
    is_reputable_source_url,
    research_sources_with_agent,
)
from app.agents.tool_schemas import CANONICAL_CONTENT_FLAG_CODES
from app.core.config import Settings
from app.rag.brief_builder import build_source_brief_with_agent
from app.rag.repository import ChunkInput
from app.workers.worker_llm import handle_llm_job
from tests.conftest import signed_json_request


def _tool_resp(*, call_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "created": 1732600000,
        "model": "deepseek-chat",
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
        "usage": {"prompt_tokens": 110, "completion_tokens": 45, "total_tokens": 155},
    }


def _json_resp(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "chatcmpl-json-1",
        "object": "chat.completion",
        "created": 1732600000,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 140, "completion_tokens": 90, "total_tokens": 230},
    }


def test_source_research_deterministic_domain_and_ssrf_filter():
    # Allowed reputable sources
    assert is_reputable_source_url("https://export.arxiv.org/api/query?id_list=1706.03762")[0] is True
    assert is_reputable_source_url("https://docs.python.org/3/library/asyncio.html")[0] is True

    # Junk / UGC domains blocked
    ok, _, reason = is_reputable_source_url("https://www.quora.com/What-is-a-B-Tree")
    assert ok is False and reason == "JUNK_DOMAIN_BLOCKED"
    ok, _, reason = is_reputable_source_url("https://medium.com/@random/sql-tips")
    assert ok is False and reason == "JUNK_DOMAIN_BLOCKED"

    # SSRF / non-HTTPS / IP literals / credentials blocked
    assert is_reputable_source_url("http://169.254.169.254/latest/meta-data")[0] is False
    assert is_reputable_source_url("https://127.0.0.1/admin")[0] is False
    assert is_reputable_source_url("https://localhost/secret")[0] is False
    assert is_reputable_source_url("https://user:pass@arxiv.org/abs/1706.03762")[0] is False
    assert is_reputable_source_url("https://random-untrusted-blog.xyz/post")[2] == "UNTRUSTED_DOMAIN"


async def test_agent1_source_research_deepseek_sdk_loop_filters_junk_and_commits():
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        body = json.loads(request.content.decode("utf-8"))
        tool_names = [t["function"]["name"] for t in body["tools"]]
        assert tool_names == ["search_sources", "inspect_source", "commit_sources"]

        if call_idx == 1:
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_sr_1",
                    tool_name="search_sources",
                    arguments={"query": "PostgreSQL B-Tree indexes", "max_results": 5},
                ),
            )
        if call_idx == 2:
            # Verify search_sources result was passed back with tool_call_id
            assert body["messages"][-1]["role"] == "tool"
            assert body["messages"][-1]["tool_call_id"] == "call_sr_1"
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_sr_2",
                    tool_name="inspect_source",
                    arguments={"url": "https://www.postgresql.org/docs/current/indexes-types.html"},
                ),
            )
        # Turn 3: Model tries to sneak in a junk URL AND an SSRF IP along with 1 good URL -> code filter keeps ONLY the valid one!
        return httpx.Response(
            200,
            json=_tool_resp(
                call_id="call_sr_3",
                tool_name="commit_sources",
                arguments={
                    "sources": [
                        {
                            "url": "https://www.quora.com/junk-answer",
                            "title": "Quora Junk",
                            "rationale": "Should be rejected by code.",
                        },
                        {
                            "url": "https://127.0.0.1/internal",
                            "title": "SSRF",
                            "rationale": "Should be rejected by code.",
                        },
                        {
                            "url": "https://www.postgresql.org/docs/current/indexes-types.html",
                            "title": "PostgreSQL Index Types",
                            "sourceKind": "web_url",
                            "rationale": "Official primary documentation for B-Tree indexes.",
                        },
                    ]
                },
            ),
        )

    async def noisy_search(_q: str, _n: int) -> list[dict[str, Any]]:
        return [
            {"url": "https://www.pinterest.com/pin/123", "title": "Junk Pin", "snippet": "Spam"},
            {
                "url": "https://www.postgresql.org/docs/current/indexes-types.html",
                "title": "PostgreSQL Index Types",
                "snippet": "Official PostgreSQL guide on B-Tree indexes.",
            },
        ]

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    res = await research_sources_with_agent(
        topic="PostgreSQL B-Tree Indexing",
        language="en",
        provider=provider,
        settings=cfg,
        search_fn=noisy_search,
    )

    assert res.tools_called == ["search_sources", "inspect_source", "commit_sources"]
    assert res.turns_used == 3
    assert len(res.sources) == 1
    assert res.sources[0].url == "https://www.postgresql.org/docs/current/indexes-types.html"
    assert res.sources[0].domain == "www.postgresql.org"
    assert any("pinterest.com" in r for r in res.rejected_urls)
    assert any("quora.com" in r for r in res.rejected_urls)
    assert any("127.0.0.1" in r for r in res.rejected_urls)


async def test_agent1_source_research_max_turns_and_internal_endpoint(ai_client):
    def looping_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_tool_resp(
                call_id="call_loop",
                tool_name="search_sources",
                arguments={"query": "Transformers"},
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(looping_handler))

    with pytest.raises(SourceResearchMaxTurnsError) as exc_info:
        await research_sources_with_agent(
            topic="Transformers",
            language="en",
            provider=provider,
            settings=cfg,
            max_turns=2,
        )
    assert exc_info.value.error_code == "max_turns"

    # Also verify signed FastAPI endpoint `/internal/sources/research` in default mock mode
    raw, headers = signed_json_request(
        "POST",
        "/internal/sources/research",
        {"topic": "Transformer Attention", "language": "en"},
    )
    resp = await ai_client.post("/internal/sources/research", content=raw, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert 1 <= len(data["sources"]) <= 3
    assert data["toolsCalled"] == ["search_sources", "inspect_source", "commit_sources"]


async def test_agent2_source_brief_single_turn_save_brief_grounds_anchors():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content.decode("utf-8"))
        assert body["tool_choice"] == {"type": "function", "function": {"name": "save_brief"}}
        assert [t["function"]["name"] for t in body["tools"]] == ["save_brief"]
        return httpx.Response(
            200,
            json=_tool_resp(
                call_id="call_brief_1",
                tool_name="save_brief",
                arguments={
                    "what": "Explains scaled dot-product self-attention and multi-head projections.",
                    "suggestedTopic": "Transformer Self-Attention",
                    "claims": ["Self-attention scales dot products by 1/sqrt(d_k)."],
                    "notation": ["Q", "K", "V", "d_k"],
                    "assumes": ["Matrix multiplication"],
                    "sections": [
                        {"anchor": "sec-attn", "heading": "Self-Attention", "gist": "Computes softmax(QK^T/sqrt(d_k))V."},
                        # Hallucinated anchor NOT present in chunks -> must be dropped!
                        {"anchor": "hallucinated-99", "heading": "Fake Section", "gist": "Should be stripped."},
                    ],
                },
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))
    chunks = [
        ChunkInput(
            chunk_index=0,
            page_number=1,
            section_anchor="sec-attn",
            content="Scaled dot-product self-attention computes softmax(QK^T / sqrt(d_k)) V over sequence tokens.",
        )
    ]

    bundle = await build_source_brief_with_agent(
        title="attention.pdf",
        chunks=chunks,
        provider=provider,
    )
    assert calls == 1  # Strictly single-turn!
    assert bundle["suggestedTopic"] == "Transformer Self-Attention"
    assert bundle["brief"]["notation"] == ["Q", "K", "V", "d_k"]
    anchors = [s["anchor"] for s in bundle["brief"]["sections"]]
    assert anchors == ["sec-attn"]


async def test_agent3_planner_read_source_brief_then_save_proposal_via_worker():
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        body = json.loads(request.content.decode("utf-8"))
        tool_names = [t["function"]["name"] for t in body["tools"]]
        assert tool_names == ["read_source_brief", "save_proposal"]

        if call_idx == 1:
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_pl_1",
                    tool_name="read_source_brief",
                    arguments={"focus": "core sections"},
                ),
            )
        assert body["messages"][-1]["role"] == "tool"
        assert body["messages"][-1]["tool_call_id"] == "call_pl_1"
        assert "sec-raft" in body["messages"][-1]["content"]
        return httpx.Response(
            200,
            json=_tool_resp(
                call_id="call_pl_2",
                tool_name="save_proposal",
                arguments={
                    "proposal": {
                        "title": "Raft Consensus Deep Dive",
                        "summary": "Master leader election and log replication from the Raft paper.",
                        "estimatedHours": 3.0,
                        "units": [
                            {
                                "title": "Leader Election",
                                "objective": "Understand randomized election timeouts.",
                                "lessons": [{"title": "Terms & Heartbeats", "focus": "sec-raft"}],
                            }
                        ],
                    }
                },
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    source_brief = {
        "what": "Raft consensus algorithm for replicated state machines.",
        "sections": [{"anchor": "sec-raft", "heading": "Leader Election", "gist": "Randomized timeouts avoid split votes."}],
    }
    res = await generate_proposal_with_tools(
        topic="Raft Consensus",
        language="en",
        learner_profile={"currentLevel": "intermediate", "depth": "deep"},
        provider=provider,
        source_brief=source_brief,
    )
    assert res.tools_called == ["read_source_brief", "save_proposal"]
    assert res.turns_used == 2
    assert res.proposal["title"] == "Raft Consensus Deep Dive"

    # Also verify `worker_llm` emits `errorCode="max_turns"` if Planner exceeds max_turns
    def stuck_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_tool_resp(call_id="call_stuck", tool_name="read_source_brief", arguments={}),
        )

    class _FakeCallback:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def post_callback(self, path: str, payload: dict[str, Any], *, correlation_id: str) -> None:
            self.calls.append((path, payload))

    stuck_provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(stuck_handler))
    fake_cb = _FakeCallback()
    cb_payload = await handle_llm_job(
        {
            "jobId": "job_plan_stuck",
            "idempotencyKey": "idem_plan_stuck",
            "jobType": "generate_proposal",
            "payload": {"topic": "Raft", "language": "en", "sourceBrief": source_brief},
        },
        provider=stuck_provider,
        callback_client=fake_cb,  # type: ignore[arg-type]
        settings=Settings(llm_provider="deepseek", llm_api_key="sk-test", planner_max_turns=2),
    )
    assert cb_payload["status"] == "failed"
    assert cb_payload["errorCode"] == "max_turns"


async def test_agent4_optional_generate_image_and_agent5_validator_flag_then_approve():
    call_idx = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_idx
        call_idx += 1
        body = json.loads(request.content.decode("utf-8"))

        # Turn 1 (Agent #4): `generate_image` is present because `image_gen_enabled=True`
        if call_idx == 1:
            names = [t["function"]["name"] for t in body["tools"]]
            assert names == ["read_source", "save_lesson", "generate_image"]
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_img_1",
                    tool_name="generate_image",
                    arguments={"prompt": "Diagram of TCP 3-way handshake", "alt": "TCP handshake", "aspectRatio": "16:9"},
                ),
            )
        # Turn 2 (Agent #4): `save_lesson`
        if call_idx == 2:
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_sl_2",
                    tool_name="save_lesson",
                    arguments={
                        "lesson": {
                            "title": "TCP Handshake",
                            "blocks": [
                                {
                                    "type": "teach",
                                    "title": "SYN, SYN-ACK, ACK",
                                    "paragraphs": ["TCP opens a reliable connection with SYN, SYN-ACK, and ACK."],
                                    "image": {"url": "/assets/generated/1.png", "alt": "TCP handshake"},
                                },
                                {
                                    "type": "mc",
                                    "question": "Which packet starts a TCP handshake?",
                                    "options": ["FIN", "SYN", "RST"],
                                    "answerIndex": 0,  # Wrong answer (should be 1)! Static QA can't know, Agent #5 catches it!
                                },
                            ],
                        }
                    },
                ),
            )
        # Turn 3 (Agent #5 Validator QA): calls native `flag_question` with `wrong_answer`
        if call_idx == 3:
            names = [t["function"]["name"] for t in body["tools"]]
            assert names == ["flag_question", "approve_lesson"]
            enum_codes = body["tools"][0]["function"]["parameters"]["properties"]["code"]["enum"]
            assert enum_codes == CANONICAL_CONTENT_FLAG_CODES
            return httpx.Response(
                200,
                json=_tool_resp(
                    call_id="call_qa_3",
                    tool_name="flag_question",
                    arguments={
                        "blockIndex": 1,
                        "code": "wrong_answer",
                        "details": "SYN is at index 1, not FIN at index 0.",
                    },
                ),
            )
        # Turn 4 (Refiner): fixes answerIndex -> 1
        if call_idx == 4:
            return httpx.Response(
                200,
                json=_json_resp(
                    {
                        "title": "TCP Handshake",
                        "blocks": [
                            {
                                "type": "teach",
                                "title": "SYN, SYN-ACK, ACK",
                                "paragraphs": ["TCP opens a reliable connection with SYN, SYN-ACK, and ACK."],
                                "image": {"url": "/assets/generated/1.png", "alt": "TCP handshake"},
                            },
                            {
                                "type": "mc",
                                "question": "Which packet starts a TCP handshake?",
                                "options": ["FIN", "SYN", "RST"],
                                "answerIndex": 1,
                            },
                        ],
                    }
                ),
            )
        # Turn 5 (Agent #5 Validator QA re-check): calls `approve_lesson`
        assert [t["function"]["name"] for t in body["tools"]] == ["flag_question", "approve_lesson"]
        return httpx.Response(
            200,
            json=_tool_resp(
                call_id="call_qa_5",
                tool_name="approve_lesson",
                arguments={"summary": "All teach blocks and quiz answer keys are accurate."},
            ),
        )

    cfg = Settings(llm_provider="deepseek", llm_api_key="sk-test-deepseek")
    provider = OpenAICompatibleProvider(cfg, transport=httpx.MockTransport(handler))

    res = await generate_lesson_with_qa_loop(
        topic="Networking",
        unit_title="Transport Layer",
        lesson_title="TCP Handshake",
        language="en",
        learner_profile={"currentLevel": "beginner"},
        provider=provider,
        image_gen_enabled=True,
        llm_qa_enabled=True,
        max_turns=6,
        max_refine_rounds=2,
    )

    assert res.tools_called == ["generate_image", "save_lesson"]
    assert res.refine_rounds == 1
    assert "wrong_answer" in res.resolved_flag_codes
    assert res.qa.content_flags == []
    assert res.lesson["blocks"][1]["answerIndex"] == 1
    assert call_idx == 5
