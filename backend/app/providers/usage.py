"""LLM usage accounting (P2.2).

Provider adapter ghi lại **metadata** của từng lời gọi (token, latency, model,
loại call) qua một collector scoped theo task. Tầng trên (worker/API/eval) đọc
collector để:

  - lưu usage event vào DB (không lưu prompt/nội dung người học);
  - áp budget theo job (token hoặc tiền) mà không phải parse log.

Collector dùng `contextvars` nên hai task chạy song song không trộn số liệu.

Quan trọng: `cost_estimate_usd` chỉ được tính khi cấu hình giá của model. Không
biết giá ⇒ `None` (không được báo 0 như thể miễn phí).
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

# Giá mặc định để TRỐNG: provider/giá do người vận hành cấu hình. Không hardcode
# giá của bên thứ ba vì giá có thể sai và làm báo cáo chi phí sai.
PRICING_ENV_HINT = (
    'LLM_PRICING_JSON=\'{"model-name": {"inputPerMTok": 0.27, "outputPerMTok": 1.1}}\''
)


@dataclass(frozen=True)
class UsageRecord:
    provider: str
    model: str
    kind: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_ms: int | None = None
    finish_reason: str | None = None


@dataclass
class UsageCollector:
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def prompt_tokens(self) -> int:
        return sum(r.prompt_tokens or 0 for r in self.records)

    @property
    def completion_tokens(self) -> int:
        return sum(r.completion_tokens or 0 for r in self.records)

    @property
    def reasoning_tokens(self) -> int:
        return sum(r.reasoning_tokens or 0 for r in self.records)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_estimate_usd(self, pricing: dict[str, Any] | None) -> float | None:
        """Tổng chi phí ước tính; None nếu có model chưa biết giá.

        Không trả 0 khi thiếu giá — báo cáo phải phân biệt "chưa biết" với
        "miễn phí".
        """
        if not pricing:
            return None
        total = 0.0
        for record in self.records:
            price = resolve_price(pricing, record.model)
            if price is None:
                return None
            total += estimate_cost_usd(
                record.prompt_tokens, record.completion_tokens, price
            )
        return round(total, 6)

    def summary(self, pricing: dict[str, Any] | None = None) -> dict[str, Any]:
        cost = self.cost_estimate_usd(pricing)
        return {
            "calls": self.calls,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "reasoningTokens": self.reasoning_tokens,
            "totalTokens": self.total_tokens,
            "costEstimateUsd": cost,
            "costKnown": cost is not None,
            "models": sorted({r.model for r in self.records if r.model}),
        }


_current: ContextVar[UsageCollector | None] = ContextVar("llm_usage_collector", default=None)


@contextmanager
def collect_usage(collector: UsageCollector | None = None) -> Iterator[UsageCollector]:
    """Mở collector cho task hiện tại; khôi phục collector cũ khi thoát.

    Truyền `collector` để giữ tham chiếu sau khi context kết thúc (ví dụ flush
    usage trong `finally` ngay cả khi lời gọi provider raise).
    """
    collector = collector if collector is not None else UsageCollector()
    token = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)


def record_usage(
    *,
    provider: str,
    model: str,
    kind: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    reasoning_tokens: int | None = None,
    latency_ms: int | None = None,
    finish_reason: str | None = None,
) -> None:
    collector = _current.get()
    if collector is None:
        return
    collector.add(
        UsageRecord(
            provider=provider,
            model=model,
            kind=kind,
            prompt_tokens=_as_int(prompt_tokens),
            completion_tokens=_as_int(completion_tokens),
            reasoning_tokens=_as_int(reasoning_tokens),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
    )


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_pricing(raw: str | None) -> dict[str, Any]:
    """Đọc cấu hình giá. Sai định dạng ⇒ {} (coi như chưa biết giá), không raise."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_price(pricing: dict[str, Any], model: str) -> dict[str, float] | None:
    """Tìm giá theo model. Hỗ trợ khóa `"*"` làm mặc định."""
    for key in (model, "*"):
        entry = pricing.get(key)
        if isinstance(entry, dict):
            price = _normalise_price(entry)
            if price is not None:
                return price
    return None


def _normalise_price(entry: dict[str, Any]) -> dict[str, float] | None:
    try:
        input_price = float(entry.get("inputPerMTok"))
        output_price = float(entry.get("outputPerMTok"))
    except (TypeError, ValueError):
        return None
    if input_price < 0 or output_price < 0:
        return None
    return {"inputPerMTok": input_price, "outputPerMTok": output_price}


def estimate_cost_usd(
    prompt_tokens: int | None, completion_tokens: int | None, price: dict[str, float]
) -> float:
    return (
        (prompt_tokens or 0) / 1_000_000 * price["inputPerMTok"]
        + (completion_tokens or 0) / 1_000_000 * price["outputPerMTok"]
    )


class Stopwatch:
    """Đo latency quanh một lời gọi provider."""

    def __init__(self) -> None:
        self._started = time.perf_counter()

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)
