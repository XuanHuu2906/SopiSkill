"""P5.2 API — flag gating, ownership, CSRF, validation, token, idempotency."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Course, Lesson, RecommendationEvent, Unit, User

PASSWORD = "Passw0rd!123"


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def _register(client) -> str:
    email = f"p52-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def _seed_course(email: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.external_id == email))
        ).scalars().first()
        if user is None:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalars().first()
        assert user is not None
        course = Course(
            user_id=user.id,
            topic="Khóa P52",
            status="ready",
            client_course_id=f"c-{uuid.uuid4().hex[:12]}",
        )
        db.add(course)
        await db.flush()
        unit = Unit(course_id=course.id, order_index=0, title="U", blurb="")
        db.add(unit)
        await db.flush()
        lesson = Lesson(
            unit_id=unit.id,
            course_id=course.id,
            order_index=0,
            title="Bài",
            content=[],
            content_version=1,
            status="ready",
        )
        db.add(lesson)
        await db.commit()
        return course.id, lesson.id


async def _course_and_token(client, email: str) -> tuple[str, str | None]:
    course_id, _lesson_id = await _seed_course(email)
    r = await client.get(f"/v1/courses/{course_id}/learning-path")
    assert r.status_code == 200, r.text
    return f"crs_{course_id}", r.json().get("recommendationToken")


@pytest.fixture
def p50_on(monkeypatch):
    """GET learning-path cần P50 (P5.0); bật riêng để test P52 TẮT vẫn gọi được."""
    monkeypatch.setattr(get_settings(), "p50_enabled", True)
    yield


@pytest.fixture
def p52_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "p52_exposure_enabled", True)
    monkeypatch.setattr(s, "p50_enabled", True)
    yield


async def test_post_requires_flag(client, p50_on):
    email = await _register(client)
    # Flag tắt: route trả 503 TRƯỚC khi chạm bảng (bảng có thể chưa migrate).
    course_id, _ = await _course_and_token(client, email)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": "x" * 16},
        headers=csrf(client),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "P52_NOT_ENABLED"


async def test_get_token_is_null_when_flag_off(client, p50_on):
    email = await _register(client)
    _course_id, token = await _course_and_token(client, email)
    assert token is None


async def test_get_token_present_when_flag_on(client, p52_on):
    email = await _register(client)
    _course_id, token = await _course_and_token(client, email)
    assert token and token.count(".") == 1


async def test_post_happy_path_then_duplicate(client, p52_on):
    email = await _register(client)
    course_id, token = await _course_and_token(client, email)
    assert token

    first = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["recorded"] is True
    assert body["duplicate"] is False
    assert body["exposureId"].startswith("rce_")

    second = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["exposureId"] == body["exposureId"]

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id
                    == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_post_rejects_extra_fields(client, p52_on):
    email = await _register(client)
    course_id, token = await _course_and_token(client, email)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token, "arm": "forged", "propensity": 0.5},
        headers=csrf(client),
    )
    assert r.status_code == 422


async def test_post_requires_csrf(client, p52_on):
    email = await _register(client)
    course_id, token = await _course_and_token(client, email)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
    )
    assert r.status_code == 403


async def test_post_cross_user_is_404(client, p52_on):
    email_a = await _register(client)
    course_id, token = await _course_and_token(client, email_a)
    await client.post("/v1/auth/logout", headers=csrf(client))
    await _register(client)  # user B
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert r.status_code == 404


async def test_post_rejects_forged_token(client, p52_on):
    email = await _register(client)
    course_id, _token = await _course_and_token(client, email)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": "Zm9yZ2Vk.c2ln"},
        headers=csrf(client),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recorded"] is False
    assert body["reason"] in {"TOKEN_INVALID", "CONTEXT_STALE"}

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.course_id
                    == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().all()
        assert rows == []


async def test_post_stale_token_after_version_change(client, p52_on):
    email = await _register(client)
    course_id, token = await _course_and_token(client, email)
    # Regenerate: tăng content_version ⇒ token mang version cũ phải bị từ chối.
    async with SessionLocal() as db:
        lesson = (
            await db.execute(
                select(Lesson).where(
                    Lesson.course_id == uuid.UUID(course_id.removeprefix("crs_"))
                )
            )
        ).scalars().first()
        lesson.content_version = 2
        await db.commit()

    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert r.status_code == 200
    assert r.json()["recorded"] is False
    assert r.json()["reason"] == "CONTEXT_STALE"
