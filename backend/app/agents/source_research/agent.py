"""Source Research Agent (P2.SR) — orchestration, bounded và deterministic.

Workflow (không có vòng lặp agent tự do):

    analyze_topic (pure, không tool call)
        → search_source_adapter cho từng query (bounded bởi max_tool_calls)
        → dedupe canonical URL
        → rank_sources (domain policy)
        → save_research_result (nếu có saver = service đã xác thực quyền)

Agent KHÔNG:
  - đọc nội dung nguồn (nên không thể nâng lên `content_available`);
  - sinh citation/DOI/tác giả;
  - gọi LLM hoặc network trực tiếp;
  - truy cập DB (chỉ qua saver do service layer tiêm vào).
"""

from __future__ import annotations

import logging
import uuid

from app.agents.source_research.policies import resolve_policy
from app.agents.source_research.ranking import dedupe_candidates, to_ranked_source_out
from app.agents.source_research.schemas import (
    ResearchError,
    ResearchRequest,
    ResearchResult,
)
from app.agents.source_research.tools import (
    MAX_RESULTS_PER_CALL,
    ResearchToolbox,
    ToolBudgetExceeded,
    ToolTimeoutError,
    ToolValidationError,
)
from app.agents.source_research.topic import analyze_topic
from app.services.source_discovery import SourceDiscoveryConfigError, SourceDiscoveryError

logger = logging.getLogger(__name__)

# Số query tối đa agent dùng cho discovery. Giữ nhỏ để chi phí bounded và kết quả
# dễ giải thích (query nào đóng góp nguồn nào).
MAX_SEARCH_QUERIES = 2

_MOCK_NOTICE = (
    "Kết quả MOCK: KHÔNG phải tìm kiếm thật, KHÔNG xác minh nội dung. "
    "Không dùng làm citation trong khóa học thật."
)
_CURATED_NOTICE = (
    "Kết quả từ danh mục nguồn chọn tay (curated): metadata do người vận hành cung cấp, "
    "chưa được đối chiếu với nội dung gốc và chưa phải citation đã xác minh."
)
_INSUFFICIENT_NOTICE = (
    "Không tìm đủ nguồn phù hợp. Nội dung khóa học (nếu tiếp tục) chỉ dựa trên kiến thức "
    "chung của AI và không có căn cứ tài liệu."
)


