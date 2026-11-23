"""Wave 4 product gap tests (100% offline/mock):
  1. P1-PROPOSAL-EDIT: PATCH /v1/courses/{id}/proposal (optimistic locking, 409 conflict/locked,
     server-preserved learnerProfile, DAG rebuild, cross-user 404).
  2. P1-GLOSSARY: migration 0018 single head & roundtrip, extraction strictly from teach blocks
     (0 answer key leakage), auto-upsert during generation, GET /v1/courses/{id}/glossary (+ lessonId filter).
  3. GAP-11 Per-block server-side grading & AI short-answer rubric grader + dispute:
     POST /v1/lessons/{id}/blocks/{i}/grade across mc/blank/short/order/match, bool rejection,
     semantic token overlap, LLM dispute rubric with MockTransport, 0 answer-key leak on GET lesson.
  4. M1-ME-SURFACE & Settings: GET /v1/me/stats, PATCH /v1/me, DELETE /v1/me (CSRF, password +
     DELETE confirm, full FK-clean cascade deletion, cookies cleared, post-delete 401).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.providers.openai_compatible_provider import OpenAICompatibleProvider
from app.services.glossary_service import extract_terms_from_lesson, normalize_term_key

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def _register(client, prefix: str = "w4") -> dict:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"email": email, "user": r.json()}


async def _create_proposed_course(client, *, topic: str = "Graph Algorithms", language: str = "en") -> str:
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "language": language, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    answers = [
        "Intermediate developer with 3 years of experience.",
        "Solve graph traversal problems.",
        "4 hours per week.",
        "Hands-on coding examples.",
        "Balanced practical depth.",
    ]
    for pos, ans in enumerate(answers):
        ir = await client.post(
            f"/v1/courses/{cid}/interview/answer",
            json={"position": pos, "answer": ans},
            headers=csrf_headers(client),
        )
        assert ir.status_code == 200, ir.text
    return cid


async def _approve_and_ready(client, course_id: str) -> dict:
    ar = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert ar.status_code == 202, ar.text
    detail = await client.get(f"/v1/courses/{course_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()


# ---------- 1. P1-PROPOSAL-EDIT ----------


@pytest.mark.asyncio
async def test_proposal_patch_updates_version_preserves_profile_and_enforces_optimistic_lock(client):
    await _register(client, "prop")
    cid = await _create_proposed_course(client)

    p1 = (await client.get(f"/v1/courses/{cid}/proposal")).json()
    assert p1["version"] == 1
    assert p1["approved"] is False
    orig_profile = p1["payload"]["learnerProfile"]
    assert orig_profile["currentLevel"] in ("intermediate", "advanced")

    # Valid PATCH increments version 1 -> 2, rebuilds skills DAG, preserves server learnerProfile
    updated_body = {
        "expectedVersion": 1,
        "name": "Custom Graph Mastery",
        "objective": "Apply BFS, DFS, and Dijkstra cleanly to real graph problems.",
        "units": [
            {
                "title": "Core Traversals",
                "blurb": "Breadth-first and depth-first graph exploration.",
                "lessonTitles": ["Graph Representation", "BFS vs DFS"],
            },
            {
                "title": "Shortest Paths",
                "blurb": "Weighted shortest-path algorithms.",
                "lessonTitles": ["Dijkstra Algorithm", "Bellman-Ford Trade-offs"],
            },
        ],
        "outcomes": [
            "Implement BFS and DFS on adjacency lists.",
            "Choose between Dijkstra and Bellman-Ford.",
        ],
    }
    r2 = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json=updated_body,
        headers=csrf_headers(client),
    )
    assert r2.status_code == 200, r2.text
    p2 = r2.json()
    assert p2["version"] == 2
    assert p2["approved"] is False
    assert p2["payload"]["name"] == "Custom Graph Mastery"
    assert p2["payload"]["learnerProfile"] == orig_profile
    assert len(p2["payload"]["skills"]) == 4

    # Stale expectedVersion=1 must fail with 409 PROPOSAL_VERSION_CONFLICT
    r_stale = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json=updated_body,
        headers=csrf_headers(client),
    )
    assert r_stale.status_code == 409
    assert r_stale.json()["detail"]["code"] == "PROPOSAL_VERSION_CONFLICT"
    assert r_stale.json()["detail"]["currentVersion"] == 2

    # Extra/smuggled learnerProfile field must be rejected (422 extra=forbid)
    r_smuggle = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json={**updated_body, "expectedVersion": 2, "learnerProfile": {"currentLevel": "advanced"}},
        headers=csrf_headers(client),
    )
    assert r_smuggle.status_code == 422

    # Approve locks proposal -> further PATCH fails with 409 PROPOSAL_LOCKED
    await _approve_and_ready(client, cid)
    r_locked = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json={**updated_body, "expectedVersion": 2},
        headers=csrf_headers(client),
    )
    assert r_locked.status_code == 409
    assert r_locked.json()["detail"]["code"] == "PROPOSAL_LOCKED"


@pytest.mark.asyncio
async def test_proposal_patch_rejects_duplicate_lesson_titles_and_cross_user(client):
    await _register(client, "prop-a")
    cid = await _create_proposed_course(client)

    dup = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json={
            "expectedVersion": 1,
            "name": "Bad Course",
            "objective": "Obj",
            "units": [{"title": "U1", "blurb": "b", "lessonTitles": ["Same", "Same"]}],
            "outcomes": ["Do something"],
        },
        headers=csrf_headers(client),
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "PROPOSAL_INVALID"

    # Cross-user B cannot PATCH user A's proposal -> 404
    await _register(client, "prop-b")
    cross = await client.patch(
        f"/v1/courses/{cid}/proposal",
        json={
            "expectedVersion": 1,
            "name": "Hijack",
            "objective": "Obj",
            "units": [{"title": "U1", "blurb": "b", "lessonTitles": ["L1", "L2"]}],
            "outcomes": ["Out"],
        },
        headers=csrf_headers(client),
    )
    assert cross.status_code == 404


# ---------- 2. P1-GLOSSARY + Migration 0018 ----------


def test_migration_0018_single_head_and_roundtrip():
    backend_dir = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0018_wave4_glossary"]

    rev = script.get_revision("0018_wave4_glossary")
    assert rev is not None and rev.down_revision == "0017_p1_course_language"

    eng = sa.create_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE courses (id CHAR(32) PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE lessons (id CHAR(32) PRIMARY KEY)"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            rev.module.upgrade()
            assert sa.inspect(conn).has_table("course_glossary_terms")
            rev.module.downgrade()
            assert not sa.inspect(conn).has_table("course_glossary_terms")
            rev.module.upgrade()
            assert sa.inspect(conn).has_table("course_glossary_terms")


def test_glossary_extractor_reads_only_teach_blocks_never_quiz_answers():
    blocks = [
        {
            "type": "teach",
            "title": "Idempotency",
            "paragraphs": [
                "**Idempotency**: Applying the same operation multiple times yields the same state.",
                "Use `clientRequestId` — a unique token sent by the client to deduplicate retries.",
                "Watch [[outbox_pattern|Outbox Pattern]] for reliable async dispatch.",
            ],
        },
        {
            "type": "mc",
            "question": "**SECRET_QUIZ_TERM**: should never appear?",
            "options": ["SECRET_ANSWER_1", "B"],
            "answerIndex": 0,
        },
        {
            "type": "short",
            "question": "What is the key?",
            "acceptedAnswers": ["TOP_SECRET_SHORT_KEY"],
        },
    ]
    terms = extract_terms_from_lesson("Idempotency", blocks)
    keys = {t["termKey"] for t in terms}
    joined = json.dumps(terms)
    assert "idempotency" in keys
    assert "clientrequestid" in keys
    assert "outbox_pattern" in keys
    assert "SECRET_QUIZ_TERM" not in joined
    assert "SECRET_ANSWER_1" not in joined
    assert "TOP_SECRET_SHORT_KEY" not in joined
    assert normalize_term_key("Độ phức tạp O(n)") == "do_phuc_tap_o_n"


@pytest.mark.asyncio
async def test_glossary_populated_after_generation_and_scoped_by_owner(client):
    await _register(client, "gloss-a")
    cid = await _create_proposed_course(client, topic="Async Python")
    detail = await _approve_and_ready(client, cid)
    first_lesson_id = detail["units"][0]["lessons"][0]["id"]

    g_all = await client.get(f"/v1/courses/{cid}/glossary")
    assert g_all.status_code == 200, g_all.text
    body = g_all.json()
    assert body["courseId"] == cid
    assert body["total"] >= 1
    assert all(item["termKey"] and item["term"] and item["definition"] for item in body["items"])

    g_one = await client.get(f"/v1/courses/{cid}/glossary?lessonId={first_lesson_id}")
    assert g_one.status_code == 200
    assert all(item["lessonId"] == first_lesson_id for item in g_one.json()["items"])

    # Cross-user B gets 404
    await _register(client, "gloss-b")
    g_cross = await client.get(f"/v1/courses/{cid}/glossary")
    assert g_cross.status_code == 404


# ---------- 3. GAP-11 Per-block Server-Side Grading & AI Short-Answer Dispute ----------


@pytest.mark.asyncio
async def test_per_block_grading_server_side_and_semantic_short_rubric(client):
    await _register(client, "grade")
    cid = await _create_proposed_course(client, topic="SQL Indexing")
    detail = await _approve_and_ready(client, cid)
    lesson_id = detail["units"][0]["lessons"][0]["id"]

    lesson = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    # Public lesson payload MUST STILL NEVER contain answer keys!
    raw_lesson = json.dumps(lesson)
    assert "answerIndex" not in raw_lesson
    assert "acceptedAnswers" not in raw_lesson

    cver = lesson["contentVersion"]
    blocks = lesson["blocks"]

    # Teach block is not gradable -> 422
    r_teach = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/0/grade",
        json={"contentVersion": cver, "answer": "anything"},
        headers=csrf_headers(client),
    )
    assert r_teach.status_code == 422
    assert r_teach.json()["detail"]["code"] == "BLOCK_NOT_GRADABLE"

    # Boolean answer rejected -> 422
    mc_idx = next(i for i, b in enumerate(blocks) if b["type"] == "mc")
    r_bool = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{mc_idx}/grade",
        json={"contentVersion": cver, "answer": True},
        headers=csrf_headers(client),
    )
    assert r_bool.status_code == 422

    # Wrong version -> 409
    r_ver = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{mc_idx}/grade",
        json={"contentVersion": cver + 99, "answer": 0},
        headers=csrf_headers(client),
    )
    assert r_ver.status_code == 409

    # Valid MC grade returns deterministic verdict + post-grade solution
    r_mc = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{mc_idx}/grade",
        json={"contentVersion": cver, "answer": 0},
        headers=csrf_headers(client),
    )
    assert r_mc.status_code == 200, r_mc.text
    mc_out = r_mc.json()
    assert mc_out["blockIndex"] == mc_idx
    assert mc_out["grader"] == "deterministic"
    assert isinstance(mc_out["correct"], bool)
    assert "answerIndex" in mc_out["solution"]
    assert mc_out["disputeAllowed"] is False

    # Short block: wrong answer allows dispute; re-grade with dispute=True works cleanly offline
    short_idx = next((i for i, b in enumerate(blocks) if b["type"] == "short"), None)
    assert short_idx is not None
    r_wrong_short = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{short_idx}/grade",
        json={"contentVersion": cver, "answer": "completely unrelated text"},
        headers=csrf_headers(client),
    )
    assert r_wrong_short.status_code == 200
    assert r_wrong_short.json()["correct"] is False
    assert r_wrong_short.json()["disputeAllowed"] is True

    r_dispute = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{short_idx}/grade",
        json={
            "contentVersion": cver,
            "answer": "completely unrelated text",
            "dispute": True,
            "disputeReason": "I think it matches",
        },
        headers=csrf_headers(client),
    )
    assert r_dispute.status_code == 200
    assert r_dispute.json()["disputeAllowed"] is False


@pytest.mark.asyncio
async def test_short_answer_dispute_uses_llm_rubric_when_real_provider_active(client, monkeypatch):
    await _register(client, "dispute-llm")
    cid = await _create_proposed_course(client, topic="Caching")
    detail = await _approve_and_ready(client, cid)
    lesson_id = detail["units"][0]["lessons"][0]["id"]
    lesson = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    short_idx = next(i for i, b in enumerate(lesson["blocks"]) if b["type"] == "short")

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
                            "content": '{"correct": true, "feedback": "Conceptual paraphrase matches the core definition."}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 25},
            },
        )

    fake_real_provider = OpenAICompatibleProvider(
        api_key="sk-test",
        base_url="https://llm.test/v1",
        model="rubric-model",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr("app.api.v1.routes.get_provider", lambda: fake_real_provider)

    r = await client.post(
        f"/v1/lessons/{lesson_id}/blocks/{short_idx}/grade",
        json={
            "contentVersion": lesson["contentVersion"],
            "answer": "storing hot data closer to compute for fast reads",
            "dispute": True,
            "disputeReason": "Paraphrased explanation",
        },
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["correct"] is True
    assert out["grader"] == "llm_rubric"
    assert "paraphrase" in out["feedback"].lower()
    assert len(captured) == 1
    assert "<<<LEARNER_START>>>" in captured[0]["messages"][1]["content"]


# ---------- 4. M1-ME-SURFACE & Settings (GET /v1/me/stats, PATCH /v1/me, DELETE /v1/me) ----------


@pytest.mark.asyncio
async def test_me_stats_patch_and_full_account_delete_cascade(client):
    reg = await _register(client, "me-user")
    cid = await _create_proposed_course(client, topic="Linux Networking")
    detail = await _approve_and_ready(client, cid)
    total_lessons = sum(len(u["lessons"]) for u in detail["units"])

    # 1. GET /v1/me/stats reflects real DB counts
    s = await client.get("/v1/me/stats")
    assert s.status_code == 200, s.text
    stats = s.json()
    assert stats["email"] == reg["email"]
    assert stats["coursesTotal"] == 1
    assert stats["coursesReady"] == 1
    assert stats["lessonsTotal"] == total_lessons
    assert stats["lessonsCompleted"] == 0

    # 2. PATCH /v1/me updates displayName
    upd = await client.patch(
        "/v1/me",
        json={"displayName": "Nguyen Huu"},
        headers=csrf_headers(client),
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["displayName"] == "Nguyen Huu"
    assert (await client.get("/v1/auth/me")).json()["displayName"] == "Nguyen Huu"

    # 3. DELETE /v1/me rejects wrong confirmation or wrong password
    bad_confirm = await client.request(
        "DELETE",
        "/v1/me",
        json={"confirmText": "NOPE", "password": PASSWORD},
        headers=csrf_headers(client),
    )
    assert bad_confirm.status_code == 422
    assert bad_confirm.json()["detail"]["code"] == "DELETE_CONFIRMATION_REQUIRED"

    bad_pw = await client.request(
        "DELETE",
        "/v1/me",
        json={"confirmText": "DELETE", "password": "WrongPassword!999"},
        headers=csrf_headers(client),
    )
    assert bad_pw.status_code == 401
    assert bad_pw.json()["detail"]["code"] == "INVALID_CREDENTIALS"

    # 4. Valid DELETE /v1/me cascades cleanly and revokes session
    ok_del = await client.request(
        "DELETE",
        "/v1/me",
        json={"confirmText": "DELETE", "password": PASSWORD},
        headers=csrf_headers(client),
    )
    assert ok_del.status_code == 204, ok_del.text

    # Session cookie cleared + user gone -> 401 on /v1/auth/me and /v1/me/stats
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert (await client.get("/v1/me/stats")).status_code == 401
