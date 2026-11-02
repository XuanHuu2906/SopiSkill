"""P5.1 extractor — read-only, chịu schema 0012 và 0015, lọc contentVersion."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from evals import mastery_dataset as md

DDL_0012 = [
    "CREATE TABLE users (id TEXT PRIMARY KEY, external_id TEXT, email TEXT)",
    "CREATE TABLE courses (id TEXT PRIMARY KEY, user_id TEXT, topic TEXT)",
    "CREATE TABLE units (id TEXT PRIMARY KEY, course_id TEXT, order_index INTEGER, title TEXT)",
    """CREATE TABLE lessons (
        id TEXT PRIMARY KEY, unit_id TEXT, course_id TEXT, order_index INTEGER,
        title TEXT, content_version INTEGER, status TEXT)""",
    """CREATE TABLE lesson_attempts (
        id TEXT PRIMARY KEY, lesson_id TEXT, user_id TEXT, client_attempt_id TEXT,
        content_version INTEGER, score_correct INTEGER, score_total INTEGER,
        duration_ms INTEGER, results TEXT, xp_awarded INTEGER, created_at TEXT)""",
]


def test_redact_dsn_hides_password():
    redacted = md.redact_dsn("postgresql+asyncpg://u:secret@h:5432/db")
    assert "secret" not in redacted
    assert "h:5432" in redacted


async def _build(tmp_path, with_skills: bool):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        for ddl in DDL_0012:
            await conn.execute(text(ddl))
        if with_skills:
            await conn.execute(
                text("CREATE TABLE skills (id TEXT PRIMARY KEY, course_id TEXT, key TEXT)")
            )
            await conn.execute(
                text("CREATE TABLE lesson_skills (lesson_id TEXT, skill_id TEXT)")
            )
    return engine


async def _seed(engine, *, version_match: bool, users: int, attempts: int):
    async with engine.begin() as conn:
        for u in range(users):
            uid = f"u{u}"
            await conn.execute(
                text("INSERT INTO users (id, external_id) VALUES (:i, :e)"),
                {"i": uid, "e": f"ext{u}"},
            )
            await conn.execute(
                text("INSERT INTO courses (id,user_id,topic) VALUES (:c,:u,'t')"),
                {"c": f"c{u}", "u": uid},
            )
            await conn.execute(
                text("INSERT INTO units (id,course_id,order_index,title) VALUES (:n,:c,0,'u')"),
                {"n": f"un{u}", "c": f"c{u}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO lessons (id,unit_id,course_id,order_index,title,"
                    "content_version,status) VALUES (:l,:un,:c,0,'L',2,'ready')"
                ),
                {"l": f"l{u}", "un": f"un{u}", "c": f"c{u}"},
            )
        now = datetime(2026, 10, 1, tzinfo=UTC)
        for i in range(attempts):
            u = i % users
            cv = 2 if version_match else 1
            await conn.execute(
                text(
                    "INSERT INTO lesson_attempts (id,lesson_id,user_id,client_attempt_id,"
                    "content_version,score_correct,score_total,duration_ms,results,"
                    "xp_awarded,created_at) VALUES (:id,:l,:u,:cid,:cv,4,5,100,'[]',0,:ts)"
                ),
                {
                    "id": f"a{i}",
                    "l": f"l{u}",
                    "u": f"u{u}",
                    "cid": f"c{i}",
                    "cv": cv,
                    "ts": (now + timedelta(minutes=i)).isoformat(),
                },
            )


async def test_extractor_falls_back_on_0012_schema(tmp_path):
    engine = await _build(tmp_path, with_skills=False)
    await _seed(engine, version_match=True, users=2, attempts=12)
    seqs, report = await md.load_sequences(engine, granularity="skill", min_sequence=2)
    assert report.skill_granularity is False
    assert report.users == 2
    assert report.raw_attempts == 12
    assert report.versioned_attempts == 12
    assert all(len(s.events) >= 1 for s in seqs)
    assert {s.key for s in seqs} == {"lesson:l0", "lesson:l1"}
    await engine.dispose()


async def test_extractor_excludes_stale_versions(tmp_path):
    engine = await _build(tmp_path, with_skills=False)
    await _seed(engine, version_match=False, users=1, attempts=10)
    seqs, report = await md.load_sequences(engine, granularity="lesson", min_sequence=1)
    assert report.raw_attempts == 10
    assert report.versioned_attempts == 0
    assert seqs == []
    await engine.dispose()


async def test_extractor_uses_skill_key_when_available(tmp_path):
    engine = await _build(tmp_path, with_skills=True)
    await _seed(engine, version_match=True, users=2, attempts=12)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO skills (id,course_id,key) VALUES ('s0','c0','alpha')")
        )
        await conn.execute(
            text("INSERT INTO lesson_skills (lesson_id,skill_id) VALUES ('l0','s0')")
        )
    seqs, report = await md.load_sequences(engine, granularity="skill", min_sequence=1)
    assert report.skill_granularity is True
    assert any(s.key == "skill:alpha" for s in seqs)
    await engine.dispose()


async def test_summarize_counts_length_thresholds(tmp_path):
    engine = await _build(tmp_path, with_skills=False)
    await _seed(engine, version_match=True, users=2, attempts=12)
    _seqs, report = await md.load_sequences(engine, granularity="lesson", min_sequence=2)
    summary = md.summarize(report, {"min_sequences": 1, "min_events": 1})
    assert summary["enough"] is True
    summary2 = md.summarize(report, {"min_sequences": 999, "min_events": 1})
    assert summary2["enough"] is False
    assert "min_sequences" in summary2["reasons"][0]
    await engine.dispose()
