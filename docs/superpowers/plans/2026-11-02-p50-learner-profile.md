# P5.0 — Learner Profile, Mastery Baseline & FSRS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn existing lesson attempts into a per-skill mastery baseline, an FSRS spaced-repetition schedule backed by immutable review events, and a prerequisite-aware "what to study next" recommendation with a human-readable reason.

**Architecture:** A new expand-only Alembic revision adds five tables (`skills`, `lesson_skills`, `skill_mastery`, `review_cards`, `review_events`). Skills are backfilled from the curriculum already stored in `course_proposals.payload`, mapped to lessons by `(unit.order_index, lesson.order_index)` because generation overwrites `lesson.title`. Mastery is a deterministic recency-weighted accuracy (rule-based, never called a probability). Spaced repetition uses the `fsrs` library pinned to the scheduler version recorded on every card/event. New read endpoints serve mastery, learning path and due cards; one CSRF-protected write endpoint grades a review card. Everything is gated by `P50_ENABLED` (default false) returning 503.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL (production) + SQLite in-memory (tests), `fsrs>=6.3,<7`, Next.js 15 + TanStack Query.

**Spec:** `docs/specs/22-P50-LEARNER-PROFILE.md`

## Global Constraints

- Alembic head is `0014_p43_ocr`; the new revision is `0015_p50_learner_profile` with `down_revision = "0014_p43_ocr"`. Never edit an existing revision.
- Migration is **expand-only**: `upgrade()` must contain no `drop_table`, `drop_column`, or `alter_column`. `downgrade()` drops only the five new tables.
- `P50_ENABLED` default **false**. When false, the three new routes return **503** with `detail.code == "P50_NOT_ENABLED"`, no rows are written, and the attempt flow is unchanged.
- `P50_BACKFILL_ENABLED` default **false**; only the periodic reconciler obeys it. Inline backfill after generation runs whenever `P50_ENABLED` is true.
- `MASTERY_PASS_THRESHOLD` default **0.7**; `MASTERY_RECENCY_HALF_LIFE_DAYS` default **30**.
- `FSRS_SCHEDULER_VERSION = "py-fsrs-6.3.2"` (constant in code, copied into every card/event row). Scheduler constructed with `enable_fuzzing=False`, `learning_steps=()`, `relearning_steps=()`, `desired_retention=0.9`.
- Every datetime read from the DB is coerced with `_as_utc(dt)` before any `fsrs` call; `fsrs` raises `ValueError` on naive or non-UTC datetimes.
- `fsrs.Card.card_id` is an `int`. Derive it as `int(uuid.int % (2**63 - 1))`. Never pass `None`.
- All tested timestamps are pinned (no `datetime.now()` inside tested pure functions — the caller passes `now`).
- Never trust client scores/ratings for mastery or XP; mastery is computed only from stored `lesson_attempts`.
- Ownership is enforced in SQL (`Course.user_id == user.id`); cross-user is 404.
- Logs contain only ids, ratings and day intervals — never lesson content or answer keys.
- New tests must be added to `backend/tests/`; the existing suite (540 passed / 25 skipped) must stay green.
- Python identifiers, docstrings and comments follow the repo's Vietnamese convention; user-facing UI copy is Vietnamese.

## Review Focus

- **Attempt on a lesson with no skill rows** (legacy/unbackfilled proposal): the attempt must still succeed, award XP, and never raise; mastery for that lesson is simply absent.
- **`score_total == 0` boundary** (all-blank submission): do not divide by zero when deriving mastery and the initial FSRS rating.
- **Naive datetimes from SQLite** in tests: a review graded immediately after creation must use UTC-aware values or `fsrs` raises `ValueError`.
- **Duplicate `clientReviewId` on retry** (network retry / double-click): must return the *current* card state with `duplicate=true`, create no second `review_events` row, and leave `due_at` unchanged.
- **Prerequisite dead-end**: a learner who completed a lesson at 80% but whose skill mastery is below threshold must still receive a usable recommendation (fallback to weakest learned lesson), never an empty path with no reason.

---

### Task 1: `fsrs` dependency + settings

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_p50_config.py`

**Interfaces:**
- Produces: `Settings.p50_enabled: bool`, `Settings.p50_backfill_enabled: bool`, `Settings.mastery_pass_threshold: float`, `Settings.mastery_recency_half_life_days: int`, `Settings.fsrs_desired_retention: float`.

- [ ] **Step 1: Write the failing test**

```python
import os

from app.core.config import Settings


def test_p50_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.p50_enabled is False
    assert settings.p50_backfill_enabled is False
    assert settings.mastery_pass_threshold == 0.7
    assert settings.mastery_recency_half_life_days == 30
    assert settings.fsrs_desired_retention == 0.9


