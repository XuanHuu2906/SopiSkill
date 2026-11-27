"""Agent #3 — Interview & Planner Agent (`itn_`): bounded `read_source_brief` + `save_proposal` loop.

Keeps latency low (1..2 turns in normal execution, strictly capped by `max_turns`).
  - Turn 1 (optional, when `source_brief` is attached): `read_source_brief`
  - Final turn: `save_proposal`
  - Fallback for `MockProvider` (or providers without `next_planner_turn`): invokes `provider.generate_proposal(...)`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.providers import LLMProvider
from app.schemas.internal import LlmUsageOut

logger = logging.getLogger(__name__)


class PlannerMaxTurnsError(RuntimeError):
    """Raised if Planner Agent hits `max_turns` without committing `save_proposal`."""

    error_code = "max_turns"


@dataclass
class PlannerResult:
    proposal: dict[str, Any]
    tools_called: list[str] = field(default_factory=list)
    turns_used: int = 0
    usage: LlmUsageOut = field(default_factory=LlmUsageOut)


def _normalize_proposal(raw: dict[str, Any], *, topic: str, language: str) -> dict[str, Any]:
    """Ensure saved proposal satisfies core-api's expected keys (`title`/`name`, `summary`/`objective`, `units`)."""
    title = str(raw.get("title") or raw.get("name") or topic).strip()[:240]
    summary = str(raw.get("summary") or raw.get("objective") or f"Structured study plan for {topic}.").strip()[:600]
    raw_units = raw.get("units") if isinstance(raw.get("units"), list) else []
    units: list[dict[str, Any]] = []
    for u_idx, unit in enumerate(raw_units[:8], start=1):
        if not isinstance(unit, dict):
            continue
        u_title = str(unit.get("title") or f"Unit {u_idx}").strip()[:180]
        raw_lessons = (
            unit.get("lessons")
            if isinstance(unit.get("lessons"), list)
            else (unit.get("lessonTitles") if isinstance(unit.get("lessonTitles"), list) else [])
        )
        lessons: list[dict[str, Any]] = []
        for l_idx, lsn in enumerate(raw_lessons[:8], start=1):
            if isinstance(lsn, dict):
                l_title = str(lsn.get("title") or f"Lesson {l_idx}").strip()[:180]
                lessons.append({"title": l_title, "focus": str(lsn.get("focus") or l_title)[:240]})
            elif isinstance(lsn, str) and lsn.strip():
                lessons.append({"title": lsn.strip()[:180], "focus": lsn.strip()[:240]})
        if lessons:
            units.append(
                {
                    "title": u_title,
                    "objective": str(unit.get("objective") or u_title)[:300],
                    "lessons": lessons,
                }
            )
    if not units:
        units = [
            {
                "title": f"{topic} Foundations" if language == "en" else f"Nền tảng {topic}",
                "objective": summary,
                "lessons": [
                    {
                        "title": f"Core Concepts of {topic}" if language == "en" else f"Khái niệm cốt lõi của {topic}",
                        "focus": topic,
                    }
                ],
            }
        ]
    out = dict(raw)
    out["title"] = title
    out["name"] = title
    out["summary"] = summary
    out["objective"] = summary
    out["estimatedHours"] = float(raw.get("estimatedHours") or max(1.0, round(len(units) * 1.5, 1)))
    out["units"] = units
    return out


async def generate_proposal_with_tools(
    *,
    topic: str,
    language: str,
    learner_profile: dict[str, Any],
    provider: LLMProvider,
    source_brief: dict[str, Any] | None = None,
    max_turns: int = 4,
) -> PlannerResult:
    """Runs bounded Interview & Planner tool loop (`read_source_brief` -> `save_proposal`)."""
    safe_max_turns = max(1, min(max_turns, 6))
    has_brief = isinstance(source_brief, dict) and bool(source_brief)

    tools_called: list[str] = []
    tool_history: list[dict[str, Any]] = []
    saved_proposal: dict[str, Any] | None = None
    turns_used = 0
    total_prompt = 0
    total_completion = 0
    last_usage = LlmUsageOut(provider=provider.name, model=provider.model)

    turn_planner = getattr(provider, "next_planner_turn", None)
    if not callable(turn_planner):
        # Deterministic path for MockProvider: track `read_source_brief` if brief exists, then `save_proposal`
        if has_brief:
            tools_called.append("read_source_brief")
            turns_used += 1
        proposal, usage = await provider.generate_proposal(topic, language, learner_profile)
        tools_called.append("save_proposal")
        turns_used += 1
        return PlannerResult(
            proposal=_normalize_proposal(proposal, topic=topic, language=language),
            tools_called=tools_called,
            turns_used=turns_used,
            usage=usage,
        )

    for turn in range(1, safe_max_turns + 1):
        turns_used = turn
        action = await turn_planner(
            turn=turn,
            topic=topic,
            language=language,
            learner_profile=learner_profile,
            has_source_brief=has_brief,
            tool_history=tool_history,
        )
        call_id = str(action.get("id") or f"call_plan_{turn}")
        tool_name = str(action.get("tool") or "")
        tool_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        u = action.get("usage")
        if isinstance(u, LlmUsageOut):
            total_prompt += u.promptTokens
            total_completion += u.completionTokens
            last_usage = u

        if tool_name == "read_source_brief":
            tools_called.append("read_source_brief")
            tool_history.append(
                {
                    "id": call_id,
                    "tool": "read_source_brief",
                    "arguments": tool_args,
                    "result": {"sourceBrief": source_brief or {}},
                }
            )
        elif tool_name == "save_proposal":
            tools_called.append("save_proposal")
            candidate = tool_args.get("proposal") if isinstance(tool_args.get("proposal"), dict) else None
            if candidate is None and isinstance(tool_args.get("units"), list):
                candidate = tool_args
            if isinstance(candidate, dict):
                saved_proposal = _normalize_proposal(candidate, topic=topic, language=language)
                tool_history.append(
                    {
                        "id": call_id,
                        "tool": "save_proposal",
                        "arguments": {"title": saved_proposal["title"]},
                        "result": {"saved": True},
                    }
                )
                break
        else:
            logger.warning("planner_unknown_tool turn=%d tool=%s", turn, tool_name)
            tool_history.append(
                {
                    "id": call_id,
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": {"error": f"Unknown tool: {tool_name}"},
                }
            )

    if saved_proposal is None:
        raise PlannerMaxTurnsError(
            f"Planner Agent reached max_turns={safe_max_turns} without committing save_proposal."
        )

    return PlannerResult(
        proposal=saved_proposal,
        tools_called=tools_called,
        turns_used=turns_used,
        usage=LlmUsageOut(
            provider=last_usage.provider,
            model=last_usage.model,
            promptTokens=total_prompt,
            completionTokens=total_completion,
            totalTokens=total_prompt + total_completion,
            latencyMs=last_usage.latencyMs,
        ),
    )
