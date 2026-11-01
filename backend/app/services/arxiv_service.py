"""P4.2 — arXiv adapter: định danh hợp lệ, metadata, PDF có provenance.

Nguyên tắc:
  - **Chỉ nhận ID arXiv**, không nhận URL tuỳ ý. URL được dựng từ ID bằng host
    cấu hình (`ARXIV_API_HOST`, `ARXIV_PDF_HOST`) ⇒ client không thể trỏ sang
    host khác.
  - Host arXiv vẫn phải nằm trong `WEB_INGEST_ALLOWED_HOSTS`: adapter **không**
    tự nới quyền outbound. Thiếu allowlist ⇒ từ chối rõ ràng.
  - Metadata mặc định đọc từ trang `arxiv.org/abs/<id>` qua thẻ Highwire
    `citation_*`. Đây là đường **tôn trọng robots.txt**: robots của
    `export.arxiv.org` (Atom API) là `Disallow: /`, nên mặc định KHÔNG dùng API.
    Atom chỉ dùng khi người vận hành chủ động đặt `ARXIV_METADATA_SOURCE=atom`
    và robots cho phép (vẫn qua đúng cổng `url_fetcher`). Atom parse bằng
    `defusedxml` (chặn entity expansion/XXE).
  - PDF tải qua cùng `url_fetcher` (SSRF guard + robots + trần byte).
  - `version` lấy từ Atom (`updated` + số version trong id) để citation biết
    đang trích bản nào; nội dung arXiv có thể đổi giữa các version.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import Settings, get_settings
from app.services import url_fetcher

logger = logging.getLogger(__name__)

# New style: 2401.12345 (4 chữ số năm + chấm + 4-5 số), optional v1.
_NEW_ID = re.compile(r"^(?P<base>\d{4}\.\d{4,5})(?P<version>v[1-9]\d{0,2})?$")
# Old style: hep-th/9901001 hoặc math.GT/0309136 (có thể có vN).
_OLD_ID = re.compile(
    r"^(?P<base>[a-z][a-z\-]*(?:\.[A-Z]{2})?/\d{7})(?P<version>v[1-9]\d{0,2})?$"
)
_ARXIV_PREFIXES = ("arxiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/")


class ArxivError(Exception):
    code = "ARXIV_ERROR"

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_error(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    version_suffix: str | None
    title: str
    authors: list[str]
    published: str | None
    updated: str | None
    summary: str | None
    categories: list[str]
    abs_url: str
    pdf_url: str

    @property
    def version(self) -> str | None:
        """Version hiển thị: `v2` (ưu tiên id) hoặc ngày `updated`."""
        if self.version_suffix:
            return self.version_suffix
        if self.updated:
            return f"updated-{self.updated}"
        return None


def normalize_arxiv_id(raw: str) -> str:
    """Chuẩn hoá input người dùng về ID arXiv (không version nếu không có).

    Chấp nhận `2401.12345`, `2401.12345v2`, `arXiv:2401.12345`,
    `https://arxiv.org/abs/2401.12345v2`. Từ chối mọi thứ khác — không đoán.
    """
    value = (raw or "").strip()
    if not value:
        raise ArxivError("ARXIV_ID_EMPTY", "Chưa nhập ID arXiv.")
    if len(value) > 200:
        raise ArxivError("ARXIV_ID_INVALID", "ID arXiv quá dài.")
    lowered = value.lower()
    for prefix in _ARXIV_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.split("?", 1)[0].split("#", 1)[0].strip().strip("/")
    if not (_NEW_ID.match(value) or _OLD_ID.match(value)):
        raise ArxivError(
            "ARXIV_ID_INVALID",
            "ID arXiv không hợp lệ (ví dụ đúng: 2401.12345 hoặc 2401.12345v2).",
        )
    return value


def split_version(arxiv_id: str) -> tuple[str, str | None]:
    match = _NEW_ID.match(arxiv_id) or _OLD_ID.match(arxiv_id)
    if not match:  # pragma: no cover — đã validate ở normalize_arxiv_id
        raise ArxivError("ARXIV_ID_INVALID", "ID arXiv không hợp lệ.")
    return match.group("base"), match.group("version")


def abs_url(arxiv_id: str, *, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base, _version = split_version(arxiv_id)
    return f"https://{cfg.arxiv_pdf_host}/abs/{base}"


def pdf_url(arxiv_id: str, *, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base, _version = split_version(arxiv_id)
    return f"https://{cfg.arxiv_pdf_host}/pdf/{base}"


def abs_page_url(arxiv_id: str, *, settings: Settings | None = None) -> str:
    """Trang abstract — path `/abs` được robots của arxiv.org cho phép."""
    return abs_url(arxiv_id, settings=settings)


def api_url(arxiv_id: str, *, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base, _version = split_version(arxiv_id)
    return f"https://{cfg.arxiv_api_host}/api/query?id_list={base}"


def _ensure_hosts_allowed(cfg: Settings) -> None:
    allowed = cfg.web_allowed_hosts
    for host in (cfg.arxiv_api_host, cfg.arxiv_pdf_host):
        if not url_fetcher.host_allowed(host, allowed):
            raise ArxivError(
                "ARXIV_HOST_NOT_ALLOWED",
                f"Host arXiv ({host}) chưa nằm trong danh sách host được phép của server.",
            )


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _text(node, tag: str, ns: dict | None = None) -> str | None:
    """Đọc text của một element con; `tag` phải kèm prefix nếu có namespace."""
    child = node.find(tag, ns or ATOM_NS) if node is not None else None
    if child is None or child.text is None:
        return None
    text = " ".join(child.text.split())
    return text or None


def parse_atom(xml_bytes: bytes, *, requested_id: str) -> ArxivPaper:
    """Parse Atom `query?id_list=` bằng defusedxml; thiếu entry ⇒ lỗi rõ."""
    from defusedxml.ElementTree import ParseError, fromstring

    try:
        root = fromstring(xml_bytes)
    except ParseError as exc:
        raise ArxivError("ARXIV_METADATA_INVALID", "Metadata arXiv không phải XML hợp lệ.") from exc
    except Exception as exc:  # noqa: BLE001 — entity expansion/XXE bị defusedxml chặn
        raise ArxivError("ARXIV_METADATA_INVALID", "Metadata arXiv không đọc được.") from exc

    ns = ATOM_NS
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ArxivError(
            "ARXIV_NOT_FOUND", "Không tìm thấy bài arXiv với ID này."
        )

    title = _text(entry, "atom:title")
    if not title:
        raise ArxivError("ARXIV_METADATA_INVALID", "Metadata arXiv thiếu tiêu đề.")

    raw_id = _text(entry, "atom:id") or ""
    identifier = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
    try:
        normalized = normalize_arxiv_id(identifier)
    except ArxivError:
        normalized = normalize_arxiv_id(requested_id)
    base_id, version_suffix = split_version(normalized)

    authors: list[str] = []
    for author in entry.findall("atom:author", ns):
        name = _text(author, "atom:name")
        if name:
            authors.append(name)

    categories: list[str] = []
    primary = entry.find("arxiv:primary_category", ns)
    if primary is not None and primary.get("term"):
        categories.append(primary.get("term"))
    for category in entry.findall("atom:category", ns):
        term = category.get("term")
        if term and term not in categories:
            categories.append(term)

    summary = _text(entry, "atom:summary")
    cfg = get_settings()
    return ArxivPaper(
        arxiv_id=base_id,
        version_suffix=version_suffix,
        title=title[:300],
        authors=authors[:20],
        published=_text(entry, "atom:published"),
        updated=_text(entry, "atom:updated"),
        summary=summary[:2000] if summary else None,
        categories=categories[:8],
        abs_url=f"https://{cfg.arxiv_pdf_host}/abs/{base_id}",
        pdf_url=f"https://{cfg.arxiv_pdf_host}/pdf/{base_id}",
    )


_META_RE = re.compile(r'<meta[^>]*>', re.IGNORECASE)
_ATTR_RE = re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')""")


