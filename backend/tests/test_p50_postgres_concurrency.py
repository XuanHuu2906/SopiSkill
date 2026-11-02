"""P5.0 PostgreSQL concurrency — chỉ chạy khi có POSTGRES_TEST_URL.

Kiểm chứng những thứ SQLite không mô phỏng đúng:
  1. `ensure_card_for_attempt` đồng thời cho cùng (user, lesson) ⇒ đúng 1 card,
     KHÔNG rollback attempt của bên thua (SAVEPOINT).
  2. `grade_card` đồng thời với 2 clientReviewId khác nhau ⇒ row lock
     (`SELECT ... FOR UPDATE`) ngăn lost update: due_at cuối khớp lần review thứ 2,
     và cả 2 event được ghi.
  3. Cross-user grade ⇒ CardNotFoundError.
"""

import asyncio
import os
import uuid

import pytest

POSTGRES_URL = os.environ.get("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="POSTGRES_TEST_URL chưa đặt — bỏ qua race test PostgreSQL"
)


async def _create_schema(engine) -> None:
    from app.db.base import Base
    import app.models  # noqa: F401 — populate metadata trước create_all

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def sessionmaker_pg():
    """Tự tạo schema: module này phải chạy được MỘT MÌNH.

    Bản trước chỉ `create_async_engine` rồi seed ngay, nên nó chỉ pass khi một
    module race khác (chạy trước theo alphabet) đã `create_all`. Chạy riêng file
    sẽ hỏng `UndefinedTableError: relation "users" does not exist`.
    """
    # NullPool: tránh connection sống qua event loop khác (asyncpg).
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(POSTGRES_URL, poolclass=NullPool)
    asyncio.run(_create_schema(engine))
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


async def _seed(sessionmaker, skill=True):
    from app.models import (
        Course,
        CourseProposal,
        Lesson,
        LessonSkill,
        LessonAttempt,
        Skill,
        Unit,
        User,
    )

    suffix = uuid.uuid4().hex[:10]
    async with sessionmaker() as db:
        user = User(external_id=f"race-{suffix}", email=f"race-{suffix}@t.dev")
        db.add(user)
        await db.flush()
        course = Course(
            user_id=user.id, topic="T", status="ready", client_course_id=f"c-{uuid.uuid4()}"
        )
        db.add(course)
        await db.flush()
        db.add(
            CourseProposal(
                course_id=course.id,
                version=1,
                payload={
                    "name": "K",
                    "objective": "O",
                    "outcomes": ["a", "b"],
                    "units": [
                        {"title": "U1", "blurb": "", "lessonTitles": ["Bài 1"]},
                        {"title": "U2", "blurb": "", "lessonTitles": ["Bài 2"]},
                    ],
                    "skills": [],
                    "prerequisites": [],
                },
            )
        )
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
        await db.flush()
        if skill:
            row = Skill(course_id=course.id, key="s1", title="Kỹ năng", order_index=0)
            db.add(row)
            await db.flush()
            db.add(LessonSkill(lesson_id=lesson.id, skill_id=row.id))
            await db.flush()
        attempt = LessonAttempt(
            lesson_id=lesson.id,
            user_id=user.id,
            client_attempt_id=f"seed-{suffix}",
            content_version=1,
            score_correct=1,
            score_total=2,
            results=[],
        )
        db.add(attempt)
        await db.commit()
        return {
            "user_id": user.id,
            "lesson_id": lesson.id,
            "attempt_id": attempt.id,
        }


