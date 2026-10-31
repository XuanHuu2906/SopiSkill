"""P2.2 — usage/cost accounting, budget guard và migration contract (offline).

Real provider không được gọi ở đây: adapter dùng `httpx.MockTransport`.
"""

import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select

import app.models  # noqa: F401 — đăng ký mapper
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Course, GenerationJob, LlmUsageEvent
from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.providers.usage import (
    UsageCollector,
    collect_usage,
    estimate_cost_usd,
    parse_pricing,
    record_usage,
    resolve_price,
)
from app.providers.base import SchemaInvalidError
from app.services import llm_usage_service
from app.services.llm_usage_service import JobBudgetExceeded, check_job_budget

# ---------- pricing helpers ----------


def test_parse_pricing_rejects_garbage_without_raising():
    assert parse_pricing(None) == {}
    assert parse_pricing("not json") == {}
    assert parse_pricing("[1,2]") == {}
    assert parse_pricing('{"m": {"inputPerMTok": 1, "outputPerMTok": 2}}') == {
        "m": {"inputPerMTok": 1, "outputPerMTok": 2}
    }


def test_resolve_price_supports_wildcard_and_rejects_negative():
    pricing = {
        "m1": {"inputPerMTok": 1.0, "outputPerMTok": 3.0},
        "bad": {"inputPerMTok": -1, "outputPerMTok": 2},
        "*": {"inputPerMTok": 0.5, "outputPerMTok": 0.5},
    }
    assert resolve_price(pricing, "m1") == {"inputPerMTok": 1.0, "outputPerMTok": 3.0}
    assert resolve_price(pricing, "bad") == {"inputPerMTok": 0.5, "outputPerMTok": 0.5}
    assert resolve_price({"bad": pricing["bad"]}, "bad") is None
    assert resolve_price({}, "m1") is None


def test_cost_is_none_when_price_unknown_not_zero():
    collector = UsageCollector()
    record_usage(
        provider="openai_compatible",
        model="m1",
        kind="lesson",
        prompt_tokens=1000,
        completion_tokens=1000,
    )
    # record_usage ghi vào contextvar; ở đây thêm trực tiếp để test thuần.
    from app.providers.usage import UsageRecord

    collector.add(UsageRecord("openai_compatible", "m1", "lesson", 1000, 1000))
    assert collector.cost_estimate_usd({}) is None
    assert collector.summary({})["costKnown"] is False
    pricing = {"m1": {"inputPerMTok": 2.0, "outputPerMTok": 4.0}}
    assert collector.cost_estimate_usd(pricing) == pytest.approx(0.006)
    assert collector.summary(pricing)["costKnown"] is True


def test_estimate_cost_uses_per_million_rates():
    price = {"inputPerMTok": 1.0, "outputPerMTok": 2.0}
    assert estimate_cost_usd(1_000_000, 500_000, price) == pytest.approx(2.0)


# ---------- adapter records usage ----------


async def test_provider_records_usage_into_collector():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"questions": ["q1","q2","q3","q4","q5"]}'
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "completion_tokens_details": {"reasoning_tokens": 7},
                },
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="sk-test",
        base_url="https://llm.test/v1",
        model="m1",
        transport=httpx.MockTransport(handler),
    )
    with collect_usage() as usage:
        await provider.generate_interview_questions("Python")

    assert usage.calls == 1
    record = usage.records[0]
    assert record.kind == "interview"
    assert record.prompt_tokens == 120
    assert record.completion_tokens == 45
    assert record.reasoning_tokens == 7
    assert record.finish_reason == "stop"
    assert record.latency_ms is not None


async def test_usage_collector_is_isolated_between_contexts():
    with collect_usage() as outer:
        record_usage(
            provider="p", model="m", kind="judge", prompt_tokens=1, completion_tokens=1
        )
        assert outer.calls == 1
    assert outer.calls == 1  # không bị collector khác ghi đè


# ---------- job budget ----------


