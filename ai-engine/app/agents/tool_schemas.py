"""OpenAI & DeepSeek compatible Function Calling JSON Schemas for SopiSkill's 8-Agent Architecture.

Active schemas (all 8 Agents — #1..#8):
  1. `SOURCE_RESEARCH_TOOL_SCHEMAS` (#1 Source Research Agent): `search_sources`, `inspect_source`, `commit_sources`
  2. `SOURCE_BRIEF_TOOL_SCHEMAS` (#2 Source Brief Agent): `save_brief` (1-turn structured brief)
  3. `PLANNER_TOOL_SCHEMAS` (#3 Interview & Planner Agent): `read_source_brief`, `save_proposal`
  4. `LESSON_GENERATOR_TOOL_SCHEMAS` (#4 Lesson Generator Agent): `read_source`, `save_lesson` (+ optional `generate_image`)
  5. `VALIDATOR_QA_TOOL_SCHEMAS` (#5 Validator / QA Agent): `flag_question`, `approve_lesson`
  6. `REEL_SCRIPT_TOOL_SCHEMAS` (#6 Reel Script Agent): `save_reel_script` (1-turn structured 11-scene audiovisual script)
  8. `TUTOR_TOOL_SCHEMAS` (#8 AI Tutor "Sopi"): `read_lesson`, `explain_deeper`, `read_source`,
     `flag_question`, `revise_proposal`, `regenerate_unit`

Note:
  - Agent #7 (Short-Answer Grader) uses direct Structured Output (zero extra tools) for low latency.
"""

from __future__ import annotations

from typing import Any

CANONICAL_CONTENT_FLAG_CODES: list[str] = [
    "figure_mismatch",
    "unanswerable",
    "ambiguous",
    "weak_distractors",
    "wrong_answer",
    "other",
]

# ---------------------------------------------------------------------------
# Agent #1: Source Research Agent (3 tools, code-enforced domain & SSRF filter)
# ---------------------------------------------------------------------------
SOURCE_RESEARCH_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_sources",
            "description": (
                "Search reputable, allowlisted academic and official technical documentation sources "
                "(e.g. arXiv, official docs, standards) for the learner's topic. "
                "Junk/untrusted domains are filtered deterministically by server code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Focused search query describing the topic and sub-concepts.",
                    },
                    "englishQuery": {
                        "type": "string",
                        "description": (
                            "Optional canonical English academic search query when the learner's topic is in Vietnamese "
                            "(or another non-English language) so English open textbooks and papers match accurately."
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "Maximum number of vetted candidate sources to return (1..8).",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_source",
            "description": (
                "Inspect a single candidate source URL (previously returned by `search_sources` or allowlisted) "
                "to verify its title, authority, headings, and excerpt before committing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "HTTPS URL of the candidate source to inspect.",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit_sources",
            "description": (
                "Commit the final 1 to 3 highest-quality, verified sources for the course. "
                "Every URL is re-validated against domain reputation and SSRF rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string"},
                                "title": {"type": "string"},
                                "sourceKind": {
                                    "type": "string",
                                    "enum": ["arxiv_url", "web_url"],
                                },
                                "rationale": {"type": "string"},
                            },
                            "required": ["url", "title", "rationale"],
                        },
                    }
                },
                "required": ["sources"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Agent #2: Source Brief Agent (`src_`, 1-turn `save_brief`)
# ---------------------------------------------------------------------------
SOURCE_BRIEF_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_brief",
            "description": (
                "Compress extracted document chunks and headings into a strict structured `source.brief` "
                "table of contents in a single turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {
                        "type": "string",
                        "description": "1-2 sentence grounded summary of what the document covers (<= 280 chars).",
                    },
                    "suggestedTopic": {
                        "type": "string",
                        "description": "Concise course topic title derived from the document.",
                    },
                    "claims": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 10,
                        "items": {"type": "string"},
                        "description": "1..10 key factual claims grounded in the document.",
                    },
                    "notation": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                        "description": "Up to 20 technical symbols, formulas, or acronyms observed in the text.",
                    },
                    "assumes": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {"type": "string"},
                        "description": "Up to 10 prerequisite knowledge items assumed by the source.",
                    },
                    "sections": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {
                            "type": "object",
                            "properties": {
                                "anchor": {"type": "string"},
                                "heading": {"type": "string"},
                                "gist": {"type": "string"},
                            },
                            "required": ["anchor", "heading", "gist"],
                        },
                        "description": "Up to 40 anchored section entries grounded in real chunk/heading anchors.",
                    },
                },
                "required": ["what", "claims", "sections"],
            },
        },
    }
]

