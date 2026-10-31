"""P2.2 — lưu usage/cost của LLM và áp budget cho generation job.

Nguyên tắc:
  - Chỉ lưu metadata (token/latency/model). Không lưu prompt/nội dung người học.
  - `cost_estimate_usd = None` khi chưa cấu hình giá model: "chưa biết" ≠ 0.
  - Budget chặn **trước** khi vượt trần: worker kiểm tra sau mỗi lời gọi và dừng
    job với `BUDGET_EXCEEDED` (không retry — retry chỉ đốt thêm tiền).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import GenerationJob, LlmUsageEvent
from app.providers.usage import UsageCollector, parse_pricing, resolve_price, estimate_cost_usd

logger = logging.getLogger(__name__)

# Lỗi riêng để worker phân loại là fatal (không requeue).
BUDGET_ERROR_CODE = "BUDGET_EXCEEDED"


class JobBudgetExceeded(RuntimeError):
    """Job vượt trần token/chi phí đã cấu hình. Fatal — không retry."""

    def __init__(self, message: str, *, code: str = BUDGET_ERROR_CODE) -> None:
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:  # worker dựa vào prefix trong classify_error
        return f"{self.code}: {super().__str__()}"


def pricing() -> dict:
    return parse_pricing(get_settings().llm_pricing_json)


def _record_cost(record, pricing_config: dict) -> float | None:
    price = resolve_price(pricing_config, record.model)
    if price is None:
        return None
    return round(
        estimate_cost_usd(record.prompt_tokens, record.completion_tokens, price), 6
    )


async def flush_usage(
    db: AsyncSession,
    collector: UsageCollector,
    *,
    job_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    mark_flushed: bool = True,
) -> dict:
    """Ghi usage event vào DB và (nếu có job) cộng dồn vào job.

    Trả summary dict. `mark_flushed` xoá record khỏi collector để lần flush sau
    không ghi trùng (worker flush sau từng lesson).
    """
    pricing_config = pricing()
    rows: list[LlmUsageEvent] = []
    total_cost: float | None = 0.0
    for record in collector.records:
        cost = _record_cost(record, pricing_config)
        if cost is None:
            total_cost = None
        elif total_cost is not None:
            total_cost += cost
        rows.append(
            LlmUsageEvent(
                job_id=job_id,
                user_id=user_id,
                provider=record.provider,
                model=record.model,
                kind=record.kind,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                reasoning_tokens=record.reasoning_tokens,
                latency_ms=record.latency_ms,
                finish_reason=record.finish_reason,
                cost_estimate_usd=cost,
            )
        )
    if rows:
        db.add_all(rows)

    summary = {
        "calls": len(rows),
        "promptTokens": sum(r.prompt_tokens or 0 for r in collector.records),
        "completionTokens": sum(r.completion_tokens or 0 for r in collector.records),
        "costEstimateUsd": None if total_cost is None else round(total_cost, 6),
        "costKnown": total_cost is not None,
    }

    if job_id is not None and rows:
        await _add_to_job(db, job_id, summary)
    if mark_flushed:
        collector.records.clear()
    return summary


async def _add_to_job(db: AsyncSession, job_id: uuid.UUID, summary: dict) -> None:
    job = (
        await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return
    job.llm_calls = (job.llm_calls or 0) + summary["calls"]
    job.prompt_tokens = (job.prompt_tokens or 0) + summary["promptTokens"]
    job.completion_tokens = (job.completion_tokens or 0) + summary["completionTokens"]
    if summary["costEstimateUsd"] is None:
        job.cost_estimate_usd = None
    else:
        job.cost_estimate_usd = round(
            (job.cost_estimate_usd or 0.0) + summary["costEstimateUsd"], 6
        )
    await db.flush()


async def job_usage(db: AsyncSession, job_id: uuid.UUID) -> dict:
    """Đọc usage đã lưu của job (dùng cho API response)."""
    job = (
        await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return {}
    return {
        "llmCalls": job.llm_calls or 0,
        "promptTokens": job.prompt_tokens,
        "completionTokens": job.completion_tokens,
        "costEstimateUsd": job.cost_estimate_usd,
        # FALSE khi chưa biết giá: UI/report phải nói "chưa biết giá", không "miễn phí".
        "costKnown": job.cost_estimate_usd is not None,
    }


async def record_standalone(
    collector: UsageCollector,
    *,
    job_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Ghi usage bằng session RIÊNG, best-effort.

    Dùng cho lời gọi phát sinh trong request (interview/proposal): request có thể
    rollback vì lỗi provider, nhưng chi phí đã phát sinh thì vẫn phải ghi nhận.
    Lỗi accounting không bao giờ được làm hỏng request.
    """
    if not collector.records:
        return
    from app.db.session import SessionLocal

    try:
        async with SessionLocal() as session:
            await flush_usage(session, collector, job_id=job_id, user_id=user_id)
            await session.commit()
    except Exception:  # noqa: BLE001 — accounting là best-effort
        logger.warning("standalone llm usage persistence failed", exc_info=False)


def _limits() -> tuple[int, float]:
    settings = get_settings()
    return (
        int(settings.generation_max_tokens_per_job or 0),
        float(settings.generation_max_cost_usd_per_job or 0.0),
    )


def check_job_budget(job: GenerationJob) -> None:
    """Raise JobBudgetExceeded nếu job đã vượt trần token/chi phí."""
    max_tokens, max_cost = _limits()
    if max_tokens > 0:
        used = (job.prompt_tokens or 0) + (job.completion_tokens or 0)
        if used > max_tokens:
            raise JobBudgetExceeded(
                f"Job đã dùng {used} token, vượt trần {max_tokens}."
            )
    if max_cost > 0 and job.cost_estimate_usd is not None:
        if job.cost_estimate_usd > max_cost:
            raise JobBudgetExceeded(
                f"Job đã tốn ~${job.cost_estimate_usd:.4f}, vượt trần ${max_cost:.4f}."
            )


async def enforce_job_budget(db: AsyncSession, job_id: uuid.UUID) -> None:
    """Đọc lại job rồi kiểm tra trần. Dùng sau khi flush usage của mỗi lesson."""
    job = (
        await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return
    check_job_budget(job)


async def mark_job_failed_budget(db: AsyncSession, job_id: uuid.UUID, exc: BaseException) -> None:
    """Ghi trạng thái failed cho job do vượt budget (không retry)."""
    await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id)
        .values(
            status="failed",
            lease_expires_at=None,
            last_error_code=BUDGET_ERROR_CODE,
            error={
                "code": BUDGET_ERROR_CODE,
                "message": str(exc)[:200],
                "retryable": False,
            },
        )
    )
    await db.commit()


def cost_for_pricing(prompt_tokens: int | None, completion_tokens: int | None, model: str) -> float | None:
    """Helper cho eval/judge: tính cost một lời gọi theo cấu hình giá hiện tại."""
    price = resolve_price(pricing(), model)
    if price is None:
        return None
    return round(estimate_cost_usd(prompt_tokens, completion_tokens, price), 6)
