"""P5.2 readiness eval — metric SQL portable, verdict trung thực, không ghi DB."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from evals import p52_readiness as ready


async def _empty_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/p52.db")
    async with engine.begin() as conn:
        for ddl in (
            "CREATE TABLE users (id TEXT PRIMARY KEY)",
            "CREATE TABLE courses (id TEXT PRIMARY KEY, user_id TEXT)",
            "CREATE TABLE units (id TEXT PRIMARY KEY, course_id TEXT, order_index INTEGER)",
            "CREATE TABLE lessons (id TEXT PRIMARY KEY, unit_id TEXT, course_id TEXT, "
            "order_index INTEGER, content_version INTEGER, status TEXT)",
            "CREATE TABLE lesson_attempts (id TEXT PRIMARY KEY, lesson_id TEXT, user_id TEXT, "
            "client_attempt_id TEXT, content_version INTEGER, score_correct INTEGER, "
            "score_total INTEGER, created_at TEXT)",
        ):
            await conn.execute(text(ddl))
    return engine


async def test_empty_database_is_blocked_not_crash(tmp_path):
    engine = await _empty_engine(tmp_path)
    metrics = await ready.collect_metrics(engine)
    verdict = ready.decide(metrics, ready.DEFAULT_THRESHOLDS)
    assert metrics["attempts"] == 0
    assert verdict["dkt"]["verdict"] == "BLOCKED"
    assert verdict["bandit"]["verdict"] == "BLOCKED"
    assert verdict["bandit"]["opeSupported"] is False
    await engine.dispose()


async def test_metrics_count_users_and_courses(tmp_path):
    engine = await _empty_engine(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC).isoformat()
    async with engine.begin() as conn:
        await conn.execute(text("INSERT INTO users (id) VALUES ('u1')"))
        await conn.execute(text("INSERT INTO users (id) VALUES ('u2')"))
        await conn.execute(
            text("INSERT INTO courses (id,user_id) VALUES ('c1','u1')")
        )
        await conn.execute(
            text("INSERT INTO units (id,course_id,order_index) VALUES ('un1','c1',0)")
        )
        await conn.execute(
            text(
                "INSERT INTO lessons (id,unit_id,course_id,order_index,content_version,status) "
                "VALUES ('l1','un1','c1',0,1,'ready')"
            )
        )
        for i in range(6):
            user = "u1" if i < 4 else "u2"
            await conn.execute(
                text(
                    "INSERT INTO lesson_attempts (id,lesson_id,user_id,client_attempt_id,"
                    "content_version,score_correct,score_total,created_at) "
                    "VALUES (:i,'l1',:u,:cid,1,4,5,:ts)"
                ),
                {"i": f"a{i}", "u": user, "cid": f"c{i}", "ts": now},
            )
    metrics = await ready.collect_metrics(engine)
    assert metrics["attempts"] == 6
    assert metrics["usersWithAttempts"] == 2
    assert metrics["maxAttemptsPerUser"] == 4
    assert metrics["coursesWithGe2Users"] == 1
    assert metrics["exposureRows"] == 0
    await engine.dispose()


def test_propensity_spread_none_without_rows():
    metrics = {"propensityMin": None, "propensityMax": None}
    assert ready._propensity_spread(metrics) is None
    assert ready._propensity_spread({"propensityMin": 1.0, "propensityMax": 1.0}) == 0.0


def test_decide_bandit_requires_propensity_spread():
    metrics = {
        "usersGe10": 10_000,
        "sequencesGe5": 10_000,
        "coursesWithGe2Users": 10_000,
        "exposureRows": 10_000,
        "distinctPolicies": 5,
        "distinctArms": 5,
        "propensityMin": 1.0,
        "propensityMax": 1.0,
    }
    verdict = ready.decide(metrics, ready.DEFAULT_THRESHOLDS)
    assert verdict["dkt"]["verdict"] == "READY"
    # Đủ mọi thứ trừ propensity spread ⇒ bandit vẫn BLOCKED. Đây là điểm trung thực
    # quan trọng nhất của phase: không được báo READY khi chưa thể OPE.
    assert verdict["bandit"]["verdict"] == "BLOCKED"
    assert any("propensitySpread" in r for r in verdict["bandit"]["reasons"])


def test_bandit_ready_requires_all_criteria():
    metrics = {
        "usersGe10": 10_000,
        "sequencesGe5": 10_000,
        "coursesWithGe2Users": 10_000,
        "exposureRows": 10_000,
        "distinctPolicies": 5,
        "distinctArms": 5,
        "propensityMin": 0.5,
        "propensityMax": 1.0,
    }
    verdict = ready.decide(metrics, ready.DEFAULT_THRESHOLDS)
    assert verdict["bandit"]["verdict"] == "READY"
    assert verdict["bandit"]["reasons"] == []