async def _job(**overrides) -> GenerationJob:
    async with SessionLocal() as db:
        course = Course(
            user_id=uuid.uuid4(),
            topic="Budget",
            client_course_id=uuid.uuid4().hex,
        )
        # Course cần user thật do FK; dùng user/课程 tối giản.
        from app.models import User

        user = User(external_id=f"p22-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course.user_id = user.id
        db.add(course)
        await db.flush()
        job = GenerationJob(course_id=course.id, **overrides)
        db.add(job)
        await db.commit()
        return job


async def test_check_job_budget_token_limit(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "generation_max_tokens_per_job", 100)
    monkeypatch.setattr(settings, "generation_max_cost_usd_per_job", 0.0)
    job = GenerationJob(course_id=uuid.uuid4(), prompt_tokens=60, completion_tokens=60)
    with pytest.raises(JobBudgetExceeded):
        check_job_budget(job)
    job.completion_tokens = 30
    check_job_budget(job)  # 90 <= 100


async def test_check_job_budget_cost_limit(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "generation_max_tokens_per_job", 0)
    monkeypatch.setattr(settings, "generation_max_cost_usd_per_job", 0.5)
    job = GenerationJob(course_id=uuid.uuid4(), cost_estimate_usd=None)
    check_job_budget(job)  # chưa biết giá ⇒ không chặn (không đoán)
    job.cost_estimate_usd = 0.75
    with pytest.raises(JobBudgetExceeded):
        check_job_budget(job)


def test_budget_error_is_fatal_not_retryable():
    from app.services.job_service import classify_error

    exc = JobBudgetExceeded("vượt trần")
    code, retryable = classify_error(exc)
    assert code == "BUDGET_EXCEEDED"
    assert retryable is False


async def test_flush_usage_persists_events_and_updates_job(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "llm_pricing_json",
        '{"m1": {"inputPerMTok": 1000.0, "outputPerMTok": 2000.0}}',
    )
    job = await _job()

    async with SessionLocal() as db:
        collector = UsageCollector()
        from app.providers.usage import UsageRecord

        collector.add(UsageRecord("openai_compatible", "m1", "lesson", 1000, 500))
        summary = await llm_usage_service.flush_usage(
            db, collector, job_id=job.id, user_id=None
        )
        await db.commit()

        stored = (
            await db.execute(
                select(LlmUsageEvent).where(LlmUsageEvent.job_id == job.id)
            )
        ).scalars().all()
        refreshed = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job.id))
        ).scalar_one()

    assert summary["calls"] == 1
    assert len(stored) == 1
    assert stored[0].provider == "openai_compatible"
    assert stored[0].cost_estimate_usd == pytest.approx(2.0)
    assert refreshed.llm_calls == 1
    assert refreshed.prompt_tokens == 1000
    assert refreshed.completion_tokens == 500
    assert refreshed.cost_estimate_usd == pytest.approx(2.0)


async def test_flush_usage_keeps_cost_unknown_when_pricing_missing(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_pricing_json", "")
    job = await _job()

    async with SessionLocal() as db:
        collector = UsageCollector()
        from app.providers.usage import UsageRecord

        collector.add(UsageRecord("openai_compatible", "unknown-model", "lesson", 10, 10))
        await llm_usage_service.flush_usage(db, collector, job_id=job.id)
        await db.commit()
        refreshed = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job.id))
        ).scalar_one()
        event = (
            await db.execute(select(LlmUsageEvent).where(LlmUsageEvent.job_id == job.id))
        ).scalars().first()

    assert refreshed.cost_estimate_usd is None
    assert event.cost_estimate_usd is None


