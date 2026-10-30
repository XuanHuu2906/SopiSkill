"""Unit tests cho MockProvider + schema validation."""

import pytest

from app.providers import SchemaInvalidError, get_provider
from app.schemas.schemas import ProposalPayload


@pytest.mark.asyncio
async def test_mock_provider_interview_questions():
    provider = get_provider()
    qs = await provider.generate_interview_questions("Python")
    assert len(qs) == 5
    assert all("Python" in q for q in qs)


@pytest.mark.asyncio
async def test_mock_provider_proposal_valid_schema():
    provider = get_provider()
    payload = await provider.generate_proposal(
        "Python cho người mới", ["q1", "q2", "q3", "q4", "q5"], ["a1", "a2", "a3", "a4", "a5"]
    )
    assert isinstance(payload, ProposalPayload)
    assert 2 <= len(payload.units) <= 6
    total_lessons = sum(len(u.lessonTitles) for u in payload.units)
    assert total_lessons >= 2


@pytest.mark.asyncio
async def test_mock_provider_proposal_rejects_bad_units():
    with pytest.raises(Exception):
        ProposalPayload(name="n", objective="o", units=[], outcomes=["x", "y"])


@pytest.mark.asyncio
async def test_mock_provider_lesson_has_all_block_types():
    provider = get_provider()
    proposal = await provider.generate_proposal("Test", ["q"] * 5, ["a"] * 5)
    lesson = await provider.generate_lesson(
        "Test", proposal, proposal.units[0].title, proposal.units[0].lessonTitles[0], []
    )
    types = {b["type"] if isinstance(b, dict) else b.type for b in lesson.blocks}
    assert {"teach", "mc", "blank", "order", "match", "short"} <= types


@pytest.mark.asyncio
async def test_mock_provider_deterministic():
    provider = get_provider()
    proposal = await provider.generate_proposal("Same topic", ["q"] * 5, ["a"] * 5)
    l1 = await provider.generate_lesson("Same topic", proposal, proposal.units[0].title, "X", [])
    l2 = await provider.generate_lesson("Same topic", proposal, proposal.units[0].title, "X", [])
    assert l1.blocks == l2.blocks  # deterministic — quan trọng cho test E2E
