"""Phase 4 unit tests: 4 figure kinds (7 SVG layouts), graph invariants, multi-blank + 1-blank
backward compatibility, and MockProvider rich lesson generation."""

from __future__ import annotations

import pytest

from app.agents.figure_validator import validate_teach_media_and_figure
from app.agents.providers import MockProvider
from app.agents.validation import validate_lesson_payload


@pytest.mark.parametrize(
    "figure",
    [
        {"kind": "formula", "latex": r"\text{Attention}(Q,K,V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V"},
        {
            "kind": "table",
            "headers": ["Method", "Trade-off"],
            "rows": [
                {"tone": "moss", "cells": ["HNSW", "Fast recall"]},
                {"tone": "clay", "cells": ["Full scan", "Slow at scale"]},
                {"tone": "neutral", "cells": ["BM25", "Exact lexical"]},
            ],
        },
        {"kind": "visual", "items": ["Encoder", "Latent Vector", "Decoder"]},
        {
            "kind": "diagram",
            "layout": "flow",
            "nodes": [{"id": "a", "label": "Input"}, {"id": "b", "label": "Transform"}, {"id": "c", "label": "Output"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        },
        {
            "kind": "diagram",
            "layout": "timeline",
            "nodes": [{"id": "t1", "label": "2017 Transformer"}, {"id": "t2", "label": "2020 RAG"}],
        },
        {
            "kind": "diagram",
            "layout": "branch",
            "nodes": [{"id": "r", "label": "Search"}, {"id": "l1", "label": "Lexical"}, {"id": "l2", "label": "Dense"}],
            "edges": [{"from": "r", "to": "l1"}, {"from": "r", "to": "l2"}],
        },
        {
            "kind": "diagram",
            "layout": "cycle",
            "nodes": [{"id": "c1", "label": "Plan"}, {"id": "c2", "label": "Build"}, {"id": "c3", "label": "Verify"}],
            "edges": [{"from": "c1", "to": "c2"}, {"from": "c2", "to": "c3"}, {"from": "c3", "to": "c1"}],
        },
        {
            "kind": "diagram",
            "layout": "stack",
            "nodes": [{"id": "s1", "label": "UI Layer"}, {"id": "s2", "label": "API Layer"}, {"id": "s3", "label": "DB Layer"}],
        },
        {
            "kind": "diagram",
            "layout": "split",
            "nodes": [{"id": "a1", "label": "Sync"}, {"id": "b1", "label": "Async"}, {"id": "a2", "label": "Blocking"}, {"id": "b2", "label": "Non-blocking"}],
        },
        {
            "kind": "diagram",
            "layout": "hub",
            "center": {"id": "hub", "label": "Core API"},
            "spokes": [{"id": "sp1", "label": "Postgres"}, {"id": "sp2", "label": "Redis"}, {"id": "sp3", "label": "AI Engine"}],
        },
        {
            "kind": "code",
            "language": "python",
            "title": "Scaled Dot-Product Attention",
            "code": "def attention(q, k, v):\n    return softmax(q @ k.T / sqrt(d_k)) @ v\n",
            "highlightLines": [2],
        },
        {
            "kind": "plot",
            "title": "Quadratic & Sine Explorer",
            "xRange": [-5, 5],
            "yRange": [-4, 6],
            "params": [{"name": "a", "label": "Amplitude", "min": 0.5, "max": 3.0, "step": 0.1, "value": 1.0}],
            "functions": [
                {"expr": "a * sin(x)", "label": "a*sin(x)"},
                {"expr": "0.2 * x^2 - 1", "label": "0.2x^2 - 1"},
            ],
            "points": [{"x": 0, "y": -1, "label": "Vertex (0, -1)"}],
        },
    ],
)
def test_all_four_figure_kinds_and_seven_svg_layouts_validate_cleanly(figure: dict):
    block = {
        "type": "teach",
        "title": "Architecture",
        "paragraphs": ["Clear explanation of the diagram above."],
        "figure": figure,
    }
    assert validate_teach_media_and_figure(block, 0) == []


def test_figure_validator_rejects_orphans_odd_split_long_cycle_and_media_conflict():
    # 1. Orphan node
    orphan_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "diagram",
                "layout": "flow",
                "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "Orphan"}],
                "edges": [{"from": "a", "to": "b"}],
            },
        },
        0,
    )
    assert any("orphan" in e.lower() for e in orphan_errs)

    # 2. Odd count on split
    split_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "diagram",
                "layout": "split",
                "nodes": [{"id": "1", "label": "One"}, {"id": "2", "label": "Two"}, {"id": "3", "label": "Three"}],
            },
        },
        0,
    )
    assert any("even number" in e.lower() for e in split_errs)

    # 3. Oversized label in cycle (>48 chars)
    cycle_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "diagram",
                "layout": "cycle",
                "nodes": [
                    {"id": "1", "label": "X" * 60},
                    {"id": "2", "label": "Build"},
                    {"id": "3", "label": "Verify"},
                ],
            },
        },
        0,
    )
    assert any("exceeds 48 chars" in e.lower() for e in cycle_errs)

    # 4. Mutual exclusion: figure + image simultaneously
    conflict_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {"kind": "formula", "latex": "a^2 + b^2 = c^2"},
            "image": {"url": "https://example.com/fig.png", "alt": "Fig"},
        },
        0,
    )
    assert any("mutually exclusive" in e.lower() for e in conflict_errs)


