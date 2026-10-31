"""Adapter interface cho Source Research Agent (P2.SR).

TÁI SỬ DỤNG, không nhân bản: adapter discovery thật đã có ở
`app.services.source_discovery` (`curated`, `mock`, `web` placeholder). Module này
chỉ định nghĩa **hợp đồng tối thiểu** mà agent cần và lớp adapter chuyển đổi
`SourceCandidateOut` → `SourceCandidate` của agent.

Muốn thêm Crossref/OpenAlex/arXiv ở tương lai: implement `SourceDiscoveryAdapter`
trong `app/services/source_discovery.py` (kèm allowlist + SSRF guard) rồi bọc ở đây.
Agent không tự gọi HTTP.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.agents.source_research.schemas import SourceCandidate
from app.services.source_discovery import SourceDiscoveryAdapter


@runtime_checkable
class ResearchDiscoveryAdapter(Protocol):
    """Hợp đồng agent dùng. Không có method nào được phép gọi mạng ngầm."""

    name: str
    deterministic: bool
    is_mock: bool

    async def search(self, query: str, *, max_results: int) -> list[SourceCandidate]:
        ...

    async def metadata(self, external_id: str) -> SourceCandidate | None:
        ...


class ServiceDiscoveryBridge:
    """Bọc một `SourceDiscoveryAdapter` sẵn có thành adapter của agent."""

    def __init__(self, adapter: SourceDiscoveryAdapter) -> None:
        self._adapter = adapter
        self.name = adapter.name
        self.deterministic = adapter.deterministic
        self.is_mock = adapter.is_mock

    async def search(self, query: str, *, max_results: int) -> list[SourceCandidate]:
        raw = await self._adapter.search_sources(query, context=None)
        converted: list[SourceCandidate] = []
        for item in raw[:max_results]:
            converted.append(
                SourceCandidate(
                    adapter=item.adapter or self.name,
                    candidateId=item.externalId,
                    sourceType=item.sourceType,
                    title=item.title,
                    canonicalUrl=item.canonicalUrl,
                    publisher=item.publisher,
                    author=item.author,
                    publicationDate=item.publicationDate,
                    language=item.language,
                    version=item.version,
                    licenseInfo=item.licenseInfo,
                    deterministic=item.deterministic,
                    isMock=item.isMock,
                )
            )
        return converted

    async def metadata(self, external_id: str) -> SourceCandidate | None:
        item = await self._adapter.get_source_metadata(external_id)
        if item is None:
            return None
        return SourceCandidate(
            adapter=item.adapter or self.name,
            candidateId=item.externalId,
            sourceType=item.sourceType,
            title=item.title,
            canonicalUrl=item.canonicalUrl,
            publisher=item.publisher,
            author=item.author,
            publicationDate=item.publicationDate,
            language=item.language,
            version=item.version,
            licenseInfo=item.licenseInfo,
            deterministic=item.deterministic,
            isMock=item.isMock,
        )


def wrap_discovery_adapter(adapter: SourceDiscoveryAdapter) -> ResearchDiscoveryAdapter:
    if isinstance(adapter, ResearchDiscoveryAdapter):
        return adapter
    return ServiceDiscoveryBridge(adapter)
