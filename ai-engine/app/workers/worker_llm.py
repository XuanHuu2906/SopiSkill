"""`ai-worker-llm`: Redis Streams consumer on `queue:ai:llm` with completeness lint + signed callback."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from redis.asyncio import Redis

from app.agents.providers import LLMProvider, get_llm_provider
from app.agents.validator_qa import run_two_tier_validator
from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings, get_settings
from app.workers.streams import RedisStreamWorker, default_consumer_name

logger = logging.getLogger(__name__)


async def handle_llm_job(
    message: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
    callback_client: CoreApiCallbackClient | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Execute one LLM generation job, validate completeness lint, and callback `core-api`."""
    cfg = settings or get_settings()
    llm = provider or get_llm_provider(cfg)
    cb = callback_client or CoreApiCallbackClient(settings=cfg)

    job_id = str(message["jobId"])
    idempotency_key = str(message["idempotencyKey"])
    job_type = str(message["jobType"])
    correlation_id = str(message.get("correlationId") or f"cor_{job_id}")
    payload = message.get("payload") or {}
    topic = str(payload.get("topic") or "Topic")
    language = "en" if payload.get("language") == "en" else "vi"
    learner_profile = payload.get("learnerProfile") or {"currentLevel": "beginner", "depth": "practical"}

    callback_payload: dict[str, Any]
    try:
        if job_type == "generate_proposal":
            proposal, usage = await llm.generate_proposal(topic, language, learner_profile)
            callback_payload = {
                "jobId": job_id,
                "idempotencyKey": idempotency_key,
                "status": "completed",
                "result": {"proposal": proposal},
                "contentFlags": [],
                "usage": usage.model_dump(),
            }
        elif job_type in {"generate_course", "generate_lesson", "regenerate_unit"}:
            course_id = str(message.get("courseId") or "")
            lesson_ids: list[str] = [str(lid) for lid in (payload.get("lessonIds") or [])]
            unit_specs = payload.get("units") or [
                {
                    "title": str(payload.get("unitTitle") or "Unit 1"),
                    "lessonTitles": [str(payload.get("lessonTitle") or f"{topic} Overview")],
                }
            ]
            generated_lessons: list[dict[str, Any]] = []
            all_flags: list[dict[str, Any]] = []
            last_usage = None
            lesson_order = 0

            for unit in unit_specs:
                u_title = str(unit.get("title") or "Unit")
                for l_title in unit.get("lessonTitles") or []:
                    lesson_profile = {**learner_profile, "_lessonOrder": lesson_order}
                    lesson, usage = await llm.generate_lesson(
                        topic, u_title, str(l_title), language, lesson_profile
                    )
                    qa = await run_two_tier_validator(
                        lesson,
                        provider=llm,
                        llm_qa_enabled=cfg.validator_llm_enabled,
                    )
                    if qa.blocking_errors:
                        raise ValueError("; ".join(qa.blocking_errors))

                    lesson["estimatedMinutes"] = qa.estimated_minutes
                    generated_lessons.append(lesson)
                    all_flags.extend(qa.content_flags)
                    last_usage = usage

                    # Phase 3 Lesson-1-First: callback each lesson immediately as it completes!
                    if lesson_order < len(lesson_ids) and course_id:
                        await cb.post_callback(
                            f"/internal/jobs/{job_id}/lesson-ready",
                            {
                                "jobId": job_id,
                                "idempotencyKey": f"{idempotency_key}:lesson:{lesson_order}",
                                "courseId": course_id,
                                "lessonId": lesson_ids[lesson_order],
                                "lessonOrder": lesson_order,
                                "status": "ready",
                                "content": lesson,
                                "estimatedMinutes": qa.estimated_minutes,
                                "contentFlags": qa.content_flags,
                                "usage": usage.model_dump() if usage else None,
                            },
                            correlation_id=correlation_id,
                        )
                    lesson_order += 1

            callback_payload = {
                "jobId": job_id,
                "idempotencyKey": idempotency_key,
                "status": "completed",
                "result": {"lessons": generated_lessons},
                "contentFlags": all_flags,
                "usage": last_usage.model_dump() if last_usage else None,
            }
        else:
            raise ValueError(f"Unsupported jobType: {job_type!r}")
    except Exception as exc:  # noqa: BLE001 — terminal validation/provider failure callback
        callback_payload = {
            "jobId": job_id,
            "idempotencyKey": idempotency_key,
            "status": "failed",
            "result": None,
            "contentFlags": [],
            "errorCode": "LLM_GENERATION_FAILED",
            "errorMessage": f"{type(exc).__name__}: {str(exc)[:240]}",
        }

    await cb.post_callback(
        f"/internal/jobs/{job_id}/complete",
        callback_payload,
        correlation_id=correlation_id,
    )
    return callback_payload


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = get_settings()
    redis = Redis.from_url(cfg.redis_url)
    worker = RedisStreamWorker(
        redis=redis,
        stream_key=cfg.stream_llm_key,
        group_name=cfg.stream_llm_group,
        dlq_key=cfg.stream_llm_dlq_key,
        consumer_name=default_consumer_name("ai-worker-llm"),
        handler=handle_llm_job,
        claim_idle_ms=cfg.stream_claim_idle_ms,
        max_retries=cfg.stream_max_retries,
        block_ms=cfg.stream_block_ms,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop)
    try:
        await worker.run_forever()
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