def test_figure_validator_rejects_unsafe_plot_expressions_and_bad_code():
    # 1. AST injection / arbitrary call in plot expression must be blocked
    inject_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "plot",
                "xRange": [-5, 5],
                "yRange": [-5, 5],
                "functions": [{"expr": "__import__('os').system('id')"}],
            },
        },
        0,
    )
    assert inject_errs and any("invalid expr" in e.lower() for e in inject_errs)

    # 2. Unknown undeclared variable in plot expression must be blocked
    var_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "plot",
                "xRange": [-5, 5],
                "yRange": [-5, 5],
                "functions": [{"expr": "secret * x + 1"}],
            },
        },
        0,
    )
    assert any("unknown identifier" in e.lower() for e in var_errs)

    # 3. Inverted plot range must be rejected
    range_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "plot",
                "xRange": [5, -5],
                "yRange": [-2, 2],
                "functions": [{"expr": "x^2"}],
            },
        },
        0,
    )
    assert any("xrange" in e.lower() for e in range_errs)

    # 4. Out-of-range highlightLines and empty code rejected
    code_errs = validate_teach_media_and_figure(
        {
            "type": "teach",
            "figure": {
                "kind": "code",
                "language": "python",
                "code": "x = 1\ny = 2",
                "highlightLines": [5],
            },
        },
        0,
    )
    assert any("out of range" in e.lower() for e in code_errs)


def test_multi_blank_and_legacy_single_blank_validation():
    # Multi-blank valid
    ok_lesson = {
        "title": "Multi-Blank Demo",
        "blocks": [
            {
                "type": "blank",
                "parts": ["Use ", " before ", "."],
                "answers": ["design", "code"],
                "bank": ["design", "code", "guess", "delay"],
            }
        ],
    }
    assert validate_lesson_payload(ok_lesson) == []

    # Multi-blank invalid (answer missing from bank)
    bad_lesson = {
        "title": "Bad Multi-Blank",
        "blocks": [
            {
                "type": "blank",
                "parts": ["Use ", " before ", "."],
                "answers": ["design", "missing_word"],
                "bank": ["design", "other"],
            }
        ],
    }
    assert any("missing from bank" in e.lower() for e in validate_lesson_payload(bad_lesson))

    # Legacy 1-blank still valid
    legacy = {
        "title": "Legacy Blank",
        "blocks": [{"type": "blank", "sentence": "The key concept is ____.", "answer": "recursion"}],
    }
    assert validate_lesson_payload(legacy) == []


async def test_mock_provider_lesson_0_and_lesson_1_rich_formats_pass_validation():
    provider = MockProvider()
    for lang in ("en", "vi"):
        l0, _ = await provider.generate_lesson("Graph Algorithms", "Foundations", "Lesson 1", lang, {"_lessonOrder": 0})
        assert len(l0["blocks"]) == 6
        assert l0["blocks"][0]["figure"]["layout"] == "flow"
        assert validate_lesson_payload(l0) == []

        l1, _ = await provider.generate_lesson("Graph Algorithms", "Foundations", "Lesson 2", lang, {"_lessonOrder": 1})
        assert len(l1["blocks"]) == 7
        types = [b["type"] for b in l1["blocks"]]
        assert types == ["teach", "blank", "mc", "mc", "speed", "short", "recap"]
        assert l1["blocks"][0]["figure"]["kind"] == "table"
        assert validate_lesson_payload(l1) == []
