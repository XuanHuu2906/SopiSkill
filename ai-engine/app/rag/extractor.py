"""Document extraction (PDF, HTML, arXiv XML, raw text) + provenance chunker + OCR fail-fast gate."""

from __future__ import annotations

import importlib.util
import io
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

import defusedxml.ElementTree as ET
import yaml
from pypdf import PdfReader

from app.core.config import Settings, get_settings
from app.rag.repository import ChunkInput


class ExtractionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _SimpleHtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []
        self._current_heading = ""
        self._in_heading = False
        self.sections: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif t in {"h1", "h2", "h3"}:
            self._in_heading = True
            self._current_heading = ""
        elif t in {"p", "br", "li", "div", "section"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t in {"h1", "h2", "h3"} and self._in_heading:
            self._in_heading = False
            heading = " ".join(self._current_heading.split())
            if heading:
                slug = re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-")[:60] or "section"
                self.sections.append((slug, heading))
                self._parts.append(f"\n## {heading}\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_heading:
            self._current_heading += data
        else:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def check_ocr_available(settings: Settings | None = None) -> str:
    """Fail-fast gate when OCR is requested without optional engine installed."""
    cfg = settings or get_settings()
    if not cfg.ocr_enabled:
        raise ExtractionError("OCR_DISABLED", "OCR is disabled by configuration.")
    engine = (cfg.ocr_engine or "vietocr").strip().lower()
    if engine == "vietocr" and importlib.util.find_spec("vietocr") is None:
        raise ExtractionError("OCR_NOT_CONFIGURED", "vietocr is not installed in this runtime.")
    if engine == "rapidocr" and importlib.util.find_spec("rapidocr_onnxruntime") is None:
        raise ExtractionError("OCR_NOT_CONFIGURED", "rapidocr_onnxruntime is not installed in this runtime.")
    return engine


def extract_pdf_pages(raw_bytes: bytes, *, ocr_enabled: bool = False, settings: Settings | None = None) -> list[tuple[int, str]]:
    """Extract `(page_number, text)` pairs from PDF bytes (PyMuPDF if installed, else pypdf)."""
    pages: list[tuple[int, str]] = []
    if importlib.util.find_spec("fitz") is not None:
        import fitz  # type: ignore[import-not-found]

        with fitz.open(stream=raw_bytes, filetype="pdf") as doc:
            for idx, page in enumerate(doc, start=1):
                pages.append((idx, (page.get_text("text") or "").strip()))
    else:
        reader = PdfReader(io.BytesIO(raw_bytes))
        for idx, page in enumerate(reader.pages, start=1):
            pages.append((idx, (page.extract_text() or "").strip()))

    non_empty = [(p, txt) for p, txt in pages if txt]
    if not non_empty and ocr_enabled:
        check_ocr_available(settings)
    return non_empty


def extract_html_text(raw_bytes: bytes) -> tuple[str, list[tuple[str, str]]]:
    parser = _SimpleHtmlTextExtractor()
    parser.feed(raw_bytes.decode("utf-8", errors="replace"))
    return parser.get_text(), parser.sections


def extract_arxiv_atom_text(raw_xml: bytes) -> tuple[str, str | None]:
    """Safely parse arXiv Atom feed via defusedxml (blocks XML entity expansion)."""
    root = ET.fromstring(raw_xml)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ExtractionError("ARXIV_EMPTY", "No entry found in arXiv metadata response.")
    title = " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split())
    summary = " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split())
    text = f"{title}\n\n{summary}".strip()
    return text, title or None


def chunk_text_with_provenance(
    pages: list[tuple[int | None, str | None, str]],
    *,
    max_chars: int = 800,
    overlap_chars: int = 120,
) -> list[ChunkInput]:
    """Deterministically chunk `(page_number, section_anchor, text)` entries preserving locators."""
    chunks: list[ChunkInput] = []
    idx = 0
    step = max(100, max_chars - overlap_chars)

    for page_num, anchor, raw_text in pages:
        cleaned = " ".join((raw_text or "").split())
        if not cleaned:
            continue
        start = 0
        while start < len(cleaned):
            piece = cleaned[start : start + max_chars].strip()
            if piece:
                chunks.append(
                    ChunkInput(
                        chunk_index=idx,
                        content=piece,
                        page_number=page_num,
                        section_anchor=anchor,
                    )
                )
                idx += 1
            if start + max_chars >= len(cleaned):
                break
            start += step
    return chunks


_PAGE_COMMENT_RE = re.compile(r"^<!--\s*page:\s*(\d+)\s*-->$", re.IGNORECASE)
_PAGE_HEADING_RE = re.compile(r"^#{2,4}\s+Page\s+(\d+)\s*$", re.IGNORECASE)
_MD_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _slugify_anchor(text: str, max_len: int = 72) -> str:
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return (slug[:max_len].rstrip("-")) or "section"


def parse_markdown_frontmatter(md_text: str) -> tuple[dict[str, Any], str]:
    """Extract optional YAML frontmatter (`--- ... ---`) from extracted textbook Markdown."""
    raw = (md_text or "").lstrip("\ufeff")
    if not raw.startswith("---\n") and not raw.startswith("---\r\n"):
        return {}, raw
    lines = raw.splitlines()
    end_idx = None
    for idx in range(1, min(len(lines), 120)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, raw
    fm_raw = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        parsed = yaml.safe_load(fm_raw)
        return (parsed if isinstance(parsed, dict) else {}), body
    except Exception:
        return {}, body


def _split_atomic_units(section_lines: list[str]) -> list[tuple[str, bool]]:
    """Split section lines into `(unit_text, is_atomic)` while NEVER splitting code fences or LaTeX display math."""
    units: list[tuple[str, bool]] = []
    para_buf: list[str] = []
    atomic_buf: list[str] = []
    mode: str | None = None  # "code" | "math_dollar" | "math_env"
    math_env_end = ""

    def _flush_para() -> None:
        if para_buf:
            text = "\n".join(para_buf).strip()
            if text:
                units.append((text, False))
            para_buf.clear()

    for line in section_lines:
        stripped = line.strip()

        if mode == "code":
            atomic_buf.append(line)
            if stripped.startswith("```"):
                units.append(("\n".join(atomic_buf).strip(), True))
                atomic_buf.clear()
                mode = None
            continue

        if mode == "math_dollar":
            atomic_buf.append(line)
            if "$$" in stripped:
                units.append(("\n".join(atomic_buf).strip(), True))
                atomic_buf.clear()
                mode = None
            continue

        if mode == "math_env":
            atomic_buf.append(line)
            if math_env_end and math_env_end in stripped:
                units.append(("\n".join(atomic_buf).strip(), True))
                atomic_buf.clear()
                mode = None
                math_env_end = ""
            continue

        # Detect start of fenced code block
        if stripped.startswith("```"):
            _flush_para()
            atomic_buf = [line]
            mode = "code"
            continue

        # Detect single-line or multi-line display LaTeX `$$ ... $$`
        if stripped.startswith("$$"):
            _flush_para()
            if stripped.count("$$") >= 2 and len(stripped) > 4:
                units.append((line.strip(), True))
            else:
                atomic_buf = [line]
                mode = "math_dollar"
            continue

        # Detect LaTeX `\begin{equation|align|gather|matrix...}` block
        env_match = re.match(r"^\\begin\{([a-zA-Z*]+)\}", stripped)
        if env_match:
            _flush_para()
            env_name = env_match.group(1)
            end_marker = f"\\end{{{env_name}}}"
            if end_marker in stripped:
                units.append((line.strip(), True))
            else:
                atomic_buf = [line]
                mode = "math_env"
                math_env_end = end_marker
            continue

        if not stripped:
            _flush_para()
        else:
            para_buf.append(line)

    _flush_para()
    if atomic_buf:
        units.append(("\n".join(atomic_buf).strip(), True))
    return units


def chunk_markdown_by_headings(
    md_text: str,
    *,
    source_title: str = "",
    target_chars: int = 1000,
    max_chars: int = 1350,
    overlap_sentences: int = 1,
) -> tuple[list[ChunkInput], list[tuple[str, str, int]]]:
    """Phase L3 Heading-Aware Markdown Chunker for long open textbooks.

    Guarantees:
      - Strips YAML frontmatter and skips redundant `## Table of Contents` outline block.
      - Tracks `H1 > H2 > H3 > H4` breadcrumb and deterministic `section_anchor` + `page_number`.
      - Never splits fenced code blocks (```` ```...``` ````) or LaTeX display math (`$$...$$`, `\\begin{...}`).
      - Prepends a lightweight context breadcrumb header `[Source: ... | Section: ...]` to each chunk.
      - Returns `(chunks, heading_entries)` where `heading_entries` is `[(anchor, heading, level), ...]`.
    """
    fm, body = parse_markdown_frontmatter(md_text)
    resolved_title = (source_title or str(fm.get("title") or "")).strip()[:160]

    lines = body.replace("\r\n", "\n").replace("\r", "\n").splitlines()

    # Group lines into logical sections while tracking heading stack & page numbers
    heading_stack: dict[int, str] = {}
    heading_entries: list[tuple[str, str, int]] = []
    used_anchors: dict[str, int] = {}

    sections: list[dict[str, Any]] = []
    current_page: int | None = None
    in_toc = False

    def _new_anchor(heading_text: str, breadcrumb: str) -> str:
        base = _slugify_anchor(breadcrumb or heading_text)
        count = used_anchors.get(base, 0) + 1
        used_anchors[base] = count
        return base if count == 1 else f"{base}-{count}"

    current_sec: dict[str, Any] = {
        "anchor": "intro",
        "breadcrumb": resolved_title or "Introduction",
        "page": 1,
        "lines": [],
    }

    def _flush_section() -> None:
        if any(ln.strip() for ln in current_sec["lines"]):
            sections.append(current_sec.copy())

    for line in lines:
        stripped = line.strip()

        page_cm = _PAGE_COMMENT_RE.match(stripped)
        if page_cm:
            current_page = int(page_cm.group(1))
            if not current_sec["lines"] and current_sec["page"] is None:
                current_sec["page"] = current_page
            continue

        page_hm = _PAGE_HEADING_RE.match(stripped)
        if page_hm:
            current_page = int(page_hm.group(1))
            if in_toc:
                in_toc = False
            if not any(ln.strip() for ln in current_sec["lines"]):
                current_sec["page"] = current_page
            continue

        hm = _MD_HEADING_RE.match(stripped)
        if hm:
            level = len(hm.group(1))
            h_text = " ".join(hm.group(2).split()).strip()
            if not h_text:
                continue
            # Skip redundant top-level Table of Contents outline list
            if h_text.casefold() in {"table of contents", "contents"} and level <= 2:
                _flush_section()
                in_toc = True
                current_sec = {"anchor": "toc", "breadcrumb": "Table of Contents", "page": current_page, "lines": []}
                continue
            in_toc = False

            # Ignore single top-level H1 book title duplicate if it matches frontmatter title
            if level == 1 and resolved_title and h_text.casefold() == resolved_title.casefold():
                continue

            _flush_section()
            # Pop deeper levels from breadcrumb stack
            for k in list(heading_stack.keys()):
                if k >= level:
                    del heading_stack[k]
            heading_stack[level] = h_text

            breadcrumb_parts = [heading_stack[k] for k in sorted(heading_stack.keys())]
            breadcrumb = " > ".join(breadcrumb_parts)
            anchor = _new_anchor(h_text, breadcrumb)
            heading_entries.append((anchor, h_text[:120], level))
            current_sec = {
                "anchor": anchor,
                "breadcrumb": breadcrumb,
                "page": current_page or 1,
                "lines": [],
            }
            continue

        if in_toc:
            continue
        current_sec["lines"].append(line)

    _flush_section()

    chunks: list[ChunkInput] = []
    chunk_idx = 0

    for sec in sections:
        units = _split_atomic_units(sec["lines"])
        if not units:
            continue
        prefix_parts = []
        if resolved_title:
            prefix_parts.append(f"Source: {resolved_title}")
        if sec["breadcrumb"]:
            prefix_parts.append(f"Section: {sec['breadcrumb']}")
        header = f"[{' | '.join(prefix_parts)}]\n" if prefix_parts else ""

        buf_units: list[str] = []
        buf_len = 0

        def _emit_chunk(body_text: str) -> None:
            nonlocal chunk_idx
            cleaned = body_text.strip()
            if not cleaned:
                return
            chunks.append(
                ChunkInput(
                    chunk_index=chunk_idx,
                    content=f"{header}{cleaned}",
                    page_number=sec["page"],
                    section_anchor=sec["anchor"],
                )
            )
            chunk_idx += 1

        def _flush_buf() -> str:
            nonlocal buf_len
            if not buf_units:
                return ""
            joined = "\n\n".join(buf_units)
            _emit_chunk(joined)
            last_overlap = ""
            if overlap_sentences > 0:
                sents = _SENTENCE_BOUNDARY_RE.split(buf_units[-1])
                if len(sents) > 1 and not buf_units[-1].startswith("```") and "$$" not in buf_units[-1]:
                    last_overlap = " ".join(sents[-overlap_sentences:]).strip()
            buf_units.clear()
            buf_len = 0
            return last_overlap

        for unit_text, is_atomic in units:
            # Split overly long non-atomic prose paragraphs along sentence boundaries
            if not is_atomic and len(unit_text) > max_chars:
                _flush_buf()
                sents = _SENTENCE_BOUNDARY_RE.split(unit_text)
                sent_buf: list[str] = []
                sent_len = 0
                for s in sents:
                    if sent_buf and sent_len + len(s) + 1 > target_chars:
                        _emit_chunk(" ".join(sent_buf))
                        sent_buf = sent_buf[-overlap_sentences:] if overlap_sentences > 0 else []
                        sent_len = sum(len(x) for x in sent_buf)
                    sent_buf.append(s)
                    sent_len += len(s) + 1
                if sent_buf:
                    _emit_chunk(" ".join(sent_buf))
                continue

            # Never split atomic code/LaTeX blocks even if slightly larger than target_chars
            if buf_units and (buf_len + len(unit_text) + 2 > target_chars) and (buf_len + len(unit_text) > max_chars or is_atomic):
                tail = _flush_buf()
                if tail and not is_atomic and len(tail) + len(unit_text) + 2 <= max_chars:
                    buf_units.append(tail)
                    buf_len += len(tail)

            buf_units.append(unit_text)
            buf_len += len(unit_text) + 2

        _flush_buf()

    return chunks, heading_entries