# ---------------------------------------------------------------------------
# Agent #3: Interview & Planner Agent (`itn_`: `read_source_brief` + `save_proposal`)
# ---------------------------------------------------------------------------
PLANNER_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_source_brief",
            "description": (
                "Read the course's compressed `source.brief` (claims, notation, assumes, and section anchors) "
                "so the proposed syllabus aligns strictly with the attached source material."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "Optional topic or section focus to inspect in the source brief.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_proposal",
            "description": "Commit the final tailored course proposal (title, summary, estimatedHours, units & lessons).",
            "parameters": {
                "type": "object",
                "properties": {
                    "proposal": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "estimatedHours": {"type": "number"},
                            "units": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "objective": {"type": "string"},
                                        "lessons": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "title": {"type": "string"},
                                                    "focus": {"type": "string"},
                                                },
                                                "required": ["title"],
                                            },
                                        },
                                    },
                                    "required": ["title", "lessons"],
                                },
                            },
                        },
                        "required": ["title", "summary", "units"],
                    }
                },
                "required": ["proposal"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Agent #4: Lesson Generator Agent (`gen_`: `read_source`, `save_lesson`, optional `generate_image`)
# ---------------------------------------------------------------------------
LESSON_GENERATOR_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_source",
            "description": "Inspect grounded excerpts from the attached course source by section anchor or search query before writing the lesson.",
            "parameters": {
                "type": "object",
                "properties": {
                    "anchor": {
                        "type": "string",
                        "description": "Exact section anchor from source.brief.sections[].anchor if known.",
                    },
                    "query": {
                        "type": "string",
                        "description": "Keyword or concept query to fetch relevant source excerpts.",
                    },
                    "englishQuery": {
                        "type": "string",
                        "description": (
                            "When writing a Vietnamese lesson from an English textbook, provide the exact English "
                            "academic terminology here to search the English book accurately."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_lesson",
            "description": "Commit the complete structured lesson JSON once ready. Must include teach blocks and gradable practice blocks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lesson": {
                        "type": "object",
                        "description": "Complete lesson object with keys `title` (string) and `blocks` (non-empty list of teach, mc, blank, order, match, short, speed, recap blocks).",
                        "properties": {
                            "title": {"type": "string"},
                            "blocks": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["title", "blocks"],
                    }
                },
                "required": ["lesson"],
            },
        },
    },
]

GENERATE_IMAGE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": (
            "Optional visual illustration request (only available when LESSON_IMAGES_ENABLED=true). "
            "Never attach both `image` and `figure` to the same teach block."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Clean pedagogical illustration prompt describing the concept.",
                },
                "alt": {
                    "type": "string",
                    "description": "Accessible alt text describing the generated image.",
                },
                "aspectRatio": {
                    "type": "string",
                    "enum": ["16:9", "4:3", "1:1"],
                },
            },
            "required": ["prompt", "alt"],
        },
    },
}


def get_lesson_generator_tool_schemas(*, image_gen_enabled: bool = False) -> list[dict[str, Any]]:
    schemas = list(LESSON_GENERATOR_TOOL_SCHEMAS)
    if image_gen_enabled:
        schemas.append(GENERATE_IMAGE_TOOL_SCHEMA)
    return schemas


