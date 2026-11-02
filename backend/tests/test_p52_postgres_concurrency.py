"""P5.2 PostgreSQL concurrency — chỉ chạy khi có POSTGRES_TEST_URL.

Kiểm chứng thứ SQLite không mô phỏng đúng: ghi exposure đồng thời cho cùng
(user, course, context, arm) phải tạo **đúng 1 row**, và SAVEPOINT phải giữ cho
mọi task không ném exception.
"""

import asyncio
import os
import uuid

import pytest

POSTGRES_URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="POSTGRES_TEST_URL chưa đặt — bỏ qua race test PostgreSQL"
)


@pytest.fixture
def sessionmaker_pg():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(POSTGRES_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed(sessionmaker):
    from app.models import Course, Lesson, Unit, User

    suffix = uuid.uuid4().hex[:10]
    async with sessionmaker() as db:
        user = User(external_id=f"p52race-{suffix}", email=f"p52race-{suffix}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(
            user_id=user.id,
            topic="Race",
            status="ready",
            client_course_id=f"c-{uuid.uuid4()}",
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
            title="L",
            content=[],
            content_version=1,
            status="ready",
        )
        db.add(lesson)
        await db.commit()
        return user.id, course.id, lesson.id


def _path(lesson_id) -> dict:
    return {
        "nextLesson": {
            "lessonId": f"lsn_{lesson_id}",
            "title": "L",
            "reason": {"code": "NEXT_IN_SEQUENCE"},
        },
        "reviewLessonId": None,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }


async def test_concurrent_exposure_single_row(sessionmaker_pg):
    from sqlalchemy import func, select

    from app.models import Course, RecommendationEvent
    from app.services import recommendation_log_service as svc

    user_id, course_id, lesson_id = await _seed(sessionmaker_pg)
    path = _path(lesson_id)

    async def one() -> dict:
        async with sessionmaker_pg() as db:
            course = (
                await db.execute(select(Course).where(Course.id == course_id))
            ).scalar_one()
            result = await svc.record_exposure(
                db,
                user_id=user_id,
                course=course,
                path=path,
                lesson_content_version=1,
            )
            await db.commit()
            return result

    results = await asyncio.gather(*[one() for _ in range(6)], return_exceptions=True)
    assert not [r for r in results if isinstance(r, Exception)], results

    async with sessionmaker_pg() as db:
        total = (
            await db.execute(
                select(func.count()).select_from(RecommendationEvent).where(
                    RecommendationEvent.course_id == course_id
                )
            )
        ).scalar_one()
    assert total == 1
    assert sum(1 for r in results if r["recorded"] and not r["duplicate"]) == 1
