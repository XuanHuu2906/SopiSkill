"""Tests for bounded Lesson Generator tool loop (`read_source` + `save_lesson`, `max_turns`)
and `Writer -> Validator QA -> Refiner` loop (max 2 rounds across all 6 canonical `content_flags`)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agents.lesson_generator import (
    MaxTurnsExceededError,
    generate_lesson_with_qa_loop,
)
from app.agents.providers import MockProvider
from app.agents.validator_qa import CONTENT_FLAG_CODES, run_static_qa
from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings
from app.schemas.internal import LlmUsageOut
from app.workers.worker_llm import handle_llm_job


def _recording_client(cfg: Settings):
    recorded: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append({"path": request.url.path, "body": json.loads(request.content.decode("utf-8"))})
        return httpx.Response(200, json={"accepted": True, "duplicate": False})

    return CoreApiCallbackClient(settings=cfg, transport=httpx.MockTransport(handler)), recorded


async def test_lesson_generator_uses_read_source_then_save_lesson_within_max_turns():
    provider = MockProvider()
    source_brief = {
        "what": "Introduction to B-Tree database indexing.",
        "claims": ["B-Trees keep keys sorted for O(log n) lookup."],
        "notation": ["O(log n)"],
        "assumes": ["Basic binary trees"],
        "sections": [
            {
                "anchor": "sec-btree",
                "heading": "B-Tree Indexing",
                "gist": "B-Tree pages minimize disk I/O by keeping high branching factors.",
            }
        ],
    }
    res = await generate_lesson_with_qa_loop(
        topic="Database Indexing",
        unit_title="Storage Engines",
        lesson_title="B-Tree Indexing",
        language="en",
        learner_profile={},
        provider=provider,
        source_brief=source_brief,
        max_turns=6,
        max_refine_rounds=2,
    )
    assert res.tools_called == ["read_source", "save_lesson"]
    assert res.turns_used == 2
    assert res.qa.blocking_errors == []
    assert res.refine_rounds == 0


class _InfiniteReadSourceProvider(MockProvider):
    """Test double that keeps calling `read_source` forever and never calls `save_lesson`."""

    async def next_lesson_generator_turn(self, *, turn: int, **_kwargs: Any) -> dict[str, Any]:
        return {
            "tool": "read_source",
            "arguments": {"query": f"turn-{turn}"},
            "usage": LlmUsageOut(provider="mock", model="mock-loop"),
        }


async def test_lesson_generator_enforces_max_turns_and_worker_emits_max_turns_error():
    cfg = Settings(
        llm_provider="mock",
        core_api_url="http://core-api.test",
        internal_service_token="tok-123",
        internal_hmac_secret="sec-456",
        lesson_gen_max_turns=3,
    )
    looping_provider = _InfiniteReadSourceProvider()

    with pytest.raises(MaxTurnsExceededError):
        await generate_lesson_with_qa_loop(
            topic="OS Kernels",
            unit_title="Scheduling",
            lesson_title="CFS Scheduler",
            language="en",
            learner_profile={},
            provider=looping_provider,
            max_turns=3,
        )

    cb_client, recorded = _recording_client(cfg)
    out = await handle_llm_job(
        {
            "jobId": "job_max_turns",
            "idempotencyKey": "idem_mt",
            "jobType": "generate_course",
            "ownerId": "usr_1",
            "courseId": "crs_1",
            "payload": {
                "topic": "OS Kernels",
                "language": "en",
                "units": [{"title": "Scheduling", "lessonTitles": ["CFS Scheduler"]}],
            },
        },
        provider=looping_provider,
        callback_client=cb_client,
        settings=cfg,
    )
    assert out["status"] == "failed"
    assert out["errorCode"] == "max_turns"
    assert recorded[-1]["body"]["errorCode"] == "max_turns"


class _FlawedDraftProvider(MockProvider):
    """Emits a draft lesson violating 5 distinct canonical `content_flags` codes to test Refiner."""

    async def generate_lesson(
        self,
        topic: str,
        unit_title: str,
        lesson_title: str,
        language: str,
        learner_profile: dict[str, Any],
    ) -> tuple[dict[str, Any], LlmUsageOut]:
        flawed = {
            "title": lesson_title,
            "blocks": [
                {
                    "type": "teach",
                    "title": "Overview",
                    "paragraphs": ["Too brief."],  # -> unanswerable
                    "figure": {"kind": "formula", "latex": "O(\\log n)"},
                    "image": {"url": "https://example.com/conflict.png"},  # -> figure_mismatch
                },
                {
                    "type": "mc",
                    "question": "Pick the valid option",
                    "options": ["B-Tree", "B-Tree", "Hash"],  # -> ambiguous
                    "answerIndex": 9,  # -> wrong_answer
                },
                {
                    "type": "blank",
                    "sentence": "A B-Tree uses B-Tree pages for ____ lookup.",  # -> weak_distractors
                    "answer": "B-Tree",
                },
            ],
        }
        return flawed, LlmUsageOut(provider="mock", model="mock-flawed")


async def test_writer_validator_refiner_resolves_canonical_6_flags_within_2_rounds():
    flawed_provider = _FlawedDraftProvider()
    raw_draft, _ = await flawed_provider.generate_lesson("Indexing", "U1", "B-Trees", "en", {})
    initial_qa = run_static_qa(raw_draft)
    initial_codes = {f["code"] for f in initial_qa.content_flags}

    # Verify all emitted flag codes belong strictly to the 6 canonical codes
    assert initial_codes.issubset(CONTENT_FLAG_CODES)
    assert {"figure_mismatch", "unanswerable", "ambiguous", "weak_distractors", "wrong_answer"}.issubset(
        initial_codes
    )

    res = await generate_lesson_with_qa_loop(
        topic="Indexing",
        unit_title="U1",
        lesson_title="B-Trees",
        language="en",
        learner_profile={},
        provider=flawed_provider,
        max_turns=4,
        max_refine_rounds=2,
    )
    assert 1 <= res.refine_rounds <= 2
    assert res.qa.blocking_errors == []
    assert res.qa.content_flags == []
    assert set(res.resolved_flag_codes) >= {
        "figure_mismatch",
        "unanswerable",
        "ambiguous",
        "weak_distractors",
        "wrong_answer",
    }


class _UnfixableDraftProvider(MockProvider):
    """Emits a lesson that stays flagged so we verify Refiner strictly stops at `max_refine_rounds = 2`."""

    def __init__(self) -> None:
        self.refine_calls = 0

    async def generate_lesson(
        self,
        topic: str,
        unit_title: str,
        lesson_title: str,
        language: str,
        learner_profile: dict[str, Any],
    ) -> tuple[dict[str, Any], LlmUsageOut]:
        return (
            {
                "title": lesson_title,
                "blocks": [
                    {"type": "teach", "title": "Short", "paragraphs": ["Hi"]},
                    {"type": "mc", "question": "Q?", "options": ["A", "A"], "answerIndex": 0},
                ],
            },
            LlmUsageOut(provider="mock", model="mock-unfixable"),
        )

    async def refine_lesson(self, *, lesson: dict[str, Any], **_kwargs: Any) -> tuple[dict[str, Any], LlmUsageOut]:
        self.refine_calls += 1
        # Intentionally return an unfixed duplicate MC option to confirm hard cap at 2 rounds
        return (
            {
                "title": lesson["title"],
                "blocks": [
                    {"type": "teach", "title": "Long", "paragraphs": ["Long enough paragraph with more than ten clear words."]},
                    {"type": "mc", "question": "Q?", "options": ["Dup", "Dup"], "answerIndex": 0},
                ],
            },
            LlmUsageOut(provider="mock", model="mock-unfixable"),
        )


async def test_refiner_loop_never_exceeds_max_2_rounds():
    provider = _UnfixableDraftProvider()
    res = await generate_lesson_with_qa_loop(
        topic="Cap Test",
        unit_title="U1",
        lesson_title="Bounded Refiner",
        language="en",
        learner_profile={},
        provider=provider,
        max_turns=4,
        max_refine_rounds=2,
    )
    assert res.refine_rounds == 2
    assert provider.refine_calls == 2
    assert all(f["code"] in CONTENT_FLAG_CODES for f in res.qa.content_flags)
