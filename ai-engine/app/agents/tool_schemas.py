"""OpenAI & DeepSeek compatible Function Calling JSON Schemas for SopiSkill Agents.

Covers:
  1. `TUTOR_TOOL_SCHEMAS` (6 tools for AI Tutor "Sopi")
  2. `LESSON_GENERATOR_TOOL_SCHEMAS` (2 tools for bounded Lesson Writer loop: `read_source`, `save_lesson`)
"""

from __future__ import annotations

from typing import Any

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
                        "enum": [
                            "figure_mismatch",
                            "unanswerable",
                            "ambiguous",
                            "weak_distractors",
                            "wrong_answer",
                            "other",
                        ],
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


def get_tutor_tool_schemas(allowed_tools: list[str] | None) -> list[dict[str, Any]]:
    if not allowed_tools:
        return list(TUTOR_TOOL_SCHEMAS.values())
    return [TUTOR_TOOL_SCHEMAS[name] for name in allowed_tools if name in TUTOR_TOOL_SCHEMAS]
