"""Phase 5 unit tests for Sopi Tutor's 6/6 agentic tools (`read_lesson`, `explain_deeper`,
`read_source` + `sourceBrief` section anchors, `flag_question`, `revise_proposal`, `regenerate_unit`)."""

from __future__ import annotations

import json

from app.agents.providers import MockProvider
from app.agents.tutor_agent import REGISTERED_TOOLS, stream_tutor_turn
from app.rag.repository import RagRepository
from app.schemas.internal import TutorLessonContext, TutorStreamInternalRequest


def _parse_frames(raw_frames: list[str]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for raw in raw_frames:
        ev = "message"
        data_lines: list[str] = []
        for line in raw.strip().splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            out.append((ev, json.loads("\n".join(data_lines))))
    return out


def test_all_six_tutor_tools_are_registered_and_active():
    assert set(REGISTERED_TOOLS.keys()) == {
        "read_lesson",
        "explain_deeper",
        "read_source",
        "flag_question",
        "revise_proposal",
        "regenerate_unit",
    }
    assert all(meta["available"] is True for meta in REGISTERED_TOOLS.values())


async def test_tutor_flag_question_emits_tool_effect_for_core_api():
    req = TutorStreamInternalRequest(
        ownerId="usr_1",
        courseId="crs_1",
        threadId="thr_1",
        messageId="tmsg_1",
        language="vi",
        entryPoint="wrong_answer",
        userMessage="Báo lỗi câu hỏi này bị mơ hồ",
        lessonContext=TutorLessonContext(
            lessonId="lsn_1",
            lessonTitle="Lesson 1",
            activeBlockIndex=2,
            publicBlocks=[{"type": "mc", "question": "Pick one", "options": ["A", "B"]}],
        ),
    )
    raw = [f async for f in stream_tutor_turn(req, provider=MockProvider(), rag_repo=RagRepository(), db=None)]
    frames = _parse_frames(raw)
    tool_events = [d for ev, d in frames if ev == "tool"]
    effects = [d for ev, d in frames if ev == "tool_effect"]
    assert tool_events[0]["name"] == "flag_question"
    assert len(effects) == 1
    assert effects[0]["kind"] == "flag_question"
    assert effects[0]["blockIndex"] == 2
    assert any(ev == "done" for ev, _ in frames)


async def test_tutor_revise_proposal_emits_revised_payload():
    req = TutorStreamInternalRequest(
        ownerId="usr_1",
        courseId="crs_1",
        threadId="thr_1",
        messageId="tmsg_2",
        language="en",
        entryPoint="proposal",
        userMessage="Add a hands-on project lesson to this plan",
        proposalContext={
            "version": 1,
            "approved": False,
            "payload": {
                "name": "Graph Algorithms",
                "objective": "Learn graph search.",
                "outcomes": ["Use BFS and DFS"],
                "units": [{"title": "Foundations", "blurb": "Basics", "lessonTitles": ["BFS"]}],
            },
        },
        allowedTools=["revise_proposal", "read_source"],
    )
    raw = [f async for f in stream_tutor_turn(req, provider=MockProvider(), rag_repo=RagRepository(), db=None)]
    frames = _parse_frames(raw)
    effects = [d for ev, d in frames if ev == "tool_effect"]
    assert len(effects) == 1
    assert effects[0]["kind"] == "revise_proposal"
    assert len(effects[0]["proposal"]["units"][0]["lessonTitles"]) == 2


async def test_tutor_regenerate_unit_emits_preview_only_requiring_confirmation():
    req = TutorStreamInternalRequest(
        ownerId="usr_1",
        courseId="crs_1",
        threadId="thr_1",
        messageId="tmsg_3",
        language="vi",
        entryPoint="path_harder",
        userMessage="Chương này quá khó, viết lại chương dễ hơn giúp mình",
        lessonContext=TutorLessonContext(
            lessonId="lsn_1",
            lessonTitle="Lesson 1",
            activeBlockIndex=0,
            publicBlocks=[{"type": "teach", "title": "Intro", "paragraphs": ["Text"]}],
        ),
        unitContext={"unitId": "unit_99", "unitTitle": "Nền tảng"},
    )
    raw = [f async for f in stream_tutor_turn(req, provider=MockProvider(), rag_repo=RagRepository(), db=None)]
    frames = _parse_frames(raw)
    effects = [d for ev, d in frames if ev == "tool_effect"]
    assert len(effects) == 1
    assert effects[0]["kind"] == "regenerate_unit"
    assert effects[0]["unitId"] == "unit_99"
    assert effects[0]["preview"]["direction"] == "easier"
    assert len(effects[0]["preview"]["changes"]) >= 1


async def test_tutor_read_source_matches_source_brief_section_anchors():
    req = TutorStreamInternalRequest(
        ownerId="usr_1",
        courseId="crs_1",
        threadId="thr_1",
        messageId="tmsg_4",
        language="en",
        entryPoint="teach_block",
        userMessage="Check the source section about attention scaling",
        lessonContext=TutorLessonContext(
            lessonId="lsn_1",
            lessonTitle="Attention",
            activeBlockIndex=0,
            publicBlocks=[{"type": "teach", "title": "Attention", "paragraphs": ["Scaling"]}],
        ),
        sourceBrief={
            "what": "Transformer architecture.",
            "sections": [
                {"anchor": "sec-dot", "heading": "Scaled Dot-Product Attention", "gist": "Scales by sqrt(d_k)."}
            ],
        },
        ragEnabled=False,
    )
    raw = [f async for f in stream_tutor_turn(req, provider=MockProvider(), rag_repo=RagRepository(), db=None)]
    frames = _parse_frames(raw)
    tool_events = [d for ev, d in frames if ev == "tool"]
    assert tool_events[0]["name"] == "read_source"
    assert tool_events[0]["status"] == "ok"
    assert "section anchors" in tool_events[0]["summary"]