def _meta_attrs(tag: str) -> dict[str, str]:
    return {
        match.group(1).lower(): (match.group(3) if match.group(3) is not None else match.group(4)) or ""
        for match in _ATTR_RE.finditer(tag)
    }


def parse_abs_metadata(html: str, *, requested_id: str) -> ArxivPaper:
    """Parse trang `/abs/<id>` qua thẻ Highwire `citation_*` (deterministic).

    Không dùng LLM, không đoán: thiếu `citation_title` ⇒ lỗi rõ. `citation_arxiv_id`
    (nếu có) được ưu tiên cho id; version lấy từ input hoặc `citation_date`.
    """
    cfg = get_settings()
    titles: list[str] = []
    authors: list[str] = []
    meta: dict[str, str] = {}
    for raw_tag in _META_RE.findall(html or ""):
        attrs = _meta_attrs(raw_tag)
        name = (attrs.get("name") or attrs.get("property") or "").strip().lower()
        content = (attrs.get("content") or "").strip()
        if not name or not content:
            continue
        if name == "citation_title":
            titles.append(content)
        elif name == "citation_author":
            authors.append(content)
        elif name.startswith("citation_") or name in ("og:title",):
            meta.setdefault(name, content)

    title = titles[0] if titles else meta.get("og:title")
    if not title:
        raise ArxivError(
            "ARXIV_METADATA_INVALID", "Trang arXiv không có metadata tiêu đề đọc được."
        )

    normalized = normalize_arxiv_id(requested_id)
    base_id, requested_version = split_version(normalized)
    published = meta.get("citation_date") or None
    arxiv_id_meta = meta.get("citation_arxiv_id")
    if arxiv_id_meta:
        try:
            base_id = split_version(normalize_arxiv_id(arxiv_id_meta))[0]
        except ArxivError:  # pragma: no cover — metadata lạ thì giữ id người dùng
            pass

    categories: list[str] = []
    subject = meta.get("citation_arxiv_primary_category") or meta.get("citation_subject")
    if subject:
        categories.append(subject.strip())

    return ArxivPaper(
        arxiv_id=base_id,
        version_suffix=requested_version,
        title=" ".join(title.split())[:300],
        authors=[_clean_author(name) for name in authors[:20]],
        published=_iso_date(published),
        updated=None,
        summary=None,
        categories=categories[:8],
        abs_url=f"https://{cfg.arxiv_pdf_host}/abs/{base_id}",
        pdf_url=f"https://{cfg.arxiv_pdf_host}/pdf/{base_id}",
    )


