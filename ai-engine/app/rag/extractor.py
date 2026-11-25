"""Document extraction (PDF, HTML, arXiv XML, raw text) + provenance chunker + OCR fail-fast gate."""

from __future__ import annotations

import importlib.util
import io
import re
from html.parser import HTMLParser

import defusedxml.ElementTree as ET
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