async def test_flush_usage_does_not_duplicate_records(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_pricing_json", "")
    job = await _job()
    async with SessionLocal() as db:
        collector = UsageCollector()
        from app.providers.usage import UsageRecord

        collector.add(UsageRecord("p", "m", "lesson", 1, 1))
        await llm_usage_service.flush_usage(db, collector, job_id=job.id)
        await llm_usage_service.flush_usage(db, collector, job_id=job.id)
        await db.commit()
        stored = (
            await db.execute(
                select(sa.func.count()).select_from(LlmUsageEvent).where(
                    LlmUsageEvent.job_id == job.id
                )
            )
        ).scalar_one()
    assert stored == 1


# ---------- migration / metadata contract ----------


def test_migration_0007_chain_and_columns():
    import importlib.util
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0007_p22_eval_cost.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0007", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0007_p22_eval_cost"
    assert module.down_revision == "0006_p2sr_source_research"
    source = path.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    assert "drop_table" in source.split("def downgrade()")[1]


def test_metadata_contains_usage_table_and_job_columns():
    table = Base.metadata.tables["llm_usage_events"]
    for column in (
        "id",
        "job_id",
        "user_id",
        "provider",
        "model",
        "kind",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "latency_ms",
        "finish_reason",
        "cost_estimate_usd",
    ):
        assert column in table.c
    assert table.c.job_id.foreign_keys
    assert table.c.user_id.foreign_keys

    jobs = Base.metadata.tables["generation_jobs"]
    for column in ("llm_calls", "prompt_tokens", "completion_tokens", "cost_estimate_usd"):
        assert column in jobs.c


async def test_generation_api_exposes_usage_fields(client):
    """GenerationOut phải có usage fields và không lộ prompt/nội dung."""
    payload = {
        "jobId": "job_x",
        "status": "queued",
        "stage": None,
        "lessonsDone": 0,
        "lessonsTotal": None,
        "error": None,
        "llmCalls": 3,
        "promptTokens": 900,
        "completionTokens": 400,
        "costEstimateUsd": None,
        "costKnown": False,
    }
    from app.schemas.schemas import GenerationOut

    parsed = GenerationOut.model_validate(payload)
    dumped = parsed.model_dump()
    assert dumped["costKnown"] is False
    # Không có field nội dung nào (prompt text/answer) bị rò rỉ.
    assert "promptText" not in dumped
    assert "content" not in dumped


# ---------- worker integration: usage persisted + budget stops job ----------


class _RecordingProvider:
    """Bọc MockProvider, giả lập usage như một provider thật (không network)."""

    name = "recording"

    def __init__(self) -> None:
        from app.providers.mock_provider import MockProvider

        self._inner = MockProvider()

    async def generate_interview_questions(self, topic):
        from app.providers.usage import record_usage

        record_usage(
            provider="recording", model="m1", kind="interview",
            prompt_tokens=100, completion_tokens=50,
        )
        return await self._inner.generate_interview_questions(topic)

    async def generate_proposal(self, *args, **kwargs):
        return await self._inner.generate_proposal(*args, **kwargs)

    async def generate_lesson(self, *args, **kwargs):
        from app.providers.usage import record_usage

        record_usage(
            provider="recording", model="m1", kind="lesson",
            prompt_tokens=300, completion_tokens=200,
        )
        return await self._inner.generate_lesson(*args, **kwargs)


async def _course_and_job() -> tuple[uuid.UUID, uuid.UUID]:
    from app.models import User
    from app.providers import get_provider
    from app.services import course_service

    async with SessionLocal() as db:
        user = User(external_id=f"p22w-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course, _ = await course_service.create_course(
            db, user.id, "Usage", uuid.uuid4().hex, get_provider()
        )
        for i in range(5):
            await course_service.answer_interview(db, course, i, f"a{i}", get_provider())
        job = await course_service.approve_course(db, course)
        return user.id, job.id


async def test_worker_persists_usage_events_and_job_totals(monkeypatch):
    from app.worker import generation

    monkeypatch.setattr(generation, "get_provider", lambda: _RecordingProvider())
    monkeypatch.setattr(generation, "source_service", generation.source_service)
    user_id, job_id = await _course_and_job()

    await generation._run_generation_async(str(job_id))

    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        events = (
            await db.execute(
                select(LlmUsageEvent).where(LlmUsageEvent.job_id == job_id)
            )
        ).scalars().all()

    assert job.status.value == "ready"
    assert job.llm_calls == len(events) >= 4
    assert job.prompt_tokens and job.prompt_tokens > 0
    assert job.completion_tokens and job.completion_tokens > 0
    assert job.cost_estimate_usd is None  # chưa cấu hình giá → chưa biết
    assert all(e.kind in {"interview", "lesson"} for e in events)


async def test_worker_stops_job_when_token_budget_exceeded(monkeypatch):
    from app.worker import generation

    settings = get_settings()
    monkeypatch.setattr(settings, "generation_max_tokens_per_job", 50)
    monkeypatch.setattr(settings, "generation_max_cost_usd_per_job", 0.0)
    monkeypatch.setattr(generation, "get_provider", lambda: _RecordingProvider())
    _, job_id = await _course_and_job()

    await generation._run_generation_async(str(job_id))

    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()

    assert job.status.value == "failed"
    assert job.last_error_code == "BUDGET_EXCEEDED"
    assert job.error["retryable"] is False


async def test_request_path_records_usage_even_when_provider_fails(monkeypatch):
    """Interview/proposal là lời gọi thật nhưng không thuộc job nào — vẫn phải có
    event usage (chi phí đã phát sinh), và lỗi provider không làm mất bản ghi."""
    from app.providers.base import SchemaInvalidError
    from app.providers.usage import record_usage
    from app.services import course_service
    from app.models import User

    monkeypatch.setattr(get_settings(), "llm_pricing_json", "")

    class FailingProvider:
        name = "failing"

        async def generate_interview_questions(self, topic):
            record_usage(provider="failing", model="m1", kind="interview", prompt_tokens=11, completion_tokens=22)
            return [f"q{i}" for i in range(5)]

        async def generate_proposal(self, topic, questions, answers):
            record_usage(provider="failing", model="m1", kind="proposal", prompt_tokens=33, completion_tokens=44)
            raise SchemaInvalidError("bad proposal")

    async with SessionLocal() as db:
        user = User(external_id=f"req-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course, _ = await course_service.create_course(
            db, user.id, "Req", uuid.uuid4().hex, FailingProvider()
        )
        for i in range(5):
            try:
                await course_service.answer_interview(db, course, i, f"a{i}", FailingProvider())
            except Exception:
                pass

    async with SessionLocal() as db:
        events = (await db.execute(select(LlmUsageEvent).where(LlmUsageEvent.user_id == user.id))).scalars().all()

    kinds = sorted({e.kind for e in events})
    assert "interview" in kinds
    assert "proposal" in kinds
    assert all(e.job_id is None for e in events)
