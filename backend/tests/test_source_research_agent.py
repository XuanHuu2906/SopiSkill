"""P2.SR — Source Research Agent (unit, offline, deterministic).

Bao phủ AC01–AC05, AC09 (agent-level):
  - topic analysis deterministic;
  - candidate validation + dedupe canonical URL;
  - ranking theo domain policy, có giải thích;
  - mock deterministic, không network, không tự verified;
  - bounded tool calls / max sources;
  - timeout & adapter failure ⇒ error state rõ ràng.
"""

import asyncio
import json
import socket
import uuid

import pytest

from app.agents.source_research import (
    ResearchRequest,
    SourceCandidate,
    SourceResearchAgent,
    analyze_topic,
    ToolBudgetExceeded,
    ToolValidationError,
    build_toolbox,
    dedupe_candidates,
    resolve_policy,
)
from app.services import source_discovery

def make_candidate(**overrides) -> SourceCandidate:
    values = {
        "adapter": "curated",
        "candidateId": overrides.pop("candidateId", f"c-{uuid.uuid4().hex[:8]}"),
        "sourceType": overrides.pop("sourceType", "official_documentation"),
        "title": overrides.pop("title", "Python Documentation"),
        "canonicalUrl": overrides.pop("canonicalUrl", "https://docs.python.org/3/"),
        "publisher": overrides.pop("publisher", "Python Software Foundation"),
        "author": overrides.pop("author", None),
        "publicationDate": overrides.pop("publicationDate", "2025-01-01"),
        "language": overrides.pop("language", "en"),
        "version": overrides.pop("version", "3.13"),
        "licenseInfo": overrides.pop("licenseInfo", "PSF License"),
        "isMock": overrides.pop("isMock", False),
        "deterministic": overrides.pop("deterministic", True),
    }
    values.update(overrides)
    return SourceCandidate(**values)


def make_request(**overrides) -> ResearchRequest:
    values = {
        "courseId": uuid.uuid4(),
        "topic": "Học Python để xây dựng ứng dụng AI từ con số 0.",
        "learnerLevel": None,
        "learningGoals": [],
        "preferredLanguage": "vi",
        "maxSources": 8,
    }
    values.update(overrides)
    return ResearchRequest(**values)


# ---------- topic analysis ----------


def test_topic_analysis_extracts_domain_subtopics_and_level():
    analysis = analyze_topic(make_request())

    assert analysis.domain == "programming"
    assert analysis.mainTopic.lower().startswith("học python")
    # Ví dụ trong đề bài yêu cầu nhận ra các chủ đề con cốt lõi.
    joined = {t.casefold() for t in analysis.subTopics}
    for expected in (
        "python basics",
        "data structures",
        "functions and modules",
        "programming fundamentals",
        "numpy",
        "machine learning fundamentals",
    ):
        assert expected in joined, f"thiếu chủ đề con {expected}: {analysis.subTopics}"
    assert analysis.learnerLevel == "beginner"
    assert "Programming Fundamentals" in analysis.prerequisites
    assert analysis.searchQueries and len(analysis.searchQueries) <= 4
    assert analysis.recommendedSourceTypes[0] == "official_documentation"


def test_topic_analysis_detects_medicine_domain():
    analysis = analyze_topic(make_request(topic="Hướng dẫn chẩn đoán và điều trị tăng huyết áp"))
    assert analysis.domain == "medicine"
    policy = resolve_policy(analysis.domain)
    assert policy.typePriority["clinical_guideline"] > policy.typePriority["community_tutorial"]
    assert "clinical_guideline" in analysis.recommendedSourceTypes


def test_topic_analysis_unknown_domain_falls_back_to_general():
    analysis = analyze_topic(make_request(topic="Lịch sử gốm sứ Việt Nam"))
    assert analysis.domain == "general"
    assert analysis.subTopics == [] or isinstance(analysis.subTopics, list)


def test_research_request_rejects_unbounded_input():
    with pytest.raises(ValueError):
        make_request(maxSources=0)
    with pytest.raises(ValueError):
        make_request(maxSources=21)
    with pytest.raises(ValueError):
        make_request(topic="   ")
    with pytest.raises(ValueError):
        make_request(learningGoals=[f"goal-{i}" for i in range(9)])


def test_source_candidate_rejects_non_http_url_and_empty_title():
    with pytest.raises(ValueError):
        make_candidate(canonicalUrl="ftp://example.com/x")
    with pytest.raises(ValueError):
        make_candidate(canonicalUrl="javascript:alert(1)")
    with pytest.raises(ValueError):
        make_candidate(title="")


