"""P1.1 — Quiz integrity, progress, XP idempotency, content versioning.

Chạy trên SQLite in-memory (logic + contract). Race thật trên PostgreSQL nằm ở
`test_p11_postgres_concurrency.py` (bỏ qua nếu không có POSTGRES_TEST_URL).
"""

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Lesson, LessonAttempt, XpEvent
from tests.support import correct_answers, load_private_blocks, wrong_answers

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"
QUIZ_TYPES = {"mc", "blank", "order", "match", "short"}


def csrf_headers(client) -> dict:
    token = client.cookies.get("csrf_token") or ""
    return {"X-CSRF-Token": token}


async def register_user(client) -> str:
    email = f"p11-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def create_course_with_lessons(client, topic="P1.1 quiz integrity"):
    await register_user(client)
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["id"]
    for i in range(5):
        ra = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=csrf_headers(client),
        )
        assert ra.status_code == 200, ra.text

    ra = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    assert ra.status_code == 202, ra.text
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready", rg.text

    rc = await client.get(f"/v1/courses/{course_id}")
    assert rc.status_code == 200
    lessons = [l for u in rc.json()["units"] for l in u["lessons"]]
    return course_id, lessons


async def submit(client, lesson_id: str, answers: list[dict], version: int, cid: str | None = None):
    return await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": cid or uuid.uuid4().hex[:16],
            "contentVersion": version,
            "answers": answers,
        },
        headers=csrf_headers(client),
    )


async def test_public_lesson_hides_answer_key_for_all_quiz_types(client):
    _, lessons = await create_course_with_lessons(client)
    rl = await client.get(f"/v1/lessons/{lessons[0]['id']}")
    assert rl.status_code == 200
    blocks = rl.json()["blocks"]

    assert {b["type"] for b in blocks} & QUIZ_TYPES == QUIZ_TYPES, "mock phải có đủ 5 loại"
    for block in blocks:
        assert set(block.keys()).isdisjoint({"answerIndex", "answer", "acceptedAnswers", "pairs"})

    order = next(b for b in blocks if b["type"] == "order")
    match = next(b for b in blocks if b["type"] == "match")
    # order: items là object {id,text} đã shuffle; match: lefts/rights tách rời.
    assert all(set(item) == {"id", "text"} for item in order["items"])
    assert all(set(item) == {"id", "text"} for item in match["lefts"])
    assert all(set(item) == {"id", "text"} for item in match["rights"])