def test_p50_enabled_can_be_set(monkeypatch):
    monkeypatch.setenv("P50_ENABLED", "true")
    monkeypatch.setenv("MASTERY_PASS_THRESHOLD", "0.8")
    settings = Settings(_env_file=None)
    assert settings.p50_enabled is True
    assert settings.mastery_pass_threshold == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'p50_enabled'`

- [ ] **Step 3: Add the dependency and settings**

In `backend/requirements.txt`, after the `defusedxml>=0.7` line, add:

```
# P5.0 — FSRS spaced repetition (pure Python; optimizer extras NOT installed)
fsrs>=6.3,<7
```

In `backend/app/core/config.py`, inside `class Settings`, add:

```python
    # P5.0 — learner profile, mastery & FSRS. Mặc định TẮT để hành vi cũ nguyên vẹn.
    p50_enabled: bool = False
    p50_backfill_enabled: bool = False
    # PROPOSAL: cần hiệu chỉnh khi có dữ liệu học thật.
    mastery_pass_threshold: float = 0.7
    mastery_recency_half_life_days: int = 30
    fsrs_desired_retention: float = 0.9
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_p50_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/app/core/config.py backend/tests/test_p50_config.py
git commit -m "feat(p5.0): add fsrs dependency and learner-profile settings"
```

---

### Task 2: Models + migration `0015_p50_learner_profile`

**Files:**
- Modify: `backend/app/models/models.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0015_p50_learner_profile.py`
- Test: `backend/tests/test_p50_migration_contract.py`

**Interfaces:**
- Produces:
  - `Skill(id, course_id, key, title, bloom_level, outcome, order_index, created_at, updated_at)` — `__tablename__ = "skills"`, `UniqueConstraint("course_id", "key", name="uq_skill_course_key")`
  - `LessonSkill(lesson_id, skill_id, created_at)` — PK `(lesson_id, skill_id)`, index on `skill_id`
  - `SkillMastery(user_id, skill_id, attempts, correct, total, mastery_score, last_attempt_at, updated_at)` — PK `(user_id, skill_id)`, index on `skill_id`
  - `ReviewCard(id, user_id, lesson_id, skill_id, state, step, stability, difficulty, due_at, last_review_at, scheduler_version, created_from_attempt_id, created_at, updated_at)` — `UniqueConstraint("user_id", "lesson_id", name="uq_review_card_user_lesson")`, `Index("ix_review_cards_user_due", "user_id", "due_at")`
  - `ReviewEvent(id, card_id, user_id, rating, reviewed_at, elapsed_days, scheduled_days, duration_ms, state_before, state_after, scheduler_version, client_review_id, created_at)` — `UniqueConstraint("card_id", "client_review_id", name="uq_review_event_client_id")`, `Index("ix_review_events_card_reviewed", "card_id", "reviewed_at")`, `Index("ix_review_events_user_reviewed", "user_id", "reviewed_at")`

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 migration contract — chain, expand-only, metadata. Không cần DB sống."""

import importlib.util
import pathlib

import app.models  # noqa: F401  (side-effect: đăng ký mapper)
from app.db.base import Base

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0015_p50_learner_profile.py"
)

NEW_TABLES = {"skills", "lesson_skills", "skill_mastery", "review_cards", "review_events"}


def _load():
    spec = importlib.util.spec_from_file_location("migration_0015", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p43_head():
    module = _load()
    assert module.revision == "0015_p50_learner_profile"
    assert module.down_revision == "0014_p43_ocr"


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body


def test_models_are_registered():
    assert NEW_TABLES <= set(Base.metadata.tables)


def test_required_unique_constraints():
    skills = Base.metadata.tables["skills"]
    names = {c.name for c in skills.constraints}
    assert "uq_skill_course_key" in names

    cards = Base.metadata.tables["review_cards"]
    assert "uq_review_card_user_lesson" in {c.name for c in cards.constraints}

    events = Base.metadata.tables["review_events"]
    assert "uq_review_event_client_id" in {c.name for c in events.constraints}


def test_review_cards_have_due_index():
    cards = Base.metadata.tables["review_cards"]
    assert "ix_review_cards_user_due" in {i.name for i in cards.indexes}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_migration_contract.py -v`
Expected: FAIL — `FileNotFoundError` on the migration path.

- [ ] **Step 3: Add the models**

In `backend/app/models/models.py`, append after `class XpEvent`:

```python
class Skill(Base):
    """Skill ổn định trong MỘT course, backfill từ `CurriculumSkill` của proposal."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("course_id", "key", name="uq_skill_course_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    bloom_level: Mapped[str] = mapped_column(Text, default="understand")
    outcome: Mapped[str] = mapped_column(Text, default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LessonSkill(Base):
    __tablename__ = "lesson_skills"
    __table_args__ = (Index("ix_lesson_skills_skill", "skill_id"),)

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillMastery(Base):
    """Snapshot mastery. `mastery_score` là heuristic CÓ TRỌNG SỐ THỜI GIAN,
    KHÔNG phải xác suất đã hiệu chuẩn."""

    __tablename__ = "skill_mastery"
    __table_args__ = (Index("ix_skill_mastery_skill", "skill_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewCard(Base):
    """Snapshot FSRS hiện tại cho (user, lesson). 1 card / cặp."""

    __tablename__ = "review_cards"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_review_card_user_lesson"),
        Index("ix_review_cards_user_due", "user_id", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[int] = mapped_column(Integer, default=2)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stability: Mapped[float | None] = mapped_column(Float, nullable=True)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduler_version: Mapped[str] = mapped_column(Text)
    created_from_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lesson_attempts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewEvent(Base):
    """Audit bất biến (append-only) của mỗi lần review."""

    __tablename__ = "review_events"
    __table_args__ = (
        UniqueConstraint("card_id", "client_review_id", name="uq_review_event_client_id"),
        Index("ix_review_events_card_reviewed", "card_id", "reviewed_at"),
        Index("ix_review_events_user_reviewed", "user_id", "reviewed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    card_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cards.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_days: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_days: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    state_before: Mapped[int] = mapped_column(Integer, default=0)
    state_after: Mapped[int] = mapped_column(Integer, default=0)
    scheduler_version: Mapped[str] = mapped_column(Text)
    client_review_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Export the new models**

In `backend/app/models/__init__.py`, add `LessonSkill, ReviewCard, ReviewEvent, Skill, SkillMastery` to the `from app.models.models import (...)` list (alphabetically) and to `__all__`.

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/0015_p50_learner_profile.py` following the `0014` style: docstring explaining expand-only scope and rollback, `revision = "0015_p50_learner_profile"`, `down_revision = "0014_p43_ocr"`, `_has_table` guard, `upgrade()` creating the five tables in FK order (`skills` → `lesson_skills`, `skill_mastery` → `review_cards` → `review_events`) with the same column types/uniques/indexes as the models, and `downgrade()` dropping the five tables in reverse FK order guarded by `_has_table`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_p50_migration_contract.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Verify the chain still loads**