# ---------- dedupe ----------


def test_dedupe_candidates_by_canonical_url_ignores_case_and_fragment():
    first = make_candidate(canonicalUrl="https://Docs.Python.org/3/#intro", candidateId="a")
    second = make_candidate(canonicalUrl="https://docs.python.org/3/", candidateId="b")
    kept, warnings = dedupe_candidates([first, second])
    assert [c.candidateId for c in kept] == ["a"]
    assert warnings and "trùng" in warnings[0].casefold()


def test_dedupe_keeps_candidates_without_url_by_external_id():
    first = make_candidate(canonicalUrl=None, candidateId="same")
    second = make_candidate(canonicalUrl=None, candidateId="same")
    kept, _ = dedupe_candidates([first, second])
    assert len(kept) == 1


# ---------- ranking / policy ----------


async def test_ranking_prefers_official_docs_for_programming_and_explains():
    catalog = json.dumps(
        [
            {
                "id": "py-docs",
                "title": "Python official documentation",
                "sourceType": "official_documentation",
                "canonicalUrl": "https://docs.python.org/3/",
                "publisher": "Python Software Foundation",
                "publicationDate": "2025-06-01",
                "version": "3.13",
                "licenseInfo": "PSF License",
                "language": "en",
                "tags": "python basics data structures functions",
            },
            {
                "id": "random-blog",
                "title": "Python basics blog post",
                "sourceType": "community_tutorial",
                "canonicalUrl": "https://blog.example.com/python-basics",
                "publisher": "Random Blog",
                "publicationDate": "2025-06-01",
                "language": "vi",
                "tags": "python basics",
            },
        ]
    )
    adapter = source_discovery.CuratedCatalogAdapter(catalog_json=catalog)
    toolbox = build_toolbox(adapter=adapter, max_tool_calls=10, tool_timeout_seconds=1.0)
    agent = SourceResearchAgent(toolbox)

    result = await agent.run(make_request(maxSources=2), run_id=uuid.uuid4())

    assert result.status == "completed"
    assert result.isMock is False
    assert [s.candidateId for s in result.sources][0] == "py-docs"
    best = result.sources[0]
    assert best.selectionReason
    assert "official_documentation" in best.selectionReason
    assert best.scores.total >= result.sources[1].scores.total
    assert result.sources[0].verificationStatus == "metadata_verified"


async def test_ranking_prefers_clinical_guidelines_for_medicine():
    from app.agents.source_research.ranking import rank_candidates

    analysis = analyze_topic(make_request(topic="Hướng dẫn điều trị tăng huyết áp"))
    policy = resolve_policy(analysis.domain)
    guideline = make_candidate(
        sourceType="clinical_guideline",
        title="Hướng dẫn điều trị tăng huyết áp",
        publisher="Bộ Y tế",
        canonicalUrl="https://guideline.example.org/htn",
    )
    blog = make_candidate(
        sourceType="community_tutorial",
        title="Blog điều trị tăng huyết áp",
        publisher="Blog",
        canonicalUrl="https://blog.example.com/htn",
    )
    ranked, _ = rank_candidates([blog, guideline], analysis, policy, max_sources=2)
    assert ranked[0].candidate.sourceType == "clinical_guideline"
    assert ranked[0].scores.total > ranked[1].scores.total


# ---------- mock determinism & honesty ----------


async def test_mock_research_is_deterministic_and_never_verified():
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
    agent = SourceResearchAgent(toolbox)

    first = await agent.run(make_request(), run_id=uuid.uuid4())
    second = await agent.run(make_request(), run_id=uuid.uuid4())

    assert first.status == "completed"
    assert first.isMock is True
    assert [s.model_dump() for s in first.sources] == [s.model_dump() for s in second.sources]
    assert first.warnings == second.warnings
    assert all(s.verificationStatus == "discovered" for s in first.sources)
    assert all(s.sourceId is None for s in first.sources)
    assert first.insufficientEvidence is False
    assert any("mock" in w.casefold() for w in first.warnings)
    # Không có citation/sourceId do agent tự sinh trong payload.
    payload = first.model_dump(mode="json")
    assert "citations" not in payload
    assert all(source["sourceId"] is None for source in payload["sources"])
    assert all("doi" not in source.keys() for source in payload["sources"])