# ---------------------------------------------------------------------------
# Agent #5: Validator / QA Agent (`fnd_`: `flag_question` [6 codes] + `approve_lesson`)
# ---------------------------------------------------------------------------
VALIDATOR_QA_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "flag_question",
            "description": (
                "Report a concrete defect in a specific lesson block using one of the 6 canonical "
                "`content_flags` codes so the Refiner can fix it deterministically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "blockIndex": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "0-based index of the defective block in lesson.blocks.",
                    },
                    "code": {
                        "type": "string",
                        "enum": CANONICAL_CONTENT_FLAG_CODES,
                        "description": "One of the 6 canonical content_flags codes.",
                    },
                    "details": {
                        "type": "string",
                        "description": "Actionable defect description explaining how to fix the block.",
                    },
                },
                "required": ["blockIndex", "code", "details"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_lesson",
            "description": "Approve the lesson when all teach blocks, figures, and quiz answers are factually accurate and unambiguous.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief confirmation note.",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Agent #8: AI Tutor "Sopi" (6 tools, strictly enforced against req.allowedTools)
# ---------------------------------------------------------------------------
TUTOR_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "read_lesson": {
        "type": "function",
        "function": {
            "name": "read_lesson",
            "description": "Read the current sanitized public lesson blocks (never contains answer keys) to answer the learner's question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "Optional concept or block title the learner is asking about.",
                    }
                },
                "required": [],
            },
        },
    },
    "explain_deeper": {
        "type": "function",
        "function": {
            "name": "explain_deeper",
            "description": "Give a deeper step-by-step Socratic explanation with a fresh analogy or concrete example.",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "The specific concept or step to explain deeper.",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["analogy", "worked_example", "first_principles"],
                        "description": "Preferred explanation style.",
                    },
                },
                "required": ["concept"],
            },
        },
    },
    "read_source": {
        "type": "function",
        "function": {
            "name": "read_source",
            "description": "Look up grounded excerpts from the attached course source via section_anchor in source.brief and Hybrid RAG.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for the source material.",
                    },
                    "englishQuery": {
                        "type": "string",
                        "description": "Optional canonical English terminology when the learner asks in Vietnamese about an English source.",
                    },
                    "section_anchor": {
                        "type": "string",
                        "description": "Optional section anchor from source.brief.sections[].anchor.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    "flag_question": {
        "type": "function",
        "function": {
            "name": "flag_question",
            "description": "Report a defective, ambiguous, unanswerable, or wrong quiz question to core-api content_flags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "enum": CANONICAL_CONTENT_FLAG_CODES,
                        "description": "Canonical content_flag taxonomy code.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Concise explanation of why the question is flawed.",
                    },
                },
                "required": ["code", "reason"],
            },
        },
    },
    "revise_proposal": {
        "type": "function",
        "function": {
            "name": "revise_proposal",
            "description": "Propose a revised course outline (for PlanChat on /new/proposal) to be saved with optimistic locking by core-api.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Concrete revision requested by the learner (e.g., shorter plan, add hands-on project).",
                    }
                },
                "required": ["instruction"],
            },
        },
    },
    "regenerate_unit": {
        "type": "function",
        "function": {
            "name": "regenerate_unit",
            "description": "Generate a preview-only ChangeCard proposing to rewrite the current unit. Never modifies lessons directly without learner confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["easier", "harder", "more_practical"],
                        "description": "Requested difficulty or style adjustment for the unit.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Short summary of what will change in the rewritten unit.",
                    },
                },
                "required": ["direction", "notes"],
            },
        },
    },
}


def get_tutor_tool_schemas(allowed_tools: list[str] | None) -> list[dict[str, Any]]:
    if not allowed_tools:
        return list(TUTOR_TOOL_SCHEMAS.values())
    return [TUTOR_TOOL_SCHEMAS[name] for name in allowed_tools if name in TUTOR_TOOL_SCHEMAS]


# ---------------------------------------------------------------------------
# Agent #6: Reel Script Agent (1-turn structured output `save_reel_script`)
# ---------------------------------------------------------------------------
REEL_SCENE_KINDS: list[str] = [
    "title",
    "statement",
    "bullets",
    "term",
    "compare",
    "figure",
    "chart",
    "code",
    "equation",
    "plot",
    "ready",
]
REEL_CUE_VERBS: list[str] = ["rise", "draw", "count", "pulse"]

REEL_SCRIPT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_reel_script",
            "description": (
                "Save a narrated audiovisual Reel script with 5 to 10 concise scenes covering the lesson's "
                "core intuition, formulas, code, charts, plots, or verified textbook `sourceFigureId`. "
                "NEVER include quiz answers or answer keys in the narration or scene content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "styleVersion": {"type": "string"},
                    "scenes": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 11,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {"type": "string", "enum": REEL_SCENE_KINDS},
                                "kicker": {"type": "string"},
                                "title": {"type": "string"},
                                "subtitle": {"type": "string"},
                                "statement": {"type": "string"},
                                "bullets": {"type": "array", "items": {"type": "string"}},
                                "term": {"type": "string"},
                                "definition": {"type": "string"},
                                "leftTitle": {"type": "string"},
                                "leftPoints": {"type": "array", "items": {"type": "string"}},
                                "rightTitle": {"type": "string"},
                                "rightPoints": {"type": "array", "items": {"type": "string"}},
                                "sourceFigureId": {"type": "string"},
                                "figure": {"type": "object"},
                                "chart": {"type": "object"},
                                "code": {"type": "string"},
                                "language": {"type": "string"},
                                "highlightLines": {"type": "array", "items": {"type": "integer"}},
                                "steps": {"type": "array", "items": {"type": "object"}},
                                "plot": {"type": "object"},
                                "ctaLabel": {"type": "string"},
                                "beats": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "say": {"type": "string"},
                                            "show": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "verb": {"type": "string", "enum": REEL_CUE_VERBS},
                                                        "target": {"type": "string"},
                                                    },
                                                    "required": ["verb", "target"],
                                                },
                                            },
                                        },
                                        "required": ["say"],
                                    },
                                },
                            },
                            "required": ["kind", "beats"],
                        },
                    },
                },
                "required": ["scenes"],
            },
        },
    }
]