class SourceResearchAgent:
    def __init__(self, toolbox: ResearchToolbox) -> None:
        self._toolbox = toolbox

    async def run(self, request: ResearchRequest, *, run_id: uuid.UUID | None = None) -> ResearchResult:
        run_id = run_id or uuid.uuid4()
        analysis = analyze_topic(request)
        policy = resolve_policy(analysis.domain)
        warnings: list[str] = []

        # Không liên kết người học với query: hồ sơ người học không được gửi ra adapter.
        queries = analysis.searchQueries[:MAX_SEARCH_QUERIES] or [analysis.mainTopic]
        per_query = max(1, min(request.maxSources * 2, MAX_RESULTS_PER_CALL))

        collected = []
        try:
            for query in queries:
                try:
                    found = await self._toolbox.search_source_adapter(
                        query, max_results=per_query
                    )
                except ToolBudgetExceeded as exc:
                    warnings.append(f"{exc.code}: {exc}")
                    break
                collected.extend(found)
        except ToolValidationError as exc:
            return self._failed(run_id, request, analysis, warnings, exc.code, str(exc))
        except ToolTimeoutError as exc:
            return self._failed(
                run_id, request, analysis, warnings, "SOURCE_RESEARCH_TIMEOUT", str(exc), retryable=True
            )
        except SourceDiscoveryConfigError as exc:
            return self._failed(
                run_id, request, analysis, warnings, exc.code, str(exc)[:300]
            )
        except SourceDiscoveryError as exc:
            return self._failed(
                run_id, request, analysis, warnings, exc.code, str(exc)[:300], retryable=True
            )
        except Exception as exc:  # noqa: BLE001 — adapter lạ phải trả lỗi có mã, không sập job
            logger.warning(
                "source research adapter failed run_id=%s adapter=%s err=%s",
                run_id,
                getattr(self._toolbox.adapter, "name", "unknown"),
                type(exc).__name__,
            )
            return self._failed(
                run_id,
                request,
                analysis,
                warnings,
                "SOURCE_RESEARCH_ADAPTER_ERROR",
                "Adapter tìm nguồn gặp lỗi không xác định.",
                retryable=True,
            )

        deduped, dedupe_warnings = dedupe_candidates(collected)
        warnings.extend(dedupe_warnings)

        try:
            ranked, rank_warnings = self._toolbox.rank_sources(
                deduped, analysis, policy, max_sources=request.maxSources
            )
        except ToolBudgetExceeded as exc:
            warnings.append(f"{exc.code}: {exc}")
            ranked, rank_warnings = [], []
        except ToolValidationError as exc:
            return self._failed(run_id, request, analysis, warnings, exc.code, str(exc))
        warnings.extend(rank_warnings)

        is_mock = bool(getattr(self._toolbox.adapter, "is_mock", False))
        sources = [
            to_ranked_source_out(item, adapter=self._toolbox.adapter.name, is_mock=is_mock)
            for item in ranked
        ]

        if is_mock and sources:
            warnings.append(
                "Nguồn là dữ liệu MOCK (deterministic, không có thật). Không được coi là đã xác minh."
            )
        if not getattr(self._toolbox.adapter, "deterministic", True):
            warnings.append("Adapter không đảm bảo deterministic; cùng input có thể khác output.")
        if analysis.learnerLevel == "advanced" and not analysis.prerequisites:
            warnings.append("Chủ đề nâng cao nhưng chưa xác định kiến thức tiên quyết.")

        insufficient = len(sources) == 0
        status = "insufficient_evidence" if insufficient else "completed"
        if insufficient:
            warnings.append(
                "Không tìm thấy nguồn phù hợp trong danh mục/adapter hiện tại; "
                "không có nguồn nào được đề xuất."
            )
        notice = _MOCK_NOTICE if is_mock else (_INSUFFICIENT_NOTICE if insufficient else _CURATED_NOTICE)

        result = ResearchResult(
            researchRunId=run_id,
            courseId=request.courseId,
            topic=request.topic,
            domain=analysis.domain,
            status=status,
            sources=sources,
            warnings=warnings[:40],
            insufficientEvidence=insufficient,
            analysis=analysis,
            error=None,
            adapter=self._toolbox.adapter.name,
            isMock=is_mock,
            toolCalls=self._toolbox.call_count,
            notice=notice,
        )

        if self._toolbox.saver is not None:
            payload = result.model_dump(mode="json")
            payload["request"] = request.model_dump(mode="json")
            try:
                await self._toolbox.save_research_result(payload)
            except ToolBudgetExceeded as exc:
                result = result.model_copy(update={"warnings": (warnings + [f"{exc.code}: {exc}"])[:40]})
            except ToolTimeoutError as exc:
                result = result.model_copy(
                    update={"warnings": (warnings + [f"Lưu kết quả nghiên cứu quá hạn: {exc}"])[:40]}
                )

        logger.info(
            "source research done run_id=%s course_id=%s adapter=%s status=%s sources=%s tool_calls=%s",
            run_id,
            request.courseId,
            result.adapter,
            result.status,
            len(result.sources),
            result.toolCalls,
        )
        return result

    def _failed(
        self,
        run_id: uuid.UUID,
        request: ResearchRequest,
        analysis,
        warnings: list[str],
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> ResearchResult:
        return ResearchResult(
            researchRunId=run_id,
            courseId=request.courseId,
            topic=request.topic,
            domain=analysis.domain,
            status="failed",
            sources=[],
            warnings=(warnings + [f"{code}: {message}"])[:40],
            insufficientEvidence=True,
            analysis=analysis,
            error=ResearchError(code=code, message=message, retryable=retryable),
            adapter=getattr(self._toolbox.adapter, "name", "unknown"),
            isMock=bool(getattr(self._toolbox.adapter, "is_mock", False)),
            toolCalls=self._toolbox.call_count,
            notice="Nghiên cứu nguồn thất bại. Không có nguồn nào được đề xuất.",
        )
