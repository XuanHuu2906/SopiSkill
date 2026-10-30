"""Integration tests — chạy app thật qua ASGI transport, luồng E2E + case lỗi."""

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.asyncio

HEADERS = {"X-User-Id": ""}


def user_headers() -> dict:
    return {"X-User-Id": f"test-user-{uuid.uuid4().hex[:8]}"}


async def create_course_flow(client, topic="Python cho người mới"):
    h = user_headers()
    r = await client.post(
        "/v1/courses",
        json={"topic": topic, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=h,
    )
    assert r.status_code == 201, r.text
    course_id = r.json()["id"]
    # trả lời đủ 5 câu
    for i in range(5):
        ra = await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"câu trả lời {i}"},
            headers=h,
        )
        assert ra.status_code == 200, ra.text
    return h, course_id


async def test_full_course_generation_flow(client):
    h, course_id = await create_course_flow(client)

    # Proposal hợp lệ
    r = await client.get(f"/v1/courses/{course_id}/proposal", headers=h)
    assert r.status_code == 200
    payload = r.json()["payload"]
    assert payload["name"] and len(payload["units"]) >= 2

    # Approve → job queued/running → poll tới ready
    r = await client.post(f"/v1/courses/{course_id}/approve", headers=h)
    assert r.status_code == 202, r.text

    status = None
    for _ in range(100):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation", headers=h)
        assert rg.status_code == 200
        status = rg.json()["status"]
        if status in ("ready", "failed"):
            break
    assert status == "ready", f"generation chưa ready: {status}"

    # Course detail có ≥2 lessons
    rc = await client.get(f"/v1/courses/{course_id}", headers=h)
    assert rc.status_code == 200
    lessons = [l for u in rc.json()["units"] for l in u["lessons"]]
    assert len(lessons) >= 2
    return h, course_id, lessons


async def test_quiz_attempt_and_persistence(client):
    h, course_id, lessons = await test_full_course_generation_flow(client)
    lesson_id = lessons[0]["id"]

    rl = await client.get(f"/v1/lessons/{lesson_id}", headers=h)
    assert rl.status_code == 200
    lesson = rl.json()
    assert lesson["contentVersion"] >= 1

    # Trả lời đúng hết: mc chọn đúng index, blank... dùng knowledge về mock
    blocks = lesson["blocks"]
    answers = []
    for idx, b in enumerate(blocks):
        t = b["type"]
        if t == "mc":
            answers.append({"index": idx, "answer": b["answerIndex"]})
        elif t == "blank":
            answers.append({"index": idx, "answer": b["answer"]})
        elif t == "order":
            answers.append({"index": idx, "answer": list(range(len(b["items"])))})
        elif t == "match":
            answers.append({"index": idx, "answer": {p[0]: p[1] for p in b["pairs"]}})
        elif t == "short":
            answers.append({"index": idx, "answer": b["acceptedAnswers"][0]})
        else:
            answers.append({"index": idx, "answer": None})

    client_attempt_id = uuid.uuid4().hex[:16]
    ra = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": client_attempt_id,
            "contentVersion": lesson["contentVersion"],
            "durationMs": 30000,
            "answers": answers,
        },
        headers=h,
    )
    assert ra.status_code == 201, ra.text
    body = ra.json()
    assert body["duplicate"] is False
    assert body["score"]["correct"] == body["score"]["total"]
    assert body["score"]["total"] > 0

    # Idempotency: nộp lại cùng clientAttemptId → duplicate=True, không cộng điểm lần 2
    ra2 = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": client_attempt_id,
            "contentVersion": lesson["contentVersion"],
            "durationMs": 30000,
            "answers": answers,
        },
        headers=h,
    )
    assert ra2.status_code == 201
    assert ra2.json()["duplicate"] is True
    assert ra2.json()["score"] == body["score"]

    # Nộp sai → điểm thấp
    wrong = [
        {"index": idx, "answer": 999 if b["type"] == "mc" else "zzz-sai"}
        for idx, b in enumerate(blocks)
        if b["type"] != "teach"
    ]
    ra3 = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        json={
            "clientAttemptId": uuid.uuid4().hex[:16],
            "contentVersion": lesson["contentVersion"],
            "answers": wrong,
        },
        headers=h,
    )
    assert ra3.status_code == 201
    assert ra3.json()["score"]["correct"] < ra3.json()["score"]["total"]


async def test_duplicate_course_creation_idempotent(client):
    h = user_headers()
    body = {"topic": "Dup topic", "clientCourseId": "dup-client-id-123"}
    r1 = await client.post("/v1/courses", json=body, headers=h)
    r2 = await client.post("/v1/courses", json=body, headers=h)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]  # không tạo trùng


async def test_course_not_owned_returns_404(client):
    h1, course_id = await create_course_flow(client, topic="Course của user 1")
    # sinh lessons để test cả lesson ownership
    await client.post(f"/v1/courses/{course_id}/approve", headers=h1)
    for _ in range(100):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation", headers=h1)
        if rg.json()["status"] in ("ready", "failed"):
            break

    h2 = user_headers()
    r = await client.get(f"/v1/courses/{course_id}", headers=h2)
    assert r.status_code == 404
    r2 = await client.get(f"/v1/courses/{course_id}/generation", headers=h2)
    assert r2.status_code == 404
    # lesson của user 1 cũng không truy cập được từ user 2
    rc = await client.get(f"/v1/courses/{course_id}", headers=h1)
    lesson_id = rc.json()["units"][0]["lessons"][0]["id"]
    r3 = await client.get(f"/v1/lessons/{lesson_id}", headers=h2)
    assert r3.status_code == 404


async def test_invalid_course_id(client):
    r = await client.get("/v1/courses/not-a-uuid", headers=user_headers())
    assert r.status_code == 404


async def test_interview_answer_out_of_range(client):
    h, course_id = await create_course_flow(client)
    r = await client.post(
        f"/v1/courses/{course_id}/interview/answer",
        json={"position": 9, "answer": "x"},
        headers=h,
    )
    assert r.status_code == 422  # pydantic ge=0 le=4


async def test_approve_without_proposal_conflict(client):
    h = user_headers()
    r = await client.post(
        "/v1/courses",
        json={"topic": "Chưa phỏng vấn", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=h,
    )
    course_id = r.json()["id"]
    r2 = await client.post(f"/v1/courses/{course_id}/approve", headers=h)
    assert r2.status_code == 409


async def test_topic_too_long_rejected(client):
    r = await client.post(
        "/v1/courses",
        json={"topic": "x" * 201, "clientCourseId": uuid.uuid4().hex[:16]},
        headers=user_headers(),
    )
    assert r.status_code == 422
