"""`ai-worker-llm`: Redis Streams consumer on `queue:ai:llm` with completeness lint + signed callback."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.lesson_generator import (
    MaxTurnsExceededError,
    _default_source_reader,
    generate_lesson_with_qa_loop,
    wrap_source_evidence,
)
from app.agents.planner_agent import (
    PlannerMaxTurnsError,
    generate_proposal_with_tools,
)
from app.agents.providers import LLMProvider, get_llm_provider
from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.rag.query_bridge import expand_cross_lingual_query
from app.rag.repository import RagRepository
from app.workers.streams import RedisStreamWorker, default_consumer_name

logger = logging.getLogger(__name__)


def _build_hybrid_rag_source_reader(
    *,
    owner_id: str,
    course_id: str,
    source_ids: list[str],
    source_languages: list[str] | None,
    source_brief: dict[str, Any] | None,
    rag_repo: RagRepository,
    db: AsyncSession | None,
):
    """Returns a `read_source(anchor, query)` callback backed by real `RagRepository.search` chunks.

    Applies Phase L4 Cross-Lingual Query Bridge (`VI -> EN`) when searching English textbooks,
    and falls back seamlessly to `_default_source_reader(source_brief)` if DB has 0 chunks.
    """
    brief_fallback = _default_source_reader(source_brief)

    async def _read(anchor: str | None, query: str | None) -> list[dict[str, Any]]:
        raw_query = " ".join(p for p in [anchor or "", query or ""] if p).strip() or "overview"
        effective_query = expand_cross_lingual_query(raw_query, source_languages=source_languages)
        hits = []
        try:
            if db is not None:
                _, hits = await rag_repo.search(
                    db,
                    owner_id=owner_id,
                    course_id=course_id,
                    query=effective_query,
                    source_ids=source_ids,
                    top_k=4,
                )
            else:
                factory = get_session_factory()
                async with factory() as session:
                    _, hits = await rag_repo.search(
                        session,
                        owner_id=owner_id,
                        course_id=course_id,
                        query=effective_query,
                        source_ids=source_ids,
                        top_k=4,
                    )
        except Exception as exc:  # noqa: BLE001 — fallback cleanly to brief reader
            logger.warning("worker_llm_rag_read_fallback error_type=%s", type(exc).__name__)
            hits = []

        if hits:
            return [
                {
                    "chunkId": h.chunkId,
                    "sourceId": h.sourceId,
                    "documentId": h.documentId,
                    "sourceTitle": h.sourceTitle,
                    "pageNumber": h.pageNumber,
                    "sectionAnchor": h.sectionAnchor,
                    "anchor": h.sectionAnchor or "",
                    "rawExcerpt": h.content[:1200],
                    "excerpt": wrap_source_evidence(h.content[:1200]),
                    "score": h.score,
                }
                for h in hits
            ]
        return await brief_fallback(anchor, query)

    return _read


async def handle_llm_job(
    message: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
    callback_client: CoreApiCallbackClient | None = None,
    settings: Settings | None = None,
    db: AsyncSession | None = None,
    rag_repo: RagRepository | None = None,
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
            source_brief = payload.get("sourceBrief") if isinstance(payload.get("sourceBrief"), dict) else None
            plan_res = await generate_proposal_with_tools(
                topic=topic,
                language=language,
                learner_profile=learner_profile,
                provider=llm,
                source_brief=source_brief,
                max_turns=cfg.planner_max_turns,
            )
            callback_payload = {
                "jobId": job_id,
                "idempotencyKey": idempotency_key,
                "status": "completed",
                "result": {"proposal": plan_res.proposal},
                "contentFlags": [],
                "usage": plan_res.usage.model_dump(),
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

            source_brief = payload.get("sourceBrief") if isinstance(payload.get("sourceBrief"), dict) else None
            raw_source_ids = payload.get("sourceIds")
            source_ids: list[str] = (
                [str(s).strip() for s in raw_source_ids if str(s).strip()]
                if isinstance(raw_source_ids, list)
                else []
            )
            raw_source_langs = payload.get("sourceLanguages")
            source_languages: list[str] = (
                [str(s).strip() for s in raw_source_langs if str(s).strip()]
                if isinstance(raw_source_langs, list)
                else []
            )
            owner_id = str(message.get("ownerId") or "")
            source_reader = None
            if source_ids and owner_id:
                repo = rag_repo or RagRepository(settings=cfg)
                source_reader = _build_hybrid_rag_source_reader(
                    owner_id=owner_id,
                    course_id=course_id,
                    source_ids=source_ids,
                    source_languages=source_languages,
                    source_brief=source_brief,
                    rag_repo=repo,
                    db=db,
                )

            for unit in unit_specs:
                u_title = str(unit.get("title") or "Unit")
                for l_title in unit.get("lessonTitles") or []:
                    lesson_profile = {**learner_profile, "_lessonOrder": lesson_order}
                    gen_res = await generate_lesson_with_qa_loop(
                        topic=topic,
                        unit_title=u_title,
                        lesson_title=str(l_title),
                        language=language,
                        learner_profile=lesson_profile,
                        provider=llm,
                        source_brief=source_brief,
                        source_reader=source_reader,
                        image_gen_enabled=cfg.lesson_images_enabled,
                        max_turns=cfg.lesson_gen_max_turns,
                        max_refine_rounds=cfg.lesson_refine_max_rounds,
                        llm_qa_enabled=cfg.validator_llm_enabled,
                    )
                    lesson = gen_res.lesson
                    qa = gen_res.qa
                    usage = gen_res.usage
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
                                "citations": gen_res.citations,
                                "grounding": gen_res.grounding,
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
    except (MaxTurnsExceededError, PlannerMaxTurnsError) as exc:
        callback_payload = {
            "jobId": job_id,
            "idempotencyKey": idempotency_key,
            "status": "failed",
            "result": None,
            "contentFlags": [],
            "errorCode": "max_turns",
            "errorMessage": str(exc)[:240],
        }
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