async def test_mock_research_opens_no_socket(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("Source Research mock không được mở socket")

    monkeypatch.setattr(socket, "socket", _boom)
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
    result = await SourceResearchAgent(toolbox).run(make_request(), run_id=uuid.uuid4())
    assert result.sources


async def test_empty_catalog_reports_insufficient_evidence():
    adapter = source_discovery.CuratedCatalogAdapter(catalog_json="[]")
    result = await SourceResearchAgent(build_toolbox(adapter=adapter)).run(
        make_request(topic="Chủ đề không có trong danh mục"), run_id=uuid.uuid4()
    )
    assert result.status == "insufficient_evidence"
    assert result.sources == []
    assert result.insufficientEvidence is True
    assert result.warnings


async def test_max_sources_is_enforced():
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
    result = await SourceResearchAgent(toolbox).run(
        make_request(maxSources=2, topic="Python"), run_id=uuid.uuid4()
    )
    assert len(result.sources) <= 2


async def test_max_sources_upper_bound_does_not_break_discovery():
    """maxSources=20 vượt trần max_results mỗi lần gọi tool ⇒ agent phải clamp,
    không được biến thành lỗi tool input."""
    for limit in (1, 8, 20):
        toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
        result = await SourceResearchAgent(toolbox).run(
            make_request(maxSources=limit, topic="Python"), run_id=uuid.uuid4()
        )
        assert result.status == "completed", result.error
        assert 1 <= len(result.sources) <= limit


# ---------- bounded tools ----------


async def test_tool_budget_is_bounded_and_reported():
    toolbox = build_toolbox(
        adapter=source_discovery.MockDiscoveryAdapter(), max_tool_calls=2, tool_timeout_seconds=1.0
    )
    result = await SourceResearchAgent(toolbox).run(
        make_request(topic="Python"), run_id=uuid.uuid4()
    )
    assert any("TOOL_BUDGET_EXCEEDED" in w for w in result.warnings)
    # Vẫn trả kết quả từ các tool call đã dùng, không treo.
    assert result.status in ("completed", "insufficient_evidence")


class _SlowAdapter(source_discovery.SourceDiscoveryAdapter):
    name = "slow"
    deterministic = False
    is_mock = False

    async def search_sources(self, topic, context=None):
        await asyncio.sleep(0.2)
        return []

    async def get_source_metadata(self, external_id):
        return None


async def test_adapter_timeout_produces_error_state():
    toolbox = build_toolbox(adapter=_SlowAdapter(), tool_timeout_seconds=0.02)
    result = await SourceResearchAgent(toolbox).run(make_request(), run_id=uuid.uuid4())
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code in ("SOURCE_RESEARCH_TIMEOUT", "SOURCE_RESEARCH_ADAPTER_ERROR")
    assert result.insufficientEvidence is True


class _BrokenAdapter(source_discovery.SourceDiscoveryAdapter):
    name = "broken"
    deterministic = False
    is_mock = False

    async def search_sources(self, topic, context=None):
        raise source_discovery.SourceDiscoveryConfigError("hỏng cấu hình")

    async def get_source_metadata(self, external_id):
        return None


async def test_adapter_config_failure_is_structured_error():
    toolbox = build_toolbox(adapter=_BrokenAdapter(), tool_timeout_seconds=1.0)
    result = await SourceResearchAgent(toolbox).run(make_request(), run_id=uuid.uuid4())
    assert result.status == "failed"
    assert result.error.code == "SOURCE_DISCOVERY_NOT_CONFIGURED"


async def test_tool_rejects_invalid_input():
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
    with pytest.raises(ToolValidationError):
        await toolbox.search_source_adapter("", max_results=5)
    with pytest.raises(ToolValidationError):
        await toolbox.search_source_adapter("python", max_results=0)
    with pytest.raises(ToolValidationError):
        toolbox.rank_sources([], analysis=None)  # type: ignore[arg-type]


async def test_curated_tool_refuses_non_curated_adapter():
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter())
    with pytest.raises(ToolValidationError):
        await toolbox.search_curated_sources("python", max_results=3)


async def test_toolbox_reports_budget_exhaustion():
    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter(), max_tool_calls=1)
    await toolbox.search_source_adapter("python", max_results=2)
    with pytest.raises(ToolBudgetExceeded):
        await toolbox.search_source_adapter("python basics", max_results=2)


async def test_save_research_result_uses_injected_saver():
    saved: list[dict] = []

    async def saver(payload: dict) -> None:
        saved.append(payload)

    toolbox = build_toolbox(adapter=source_discovery.MockDiscoveryAdapter(), saver=saver)
    await SourceResearchAgent(toolbox).run(make_request(topic="Python"), run_id=uuid.uuid4())
    assert saved and saved[0]["status"] in ("completed", "insufficient_evidence")
