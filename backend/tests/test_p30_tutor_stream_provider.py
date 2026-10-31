"""P3.0 — OpenAI-compatible **streaming** adapter với HTTP mock (không network).

Không phải bằng chứng LLM thật: `httpx.MockTransport` mô phỏng đúng định dạng
SSE của `/chat/completions` để kiểm tra parser, usage, lỗi và hợp đồng "chỉ yield
text mới". Chạy với provider thật được ghi riêng là NOT TESTED trong progress.
"""

import json

import httpx
import pytest

from app.providers import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    SchemaInvalidError,
)
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.providers.usage import UsageCollector, collect_usage


def _provider(handler) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key="sk-test-not-real",
        base_url="https://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )


def _sse(chunks: list[dict | str], usage: dict | None = None) -> bytes:
    lines: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, str):
            lines.append(f"data: {chunk}\n\n")
            continue
        body = chunk
        if usage is not None and chunk.get("choices"):
            body = {**chunk, "usage": usage}
            usage = None
        lines.append(f"data: {json.dumps(body)}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


async def _collect(provider, system="sys", messages=None) -> str:
    pieces: list[str] = []
    async for piece in provider.stream_tutor_reply(
        system=system, messages=messages or [{"role": "user", "content": "hỏi"}], max_input_chars=8000
    ):
        pieces.append(piece)
    return "".join(pieces)


def _chunk(text: str, finish: str | None = None) -> dict:
    return {
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}],
    }


async def test_stream_yields_only_new_text_in_order():
    seen_payload: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers["accept"] == "text/event-stream"
        seen_payload.update(json.loads(request.content))
        return httpx.Response(200, content=_sse([_chunk("Xin "), _chunk("chào "), _chunk("bạn")]))

    text = await _collect(_provider(handler))
    assert text == "Xin chào bạn"
    assert seen_payload["stream"] is True
    assert seen_payload["messages"][0]["role"] == "system"
    assert seen_payload["messages"][1] == {"role": "user", "content": "hỏi"}
    assert seen_payload["max_tokens"] > 0


async def test_stream_records_usage_and_finish_reason():
    collector = UsageCollector()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                [_chunk("a"), _chunk("b", finish="stop")],
                usage={"prompt_tokens": 31, "completion_tokens": 7},
            ),
        )

    with collect_usage(collector):
        text = await _collect(_provider(handler))
    assert text == "ab"
    assert collector.calls == 1
    record = collector.records[0]
    assert record.kind == "tutor"
    assert record.prompt_tokens == 31
    assert record.completion_tokens == 7
    assert record.finish_reason == "stop"


async def test_stream_ignores_keepalive_and_empty_deltas():
    async def handler(request: httpx.Request) -> httpx.Response:
        raw = (
            ": keepalive\n\n"
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":""},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=raw.encode())

    assert await _collect(_provider(handler)) == "ok"


async def test_stream_malformed_chunk_is_transient_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raw = "data: {not json}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, content=raw.encode())

    with pytest.raises(ProviderTransientError):
        await _collect(_provider(handler))


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ProviderAuthError),
        (429, ProviderRateLimitError),
        (503, ProviderTransientError),
        (400, SchemaInvalidError),
    ],
)
async def test_stream_http_status_maps_to_taxonomy(status, expected):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "secret-internal-detail"})

    with pytest.raises(expected) as info:
        await _collect(_provider(handler))
    assert "secret-internal-detail" not in str(info.value)


async def test_stream_timeout_maps_to_provider_timeout():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderTimeoutError):
        await _collect(_provider(handler))


async def test_stream_input_is_truncated_to_configured_limit():
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_sse([_chunk("ok")]))

    messages = [{"role": "user", "content": "x" * 5000}]
    provider = _provider(handler)
    async for _ in provider.stream_tutor_reply(
        system="s", messages=messages, max_input_chars=100
    ):
        pass
    sent = seen["messages"][1]["content"]
    assert len(sent) <= 100


async def test_stream_logs_metadata_without_prompt_or_key(caplog):
    import logging

    secret = "sk-live-SUPER-SECRET"
    marker = "NỘI-DUNG-RIÊNG"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                [_chunk("ok", finish="stop")],
                usage={"prompt_tokens": 5, "completion_tokens": 1},
            ),
        )

    provider = OpenAICompatibleProvider(
        api_key=secret,
        base_url="https://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    with caplog.at_level(logging.INFO):
        async for _ in provider.stream_tutor_reply(
            system="s", messages=[{"role": "user", "content": marker}], max_input_chars=100
        ):
            pass
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in joined
    assert marker not in joined
    assert "test-model" in joined
