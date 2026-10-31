"""Source Discovery adapters (P3.0) — interface trung lập, mặc định KHÔNG network.

Contract tối thiểu:
    search_sources(topic, context) → list[SourceCandidate]
    get_source_metadata(external_id) → SourceCandidate | None

Adapter hiện có:
  - `curated`  : đọc danh sách nguồn cấu hình tay (env `SOURCE_CURATED_CATALOG`),
                 lọc keyword. Không network.
  - `mock`     : deterministic từ hash chủ đề, KHÔNG network, dùng cho test/dev.

Discovery chỉ trả **candidate** (chưa phải Source trong registry). Việc đăng ký
nguồn là hành động riêng của người dùng qua POST /v1/sources, nên model/thuật toán
tìm kiếm không thể tự đẩy một nguồn vào trạng thái verified.

Không bật web/arXiv fetch ở phase này: cần allowlist + chống SSRF + giới hạn
size/time đã được kiểm thử (P4.2). Adapter `network_disabled` ném lỗi cấu hình rõ
ràng thay vì âm thầm gọi mạng.
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.schemas.schemas import SourceCandidateOut

logger = logging.getLogger(__name__)


class SourceDiscoveryError(Exception):
    code = "SOURCE_DISCOVERY_ERROR"


class SourceDiscoveryConfigError(SourceDiscoveryError):
    code = "SOURCE_DISCOVERY_NOT_CONFIGURED"


class SourceDiscoveryAdapter(ABC):
    name: str = "base"
    deterministic: bool = True
    is_mock: bool = False

    @abstractmethod
    async def search_sources(self, topic: str, context: dict | None = None) -> list[SourceCandidateOut]:
        ...

    @abstractmethod
    async def get_source_metadata(self, external_id: str) -> SourceCandidateOut | None:
        ...


def _candidate(
    *,
    adapter: str,
    external_id: str,
    source_type: str,
    title: str,
    canonical_url: str | None,
    publisher: str | None = None,
    author: str | None = None,
    publication_date: str | None = None,
    language: str | None = None,
    version: str | None = None,
    license_info: str | None = None,
    deterministic: bool = True,
    is_mock: bool = False,
) -> SourceCandidateOut:
    return SourceCandidateOut(
        adapter=adapter,
        externalId=external_id,
        sourceType=source_type,
        title=title,
        canonicalUrl=canonical_url,
        author=author,
        publisher=publisher,
        publicationDate=publication_date,
        language=language,
        version=version,
        licenseInfo=license_info,
        deterministic=deterministic,
        isMock=is_mock,
    )


class CuratedCatalogAdapter(SourceDiscoveryAdapter):
    """Danh mục nguồn do người vận hành cấu hình tay (JSON trong env)."""

    name = "curated"
    deterministic = True
    is_mock = False

    def __init__(self, catalog_json: str | None = None) -> None:
        raw = catalog_json if catalog_json is not None else get_settings().source_curated_catalog
        self._entries: list[dict] = []
        if raw and raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError as exc:
                raise SourceDiscoveryConfigError(
                    "SOURCE_CURATED_CATALOG không phải JSON hợp lệ."
                ) from exc
            if not isinstance(parsed, list):
                raise SourceDiscoveryConfigError("SOURCE_CURATED_CATALOG phải là mảng JSON.")
            for entry in parsed:
                if isinstance(entry, dict) and entry.get("title"):
                    self._entries.append(entry)

    async def search_sources(self, topic: str, context: dict | None = None) -> list[SourceCandidateOut]:
        words = {w for w in (topic or "").casefold().split() if len(w) >= 3}
        results: list[SourceCandidateOut] = []
        for index, entry in enumerate(self._entries):
            haystack = " ".join(
                str(entry.get(key, "")) for key in ("title", "publisher", "tags")
            ).casefold()
            if words and not any(word in haystack for word in words):
                continue
            results.append(self._entry_to_candidate(entry, index))
        return results

    async def get_source_metadata(self, external_id: str) -> SourceCandidateOut | None:
        for index, entry in enumerate(self._entries):
            if str(entry.get("id", f"curated-{index}")) == external_id:
                return self._entry_to_candidate(entry, index)
        return None

    def _entry_to_candidate(self, entry: dict, index: int) -> SourceCandidateOut:
        return _candidate(
            adapter=self.name,
            external_id=str(entry.get("id", f"curated-{index}")),
            source_type=str(entry.get("sourceType", "webpage")),
            title=str(entry.get("title", "")),
            canonical_url=entry.get("canonicalUrl"),
            publisher=entry.get("publisher"),
            author=entry.get("author"),
            publication_date=entry.get("publicationDate"),
            language=entry.get("language"),
            version=entry.get("version"),
            license_info=entry.get("licenseInfo"),
            deterministic=True,
            is_mock=False,
        )


class MockDiscoveryAdapter(SourceDiscoveryAdapter):
    """Deterministic, KHÔNG network. Không phải kết quả tìm kiếm thật."""

    name = "mock"
    deterministic = True
    is_mock = True

    async def search_sources(self, topic: str, context: dict | None = None) -> list[SourceCandidateOut]:
        seed = hashlib.sha256((topic or "").encode("utf-8")).hexdigest()
        topic_label = (topic or "chủ đề").strip()[:80]
        return [
            _candidate(
                adapter=self.name,
                external_id=f"mock-doc-{seed[:8]}",
                source_type="official_documentation",
                title=f"[MOCK] Tài liệu chính thức về {topic_label}",
                canonical_url=f"https://example.invalid/docs/{seed[:8]}",
                publisher="Example Documentation (mock)",
                language="en",
                version="1.0",
                license_info="CC BY 4.0 (mock)",
                is_mock=True,
            ),
            _candidate(
                adapter=self.name,
                external_id=f"mock-paper-{seed[8:16]}",
                source_type="academic",
                title=f"[MOCK] Khảo sát học thuật về {topic_label}",
                canonical_url=f"https://example.invalid/papers/{seed[8:16]}",
                author="Mock Author",
                publisher="Mock Press",
                publication_date="2024-01-01",
                language="en",
                is_mock=True,
            ),
            _candidate(
                adapter=self.name,
                external_id=f"mock-page-{seed[16:24]}",
                source_type="webpage",
                title=f"[MOCK] Bài viết nhập môn {topic_label}",
                canonical_url=f"https://example.invalid/blog/{seed[16:24]}",
                publisher="Mock Blog",
                language="vi",
                is_mock=True,
            ),
        ]

    async def get_source_metadata(self, external_id: str) -> SourceCandidateOut | None:
        if external_id.startswith("mock-doc-"):
            return _candidate(
                adapter=self.name,
                external_id=external_id,
                source_type="official_documentation",
                title="[MOCK] Tài liệu chính thức",
                canonical_url=f"https://example.invalid/docs/{external_id}",
                publisher="Example Documentation (mock)",
                language="en",
                version="1.0",
                is_mock=True,
            )
        if external_id.startswith("mock-paper-"):
            return _candidate(
                adapter=self.name,
                external_id=external_id,
                source_type="academic",
                title="[MOCK] Khảo sát học thuật",
                canonical_url=f"https://example.invalid/papers/{external_id}",
                author="Mock Author",
                publisher="Mock Press",
                is_mock=True,
            )
        if external_id.startswith("mock-page-"):
            return _candidate(
                adapter=self.name,
                external_id=external_id,
                source_type="webpage",
                title="[MOCK] Bài viết nhập môn",
                canonical_url=f"https://example.invalid/blog/{external_id}",
                publisher="Mock Blog",
                is_mock=True,
            )
        return None


class NetworkAdapterPlaceholder(SourceDiscoveryAdapter):
    """Chỗ đặt P4.2 (web/arXiv). Chưa triển khai ⇒ từ chối rõ ràng, không gọi mạng."""

    name = "web"
    deterministic = False
    is_mock = False

    async def search_sources(self, topic: str, context: dict | None = None) -> list[SourceCandidateOut]:
        raise SourceDiscoveryConfigError(
            "Web/arXiv discovery chưa được triển khai (cần allowlist + chống SSRF, P4.2)."
        )

    async def get_source_metadata(self, external_id: str) -> SourceCandidateOut | None:
        raise SourceDiscoveryConfigError(
            "Web/arXiv discovery chưa được triển khai (P4.2)."
        )


_ADAPTERS: dict[str, type[SourceDiscoveryAdapter]] = {
    "curated": CuratedCatalogAdapter,
    "mock": MockDiscoveryAdapter,
    "web": NetworkAdapterPlaceholder,
}


def get_discovery_adapter(name: str | None = None) -> SourceDiscoveryAdapter:
    key = (name or get_settings().source_discovery_adapter or "curated").strip().lower()
    cls = _ADAPTERS.get(key)
    if cls is None:
        raise SourceDiscoveryConfigError(
            f"Adapter discovery '{key}' chưa hỗ trợ. Hợp lệ: {', '.join(sorted(_ADAPTERS))}."
        )
    return cls()