async def test_order_and_match_need_public_ids_so_guessing_fails(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    _, version, blocks = await load_private_blocks(lesson_id)

    # Đoán theo thứ tự mảng gốc / theo text đều sai.
    guess: list[dict] = []
    for idx, block in enumerate(blocks):
        if block.get("type") == "teach":
            continue
        if block["type"] == "order":
            guess.append({"index": idx, "answer": list(range(len(block["items"])))})
        elif block["type"] == "match":
            guess.append(
                {"index": idx, "answer": {p[0]: p[1] for p in block["pairs"]}}
            )
        else:
            guess.append({"index": idx, "answer": "zzz"})

    r = await submit(client, lesson_id, guess, version)
    assert r.status_code == 201, r.text
    assert r.json()["score"]["correct"] == 0


async def test_client_cannot_forge_correct_flag_or_score(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    _, version, blocks = await load_private_blocks(lesson_id)

    # Field "chỉ điểm" do client tự gửi bị từ chối ở schema (extra=forbid).
    forged = []
    for idx, block in enumerate(blocks):
        if block.get("type") == "teach":
            continue
        forged.append(
            {
                "index": idx,
                "answer": "sai",
                "correct": True,
                "score": 999,
                "xpEarned": 9999,
            }
        )
    r = await submit(client, lesson_id, forged, version)
    assert r.status_code == 422, r.text

    # Không có field lạ: điểm hoàn toàn do server chấm.
    honest = [{"index": a["index"], "answer": "sai"} for a in forged]
    r = await submit(client, lesson_id, honest, version)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["score"]["correct"] == 0
    assert body["score"]["total"] > 0
    assert body["rewards"]["xpEarned"] == 0

    # bool cũng bị từ chối (true không được coerce thành 1 = đáp án đúng).
    r = await submit(client, lesson_id, [{"index": 1, "answer": True}], version)
    assert r.status_code == 422, r.text


async def test_duplicate_and_out_of_bounds_answer_index_rejected(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    _, version, _ = await load_private_blocks(lesson_id)

    dup = await submit(
        client,
        lesson_id,
        [{"index": 1, "answer": "a"}, {"index": 1, "answer": "b"}],
        version,
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "DUPLICATE_ANSWER_INDEX"

    oob = await submit(client, lesson_id, [{"index": 999, "answer": "a"}], version)
    assert oob.status_code == 422
    assert oob.json()["detail"]["code"] == "ANSWER_INDEX_OUT_OF_BOUNDS"


async def test_progress_counts_attempts_not_lesson_status(client):
    course_id, lessons = await create_course_with_lessons(client)
    before = (await client.get(f"/v1/courses/{course_id}")).json()
    assert before["progress"] == {"completed": 0, "total": len(lessons), "percent": 0}
    assert all(l["completed"] is False for u in before["units"] for l in u["lessons"])

    # Nộp sai toàn bộ → không tính completed dù lesson.status == ready.
    lesson_id = lessons[0]["id"]
    _, version, blocks = await load_private_blocks(lesson_id)
    r = await submit(client, lesson_id, wrong_answers(blocks), version)
    assert r.status_code == 201
    mid = (await client.get(f"/v1/courses/{course_id}")).json()
    assert mid["progress"]["completed"] == 0

    # Nộp đúng → completed tăng và bền qua reload (GET mới, session mới).
    _, answers = await correct_answers(lesson_id)
    r = await submit(client, lesson_id, answers, version)
    assert r.status_code == 201
    after = (await client.get(f"/v1/courses/{course_id}")).json()
    assert after["progress"]["completed"] == 1
    assert after["progress"]["total"] == len(lessons)
    assert after["progress"]["percent"] == round(1 / len(lessons) * 100)
    done = [l for u in after["units"] for l in u["lessons"] if l["completed"]]
    assert [l["id"] for l in done] == [lesson_id]


async def test_progress_persists_after_relogin(client):
    course_id, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    version, answers = await correct_answers(lesson_id)
    assert (await submit(client, lesson_id, answers, version)).status_code == 201

    email = (await client.get("/v1/auth/me")).json()["email"]
    await client.post("/v1/auth/logout", headers=csrf_headers(client))
    r = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text

    after = (await client.get(f"/v1/courses/{course_id}")).json()
    assert after["progress"]["completed"] == 1


async def test_other_user_cannot_read_lesson_or_progress(client):
    course_id, lessons = await create_course_with_lessons(client)
    await register_user(client)  # chuyển sang user B
    assert (await client.get(f"/v1/courses/{course_id}")).status_code == 404
    assert (await client.get(f"/v1/lessons/{lessons[0]['id']}")).status_code == 404
    r = await submit(client, lessons[0]["id"], [{"index": 1, "answer": "x"}], 1)
    assert r.status_code == 404


async def test_xp_is_not_farmable_with_new_client_attempt_ids(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    version, answers = await correct_answers(lesson_id)

    first = (await submit(client, lesson_id, answers, version)).json()
    assert first["rewards"]["xpEarned"] > 0
    xp_after_first = first["rewards"]["xp"]

    for _ in range(5):
        r = (await submit(client, lesson_id, answers, version)).json()
        assert r["rewards"]["xpEarned"] == 0
        assert r["rewards"]["xp"] == xp_after_first

    # Tổng XP cộng cho (user, lesson, version) đúng bằng phần thưởng tối đa 1 lần.
    xp_events = await _xp_events_for(lesson_id)
    assert sum(e.amount for e in xp_events) == xp_after_first


async def test_same_client_attempt_id_returns_same_attempt_row(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    version, answers = await correct_answers(lesson_id)
    cid = uuid.uuid4().hex[:16]

    first = (await submit(client, lesson_id, answers, version, cid)).json()
    second = (await submit(client, lesson_id, answers, version, cid)).json()
    assert first["attemptId"] == second["attemptId"]
    assert second["duplicate"] is True

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(LessonAttempt).where(LessonAttempt.client_attempt_id == cid)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].xp_awarded == first["rewards"]["xpEarned"]


async def test_stale_content_version_rejected_409(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    _, answers = await correct_answers(lesson_id)
    r = await submit(client, lesson_id, answers, 999)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "CONTENT_VERSION_MISMATCH"


async def test_retry_preserves_attempts_and_only_bumps_version_on_change(client):
    course_id, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    version, answers = await correct_answers(lesson_id)
    attempt = (await submit(client, lesson_id, answers, version)).json()

    # Retry khi course ready + nội dung mock giống hệt → version KHÔNG đổi.
    r = await client.post(f"/v1/courses/{course_id}/retry", headers=csrf_headers(client))
    assert r.status_code == 202, r.text
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready"

    after = (await client.get(f"/v1/lessons/{lesson_id}")).json()
    assert after["contentVersion"] == version

    # Attempt cũ vẫn còn và progress vẫn tính.
    async with SessionLocal() as db:
        count = len(
            (
                await db.execute(
                    select(LessonAttempt).where(LessonAttempt.lesson_id == uuid.UUID(lesson_id.removeprefix("lsn_")))
                )
            ).scalars().all()
        )
    assert count >= 1
    assert (await client.get(f"/v1/courses/{course_id}")).json()["progress"]["completed"] == 1
    assert attempt["attemptId"]

    # Nội dung đổi thật (mô phỏng regenerate khác đi) → version tăng khi retry.
    async with SessionLocal() as db:
        lesson = (
            await db.execute(select(Lesson).where(Lesson.id == uuid.UUID(lesson_id.removeprefix("lsn_"))))
        ).scalar_one()
        lesson.content = [*lesson.content, {"type": "teach", "title": "extra", "paragraphs": ["x"]}]
        await db.commit()

    r = await client.post(f"/v1/courses/{course_id}/retry", headers=csrf_headers(client))
    assert r.status_code == 202, r.text
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready"
    bumped = (await client.get(f"/v1/lessons/{lesson_id}")).json()["contentVersion"]
    assert bumped == version + 1

    # Version mới → attempt cũ không còn tính completed cho tới khi nộp lại.
    assert (await client.get(f"/v1/courses/{course_id}")).json()["progress"]["completed"] == 0
    assert (await submit(client, lesson_id, answers, version)).status_code == 409


async def test_proposal_approved_flag_reflects_state(client):
    await register_user(client)
    r = await client.post(
        "/v1/courses",
        json={"topic": "approval flag", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    course_id = r.json()["id"]
    for i in range(5):
        await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"a{i}"},
            headers=csrf_headers(client),
        )

    proposal = (await client.get(f"/v1/courses/{course_id}/proposal")).json()
    assert proposal["approved"] is False

    assert (
        await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
    ).status_code == 202

    proposal = (await client.get(f"/v1/courses/{course_id}/proposal")).json()
    assert proposal["approved"] is True

    # Đợi generation inline xong để task nền không chạy sang test kế tiếp
    # (P1.2 sẽ thay bằng claim dispatch đúng nghĩa).
    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    assert rg.json()["status"] == "ready"

    async with SessionLocal() as db:
        from app.models import CourseProposal

        row = (
            await db.execute(
                select(CourseProposal).where(
                    CourseProposal.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalar_one()
    assert row.approved_at is not None


async def test_xp_event_records_content_version(client):
    _, lessons = await create_course_with_lessons(client)
    lesson_id = lessons[0]["id"]
    version, answers = await correct_answers(lesson_id)
    await submit(client, lesson_id, answers, version)

    events = await _xp_events_for(lesson_id)
    assert events, "phải có xp_event"
    assert all(e.content_version == version for e in events)


async def _xp_events_for(lesson_id: str) -> list[XpEvent]:
    async with SessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(XpEvent).where(
                        XpEvent.lesson_id == uuid.UUID(lesson_id.removeprefix("lsn_"))
                    )
                )
            ).scalars().all()
        )