Run: `cd backend && python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; s=ScriptDirectory.from_config(Config('alembic.ini')); print(s.get_heads())"`
Expected: `['0015_p50_learner_profile']` (single head)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/models.py backend/app/models/__init__.py backend/alembic/versions/0015_p50_learner_profile.py backend/tests/test_p50_migration_contract.py
git commit -m "feat(p5.0): skill/mastery/review tables with expand-only migration 0015"
```

---

### Task 3: Skill backfill service

**Files:**
- Create: `backend/app/services/learner_profile_service.py`
- Test: `backend/tests/test_p50_skills.py`

**Interfaces:**
- Produces:
  - `async def backfill_course_skills(db: AsyncSession, course: Course) -> int` — returns number of `lesson_skills` rows written (idempotent). Raises nothing on missing proposal; returns 0.
  - `async def skills_for_course(db: AsyncSession, course_id: uuid.UUID) -> list[Skill]`
  - `def position_key(unit_index: int, lesson_index: int) -> tuple[int, int]` (module-level helper, used by tests)
- Consumes: `pedagogy.normalize_curriculum`, `ProposalPayload`, models from Task 2.

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 skill backfill — proposal payload → skills/lesson_skills."""

import uuid

import pytest

from app.models import Course, CourseProposal, Lesson, Unit, User
from app.schemas.schemas import ProposalPayload
from app.services import learner_profile_service


def _payload(**overrides) -> dict:
    base = {
        "title": "Học Python",
        "summary": "Từ đầu",
        "units": [
            {"title": "U1", "blurb": "", "lessonTitles": ["Biến và kiểu", "Vòng lặp"]},
            {"title": "U2", "blurb": "", "lessonTitles": ["Hàm"]},
        ],
        "skills": [],
        "prerequisites": [],
    }
    base.update(overrides)
    return base


async def _seed_course(db, user, proposal_payload, lesson_titles):
    course = Course(user_id=user.id, topic="Python", status="ready", client_course_id=f"c-{uuid.uuid4()}")
    db.add(course)
    await db.flush()
    db.add(CourseProposal(course_id=course.id, version=1, payload=proposal_payload))
    unit = Unit(course_id=course.id, order_index=0, title="U1", blurb="")
    db.add(unit)
    await db.flush()
    lesson = Lesson(
        unit_id=unit.id,
        course_id=course.id,
        order_index=0,
        title=lesson_titles,   # provider title KHÁC proposal title
        content=[],
        content_version=1,
        status="ready",
    )
    db.add(lesson)
    await db.commit()
    return course, lesson


@pytest.mark.asyncio
async def test_backfill_creates_skills_and_links(db, user):
    course, lesson = await _seed_course(
        db, user, _payload(), "Tiêu đề do model sinh: Biến"
    )
    written = await learner_profile_service.backfill_course_skills(db, course)
    assert written >= 1

    skills = await learner_profile_service.skills_for_course(db, course.id)
    assert [s.key for s in skills][:1] == ["bien-va-kieu"]
    assert skills[0].title == "Biến và kiểu"


@pytest.mark.asyncio
async def test_backfill_maps_by_position_not_title(db, user):
    course, lesson = await _seed_course(
        db, user, _payload(), "Tiêu đề hoàn toàn khác"
    )
    await learner_profile_service.backfill_course_skills(db, course)
    row = await learner_profile_service.skill_for_lesson(db, lesson.id)
    assert row is not None
    assert row.key == "bien-va-kieu"


@pytest.mark.asyncio
async def test_backfill_is_idempotent(db, user):
    course, _ = await _seed_course(db, user, _payload(), "X")
    first = await learner_profile_service.backfill_course_skills(db, course)
    second = await learner_profile_service.backfill_course_skills(db, course)
    assert first == second
    skills = await learner_profile_service.skills_for_course(db, course.id)
    assert len({s.key for s in skills}) == len(skills)


@pytest.mark.asyncio
async def test_backfill_without_proposal_returns_zero(db, user):
    course = Course(user_id=user.id, topic="T", status="ready", client_course_id=f"c-{uuid.uuid4()}")
    db.add(course)
    await db.commit()
    assert await learner_profile_service.backfill_course_skills(db, course) == 0


@pytest.mark.asyncio
async def test_duplicate_slugs_get_deterministic_suffixes(db, user):
    payload = _payload(
        units=[{"title": "U", "blurb": "", "lessonTitles": [
            "Cùng một tiêu đề rất dài giống nhau A",
            "Cùng một tiêu đề rất dài giống nhau B",
        ]}]
    )
    course, _ = await _seed_course(db, user, payload, "X")
    await learner_profile_service.backfill_course_skills(db, course)
    skills = await learner_profile_service.skills_for_course(db, course.id)
    keys = [s.key for s in skills]
    assert len(keys) == len(set(keys))
    assert any(k.endswith("-2") for k in keys)
```

Note: add a `db`/`user` fixture pair to `backend/tests/conftest.py` if not present — use `SessionLocal()` for `db` and create+commit a `User` for `user`, rolling back/cleaning after.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_skills.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.learner_profile_service`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/learner_profile_service.py` with:
- `backfill_course_skills`: load latest `CourseProposal` for the course (highest `version`), return 0 when absent; `ProposalPayload.model_validate(payload)` then `pedagogy.normalize_curriculum(payload)`; build `lesson_positions = [(u_idx, l_idx, title) ...]` from `payload.units`; dedupe skill keys by appending `-2`, `-3`, … in proposal order when `_slug` collides; upsert `Skill` by `(course_id, key)` (select then insert/update — never delete); load lessons for the course ordered by `(Unit.order_index, Lesson.order_index)`; map each skill to its lesson **by position**; upsert `LessonSkill` pairs (skip existing); `await db.commit()`; return the number of `lesson_skills` rows present after the run.
- `skills_for_course`, `skill_for_lesson` read helpers.

