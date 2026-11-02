"""P5.0 API — flag gating, ownership, CSRF, validation."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Course,
    Lesson,
    ReviewCard,
    User,
)
from app.services import spaced_repetition_service as srp

PASSWORD = "Passw0rd!123"


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def _register(client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"p50api-{suffix}@test.dev"
    resp = await client.post(
        "/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 201, resp.text
    return email


async def _seed_course_with_lesson(user_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.external_id == user_id))
        ).scalars().first()
        if user is None:
            user = (
                await db.execute(select(User).where(User.email == user_id))
            ).scalars().first()
        assert user is not None
        course = Course(
            user_id=user.id,
            topic="Khóa P50",
            status="ready",
            client_course_id=f"c-{uuid.uuid4().hex[:12]}",
        )
        db.add(course)
        await db.flush()
        from app.models import Unit

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


async def _seed_review_card(user_id: str, lesson_id: uuid.UUID) -> uuid.UUID:
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == user_id))
        ).scalars().first()
        assert user is not None
        row = ReviewCard(
            user_id=user.id,
            lesson_id=lesson_id,
            state=2,
            due_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            last_review_at=None,
            scheduler_version=srp.FSRS_SCHEDULER_VERSION,
        )
        db.add(row)
        await db.commit()
        return row.id


@pytest.fixture
def p50_on(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "p50_enabled", True)
    yield
    monkeypatch.setattr(settings, "p50_enabled", False)


@pytest.mark.asyncio
async def test_routes_return_503_when_disabled(client):
    await _register(client)
    resp = await client.get("/v1/courses/crs_00000000-0000-0000-0000-000000000000/mastery")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "P50_NOT_ENABLED"


@pytest.mark.asyncio
async def test_mastery_requires_ownership(client, p50_on):
    email_a = await _register(client)
    course_id, _lesson_id = await _seed_course_with_lesson(email_a)

    client.cookies.clear()
    await _register(client)
    resp = await client.get(f"/v1/courses/crs_{course_id}/mastery")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mastery_ok_for_owner(client, p50_on):
    email = await _register(client)
    course_id, _lesson_id = await _seed_course_with_lesson(email)
    resp = await client.get(f"/v1/courses/crs_{course_id}/mastery")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["coursePercent"] == 0.0
    assert body["reviewDueCount"] == 0


@pytest.mark.asyncio
async def test_learning_path_ok_for_owner(client, p50_on):
    email = await _register(client)
    course_id, lesson_id = await _seed_course_with_lesson(email)
    resp = await client.get(f"/v1/courses/crs_{course_id}/learning-path")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["nextLesson"]["lessonId"] == f"lsn_{lesson_id}"
    assert body["prerequisitesDag"]["nodes"] == []


@pytest.mark.asyncio
async def test_grade_requires_csrf(client, p50_on):
    email = await _register(client)
    _course_id, lesson_id = await _seed_course_with_lesson(email)
    card_id = await _seed_review_card(email, lesson_id)
    resp = await client.post(
        f"/v1/reviews/rvc_{card_id}/grade",
        json={"rating": 3, "clientReviewId": "rv-1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_grade_rejects_out_of_range_rating(client, p50_on):
    email = await _register(client)
    _course_id, lesson_id = await _seed_course_with_lesson(email)
    card_id = await _seed_review_card(email, lesson_id)
    resp = await client.post(
        f"/v1/reviews/rvc_{card_id}/grade",
        headers=csrf(client),
        json={"rating": 5, "clientReviewId": "rv-1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_grade_ok_and_idempotent(client, p50_on):
    email = await _register(client)
    _course_id, lesson_id = await _seed_course_with_lesson(email)
    card_id = await _seed_review_card(email, lesson_id)
    body = {"rating": 3, "clientReviewId": "rv-1"}
    url = f"/v1/reviews/rvc_{card_id}/grade"

    first = await client.post(url, headers=csrf(client), json=body)
    second = await client.post(url, headers=csrf(client), json=body)
    assert first.status_code == 200, first.text
    assert first.json()["duplicate"] is False
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    assert first.json()["card"]["dueAt"] == second.json()["card"]["dueAt"]


@pytest.mark.asyncio
async def test_grade_cross_user_is_404(client, p50_on):
    email_a = await _register(client)
    _course_id, lesson_id = await _seed_course_with_lesson(email_a)
    card_id = await _seed_review_card(email_a, lesson_id)

    client.cookies.clear()
    await _register(client)
    resp = await client.post(
        f"/v1/reviews/rvc_{card_id}/grade",
        headers=csrf(client),
        json={"rating": 3, "clientReviewId": "rv-x"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "REVIEW_CARD_NOT_FOUND"


@pytest.mark.asyncio
async def test_due_reviews_only_own(client, p50_on):
    email = await _register(client)
    course_id, lesson_id = await _seed_course_with_lesson(email)
    await _seed_review_card(email, lesson_id)

    resp = await client.get(f"/v1/reviews/due?courseId=crs_{course_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1

    client.cookies.clear()
    await _register(client)
    resp = await client.get("/v1/reviews/due")
    assert resp.json()["total"] == 0
