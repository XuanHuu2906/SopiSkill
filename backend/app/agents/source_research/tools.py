"""Allowlisted tools cho Source Research Agent (P2.SR).

Đây là **toàn bộ** bề mặt agent được phép chạm tới. Không có tool nào:
  - thực thi shell/Python tuỳ ý;
  - đọc filesystem;
  - gọi network trực tiếp (chỉ qua adapter được tiêm vào);
  - gửi thông tin người học ra ngoài (context luôn rỗng/đã lọc).

Mọi tool đều kiểm tra: input hợp lệ, ngân sách call, timeout, và (với tool ghi)
uỷ quyền cho service layer đã xác thực ownership.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agents.source_research.adapters.base import (
    ResearchDiscoveryAdapter,
    wrap_discovery_adapter,
)
from app.agents.source_research.policies import DomainPolicy, resolve_policy
from app.agents.source_research.ranking import (
    RankedSource,
    _freshness,
    _metadata_completeness,
    _relevance,
    metadata_verification_status,
    rank_candidates,
)
from app.agents.source_research.schemas import (
    CandidateScores,
    SourceCandidate,
    TopicAnalysis,
)

DEFAULT_MAX_TOOL_CALLS = 12
DEFAULT_TOOL_TIMEOUT_SECONDS = 5.0
MAX_QUERY_LENGTH = 320
MAX_RESULTS_PER_CALL = 20

ALLOWED_TOOLS: tuple[str, ...] = (
    "search_curated_sources",
    "search_source_adapter",
    "get_source_metadata",
    "evaluate_source_metadata",
    "rank_sources",
    "save_research_result",
)


class ToolError(Exception):
    code = "SOURCE_RESEARCH_TOOL_ERROR"


class ToolValidationError(ToolError):
    code = "SOURCE_RESEARCH_TOOL_INVALID_INPUT"


class ToolBudgetExceeded(ToolError):
    code = "TOOL_BUDGET_EXCEEDED"


class ToolTimeoutError(ToolError):
    code = "SOURCE_RESEARCH_TIMEOUT"


def _validate_query(query: str) -> str:
    if not isinstance(query, str):
        raise ToolValidationError("query phải là chuỗi.")
    cleaned = " ".join(query.split())
    if not cleaned:
        raise ToolValidationError("query không được rỗng.")
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise ToolValidationError(f"query tối đa {MAX_QUERY_LENGTH} ký tự.")
    return cleaned


def _validate_max_results(max_results: int) -> int:
    if not isinstance(max_results, int) or isinstance(max_results, bool):
        raise ToolValidationError("max_results phải là số nguyên.")
    if not (1 <= max_results <= MAX_RESULTS_PER_CALL):
        raise ToolValidationError(f"max_results phải trong khoảng 1..{MAX_RESULTS_PER_CALL}.")
    return max_results


@dataclass
class ToolCall:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ResearchToolbox:
    adapter: ResearchDiscoveryAdapter
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS
    saver: Callable[[dict], Awaitable[None]] | None = None
    calls: list[ToolCall] = field(default_factory=list)

    # ---------- budget ----------

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _charge(self, name: str) -> None:
        if name not in ALLOWED_TOOLS:
            raise ToolValidationError(f"Tool '{name}' không nằm trong allowlist.")
        if len(self.calls) >= self.max_tool_calls:
            raise ToolBudgetExceeded(
                f"Vượt ngân sách {self.max_tool_calls} tool calls; dừng nghiên cứu."
            )
        self.calls.append(ToolCall(name=name, ok=True))

    async def _with_timeout(self, awaitable):
        try:
            return await asyncio.wait_for(awaitable, timeout=self.tool_timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise ToolTimeoutError(
                f"Tool vượt {self.tool_timeout_seconds}s; nguồn không phản hồi."
            ) from exc

    # ---------- discovery ----------

    async def search_source_adapter(self, query: str, *, max_results: int) -> list[SourceCandidate]:
        cleaned = _validate_query(query)
        limit = _validate_max_results(max_results)
        self._charge("search_source_adapter")
        return await self._with_timeout(self.adapter.search(cleaned, max_results=limit))

    async def search_curated_sources(self, query: str, *, max_results: int) -> list[SourceCandidate]:
        """Chỉ dùng được với adapter `curated`; adapter khác ⇒ từ chối (không đổi ý định ngầm)."""
        if getattr(self.adapter, "name", "") != "curated":
            raise ToolValidationError(
                "search_curated_sources chỉ hợp lệ với adapter 'curated'."
            )
        cleaned = _validate_query(query)
        limit = _validate_max_results(max_results)
        self._charge("search_curated_sources")
        return await self._with_timeout(self.adapter.search(cleaned, max_results=limit))

    async def get_source_metadata(self, external_id: str) -> SourceCandidate | None:
        if not isinstance(external_id, str) or not external_id.strip():
            raise ToolValidationError("external_id không được rỗng.")
        if len(external_id) > 128:
            raise ToolValidationError("external_id tối đa 128 ký tự.")
        self._charge("get_source_metadata")
        return await self._with_timeout(self.adapter.metadata(external_id.strip()))

    # ---------- evaluation / ranking ----------

    def evaluate_source_metadata(
        self, candidate: SourceCandidate
    ) -> tuple[str, CandidateScores, list[str]]:
        """Đánh giá **metadata** của một ứng viên (không đọc nội dung).

        Trả (verificationStatus, scores, reasons). Không bao giờ trả
        `content_available`/`evidence_verified`.
        """
        if not isinstance(candidate, SourceCandidate):
            raise ToolValidationError("candidate phải là SourceCandidate.")
        self._charge("evaluate_source_metadata")
        relevance, _note = _relevance(
            candidate,
            TopicAnalysis(
                mainTopic=candidate.title,
                domain="general",
                learnerLevel="beginner",
                language=candidate.language or "en",
            ),
        )
        freshness, _fnote = _freshness(candidate, "general", datetime.now(UTC))
        completeness, _cnote = _metadata_completeness(candidate)
        status, reasons = metadata_verification_status(candidate)
        policy = resolve_policy("general")
        scores = CandidateScores(
            authority=policy.priority_of(candidate.sourceType),
            relevance=relevance,
            freshness=freshness,
            metadataCompleteness=completeness,
            total=0.0,
            notes=["Đánh giá metadata đơn lẻ; total chỉ có nghĩa khi xếp hạng cùng bộ."],
        )
        return status, scores, reasons

    def rank_sources(
        self,
        candidates: list[SourceCandidate],
        analysis: TopicAnalysis,
        policy: DomainPolicy | None = None,
        *,
        max_sources: int = 8,
    ) -> tuple[list[RankedSource], list[str]]:
        if analysis is None:
            raise ToolValidationError("rank_sources cần TopicAnalysis.")
        if not isinstance(candidates, list):
            raise ToolValidationError("candidates phải là list.")
        if policy is None:
            from app.agents.source_research.policies import resolve_policy

            policy = resolve_policy(analysis.domain)
        self._charge("rank_sources")
        return rank_candidates(candidates, analysis, policy, max_sources=max_sources)

    # ---------- persistence ----------

    async def save_research_result(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict) or not payload:
            raise ToolValidationError("payload phải là dict không rỗng.")
        if self.saver is None:
            raise ToolValidationError(
                "Không có saver được cấu hình; service layer phải tiêm saver có kiểm tra quyền."
            )
        self._charge("save_research_result")
        await self._with_timeout(self.saver(payload))


def build_toolbox(
    *,
    adapter: Any,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    saver: Callable[[dict], Awaitable[None]] | None = None,
) -> ResearchToolbox:
    """Tạo toolbox từ một adapter discovery (agent-native hoặc service-level)."""
    if max_tool_calls < 1:
        raise ToolValidationError("max_tool_calls phải >= 1.")
    if tool_timeout_seconds <= 0:
        raise ToolValidationError("tool_timeout_seconds phải > 0.")
    wrapped = wrap_discovery_adapter(adapter)
    return ResearchToolbox(
        adapter=wrapped,
        max_tool_calls=max_tool_calls,
        tool_timeout_seconds=tool_timeout_seconds,
        saver=saver,
    )