Use the module docstring to state explicitly that mapping is positional because `Lesson.title` is overwritten by the provider.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_p50_skills.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/learner_profile_service.py backend/tests/test_p50_skills.py backend/tests/conftest.py
git commit -m "feat(p5.0): backfill skills from proposal with positional lesson mapping"
```

---

### Task 4: Mastery computation + attempt hook

**Files:**
- Modify: `backend/app/services/learner_profile_service.py`
- Modify: `backend/app/services/lesson_service.py` (in `submit_attempt`, before `db.commit()` at the `try:` block)
- Modify: `backend/app/schemas/schemas.py` (`AttemptOut`)
- Modify: `backend/app/api/v1/routes.py` (`submit_attempt` response)
- Test: `backend/tests/test_p50_mastery.py`

**Interfaces:**
- Produces:
  - `def compute_mastery(attempts: list[tuple[float, datetime]], now: datetime, half_life_days: int = 30) -> float` — pure; `attempts` are `(block_accuracy, created_at)`.
  - `async def refresh_skill_mastery(db: AsyncSession, user_id, skill_id, now: datetime) -> SkillMastery | None`
  - `async def course_mastery(db: AsyncSession, course: Course, user_id) -> dict`
  - `submit_attempt` returns `(attempt, duplicate, review_card_created)` — **adds a third element**; update the route and any other caller.

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 mastery — deterministic, recency-weighted, version-aware."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.learner_profile_service import compute_mastery

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_empty_attempts_is_zero():
    assert compute_mastery([], NOW) == 0.0


def test_single_recent_perfect_attempt_is_one():
    assert compute_mastery([(1.0, NOW)], NOW) == 1.0


def test_zero_total_is_ignored_not_divided():
    # accuracy 0.0 với total 0 phải được caller lọc; hàm chỉ nhận accuracy hợp lệ
    assert compute_mastery([(0.0, NOW)], NOW) == 0.0


def test_recency_weights_recent_more():
    old = NOW - timedelta(days=30)
    score = compute_mastery([(0.0, old), (1.0, NOW)], NOW, half_life_days=30)
    assert score > 0.5  # attempt mới nặng hơn


def test_deterministic():
    data = [(0.5, NOW - timedelta(days=10)), (0.9, NOW)]
    assert compute_mastery(data, NOW) == compute_mastery(data, NOW)


def test_score_is_clamped():
    assert 0.0 <= compute_mastery([(5.0, NOW)], NOW) <= 1.0


@pytest.mark.asyncio
async def test_attempt_without_skill_does_not_fail(client, auth_headers, seeded_lesson_no_skill):
    # Nộp bài trên lesson chưa backfill ⇒ attempt thành công, reviewCardCreated=False
    lesson_id = seeded_lesson_no_skill
    resp = await client.post(
        f"/v1/lessons/{lesson_id}/attempts",
        headers=auth_headers,
        json={"clientAttemptId": "att-noskill-1", "contentVersion": 1, "answers": []},
    )
    assert resp.status_code == 201
    assert resp.json()["reviewCardCreated"] is False
```

Note: reuse existing tryout fixtures in `conftest.py` where possible; add `seeded_lesson_no_skill` if needed (a lesson with no `lesson_skills` row). The `auth_headers` helper must reuse whatever the existing P1.1 tests use — mirror `tests/test_api_flow.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_mastery.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_mastery'`

- [ ] **Step 3: Implement `compute_mastery`**

```python
def compute_mastery(attempts, now, half_life_days=30):
    """Accuracy có trọng số thời gian. KHÔNG phải xác suất đã hiệu chuẩn."""
    if not attempts:
        return 0.0
    weighted_sum = 0.0
    weight_total = 0.0
    for accuracy, created_at in attempts:
        created_at = _as_utc(created_at)
        age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
        weight = 0.5 ** (age_days / max(1, half_life_days))
        weighted_sum += weight * min(1.0, max(0.0, float(accuracy)))
        weight_total += weight
    if weight_total <= 0:
        return 0.0
    return min(1.0, max(0.0, weighted_sum / weight_total))
```

Add `_as_utc(dt)` (replace `tzinfo=UTC` when naive).

- [ ] **Step 4: Implement `refresh_skill_mastery` and `course_mastery`**

`refresh_skill_mastery`: select attempts of the user for lessons linked to `skill_id` **with `content_version == Lesson.content_version`** and `score_total > 0`, build `(score_correct/score_total, created_at)`, call `compute_mastery`, upsert `SkillMastery` on the `(user_id, skill_id)` PK (`INSERT ... ON CONFLICT` on PostgreSQL, select-then-write on SQLite).

`course_mastery`: join `Skill` with `SkillMastery` for the user, return `{"items": [...], "coursePercent": ..., "reviewDueCount": ...}` matching the API shape in the spec; `coursePercent` = mean of score over skills that have rows (0 when none), rounded to 1 decimal.

- [ ] **Step 5: Hook mastery into `submit_attempt`**

In `lesson_service.submit_attempt`, inside the existing `try:` block immediately after `db.add(attempt)` and the XP block, **before** `await db.commit()`:

