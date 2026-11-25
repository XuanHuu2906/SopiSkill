"""Tests cho P1-LEVEL-FIT: nhận diện trình độ VI/EN và truyền learnerProfile vào prompt generate_lesson."""

from __future__ import annotations

import json

import httpx
import pytest

from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.schemas.schemas import (
    CurriculumSkill,
    LearnerProfile,
    ProposalPayload,
    ProposalUnit,
)
from app.services.pedagogy import extract_learner_profile


@pytest.mark.parametrize(
    ("answer", "expected_level"),
    [
        ("I have no experience with Excel at all.", "beginner"),
        ("I'm completely new to guitar and just starting out.", "beginner"),
        ("I have never used Python before.", "beginner"),
        ("I have basic knowledge only.", "beginner"),
        ("Mình mới bắt đầu học Python từ đầu.", "beginner"),
        ("I have some experience writing SQL queries.", "intermediate"),
        ("I'm familiar with Python and use it at work.", "intermediate"),
        ("I have 2 years working with relational databases.", "intermediate"),
        ("I have a solid foundation in technical writing.", "intermediate"),
        ("I'm comfortable with Git branching workflows.", "intermediate"),
        ("Mình đã học qua SQL và làm bài tập nhỏ rồi.", "intermediate"),
        ("I have 5+ years of experience running distributed systems in production.", "advanced"),
        ("I am a senior backend engineer proficient in Raft and Paxos.", "advanced"),
        ("I work as a staff engineer designing high-throughput pipelines.", "advanced"),
        ("I want mastery over behavioral economics edge cases.", "advanced"),
        ("Mình có nhiều năm kinh nghiệm làm hệ thống phân tán.", "advanced"),
    ],
)
def test_english_and_vietnamese_level_detection(answer: str, expected_level: str):
    profile = extract_learner_profile(
        ["Level?", "Goal?", "Time?", "Style?", "Depth?"],
        [answer, "Improve my skills", "3 hours per week", "Examples", "Balanced"],
    )
    assert profile.currentLevel == expected_level


def test_contradictory_english_level_warns_and_falls_back_intermediate():
    profile = extract_learner_profile(
        ["Level?", "Goal?", "Time?", "Style?", "Depth?"],
        [
            "I'm a complete beginner in ML but have years of experience in production.",
            "Build models",
            "4 hours/week",
            "Hands-on",
            "Deep dive",
        ],
    )
    assert profile.currentLevel == "intermediate"
    assert profile.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["beginner", "intermediate", "advanced"])
async def test_generate_lesson_prompt_includes_learner_profile_level_and_depth(level: str):
    """P1-LEVEL-FIT: generate_lesson PHẢI đưa learnerProfile vào prompt sinh bài."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Replication",
                                    "blocks": [
                                        {
                                            "type": "teach",
                                            "title": "Replication trade-offs",
                                            "paragraphs": [
                                                "Leader-follower replication trades write latency against stale reads."
                                            ],
                                        },
                                        {
                                            "type": "mc",
                                            "question": "What does p99 lag of 2s mean?",
                                            "options": [
                                                "1% of reads see lag exceeding 2s",
                                                "99% of reads exceed 2s",
                                                "Average lag is 2s",
                                            ],
                                            "answerIndex": 0,
                                        },
                                    ],
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 110},
            },
        )

    proposal = ProposalPayload(
        name="Distributed Systems",
        objective="Understand replication and consistency.",
        units=[
            ProposalUnit(title="Unit 1", blurb="Core", lessonTitles=["Replication"]),
            ProposalUnit(title="Unit 2", blurb="Consensus", lessonTitles=["Raft"]),
        ],
        outcomes=["Analyze replication lag", "Explain leader election"],
        learnerProfile=LearnerProfile(
            goal="Design resilient systems",
            currentLevel=level,  # type: ignore[arg-type]
            weeklyMinutes=240,
            preferredStyles=["hands_on", "visual"],
            depth="deep",
        ),
        skills=[
            CurriculumSkill(id="s1", title="Replication", lesson="Replication", bloomLevel="analyze", outcome="Analyze lag"),
            CurriculumSkill(id="s2", title="Raft", lesson="Raft", bloomLevel="evaluate", outcome="Evaluate consensus"),
        ],
        prerequisites=[("s1", "s2")],
    )

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    await provider.generate_lesson(
        "Distributed Systems", proposal, "Unit 1", "Replication", [], language="en"
    )
    assert len(captured) == 1
    user_prompt = captured[0]["messages"][1]["content"]
    assert f"currentLevel={level}" in user_prompt
    assert "depth=deep" in user_prompt
    assert "hands_on, visual" in user_prompt
    assert level.upper() in user_prompt
