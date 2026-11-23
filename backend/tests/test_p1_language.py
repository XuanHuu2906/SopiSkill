"""Tests cho P1-LANG: ngôn ngữ khóa học (`vi` | `en`) xuyên suốt pipeline + migration 0017."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.schemas.schemas import CurriculumSkill, LearnerProfile, ProposalPayload, ProposalUnit
from app.services.tutor_context import build_tutor_system
from evals.dataset import EvalCase
from evals.pipeline import run_case
from app.providers.mock_provider import MockProvider

PASSWORD = "StrongPassword123!"


def csrf_headers(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("csrf_token", "")}


async def _register(client, prefix: str) -> str:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


@pytest.mark.asyncio
async def test_course_defaults_to_vi_and_rejects_unsupported_language(client):
    await _register(client, "p1lang-def")

    r_def = await client.post(
        "/v1/courses",
        json={"topic": "Python cơ bản", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r_def.status_code == 201, r_def.text
    assert r_def.json()["language"] == "vi"

    for bad_lang in ("fr", "de", "jp", "", "VI"):
        r_bad = await client.post(
            "/v1/courses",
            json={
                "topic": "Python basics",
                "clientCourseId": uuid.uuid4().hex[:16],
                "language": bad_lang,
            },
            headers=csrf_headers(client),
        )
        assert r_bad.status_code == 422, f"expected 422 for language={bad_lang!r}, got {r_bad.status_code}"


@pytest.mark.asyncio
async def test_english_course_end_to_end_with_mock_provider(client):
    """Khóa học language='en' đi trọn interview → proposal → generation → lesson bằng tiếng Anh."""
    await _register(client, "p1lang-en")
    r_create = await client.post(
        "/v1/courses",
        json={
            "topic": "Distributed Systems",
            "clientCourseId": uuid.uuid4().hex[:16],
            "language": "en",
        },
        headers=csrf_headers(client),
    )
    assert r_create.status_code == 201, r_create.text
    course = r_create.json()
    assert course["language"] == "en"
    course_id = course["id"]

    iv = (await client.get(f"/v1/courses/{course_id}/interview")).json()
    assert len(iv["questions"]) == 5
    # Không rò dấu tiếng Việt ở câu hỏi phỏng vấn tiếng Anh.
    assert all("Bạn" not in q for q in iv["questions"])

    en_answers = [
        "I have 3 years of backend experience working with services.",
        "I want to design resilient replication pipelines.",
        "About 4 hours per week.",
        "Hands-on examples and diagrams.",
        "Deep dive into failure modes.",
    ]
    for pos, ans in enumerate(en_answers):
        ra = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": pos, "answer": ans},
            headers=csrf_headers(client),
        )
        assert ra.status_code == 200, ra.text

    prop = (await client.get(f"/v1/courses/{course_id}/proposal")).json()
    assert "Foundations" in prop["payload"]["units"][0]["title"]
    assert "Nền tảng" not in prop["payload"]["units"][0]["title"]

    rap = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert rap.status_code == 202, rap.text

    status = None
    for _ in range(200):
        await asyncio.sleep(0.05)
        status = (await client.get(f"/v1/courses/{course_id}/generation")).json()["status"]
        if status in ("ready", "failed"):
            break
    assert status == "ready"

    detail = (await client.get(f"/v1/courses/{course_id}")).json()
    assert detail["language"] == "en"
    first_lesson_id = detail["units"][0]["lessons"][0]["id"]
    lesson = (await client.get(f"/v1/lessons/{first_lesson_id}")).json()
    teach = next(b for b in lesson["blocks"] if b["type"] == "teach")
    joined = " ".join(teach["paragraphs"])
    assert "core concepts" in joined
    assert "nội dung cốt lõi" not in joined

    courses_list = (await client.get("/v1/courses")).json()
    matched = next(c for c in courses_list["items"] if c["id"] == course_id)
    assert matched["language"] == "en"


@pytest.mark.asyncio
async def test_openai_provider_honors_english_language_without_vietnamese_hardcode():
    """Payload gửi provider thật khi language='en' không chứa chuỗi hardcode tiếng Việt."""
    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        idx = len(captured_payloads)
        if idx == 1:
            content = json.dumps(
                {
                    "questions": [
                        "What is your current SQL level?",
                        "What is your primary goal?",
                        "How many hours per week can you study?",
                        "What learning style do you prefer?",
                        "Do you prefer breadth or depth?",
                    ]
                }
            )
        elif idx == 2:
            content = json.dumps(
                {
                    "name": "SQL Mastery",
                    "objective": "Write and optimize production SQL queries.",
                    "units": [
                        {"title": "Unit 1", "blurb": "Core queries.", "lessonTitles": ["Joins"]},
                        {"title": "Unit 2", "blurb": "Tuning.", "lessonTitles": ["Indexes"]},
                    ],
                    "outcomes": ["Write multi-table joins", "Optimize query plans"],
                    "skills": [
                        {"id": "sk1", "title": "Joins", "lesson": "Joins", "bloomLevel": "apply", "outcome": "Combine tables"},
                        {"id": "sk2", "title": "Indexes", "lesson": "Indexes", "bloomLevel": "analyze", "outcome": "Speed up queries"},
                    ],
                    "prerequisites": [["sk1", "sk2"]],
                }
            )
        else:
            content = json.dumps(
                {
                    "title": "Joins",
                    "blocks": [
                        {
                            "type": "teach",
                            "title": "SQL Joins",
                            "paragraphs": [
                                "INNER JOIN returns rows with matching keys in both tables.",
                                "LEFT JOIN keeps all rows from the left table even without matches.",
                            ],
                        },
                        {
                            "type": "mc",
                            "question": "Which join keeps unmatched rows from the left table?",
                            "options": ["INNER JOIN", "LEFT JOIN", "CROSS JOIN"],
                            "answerIndex": 1,
                        },
                    ],
                }
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 80},
            },
        )

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    questions = await provider.generate_interview_questions("SQL", language="en")
    assert len(questions) == 5

    proposal = await provider.generate_proposal(
        "SQL",
        questions,
        ["Intermediate", "Optimize queries", "3 hours", "Examples", "Deep"],
        language="en",
    )
    proposal.learnerProfile = LearnerProfile(
        goal="Optimize queries",
        currentLevel="intermediate",
        weeklyMinutes=180,
        preferredStyles=["hands_on"],
        depth="deep",
    )

    lesson = await provider.generate_lesson(
        "SQL", proposal, "Unit 1", "Joins", [], language="en"
    )
    assert lesson.title == "Joins"
    assert len(captured_payloads) == 3

    for payload in captured_payloads:
        text = json.dumps(payload, ensure_ascii=False)
        assert "Target language: English" in text
        assert "bằng tiếng Việt" not in text
        assert "ngôn ngữ mục tiêu: Vietnamese" not in text


def test_tutor_system_prompt_reflects_course_language():
    blocks = [{"type": "teach", "title": "Intro", "paragraphs": ["Hello world."]}]
    en_sys = build_tutor_system(
        lesson_title="Intro", blocks=blocks, block_index=0, language="en"
    )
    assert "Course language: English" in en_sys

    vi_sys = build_tutor_system(
        lesson_title="Intro", blocks=blocks, block_index=0, language="vi"
    )
    assert "Ngôn ngữ khóa học: tiếng Việt" in vi_sys


@pytest.mark.asyncio
async def test_eval_pipeline_passes_case_language_and_passes_en_rubric():
    case = EvalCase(
        id="en-test-sql",
        topic="SQL Indexing",
        language="en",
        level="intermediate",
        ambiguity="clear",
        answers=(
            "I have 2 years of experience using SQL at work.",
            "Optimize slow queries.",
            "3 hours per week.",
            "Hands-on examples.",
            "Deep dive.",
        ),
    )
    result = await run_case(MockProvider(), case, model="mock")
    assert result.passed is True
    lang_criterion = next(c for c in result.rubric["criteria"] if c["id"] == "language")
    assert lang_criterion["passed"] is True
    assert lang_criterion["detail"] == "clean English"


def test_migration_0017_single_head_and_roundtrip(tmp_path):
    """Migration 0017 là expand-only, single-headed và upgrade/downgrade sạch trên DB thật."""
    import importlib.util
    import pathlib

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import text

    from app.db.base import Base
    import app.models  # noqa: F401

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    # Graph chỉ có đúng một head duy nhất và chứa revision 0017_p1_course_language.
    assert len(script.get_heads()) == 1
    assert script.get_revision("0017_p1_course_language") is not None
    assert "language" in Base.metadata.tables["courses"].c

    mig_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0017_p1_course_language.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0017", mig_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0017_p1_course_language"
    assert module.down_revision == "0016_p52_exposure"

    db_path = tmp_path / "mig0017.db"
    sync_engine = create_engine(f"sqlite:///{db_path}")
    try:
        with sync_engine.begin() as conn:
            conn.execute(text("CREATE TABLE courses (id TEXT PRIMARY KEY, topic TEXT NOT NULL)"))
            conn.execute(text("INSERT INTO courses (id, topic) VALUES ('c1', 'Legacy Python')"))
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                module.upgrade()

            cols = {c["name"] for c in inspect(conn).get_columns("courses")}
            assert "language" in cols
            legacy_lang = conn.execute(
                text("SELECT language FROM courses WHERE id = 'c1'")
            ).scalar_one()
            assert legacy_lang == "vi"

            # Downgrade phải gỡ sạch cột language mà vẫn bảo toàn dữ liệu bảng courses.
            with Operations.context(ctx):
                module.downgrade()
            cols_after_down = {c["name"] for c in inspect(conn).get_columns("courses")}
            assert "language" not in cols_after_down
            assert (
                conn.execute(text("SELECT topic FROM courses WHERE id = 'c1'")).scalar_one()
                == "Legacy Python"
            )

            # Re-upgrade idempotent.
            with Operations.context(ctx):
                module.upgrade()
            assert "language" in {c["name"] for c in inspect(conn).get_columns("courses")}
    finally:
        sync_engine.dispose()