```python
    await db.flush()  # cần attempt.id cho created_from_attempt_id và thứ tự FK
    review_card_created = False
    if get_settings().p50_enabled:
        from app.services import learner_profile_service, spaced_repetition_service

        skill = await learner_profile_service.skill_for_lesson(db, lesson.id)
        if skill is not None:
            await learner_profile_service.refresh_skill_mastery(
                db, user_id=user.id, skill_id=skill.id, now=datetime.now(UTC)
            )
        review_card_created = await spaced_repetition_service.ensure_card_for_attempt(
            db, lesson=lesson, attempt=attempt, user_id=user.id
        )
```

Return `(attempt, False, review_card_created)` on success and `(existing, True, False)` on the duplicate paths.

- [ ] **Step 6: Update the route + schema**

In `schemas.py` add to `AttemptOut`: `reviewCardCreated: bool = False`.
In `routes.py` `submit_attempt`: unpack three values and pass `reviewCardCreated=review_card_created`.

- [ ] **Step 7: Run tests**

Run: `cd backend && python -m pytest tests/test_p50_mastery.py tests/test_api_flow.py tests/test_grading.py -v`
Expected: PASS, no regression.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/learner_profile_service.py backend/app/services/lesson_service.py backend/app/schemas/schemas.py backend/app/api/v1/routes.py backend/tests/test_p50_mastery.py
git commit -m "feat(p5.0): recency-weighted mastery in submit_attempt"
```

Note: `spaced_repetition_service` is created in Task 5; run Task 5 before this task's Step 7, or land Task 4 and 5 together in one commit.

---

### Task 5: FSRS spaced repetition service

**Files:**
- Create: `backend/app/services/spaced_repetition_service.py`
- Test: `backend/tests/test_p50_fsrs.py`

**Interfaces:**
- Produces:
  - `FSRS_SCHEDULER_VERSION = "py-fsrs-6.3.2"`
  - `def scheduler() -> Scheduler` (cached)
  - `def initial_rating(block_accuracy: float) -> Rating`
  - `def _card_id(card_uuid: uuid.UUID) -> int`
  - `async def ensure_card_for_attempt(db, lesson, attempt, user_id) -> bool`
  - `async def due_cards(db, user_id, course_id=None, limit=20, now=None) -> dict`
  - `async def grade_card(db, card_id, user_id, rating, client_review_id, duration_ms=None, now=None) -> dict`
  - `class CardNotFoundError(Exception)`, `class ReviewInProgressError` (not used in v1)

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 FSRS — deterministic scheduling, idempotency, UTC coercion."""

from datetime import UTC, datetime, timedelta

import pytest
from fsrs import Rating, State

from app.services import spaced_repetition_service as srp

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_initial_rating_thresholds():
    assert srp.initial_rating(0.3) == Rating.Again
    assert srp.initial_rating(0.7) == Rating.Hard
    assert srp.initial_rating(0.9) == Rating.Good
    assert srp.initial_rating(1.0) == Rating.Easy


def test_scheduler_is_deterministic_and_reaches_review_state():
    card, _ = srp.review(srp.new_card(123), Rating.Good, NOW)
    assert card.state == State.Review
    assert card.step is None
    assert card.due == NOW + timedelta(days=2)


@pytest.mark.parametrize(
    "rating,days",
    [(Rating.Again, 1), (Rating.Hard, 1), (Rating.Good, 2), (Rating.Easy, 8)],
)
def test_initial_intervals(rating, days):
    card, _ = srp.review(srp.new_card(123), rating, NOW)
    assert card.due == NOW + timedelta(days=days)


def test_naive_datetime_is_coerced():
    card, _ = srp.review(srp.new_card(1), Rating.Good, datetime(2026, 11, 2, 12, 0))
    assert card.due.tzinfo is not None


@pytest.mark.asyncio
async def test_grade_is_idempotent_by_client_review_id(db, seeded_card):
    first = await srp.grade_card(db, seeded_card.id, seeded_card.user_id, 3, "rv-1", now=NOW)
    second = await srp.grade_card(db, seeded_card.id, seeded_card.user_id, 3, "rv-1", now=NOW)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["card"]["dueAt"] == first["card"]["dueAt"]


@pytest.mark.asyncio
async def test_cross_user_card_is_not_found(db, seeded_card, other_user):
    with pytest.raises(srp.CardNotFoundError):
        await srp.grade_card(db, seeded_card.id, other_user.id, 3, "rv-x", now=NOW)


@pytest.mark.asyncio
async def test_card_created_on_first_attempt_even_below_threshold(db, seeded_lesson_attempt_low):
    attempt = seeded_lesson_attempt_low
    created = await srp.ensure_card_for_attempt(db, attempt.lesson, attempt, attempt.user_id)
    assert created is True
    # attempt thứ hai không tạo card mới
    created_again = await srp.ensure_card_for_attempt(db, attempt.lesson, attempt, attempt.user_id)
    assert created_again is False
```

Add a thin `review(card, rating, now)` wrapper in the service so tests do not need to construct a `Scheduler`; it must use the module scheduler and coerce `now`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_fsrs.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the service**

`new_card(int_id) -> Card(card_id=int_id)`; `scheduler()` cached with `enable_fuzzing=False, learning_steps=(), relearning_steps=(), desired_retention=settings.fsrs_desired_retention`; `review(card, rating, now)` = `_as_utc(now)` then `scheduler().review_card(card, rating, review_datetime=now)`.

