"""Mock adapter cho Source Research Agent (P2.SR).

Mục đích: chạy offline, deterministic, và **không bao giờ** làm người dùng tưởng
đây là kết quả tìm kiếm thật. Mọi candidate đều mang `isMock=True`; agent sẽ gắn
thêm cảnh báo ở cấp ResearchResult.

Không network: adapter này chỉ đọc hằng số trong file.
"""

from __future__ import annotations

import hashlib

from app.agents.source_research.schemas import SourceCandidate
from app.agents.source_research.adapters.base import ResearchDiscoveryAdapter

_TEMPLATE = (
    ("doc", "official_documentation", "[MOCK] Tài liệu chính thức về {topic}",
     "Example Documentation (mock)", None, "1.0"),
    ("paper", "academic", "[MOCK] Khảo sát học thuật về {topic}",
     "Mock Press", "2024-01-01", None),
    ("guide", "curated_reference", "[MOCK] Hướng dẫn nhập môn {topic}",
     "Mock Learning Hub", "2024-06-01", "2.0"),
)


class MockResearchDiscoveryAdapter(ResearchDiscoveryAdapter):
    name = "mock"
    deterministic = True
    is_mock = True

    async def search(self, query: str, *, max_results: int) -> list[SourceCandidate]:
        seed = hashlib.sha256((query or "").encode("utf-8")).hexdigest()
        label = (query or "chủ đề").strip()[:80]
        results: list[SourceCandidate] = []
        for index, (slug, source_type, title, publisher, published, version) in enumerate(_TEMPLATE):
            results.append(
                SourceCandidate(
                    adapter=self.name,
                    candidateId=f"mock-{slug}-{seed[index * 8 : (index + 1) * 8]}",
                    sourceType=source_type,
                    title=title.format(topic=label),
                    canonicalUrl=f"https://example.invalid/{slug}/{seed[index * 8 : (index + 1) * 8]}",
                    publisher=publisher,
                    author=None,
                    publicationDate=published,
                    language="en" if index != 2 else "vi",
                    version=version,
                    licenseInfo="CC BY 4.0 (mock)",
                    deterministic=True,
                    isMock=True,
                )
            )
        return results[:max_results]

    async def metadata(self, external_id: str) -> SourceCandidate | None:
        for slug, source_type, title, publisher, published, version in _TEMPLATE:
            if external_id.startswith(f"mock-{slug}-"):
                suffix = external_id.rsplit("-", 1)[-1]
                return SourceCandidate(
                    adapter=self.name,
                    candidateId=external_id,
                    sourceType=source_type,
                    title=title.format(topic="(mock)"),
                    canonicalUrl=f"https://example.invalid/{slug}/{suffix}",
                    publisher=publisher,
                    publicationDate=published,
                    language="en",
                    version=version,
                    licenseInfo="CC BY 4.0 (mock)",
                    deterministic=True,
                    isMock=True,
                )
        return None
