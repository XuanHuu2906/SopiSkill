"""P1.3 — Frontend-facing backend contract: course list scoping, pagination, resume.

UI-level behaviour (cache isolation, route guard) được test ở `test_frontend_contract.py`
qua API + ở build. File này tập trung vào API mà dashboard phụ thuộc.
"""

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.asyncio

PASSWORD = "Passw0rd!123"


def csrf_headers(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def register(client) -> str:
    email = f"p13-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def new_course(client, topic: str, answer: bool = False):
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
            json={"position": i, "answer": f"a{i}"},
            headers=csrf_headers(client),
        )
        assert ra.status_code == 200, ra.text
    if answer:
        ra = await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))
        assert ra.status_code == 202, ra.text
        for _ in range(200):
            await asyncio.sleep(0.05)
            rg = await client.get(f"/v1/courses/{course_id}/generation")
            if rg.json()["status"] in ("ready", "failed"):
                break
        assert rg.json()["status"] == "ready"
    return course_id


async def test_course_list_is_user_scoped(client):
    await register(client)
    mine = await new_course(client, "Course của tôi")

    # User B không được thấy course của A.
    await register(client)
    r = await client.get("/v1/courses")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0

    theirs = await new_course(client, "Course của B")
    body = (await client.get("/v1/courses")).json()
    ids = [i["id"] for i in body["items"]]
    assert ids == [theirs]
    assert mine not in ids


async def test_course_list_pagination_and_ordering(client):
    await register(client)
    created = []
    for i in range(3):
        created.append(await new_course(client, f"Topic {i}"))

    page1 = (await client.get("/v1/courses?limit=2&offset=0")).json()
    page2 = (await client.get("/v1/courses?limit=2&offset=2")).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert page1["hasMore"] is True
    assert len(page2["items"]) == 1
    assert page2["hasMore"] is False

    seen = {i["id"] for i in page1["items"]} | {i["id"] for i in page2["items"]}
    assert seen == set(created)


async def test_course_list_rejects_out_of_range_params(client):
    await register(client)
    assert (await client.get("/v1/courses?limit=0")).status_code == 422
    assert (await client.get("/v1/courses?limit=51")).status_code == 422
    assert (await client.get("/v1/courses?offset=-1")).status_code == 422


async def test_resume_points_at_first_uncompleted_lesson(client):
    await register(client)
    course_id = await new_course(client, "Resume", answer=True)

    item = (await client.get("/v1/courses")).json()["items"][0]
    assert item["progress"] == {"completed": 0, "total": 4, "percent": 0}
    assert item["resumeLessonId"] and item["resumeLessonId"].startswith("lsn_")
    assert item["resumeLessonTitle"]
    assert item["lastCompletedLessonTitle"] is None

    # Hoàn thành bài đầu tiên (dùng private content như test P1.1).
    from tests.support import correct_answers

    done_lesson_id = item["resumeLessonId"]
    version, answers = await correct_answers(done_lesson_id)
    r = await client.post(
        f"/v1/lessons/{done_lesson_id}/attempts",
        json={"clientAttemptId": uuid.uuid4().hex[:16], "contentVersion": version, "answers": answers},
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text

    item = (await client.get("/v1/courses")).json()["items"][0]
    assert item["progress"]["completed"] == 1
    assert item["progress"]["percent"] == 25
    # Resume trỏ sang bài khác bài vừa hoàn thành.
    assert item["resumeLessonId"] != done_lesson_id
    assert item["lastCompletedLessonTitle"]


async def test_course_list_requires_auth(client):
    assert (await client.get("/v1/courses")).status_code == 401


async def test_course_list_not_affected_by_client_supplied_user_id(client):
    """Không có tham số userId nào được chấp nhận — không thể đọc list người khác."""
    await register(client)
    other = await new_course(client, "Private")
    r = await client.get(f"/v1/courses?userId={uuid.uuid4()}")
    assert r.status_code == 200
    assert other in [i["id"] for i in r.json()["items"]]