`ensure_card_for_attempt`: select existing `ReviewCard` by `(user_id, lesson_id)`; if present return `False`. Else compute `block_accuracy = attempt.score_correct / attempt.score_total` (guard `score_total == 0` → `0.0`), `rating = initial_rating(...)`, create card, `card, _ = review(card, rating, attempt.created_at)`; insert `ReviewCard` with `state=card.state`, `stability`, `difficulty`, the **existing** `skill_id` for the lesson (`learner_profile_service.skill_for_lesson`, may be `None`), `due_at=card.due`, `last_review_at=attempt.created_at`, `scheduler_version=FSRS_SCHEDULER_VERSION`, `created_from_attempt_id=attempt.id`; also append the corresponding `ReviewEvent` (rating, reviewed_at, `elapsed_days=0`, `scheduled_days=max(0,(card.due-attempt.created_at).days)`, `state_before=State.Learning`, `state_after=card.state`, `client_review_id=f"initial:{attempt.id}"`); commit; return `True`. On `IntegrityError` (concurrent creation) rollback and return `False`.

`grade_card`: load card scoped `user_id`; raise `CardNotFoundError` if absent. If a `ReviewEvent` already exists for `(card_id, client_review_id)` → return `{"card": <current>, "eventId": ..., "duplicate": True}`. Else read `last_review_at`/`due_at`, coerce to UTC, rebuild the `fsrs.Card` from the row (derive int id from UUID), call `review`, update the row, insert `ReviewEvent` (`elapsed_days` from `last_review_at` → `now`, `scheduled_days` from `now` → new due, `state_before`/`state_after`, `duration_ms`), commit, return `{"card": {...}, "eventId": ..., "duplicate": False}`. On `IntegrityError` from the unique constraint, rollback and re-read to return `duplicate=True`.

`due_cards`: select cards for the user with `due_at <= now`, optionally filtered by `course_id` via a join on `Lesson`, ordered by `due_at`, limit capped at 100; return `{"items": [...], "total": ...}` with `overdueDays = max(0, (now - due_at).days)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_p50_fsrs.py -v`
Expected: PASS (all)

- [ ] **Step 5: Run Task 4's tests now that the service exists**

Run: `cd backend && python -m pytest tests/test_p50_mastery.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/spaced_repetition_service.py backend/tests/test_p50_fsrs.py
git commit -m "feat(p5.0): FSRS scheduler adapter with idempotent review grading"
```

---

### Task 6: Learning path service

**Files:**
- Create: `backend/app/services/learning_path_service.py`
- Test: `backend/tests/test_p50_learning_path.py`

**Interfaces:**
- Produces: `async def build_learning_path(db, course, user_id) -> dict` returning `{nextLesson, reviewLessonId, reviewDueCount, blockedBy, prerequisitesDag}` exactly as in spec §10. Reason codes: `NEXT_IN_SEQUENCE`, `PREREQUISITES_MET`, `PREREQUISITE_NOT_MET`, `FALLBACK_REVIEW_WEAKEST`.
- Consumes: `learner_profile_service.skills_for_course`, `course_service._completed_lesson_ids`, `spaced_repetition_service.due_cards`.

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 learning path — prerequisite gating + weakest-lesson fallback."""

import pytest

from app.services import learning_path_service


@pytest.mark.asyncio
async def test_blocks_next_lesson_when_prerequisite_not_met(db, course_two_lessons_dep):
    path = await learning_path_service.build_learning_path(db, course_two_lessons_dep, course_two_lessons_dep.user_id)
    assert path["nextLesson"] is None
    assert path["blockedBy"]
    assert path["blockedBy"][0]["prerequisites"][0]["met"] is False
    assert path["reviewLessonId"] is not None
    assert path["blockedBy"][0]["reason"]["code"] == "PREREQUISITE_NOT_MET"


@pytest.mark.asyncio
async def test_recommends_next_when_prerequisite_met(db, course_two_lessons_dep_met):
    path = await learning_path_service.build_learning_path(db, course_two_lessons_dep_met, course_two_lessons_dep_met.user_id)
    assert path["nextLesson"] is not None
    assert path["nextLesson"]["reason"]["code"] in {"NEXT_IN_SEQUENCE", "PREREQUISITES_MET"}
    assert path["blockedBy"] == []


@pytest.mark.asyncio
async def test_dag_exposes_nodes_and_edges(db, course_two_lessons_dep):
    path = await learning_path_service.build_learning_path(db, course_two_lessons_dep, course_two_lessons_dep.user_id)
    dag = path["prerequisitesDag"]
    assert {n["id"] for n in dag["nodes"]} >= {"s1", "s2"}
    assert len(dag["edges"]) == 1
```

Fixtures `course_two_lessons_dep` and `course_two_lessons_dep_met` seed a proposal with `skills=[{id:"s1",...lesson:A},{id:"s2",...lesson:B}]` and `prerequisites=[["s1","s2"]]`, plus lessons, and set `SkillMastery` for `s1` to 0.4 / 0.9 respectively.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_learning_path.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the service**

Load the latest proposal; normalize; build `skill_by_key`, `lesson_by_position`. Load the course with units+lessons and the user's `SkillMastery` rows. Compute `completed_ids` via `course_service._completed_lesson_ids`. Walk lessons in `(unit.order_index, lesson.order_index)` order; the first `ready` non-completed lesson with all prerequisite skills `>= settings.mastery_pass_threshold` (or no prerequisites) becomes `nextLesson` with `reason.code = "PREREQUISITES_MET"` when it had prerequisites, else `"NEXT_IN_SEQUENCE"`. If a `ready` non-completed lesson has an unmet prerequisite, add it to `blockedBy` with per-prerequisite `{skillId, title, masteryScore, met}` and `reason.code = "PREREQUISITE_NOT_MET"`; skip it. `reviewLessonId` = the completed ready lesson whose skill has the lowest `mastery_score` (fallback `FALLBACK_REVIEW_WEAKEST`), else `None`. `prerequisitesDag` nodes = `{id, title, lessonId}`, edges = `[[parent, child]]` from the normalized proposal. `reviewDueCount` from `spaced_repetition_service.due_cards`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_p50_learning_path.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/learning_path_service.py backend/tests/test_p50_learning_path.py
git commit -m "feat(p5.0): prerequisite-aware learning path with weakest-lesson fallback"
```

---

### Task 7: API routes + schemas

**Files:**
- Create: `backend/app/api/v1/learner.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/schemas.py`
- Test: `backend/tests/test_p50_api.py`

**Interfaces:**
- Produces: `router` in `app/api/v1/learner.py` with the four endpoints from spec §10; `P50_DISABLED_CODE = "P50_NOT_ENABLED"`.
- Consumes: all three services.

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 API — flag gating, ownership, CSRF, validation."""