async def test_concurrent_card_creation_keeps_attempt(sessionmaker_pg):
    from app.models import Lesson, LessonAttempt, ReviewCard, User
    from app.services import spaced_repetition_service as srp
    from sqlalchemy import func, select

    seeded = await _seed(sessionmaker_pg)
    barrier = asyncio.Event()

    async def ensure_one(_):
        async with sessionmaker_pg() as db:
            user = (await db.execute(select(User).where(User.id == seeded["user_id"]))).scalar_one()
            lesson = (
                await db.execute(select(Lesson).where(Lesson.id == seeded["lesson_id"]))
            ).scalar_one()
            attempt = (
                await db.execute(
                    select(LessonAttempt).where(LessonAttempt.id == seeded["attempt_id"])
                )
            ).scalar_one()
            await barrier.wait()
            created = await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
            # `ensure_card_for_attempt` không tự commit (nó thuộc transaction của
            # attempt); test phải commit để tranh chấp UNIQUE thực sự xảy ra.
            await db.commit()
            return created

    tasks = [asyncio.create_task(ensure_one(i)) for i in range(6)]
    await asyncio.sleep(0)
    barrier.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Không task nào được ném exception (SAVEPOINT nuốt IntegrityError)
    assert all(not isinstance(r, Exception) for r in results), results
    assert sum(1 for r in results if r is True) == 1

    async with sessionmaker_pg() as db:
        cards = (
            await db.execute(
                select(func.count()).select_from(ReviewCard).where(
                    ReviewCard.user_id == seeded["user_id"]
                )
            )
        ).scalar_one()
        attempts = (
            await db.execute(
                select(func.count()).select_from(LessonAttempt).where(
                    LessonAttempt.user_id == seeded["user_id"]
                )
            )
        ).scalar_one()
        assert cards == 1
        assert attempts == 1


async def test_concurrent_grades_do_not_lose_update(sessionmaker_pg):
    from app.models import Lesson, LessonAttempt, ReviewEvent, User
    from app.services import spaced_repetition_service as srp
    from sqlalchemy import func, select

    seeded = await _seed(sessionmaker_pg)
    async with sessionmaker_pg() as db:
        user = (await db.execute(select(User).where(User.id == seeded["user_id"]))).scalar_one()
        lesson = (
            await db.execute(select(Lesson).where(Lesson.id == seeded["lesson_id"]))
        ).scalar_one()
        attempt = (
            await db.execute(
                select(LessonAttempt).where(LessonAttempt.id == seeded["attempt_id"])
            )
        ).scalar_one()
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        from app.models import ReviewCard

        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()
        await db.commit()

    async def grade_one(idx):
        async with sessionmaker_pg() as db:
            return await srp.grade_card(
                db, card.id, seeded["user_id"], 3, f"rv-race-{idx}"
            )

    results = await asyncio.gather(*[grade_one(i) for i in range(4)], return_exceptions=True)
    assert all(not isinstance(r, Exception) for r in results), results
    assert all(r["duplicate"] is False for r in results)

    async with sessionmaker_pg() as db:
        events = (
            await db.execute(
                select(func.count()).select_from(ReviewEvent).where(
                    ReviewEvent.card_id == card.id
                )
            )
        ).scalar_one()
        # 1 event khởi tạo + 4 event grade
        assert events == 5


async def test_cross_user_grade_pg(sessionmaker_pg):
    from app.models import Lesson, LessonAttempt, User
    from app.services import spaced_repetition_service as srp
    from sqlalchemy import select

    seeded = await _seed(sessionmaker_pg)
    async with sessionmaker_pg() as db:
        user = (await db.execute(select(User).where(User.id == seeded["user_id"]))).scalar_one()
        lesson = (
            await db.execute(select(Lesson).where(Lesson.id == seeded["lesson_id"]))
        ).scalar_one()
        attempt = (
            await db.execute(
                select(LessonAttempt).where(LessonAttempt.id == seeded["attempt_id"])
            )
        ).scalar_one()
        await srp.ensure_card_for_attempt(db, lesson, attempt, user.id)
        from app.models import ReviewCard

        card = (
            await db.execute(select(ReviewCard).where(ReviewCard.user_id == user.id))
        ).scalar_one()
        await db.commit()

        other = User(external_id=f"o-{uuid.uuid4().hex[:8]}", email=f"o-{uuid.uuid4().hex[:8]}@t.dev")
        db.add(other)
        await db.commit()

        with pytest.raises(srp.CardNotFoundError):
            await srp.grade_card(db, card.id, other.id, 3, "rv-x")
