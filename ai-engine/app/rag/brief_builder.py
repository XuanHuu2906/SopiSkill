"""Structured `source.brief` builder grounded strictly in real extracted chunks & headings (Phase 3)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.rag.repository import ChunkInput

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_NOTATION_RE = re.compile(r"\b(?:O\([^)]+\)|[A-Z]{2,6}|[a-zA-Z]+_[a-zA-Z0-9]+)\b")


def _clean_sentence(text: str, max_len: int = 220) -> str:
    compact = " ".join((text or "").split()).strip()
    return compact[:max_len]


def build_source_brief(
    *,
    title: str | None,
    chunks: list[ChunkInput],
    headings: list[tuple[str, str]] | None = None,
    heading_levels: list[tuple[str, str, int]] | None = None,
    max_sections: int = 60,
) -> dict[str, Any]:
    """Build deterministic hard-schema `source.brief` anchored to real chunks/headings.

    Schema guarantees:
      - `what`: non-empty summary grounded in opening content
      - `claims`: 1..10 key statements extracted from real chunks
      - `notation`: <=20 technical symbols/acronyms observed in chunks
      - `assumes`: <=10 prerequisite hints grounded in document vocabulary
      - `sections`: <=60 `{anchor, heading, gist}` items prioritizing ALL top-level Chapters
        across the entire book before filling key subsections so Planner sees the full syllabus.
    """
    full_text = " ".join(c.content for c in chunks)
    words = full_text.split()
    word_count = len(words)
    duration_minutes = max(1, min(240, round(word_count / 200))) if word_count else 1

    first_chunk = chunks[0].content if chunks else (title or "Document")
    sentences: list[str] = []
    for chunk in chunks:
        for sent in _SENTENCE_SPLIT_RE.split(chunk.content):
            cleaned = _clean_sentence(sent)
            if len(cleaned) >= 20:
                sentences.append(cleaned)

    what = _clean_sentence(
        sentences[0] if sentences else first_chunk,
        max_len=280,
    )

    claims: list[str] = []
    seen_claims: set[str] = set()
    for sent in sentences:
        key = sent.casefold()
        if key not in seen_claims:
            seen_claims.add(key)
            claims.append(sent)
        if len(claims) >= 10:
            break
    if not claims:
        claims = [what]

    notation: list[str] = []
    seen_not: set[str] = set()
    for match in _NOTATION_RE.findall(full_text):
        if match not in seen_not and len(match) <= 32:
            seen_not.add(match)
            notation.append(match)
        if len(notation) >= 20:
            break

    assumes: list[str] = []
    lowered = full_text.casefold()
    for keyword, label in [
        ("sql", "Basic SQL syntax"),
        ("python", "Basic Python syntax"),
        ("probability", "Introductory probability"),
        ("matrix", "Linear algebra basics"),
        ("gradient", "Calculus derivatives"),
        ("http", "HTTP client-server concepts"),
        ("kubernetes", "Container fundamentals"),
        ("docker", "Container fundamentals"),
    ]:
        if keyword in lowered and label not in assumes:
            assumes.append(label)
        if len(assumes) >= 10:
            break

    safe_max_sections = max(1, min(max_sections, 60))
    chunk_by_anchor: dict[str, str] = {}
    for ch in chunks:
        if ch.section_anchor and ch.section_anchor not in chunk_by_anchor:
            chunk_by_anchor[ch.section_anchor] = ch.content

    sections: list[dict[str, str]] = []
    seen_anchors: set[str] = set()

    if heading_levels:
        # Phase L3 Full-Book TOC prioritization: keep ALL top-level Chapters (level <= 2) across the entire book
        # first, then backfill subsections (level >= 3) up to `safe_max_sections`, preserving original book order!
        indexed = list(enumerate(heading_levels))
        top_level = [(idx, a, h) for idx, (a, h, lvl) in indexed if lvl <= 2]
        sub_level = [(idx, a, h) for idx, (a, h, lvl) in indexed if lvl > 2]

        chosen: list[tuple[int, str, str]] = []
        if len(top_level) <= safe_max_sections:
            chosen.extend(top_level)
            remaining = safe_max_sections - len(chosen)
            if remaining > 0 and sub_level:
                # Sample subsections evenly across the entire book rather than only Chapter 1
                step = max(1, len(sub_level) // remaining) if len(sub_level) > remaining else 1
                chosen.extend(sub_level[::step][:remaining])
        else:
            # Evenly stride across top-level chapters so beginning, middle, and final chapters are always represented
            step = max(1, len(top_level) // safe_max_sections)
            chosen.extend(top_level[::step][:safe_max_sections])
            if top_level[-1] not in chosen:
                chosen[-1] = top_level[-1]

        chosen.sort(key=lambda item: item[0])
        for idx, anchor, heading in chosen:
            sec_anchor = anchor or f"s{idx + 1}"
            if sec_anchor in seen_anchors:
                continue
            seen_anchors.add(sec_anchor)
            snippet_src = chunk_by_anchor.get(sec_anchor) or (
                chunks[min(idx, len(chunks) - 1)].content if chunks else heading
            )
            sections.append(
                {
                    "anchor": sec_anchor,
                    "heading": heading[:120],
                    "gist": _clean_sentence(snippet_src, max_len=160),
                }
            )
    elif headings:
        for idx, (anchor, heading) in enumerate(headings[:safe_max_sections]):
            gist = _clean_sentence(
                chunk_by_anchor.get(anchor) or (chunks[min(idx, len(chunks) - 1)].content if chunks else heading),
                max_len=160,
            )
            sec_anchor = anchor or f"s{idx + 1}"
            if sec_anchor not in seen_anchors:
                seen_anchors.add(sec_anchor)
                sections.append({"anchor": sec_anchor, "heading": heading[:120], "gist": gist})

    for chunk in chunks:
        if len(sections) >= safe_max_sections:
            break
        anchor = chunk.section_anchor or (f"p{chunk.page_number}" if chunk.page_number else f"c{chunk.chunk_index + 1}")
        if anchor in seen_anchors:
            continue
        seen_anchors.add(anchor)
        heading = f"Page {chunk.page_number}" if chunk.page_number else f"Section {chunk.chunk_index + 1}"
        sections.append(
            {
                "anchor": anchor,
                "heading": heading,
                "gist": _clean_sentence(chunk.content, max_len=160),
            }
        )

    suggested_topic = (title or (sections[0]["heading"] if sections else "Tài liệu mới")).strip()[:200]
    if suggested_topic.lower().endswith(".pdf"):
        suggested_topic = suggested_topic[:-4].replace("_", " ").replace("-", " ").strip()[:200]

    return {
        "brief": {
            "what": what,
            "claims": claims[:10],
            "notation": notation[:20],
            "assumes": assumes[:10],
            "sections": sections[:safe_max_sections],
        },
        "wordCount": word_count,
        "durationMinutes": duration_minutes,
        "suggestedTopic": suggested_topic or "Khóa học từ tài liệu",
    }


async def build_source_brief_with_agent(
    *,
    title: str | None,
    chunks: list[ChunkInput],
    headings: list[tuple[str, str]] | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    """Agent #2 (`src_` Source Brief): 1-turn `save_brief` SDK call with deterministic anchor clamping.

    - In `mock` mode (or if `provider` has no `build_source_brief_with_tool`), returns deterministic `build_source_brief`.
    - On real DeepSeek/OpenAI providers, invokes `save_brief` ONCE and clamps all fields to hard schema bounds
      while keeping `sections[].anchor` grounded strictly in observed document anchors.
    """
    baseline = build_source_brief(title=title, chunks=chunks, headings=headings)
    tool_fn = getattr(provider, "build_source_brief_with_tool", None) if provider is not None else None
    if not callable(tool_fn) or getattr(provider, "name", "mock") == "mock":
        return baseline

    valid_anchors = [str(s["anchor"]) for s in baseline["brief"]["sections"] if s.get("anchor")]
    valid_anchor_set = set(valid_anchors)
    excerpt_payload = {
        "availableAnchors": valid_anchors[:40],
        "headings": [{"anchor": a, "heading": h} for a, h in (headings or [])[:40]],
        "chunkExcerpts": [
            {
                "anchor": c.section_anchor or (f"p{c.page_number}" if c.page_number else f"c{c.chunk_index + 1}"),
                "text": _clean_sentence(c.content, max_len=360),
            }
            for c in chunks[:24]
        ],
    }
    try:
        raw_brief, _usage = await tool_fn(title=title, excerpt_payload=excerpt_payload)
        if not isinstance(raw_brief, dict) or not raw_brief:
            return baseline

        what = _clean_sentence(str(raw_brief.get("what") or ""), max_len=280) or baseline["brief"]["what"]
        raw_claims = [
            _clean_sentence(str(c), max_len=220)
            for c in (raw_brief.get("claims") or [])
            if str(c).strip()
        ]
        claims = raw_claims[:10] or baseline["brief"]["claims"]
        raw_notation = [
            str(n).strip()[:32]
            for n in (raw_brief.get("notation") or [])
            if str(n).strip()
        ]
        notation = raw_notation[:20] or baseline["brief"]["notation"]
        raw_assumes = [
            _clean_sentence(str(a), max_len=120)
            for a in (raw_brief.get("assumes") or [])
            if str(a).strip()
        ]
        assumes = raw_assumes[:10] or baseline["brief"]["assumes"]

        grounded_sections: list[dict[str, str]] = []
        seen_anchors: set[str] = set()
        for sec in (raw_brief.get("sections") or [])[:40]:
            if not isinstance(sec, dict):
                continue
            anchor = str(sec.get("anchor") or "").strip()
            if valid_anchor_set and anchor not in valid_anchor_set:
                continue
            if not anchor or anchor in seen_anchors:
                continue
            seen_anchors.add(anchor)
            grounded_sections.append(
                {
                    "anchor": anchor,
                    "heading": str(sec.get("heading") or anchor).strip()[:120],
                    "gist": _clean_sentence(str(sec.get("gist") or ""), max_len=160),
                }
            )
        sections = grounded_sections or baseline["brief"]["sections"]
        suggested_topic = (
            str(raw_brief.get("suggestedTopic") or "").strip()[:200] or baseline["suggestedTopic"]
        )
        return {
            "brief": {
                "what": what,
                "claims": claims,
                "notation": notation,
                "assumes": assumes,
                "sections": sections,
            },
            "wordCount": baseline["wordCount"],
            "durationMinutes": baseline["durationMinutes"],
            "suggestedTopic": suggested_topic,
        }
    except Exception as exc:  # noqa: BLE001 — fallback cleanly to deterministic anchor brief
        logger.warning("source_brief_agent_fallback error_type=%s", type(exc).__name__)
        return baseline
