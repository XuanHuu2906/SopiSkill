"""P4.2 — trích text từ HTML (sanitize khi trích, KHÔNG render HTML).

Nguyên tắc:
  - **Không render** HTML từ nguồn ra browser. Chỉ trích text thuần để chunk.
  - Bỏ hẳn nội dung không phải văn bản (`script`, `style`, `noscript`, `template`,
    `svg`, `math`, `iframe`, `object`, `embed`) và chrome điều hướng
    (`nav`, `footer`, `aside`, `form`, `button`, các control nhập liệu).
  - Giữ **heading provenance**: breadcrumb `H1 › H2 › H3` làm `section_anchor` cho
    chunk, cùng offset `char_start/char_end` thật trong text đã dựng ⇒ citation
    trỏ đúng đoạn, không cần đoán.
  - Trần ký tự cấu hình (`WEB_MAX_EXTRACTED_CHARS`): vượt ⇒ lỗi rõ, không cắt
    âm thầm rồi coi như đã ingest đầy đủ.
  - HTML là **dữ liệu không tin cậy**: text trích ra vẫn phải nằm trong delimiter
    khi đưa vào prompt (dùng `ingest.wrap_untrusted`).

Trả `HtmlExtraction` gồm `text` (dựng từ block, mỗi block cách nhau một dòng
trống) + `sections` + `title` + `links`. Text này được đưa tiếp vào
`ingest.chunk_pages` để dùng CHUNG pipeline chunking/embedding với PDF (P4.0/P4.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

_WS = re.compile(r"[ \t\u00a0\u2000-\u200b\ufeff]+")
_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "math",
        "iframe",
        "object",
        "embed",
        "nav",
        "footer",
        "aside",
        "form",
        "button",
        "input",
        "select",
        "option",
        "textarea",
        "canvas",
        "video",
        "audio",
    }
)
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "li",
        "ul",
        "ol",
        "dl",
        "dd",
        "dt",
        "blockquote",
        "pre",
        "code",
        "td",
        "th",
        "tr",
        "table",
        "figure",
        "figcaption",
        "body",
        "br",
        "hr",
        "header",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)
_HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}


class HtmlExtractionError(Exception):
    code = "WEB_HTML_INVALID"


class HtmlTooLargeError(HtmlExtractionError):
    code = "WEB_HTML_TOO_LARGE"


@dataclass
class HtmlSection:
    heading: str
    level: int
    char_start: int
    char_end: int
    anchor_id: str | None = None


@dataclass
class HtmlExtraction:
    title: str | None
    text: str
    sections: list[HtmlSection] = field(default_factory=list)
    links: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


def _clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\r", " ").replace("\n", " ")).strip()


class _Extractor(HTMLParser):
    def __init__(self, *, base_url: str, max_chars: int, max_links: int = 200) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.max_chars = max_chars
        self.max_links = max_links
        self.blocks: list[str] = []
        self.text_len = 0
        self._buffer: list[str] = []
        self._skip_depth: dict[str, int] = {}
        self._heading_stack: list[tuple[int, str]] = []
        self._heading_level: int | None = None
        self._heading_anchor: str | None = None
        self._pending_anchor: str | None = None
        self._in_title = False
        self.title_parts: list[str] = []
        self.sections: list[HtmlSection] = []
        self.links: list[str] = []
        # Section được ghi theo CHỈ SỐ BLOCK rồi quy đổi offset sau khi nối text,
        # để offset luôn khớp tuyệt đối với chuỗi cuối cùng (không lệch do join).
        self._section_start_block: int | None = None
        self._section_heading: str | None = None
        self._section_level = 0
        self._section_anchor: str | None = None

    # -- helpers ---------------------------------------------------------

    def _skipping(self) -> bool:
        return any(depth > 0 for depth in self._skip_depth.values())

    def _flush(self) -> None:
        if self._heading_level is None and not self._buffer:
            return
        raw = "".join(self._buffer)
        self._buffer = []
        text = _clean(raw)
        if not text:
            self._heading_level = None
            self._heading_anchor = None
            return

        if self._heading_level is not None:
            level = self._heading_level
            self._heading_level = None
            self._heading_stack = [
                (lvl, name) for lvl, name in self._heading_stack if lvl < level
            ]
            self._heading_stack.append((level, text))
            self._close_section()
            self._section_start_block = len(self.blocks)
            self._section_heading = " › ".join(name for _lvl, name in self._heading_stack)
            self._section_level = level
            self._section_anchor = self._heading_anchor
            self._pending_anchor = None
            # Heading cũng là một block để chunker nhận diện `section_anchor`.
            self._append_block(text[:80])
            return

        self._append_block(text)

    def _append_block(self, text: str) -> None:
        if not text:
            return
        next_len = self.text_len + len(text) + 1
        if next_len > self.max_chars:
            raise HtmlTooLargeError(
                f"Văn bản HTML vượt giới hạn {self.max_chars} ký tự."
            )
        self.blocks.append(text)
        self.text_len = next_len

    def _close_section(self) -> None:
        if self._section_start_block is None or self._section_heading is None:
            return
        self.sections.append(
            HtmlSection(
                heading=self._section_heading[:120],
                level=self._section_level,
                char_start=self._section_start_block,
                char_end=len(self.blocks),
                anchor_id=self._section_anchor,
            )
        )
        self._section_start_block = None
        self._section_heading = None
        self._section_anchor = None

    # -- parser hooks ----------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        if tag == "title":
            self._in_title = True
            return
        if tag in _SKIP_TAGS:
            self._skip_depth[tag] = self._skip_depth.get(tag, 0) + 1
            return
        if self._skipping():
            return
        if tag == "a":
            href = attr_map.get("href", "").strip()
            if href and len(self.links) < self.max_links:
                absolute = urljoin(self.base_url, href)
                if absolute.lower().startswith(("http://", "https://")):
                    self.links.append(absolute[:2048])
        if tag in _HEADING_TAGS:
            self._flush()
            self._heading_level = _HEADING_TAGS[tag]
            self._heading_anchor = attr_map.get("id") or None
        if tag in _BLOCK_TAGS and tag not in _HEADING_TAGS:
            self._flush()
        if tag == "br":
            self._flush()

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in _SKIP_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag in _SKIP_TAGS:
            depth = self._skip_depth.get(tag, 0)
            if depth <= 1:
                self._skip_depth.pop(tag, None)
            else:
                self._skip_depth[tag] = depth - 1
            return
        if self._skipping():
            return
        if tag in _HEADING_TAGS:
            self._flush()
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skipping():
            return
        self._buffer.append(data)

    def close(self) -> None:  # noqa: D401 — override để flush phần còn lại
        super().close()
        self._flush()
        self._close_section()


def sanitize_extract(
    html: str, *, base_url: str, max_chars: int = 2_000_000
) -> HtmlExtraction:
    """Trích text + section provenance từ HTML. `base_url` dùng resolve link tương đối."""
    parser = _Extractor(base_url=base_url, max_chars=max_chars)
    try:
        parser.feed(html or "")
        parser.close()
    except HtmlExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 — parser lỗi lạ phải fail an toàn
        raise HtmlExtractionError("HTML không đọc được.") from exc

    # Mỗi block cách nhau bằng dòng trống để `_split_blocks` của P4.0 nhận đúng
    # ranh giới block; offset được dựng lại trên chính chuỗi này nên luôn khớp.
    text = "\n\n".join(parser.blocks)
    title = _clean("".join(parser.title_parts)) or None
    sections = _sections_to_offsets(parser.sections, blocks=parser.blocks)
    return HtmlExtraction(
        title=title[:300] if title else None,
        text=text,
        sections=sections,
        links=parser.links,
    )


def _sections_to_offsets(
    sections: list[HtmlSection], *, blocks: list[str]
) -> list[HtmlSection]:
    """Đổi (start_block, end_block) sang offset ký tự tính trên chuỗi nối thật."""
    starts: list[int] = []
    cursor = 0
    for block in blocks:
        starts.append(cursor)
        cursor += len(block) + 2  # "\n\n"
    total = max(0, cursor - 2) if blocks else 0

    fixed: list[HtmlSection] = []
    for section in sections:
        first = max(0, min(section.char_start, len(blocks) - 1)) if blocks else 0
        last = max(first, min(section.char_end, len(blocks))) if blocks else 0
        char_start = starts[first] if starts else 0
        char_end = starts[last - 1] + len(blocks[last - 1]) if last - 1 >= 0 and blocks else 0
        char_end = max(char_start, min(char_end, total))
        fixed.append(
            HtmlSection(
                heading=section.heading,
                level=section.level,
                char_start=char_start,
                char_end=char_end,
                anchor_id=section.anchor_id,
            )
        )
    return fixed


def section_for_offset(sections: list[HtmlSection], offset: int) -> str | None:
    """Heading gần nhất bao quanh offset — dùng kiểm tra provenance khi test."""
    best: HtmlSection | None = None
    for section in sections:
        if section.char_start <= offset <= section.char_end:
            if best is None or section.char_start >= best.char_start:
                best = section
    return best.heading if best else None