def _clean_author(name: str) -> str:
    return " ".join(name.split())[:200]


def _iso_date(value: str | None) -> str | None:
    """arXiv dùng `YYYY/MM/DD` trong `citation_date`; giữ nguyên dạng ISO ngày."""
    if not value:
        return None
    text = value.strip()
    match = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return text[:32]


async def fetch_metadata(
    arxiv_id: str,
    *,
    settings: Settings | None = None,
    transport=None,
) -> ArxivPaper:
    cfg = settings or get_settings()
    _ensure_hosts_allowed(cfg)
    normalized = normalize_arxiv_id(arxiv_id)
    base_id, _version = split_version(normalized)

    if (cfg.arxiv_metadata_source or "abs").strip().lower() == "atom":
        resource = await url_fetcher.fetch_resource(
            api_url(base_id, settings=cfg),
            kind="text",
            settings=cfg,
            transport=transport,
        )
        return parse_atom(resource.data, requested_id=base_id)

    resource = await url_fetcher.fetch_resource(
        abs_page_url(base_id, settings=cfg),
        kind="html",
        settings=cfg,
        transport=transport,
    )
    html = url_fetcher.decode_html(resource.data, resource.content_type_header)
    return parse_abs_metadata(html, requested_id=base_id)


async def fetch_pdf(
    arxiv_id: str,
    *,
    settings: Settings | None = None,
    transport=None,
) -> url_fetcher.FetchedResource:
    cfg = settings or get_settings()
    _ensure_hosts_allowed(cfg)
    normalized = normalize_arxiv_id(arxiv_id)
    base_id, _version = split_version(normalized)
    return await url_fetcher.fetch_resource(
        pdf_url(base_id, settings=cfg), kind="pdf", settings=cfg, transport=transport
    )


def retrieved_now() -> datetime:
    return datetime.now(UTC)