import pytest


@pytest.mark.asyncio
async def test_routes_return_503_when_disabled(client, auth_headers, course_id):
    resp = await client.get(f"/v1/courses/{course_id}/mastery", headers=auth_headers)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "P50_NOT_ENABLED"


@pytest.mark.asyncio
async def test_mastery_requires_ownership(client, auth_headers_b, course_id):
    resp = await client.get(f"/v1/courses/{course_id}/mastery", headers=auth_headers_b)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_grade_requires_csrf(client, auth_headers, seeded_card):
    resp = await client.post(
        f"/v1/reviews/{seeded_card.id}/grade",
        headers=auth_headers,
        json={"rating": 3, "clientReviewId": "rv-1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_grade_rejects_out_of_range_rating(client, auth_headers_csrf, seeded_card):
    resp = await client.post(
        f"/v1/reviews/{seeded_card.id}/grade",
        headers=auth_headers_csrf,
        json={"rating": 5, "clientReviewId": "rv-1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_grade_ok_and_idempotent(client, auth_headers_csrf, seeded_card):
    body = {"rating": 3, "clientReviewId": "rv-1"}
    url = f"/v1/reviews/{seeded_card.id}/grade"
    first = await client.post(url, headers=auth_headers_csrf, json=body)
    second = await client.post(url, headers=auth_headers_csrf, json=body)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
```

Flag-on fixtures must monkeypatch `app.core.config.get_settings().p50_enabled` (or set env before importing) so the suite can test both states. Use a small `p50_enabled` context manager fixture that clears the `get_settings` lru_cache before and after.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_api.py -v`
Expected: FAIL — 404 (routes not registered).

- [ ] **Step 3: Add schemas**

In `schemas.py` add `SkillMasteryOut`, `MasteryOut`, `LearningPathOut`, `ReviewDueOut`, `ReviewGradeRequest` (`rating: int = Field(ge=1, le=4)`, `clientReviewId: str = Field(min_length=1, max_length=64)`, `durationMs: int | None = Field(default=None, ge=0)`), `ReviewGradeOut`, `ReviewCardOut` (without `stability`/`difficulty`).

- [ ] **Step 4: Implement the router**

`_require_enabled()` mirroring `tutor.py` (`503` + `P50_NOT_ENABLED`). `GET /v1/courses/{courseId}/mastery` → `learner_profile_service.course_mastery`; `GET /v1/courses/{courseId}/learning-path` → `learning_path_service.build_learning_path`; `GET /v1/reviews/due` → `spaced_repetition_service.due_cards` (own user only; optional `courseId`); `POST /v1/reviews/{cardId}/grade` → `verify_csrf`, `rate_limit(request, "review_grade", limit=120, window_seconds=60)`, parse prefixed UUID, call `grade_card`, map `CardNotFoundError` → 404 `REVIEW_CARD_NOT_FOUND`. Register `learner_router` in `main.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_p50_api.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all previous tests still pass (no regressions)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/learner.py backend/app/main.py backend/app/schemas/schemas.py backend/tests/test_p50_api.py
git commit -m "feat(p5.0): mastery, learning-path and review endpoints gated by P50_ENABLED"
```

---

### Task 8: Generation hook + backfill reconciler

**Files:**
- Modify: `backend/app/worker/generation.py` (after the lesson loop finishes)
- Modify: `backend/app/worker/*` beat schedule file where other reconcilers live (inspect `celery_app` include/beat; add `reconcile_skills` next to the existing ingest/embed reconcilers)
- Test: `backend/tests/test_p50_generation_hook.py`

**Interfaces:**
- Produces: `async def backfill_all_skills(db) -> int` in `learner_profile_service` (guarded by `settings.p50_backfill_enabled`); generation calls `backfill_course_skills` inline when `settings.p50_enabled`.
- Consumes: Task 3.

- [ ] **Step 1: Write the failing test**

```python
"""P5.0 generation hook — skills written when flag on, untouched when off."""

import pytest


@pytest.mark.asyncio
async def test_generation_writes_skills_when_enabled(db, generated_course):
    course = generated_course
    skills = await learner_profile_service.skills_for_course(db, course.id)
    assert skills
    assert all(s.course_id == course.id for s in skills)


@pytest.mark.asyncio
async def test_reconciler_respects_backfill_flag(db, course_without_skills, monkeypatch):
    monkeypatch.setattr(settings, "p50_backfill_enabled", False)
    assert await learner_profile_service.backfill_all_skills(db) == 0
    monkeypatch.setattr(settings, "p50_backfill_enabled", True)
    assert await learner_profile_service.backfill_all_skills(db) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p50_generation_hook.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'backfill_all_skills'`

- [ ] **Step 3: Implement**

Add `backfill_all_skills(db)` (paginate owned courses, call `backfill_course_skills`, return rows written; no-op returning 0 when flag off). In `worker/generation.py`, after the lesson loop and before the job is marked ready, call `await learner_profile_service.backfill_course_skills(db, course)` when `settings.p50_enabled`; wrap in `try/except Exception` with `logger.exception` so a backfill failure cannot fail an otherwise successful generation (matches the source-research precedent).

- [ ] **Step 4: Register the reconciler on the beat schedule** next to the existing embed/ingest reconcilers.

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_p50_generation_hook.py tests/test_api_flow.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/learner_profile_service.py backend/app/worker/ backend/tests/test_p50_generation_hook.py
git commit -m "feat(p5.0): backfill skills after generation plus guarded reconciler"
```

---

### Task 9: Frontend — API client + course blocks

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/app/course/[courseId]/page.tsx`
- Test: `frontend` typecheck + build

**Interfaces:**
- Produces: `fetchCourseMastery(courseId)`, `fetchLearningPath(courseId)`, `fetchDueReviews(courseId?, limit?)`, `gradeReview(cardId, body)`; TS types `SkillMastery`, `LearningPath`, `DueReview`, `ReviewGradeResult`.

- [ ] **Step 1: Add client functions** in `lib/api.ts` following the existing `api<T>()` pattern (CSRF is automatic for non-GET).

- [ ] **Step 2: Add the two blocks** in the course page: "Học tiếp" (title + reason message, or `blockedBy` explanation + a link to the fallback review lesson) and "Ôn tập (N)" linking to `/review?courseId=…`; plus a per-skill mastery bar list. Handle 503 as a neutral "Chưa bật" state so the page never breaks when the flag is off.

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: 0 type errors, successful build.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/app/course/[courseId]/page.tsx
git commit -m "feat(p5.0-ui): next-lesson, review count and mastery blocks on course page"
```

---

### Task 10: Frontend — review page + lesson notice

**Files:**
- Create: `frontend/src/app/review/page.tsx`
- Modify: `frontend/src/app/lesson/[lessonId]/page.tsx`
- Modify: `frontend/src/app/globals.css`
- Test: typecheck + build

**Interfaces:**
- Consumes: Task 9 client functions.

- [ ] **Step 1: Build the review page** — queue from `fetchDueReviews`, card shows lesson title + skill, "Hiện đáp án" reveals the recall hint (never quiz answer keys), 4 rating buttons with `aria-label`, "Còn N thẻ", one `clientReviewId` per in-flight grade held in `useRef`, buttons disabled while pending, empty state when the queue is exhausted.

- [ ] **Step 2: Lesson notice** — after a successful attempt with `reviewCardCreated === true`, show "Đã thêm vào lịch ôn tập".

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: 0 errors, build OK.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/review/page.tsx "frontend/src/app/lesson/[lessonId]/page.tsx" frontend/src/app/globals.css
git commit -m "feat(p5.0-ui): spaced-repetition review page and lesson notice"
```

---

### Task 11: E2E checks, docs and progress report

**Files:**
- Modify: `backend/e2e_acceptance.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml` (backend/worker/beat env)
- Modify: `docs/development-progress.md`
- Modify: `docs/database-design.md`
- Modify: `docs/migration-runbook.md`
- Modify: `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`

- [ ] **Step 1: Add E2E checks** — with `P50_ENABLED=true`: mastery endpoint returns items after an attempt; learning-path returns a reason code; grade a review card returns `duplicate=false` then `duplicate=true` on the same `clientReviewId`. Confirm the default (flag off) run is byte-for-byte unchanged in existing checks.

- [ ] **Step 2: Add env plumbing** — `.env.example` and the three compose services get `P50_ENABLED`, `P50_BACKFILL_ENABLED`, `MASTERY_PASS_THRESHOLD`, `MASTERY_RECENCY_HALF_LIFE_DAYS`, `FSRS_DESIRED_RETENTION`.

- [ ] **Step 3: Run the full verification**

Run: `cd backend && python -m pytest -q`
Run: `cd frontend && npx tsc --noEmit && npm run build`
Run: `git diff --check`
Expected: all green.

- [ ] **Step 4: Write the progress entry** following the repo's phase-report template, marking IMPLEMENTED / TESTED / NOT TESTED / BLOCKED explicitly. Must state: mastery is a heuristic (not a probability), FSRS intervals measured from the pinned library version, and that no real-dataset calibration has been done (PROPOSAL thresholds).

- [ ] **Step 5: Commit**

```bash
git add backend/e2e_acceptance.py .env.example docker-compose.yml docs/
git commit -m "docs(p5.0): e2e checks, env plumbing and phase report"
```

---

## Self-Review

**Spec coverage:** §5 tables → Task 2; §6 backfill → Task 3; §7 mastery → Task 4; §8 FSRS → Task 5; §9 learning path → Task 6; §10 API → Task 7; §11 frontend → Tasks 9–10; §12 tests → every task plus Task 11; §13 safety → Tasks 4, 5, 7; §16 decisions → Tasks 4, 5, 6 and the global constraints.

**Step scan:** Every step names an exact file, signature or command with expected output. No "handle edge cases" lines; the four edge cases in Review Focus each have a named test (missing skill → Task 4 test; `score_total == 0` → Task 4 division guard + Task 5 rating guard; naive datetime → Task 5 test; duplicate `clientReviewId` → Tasks 5 and 7 tests; prerequisite dead-end → Task 6 test).

**Type consistency:** `submit_attempt` changes from 2-tuple to 3-tuple — Task 4 updates both the route and the duplicate-return paths. `ensure_card_for_attempt` returns `bool` in both Tasks 4 and 5. `grade_card` returns the same dict shape in Tasks 5 and 7. `compute_mastery` takes `(attempts, now, half_life_days)` in Task 4's test and implementation. `initial_rating` returns `Rating` (Task 5 test asserts against `fsrs.Rating`).

**Known ordering note:** Task 4's Step 7 depends on Task 5's module; the plan states they may land as one commit, or Task 5 executes first.
