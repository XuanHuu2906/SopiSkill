"""Tests for SSRF guard, document extraction, provenance chunking, OCR fail-fast, and completeness lint."""

from __future__ import annotations

import pytest

from app.agents.validation import validate_lesson_payload
from app.core.config import Settings
from app.rag.extractor import (
    ExtractionError,
    check_ocr_available,
    chunk_text_with_provenance,
    extract_arxiv_atom_text,
    extract_html_text,
)
from app.rag.url_fetcher import WebFetchError, validate_outbound_url


def test_ssrf_guard_blocks_disabled_private_metadata_and_non_allowlist():
    disabled_cfg = Settings(web_ingest_enabled=False, web_ingest_allowed_hosts="docs.python.org")
    with pytest.raises(WebFetchError) as exc:
        validate_outbound_url("https://docs.python.org/3/", settings=disabled_cfg, resolve_dns=False)
    assert exc.value.code == "WEB_INGEST_DISABLED"

    cfg = Settings(
        web_ingest_enabled=True,
        web_ingest_allowed_hosts="docs.python.org,127.0.0.1,169.254.169.254,10.0.0.1",
    )
    for bad_url, expected_code in [
        ("http://docs.python.org/3/", "URL_SCHEME_FORBIDDEN"),
        ("https://user:pass@docs.python.org/3/", "URL_HAS_USERINFO"),
        ("https://docs.python.org:8443/3/", "URL_PORT_FORBIDDEN"),
        ("https://evil.example.com/pwn", "URL_HOST_NOT_ALLOWED"),
        ("https://127.0.0.1/admin", "SSRF_BLOCKED_IP"),
        ("https://169.254.169.254/latest/meta-data/", "SSRF_BLOCKED_IP"),
        ("https://10.0.0.1/internal", "SSRF_BLOCKED_IP"),
    ]:
        with pytest.raises(WebFetchError) as err:
            validate_outbound_url(bad_url, settings=cfg, resolve_dns=False)
        assert err.value.code == expected_code

    scheme, host, port = validate_outbound_url(
        "https://docs.python.org/3/library/", settings=cfg, resolve_dns=False
    )
    assert (scheme, host, port) == ("https", "docs.python.org", 443)


def test_html_arxiv_chunking_and_ocr_fail_fast():
    html = b"<html><body><h1>Graph Theory</h1><script>alert(1)</script><p>Vertices and edges.</p></body></html>"
    text, sections = extract_html_text(html)
    assert "alert(1)" not in text
    assert "Vertices and edges." in text
    assert sections == [("graph-theory", "Graph Theory")]

    atom = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Attention Is All You Need</title>
        <summary>Transformer architecture based solely on attention mechanisms.</summary>
      </entry>
    </feed>"""
    arxiv_text, title = extract_arxiv_atom_text(atom)
    assert title == "Attention Is All You Need"
    assert "Transformer architecture" in arxiv_text

    chunks = chunk_text_with_provenance([(3, "sec-intro", "word " * 300)], max_chars=400, overlap_chars=50)
    assert len(chunks) >= 3
    assert all(c.page_number == 3 and c.section_anchor == "sec-intro" for c in chunks)

    with pytest.raises(ExtractionError) as ocr_err:
        check_ocr_available(Settings(ocr_enabled=True, ocr_engine="vietocr"))
    assert ocr_err.value.code == "OCR_NOT_CONFIGURED"


def test_completeness_lint_and_single_blank_validation():
    bad_lesson = {
        "title": "Broken Lesson",
        "blocks": [
            {"type": "teach", "title": "Intro", "paragraphs": ["Code: `diem = [7, 8,`"]},
            {"type": "blank", "sentence": "Fill ____ and ____.", "answer": "two"},
        ],
    }
    errors = validate_lesson_payload(bad_lesson)
    assert any("unbalanced brackets" in e for e in errors)
    assert any("expected exactly 1 blank slot" in e for e in errors)
