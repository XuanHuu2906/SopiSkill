# P5.2 — Adaptive readiness evidence + exposure logging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add (A) a read-only readiness evaluation that quantifies why DKT/LSTM and contextual bandits are not yet viable, and (B) an append-only, flag-gated exposure log with a signed token so that off-policy data starts accumulating without changing what any learner sees.

**Architecture:** A new read-only eval (`evals/p52_readiness.py`) reuses the P5.1 extractor; a new `recommendation_events` table (migration `0016`, expand-only) plus `recommendation_log_service` records one row per (user, course, context, arm); the learning-path GET gains an additive `recommendationToken` (HMAC over the server-computed context+arm) and a new CSRF-protected POST verifies that token and writes the row. Everything is gated by `P52_EXPOSURE_ENABLED` (default false → 503). No model training, no change to the recommendation order, no dependency changes.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL (prod) + SQLite in-memory (tests), hmac/hashlib from stdlib, Next.js 15 + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-11-02-p52-adaptive-readiness-design.md`

## Global Constraints

- **Plan amendment is part of the deliverable.** `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` §18 must split P5.2 into **P5.2a (research/readiness)** and **P5.2b (exposure logging, flag off)**, and §26 must get a decision-log row dated 2026-11-02 recording that the user approved the runtime part. Without those edits the runtime part must not ship.
- Never edit migrations `0001`–`0015`. New revision: `0016_p52_exposure`, `down_revision = "0015_p50_learner_profile"`.
- Migration is **expand-only**: `upgrade()` contains no `drop_table`/`drop_column`/`alter_column`, no raw `op.execute` DDL. `downgrade()` drops only `recommendation_events`.
- Migration must repeat the prerequisite guard from `0015` (`_has_table` check for `courses`, `lessons`, `users`) and raise a clear error otherwise.
- Exact constraint/index names: `uq_recommendation_event_context`, `ix_recommendation_events_course`, `ix_recommendation_events_user`.
- `P52_EXPOSURE_ENABLED` default **false**. When false: POST returns **503** `detail.code == "P52_NOT_ENABLED"`, no DB read/write of the new table, and `recommendationToken` is `null` in the GET response.
- The POST route also requires `P50_ENABLED` (it calls `build_learning_path`); if P50 is off it returns 503 `P50_NOT_ENABLED`. P52 never enables P50 implicitly.
- `arm_id` is **NOT NULL**. No nullable-arm variant; the UNIQUE constraint must be enforceable on PostgreSQL without NULL-semantics tricks.
- `lesson_content_version` is captured **at exposure time** and used for reward joins later; never read `lessons.content_version` at reward time.
- Reward is derived **offline only** (`reward_for_events`); no `reward_*` column, no UPDATE of exposure rows.
- `propensity` is written as `1.0` and the response/report must state `opeSupported=false`. No policy-value estimate is computed anywhere.
- Token: HMAC-SHA256 over a canonical JSON payload using `settings.jwt_secret`; TTL default 900 s (`P52_TOKEN_TTL_SECONDS`). Invalid signature, expired, wrong user, or wrong course ⇒ `recorded=false` with a reason code, HTTP **200**, and no row.
- Client never sends `userId`, `courseId`, `arm`, `propensity`, or a self-computed hash. Request schema uses `model_config = {"extra": "forbid"}`.
- Ownership: `course_service.get_owned_course(db, course_id, user.id)` → 404 for cross-user, before any write.
- CSRF: `verify_csrf(request)`; rate limit: `rate_limit(request, "recommendation_event", limit=60, window_seconds=60)`.
- Idempotency: UNIQUE constraint in DB + `db.begin_nested()` SAVEPOINT so a duplicate insert cannot poison the outer transaction.
- Logs: ids, hash, reason codes only. No lesson content, no mastery payload, no PII.
- Eval SQL must run on **both** SQLite and PostgreSQL: no multi-column `COUNT(DISTINCT a, b)`; use `SELECT COUNT(*) FROM (SELECT DISTINCT a, b …)`.
- `exposureId` prefix is `rce_`; add it to `course_service.ID_PREFIXES`.
- New tests go in `backend/tests/`; the existing suite (**635 passed / 28 skipped** baseline) must stay green (counts re-measured at run time, never copied).

## Review Focus

1. **Token replay across users** — user B posting user A's token must not create a row and must not leak whether A's course exists.
2. **Exposure duplication under concurrent POSTs** — two simultaneous requests with the same token must yield exactly one row and two 200 responses.
3. **Stale token after regeneration** — a token minted before `content_version` changed must not record a row that later joins the wrong version's attempts.
4. **Flag-off must not touch the table** — with `P52_EXPOSURE_ENABLED=false` on a database where `0016` was never applied, POST must return 503 rather than raising a `ProgrammingError`.
5. **Reward join correctness for the review arm** — `review_events` has no `lesson_id`; the join must go through `review_cards`, and events before `exposed_at` must be excluded.

---

### Task 1: Model + migration + ID prefix

**Files:**
- Modify: `backend/app/models/models.py` (append `RecommendationEvent`)
- Modify: `backend/app/models/__init__.py` (import + `__all__`)
- Create: `backend/alembic/versions/0016_p52_exposure.py`
- Modify: `backend/app/services/course_service.py:31-35` (add `"rce_"` to `ID_PREFIXES`)
- Test: `backend/tests/test_p52_migration_contract.py`

**Interfaces:**
- Produces: `RecommendationEvent` with columns `id, user_id, course_id, context_hash, policy_version, arm_kind, arm_id, lesson_content_version, propensity, reason_code, exposed_at, created_at`; constraint `uq_recommendation_event_context`; indexes `ix_recommendation_events_course`, `ix_recommendation_events_user`.

- [ ] **Step 1: Write the failing test**

```python
"""P5.2 migration contract — chain, expand-only, names, metadata. Không cần DB sống."""

import importlib.util
import pathlib

import app.models  # noqa: F401
from app.db.base import Base

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0016_p52_exposure.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0016", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p50_head():
    module = _load()
    assert module.revision == "0016_p52_exposure"
    assert module.down_revision == "0015_p50_learner_profile"


def test_upgrade_is_expand_only_and_has_no_raw_ddl():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body
    assert "op.execute" not in upgrade_body
    assert "_has_table('courses')" in upgrade_body or '_has_table("courses")' in upgrade_body


def test_model_registered_with_exact_names():
    assert "recommendation_events" in Base.metadata.tables
    table = Base.metadata.tables["recommendation_events"]
    names = {c.name for c in table.constraints}
    assert "uq_recommendation_event_context" in names
    assert "ix_recommendation_events_course" in {i.name for i in table.indexes}
    assert "ix_recommendation_events_user" in {i.name for i in table.indexes}


def test_arm_id_is_not_nullable():
    table = Base.metadata.tables["recommendation_events"]
    assert table.c.arm_id.nullable is False
    assert table.c.lesson_content_version.nullable is False
    assert table.c.propensity.nullable is False


def test_id_prefix_parses_exposure_id():
    from app.services import course_service

    uid = "12345678-1234-5678-1234-567812345678"
    assert course_service.parse_prefixed_uuid(f"rce_{uid}") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p52_migration_contract.py -q`
Expected: FAIL — `FileNotFoundError` for the migration / missing table.

- [ ] **Step 3: Add the model**

Append to `backend/app/models/models.py` (mirroring `ReviewEvent` style, Vietnamese docstring):

```python
class RecommendationEvent(Base):
    """Audit append-only của MỘT lần gợi ý đã hiển thị (P5.2b).

    Không có `reward_*`: reward suy ra offline bằng JOIN với `lesson_attempts`
    (theo `arm_id` + `lesson_content_version`) và `review_events` (qua
    `review_cards.lesson_id`).

    UNIQUE = "một exposure cho mỗi (user, course, context, arm)", KHÔNG phải đếm
    impression. Bandit cần impression count thì phải thêm bảng riêng.

    `propensity = 1.0` phản ánh policy deterministic hiện tại ⇒ OPE chưa hợp lệ.
    """
```

Columns declared with `Mapped[...]`: `id` UUID PK default `_uuid`; `user_id` FK `users.id` `ondelete="CASCADE"` index; `course_id` FK `courses.id` `ondelete="CASCADE"`; `context_hash` `String(64)`; `policy_version` `Text`; `arm_kind` `Text`; `arm_id` `UUID` not null; `lesson_content_version` `Integer`; `propensity` `Float`; `reason_code` `Text`; `exposed_at` `DateTime(timezone=True)`; `created_at` server_default `func.now()`.
`__table_args__` = `(UniqueConstraint("user_id","course_id","context_hash","arm_kind","arm_id", name="uq_recommendation_event_context"), Index("ix_recommendation_events_course","course_id","exposed_at"), Index("ix_recommendation_events_user","user_id","exposed_at"))`.

Export it in `backend/app/models/__init__.py` (import list + `__all__`).

- [ ] **Step 4: Write the migration**

`0016_p52_exposure.py` follows `0015` exactly: module-level `revision`/`down_revision`, `_inspector()`/`_has_table()` helpers, a guard raising `RuntimeError` if `courses`/`lessons`/`users` are missing, `upgrade()` creating the table only when `not _has_table("recommendation_events")`, and `downgrade()` dropping only that table when present. Use `op.create_table`, `op.create_index` — never `op.execute`.

- [ ] **Step 5: Add the ID prefix**

Add `"rce_"` to `ID_PREFIXES` in `backend/app/services/course_service.py` under a `# P5.2 exposure` comment.

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_p52_migration_contract.py -q && python -m pytest -q`
Expected: contract tests pass; full suite green with the pre-existing tests unaffected.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models backend/alembic/versions/0016_p52_exposure.py backend/app/services/course_service.py backend/tests/test_p52_migration_contract.py
git commit -m "feat(p5.2): recommendation_events model and expand-only migration"
```

---

### Task 2: Token minting and verification

**Files:**
- Create: `backend/app/services/recommendation_token_service.py`
- Modify: `backend/app/core/config.py` (near the P5.0 block)
- Test: `backend/tests/test_p52_token.py`

**Interfaces:**
- Produces:
  - `def mint(*, user_id: str, course_id: str, arm_kind: str, arm_id: str, context_hash: str, lesson_content_version: int, policy_version: str, now: datetime | None = None) -> str`
  - `class TokenError(Exception)` with `.reason` in `{"TOKEN_INVALID","TOKEN_EXPIRED"}`
  - `def verify(token: str, *, user_id: str, course_id: str, now: datetime | None = None) -> dict` returning the payload dict
  - `def context_hash_from_path(payload: dict) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""P5.2 token — ký/verify, hết hạn, sai user/course, canonical hash."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services import recommendation_token_service as tok


def _mint(**over):
    base = dict(
        user_id=str(uuid.uuid4()),
        course_id=str(uuid.uuid4()),
        arm_kind="next_lesson",
        arm_id=str(uuid.uuid4()),
        context_hash="a" * 64,
        lesson_content_version=1,
        policy_version="p5.0-rule-v1",
    )
    base.update(over)
    return base


def test_mint_then_verify_roundtrip():
    args = _mint()
    token = tok.mint(**args)
    payload = tok.verify(token, user_id=args["user_id"], course_id=args["course_id"])
    assert payload["armKind"] == args["arm_kind"]
    assert payload["armId"] == args["arm_id"]
    assert payload["lessonContentVersion"] == 1


def test_verify_rejects_other_user():
    args = _mint()
    token = tok.mint(**args)
    with pytest.raises(tok.TokenError) as exc:
        tok.verify(token, user_id=str(uuid.uuid4()), course_id=args["course_id"])
    assert exc.value.reason == "TOKEN_INVALID"


def test_verify_rejects_other_course():
    args = _mint()
    token = tok.mint(**args)
    with pytest.raises(tok.TokenError):
        tok.verify(token, user_id=args["user_id"], course_id=str(uuid.uuid4()))


def test_verify_rejects_tampered_token():
    args = _mint()
    token = tok.mint(**args)
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(tok.TokenError):
        tok.verify(tampered, user_id=args["user_id"], course_id=args["course_id"])


def test_verify_rejects_expired():
    args = _mint()
    issued = datetime(2026, 1, 1, tzinfo=UTC)
    token = tok.mint(**args, now=issued)
    with pytest.raises(tok.TokenError) as exc:
        tok.verify(
            token,
            user_id=args["user_id"],
            course_id=args["course_id"],
            now=issued + timedelta(hours=2),
        )
    assert exc.value.reason == "TOKEN_EXPIRED"


def test_context_hash_is_order_independent():
    path_a = {
        "nextLesson": {"lessonId": "lsn_a", "title": "A", "reason": {"code": "X"}},
        "reviewLessonId": None,
        "reviewDueCount": 2,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [{"id": "s1"}], "edges": []},
    }
    path_b = {
        "prerequisitesDag": {"edges": [], "nodes": [{"id": "s1"}]},
        "blockedBy": [],
        "reviewDueCount": 2,
        "reviewLessonId": None,
        "nextLesson": {"reason": {"code": "X"}, "title": "A", "lessonId": "lsn_a"},
    }
    assert tok.context_hash_from_path(path_a) == tok.context_hash_from_path(path_b)
    assert len(tok.context_hash_from_path(path_a)) == 64


def test_context_hash_changes_with_arm():
    base = {"nextLesson": {"lessonId": "lsn_a"}, "reviewLessonId": None,
            "reviewDueCount": 0, "blockedBy": [], "prerequisitesDag": {"nodes": [], "edges": []}}
    other = {**base, "nextLesson": {"lessonId": "lsn_b"}}
    assert tok.context_hash_from_path(base) != tok.context_hash_from_path(other)


def test_mint_requires_secret(monkeypatch):
    from app.services import recommendation_token_service as mod

    monkeypatch.setattr(mod, "_secret", lambda: "")
    with pytest.raises(RuntimeError):
        mod.mint(**_mint())
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_p52_token.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the service**

Add to `backend/app/core/config.py`, beside `p50_enabled`:

```python
    # P5.2b — exposure logging (mặc định TẮT). Token HMAC dùng jwt_secret.
    p52_exposure_enabled: bool = False
    p52_token_ttl_seconds: int = 900
```

Implementation notes (pin these):
- `_secret()` reads `get_settings().jwt_secret`; empty ⇒ `RuntimeError("P52_TOKEN_NOT_CONFIGURED")`.
- Payload JSON canonical: `{"v":1,"uid":…,"cid":…,"kind":…,"aid":…,"ctx":…,"cv":…,"pv":…,"iat":…}` with `sort_keys=True, separators=(",",":")`.
- Token format `"<b64url(payload_json)>.<b64url(hmac_sha256)>"`; verify recomputes with `hmac.compare_digest`.
- `verify` raises `TokenError("TOKEN_EXPIRED")` when `now - iat > ttl`, `TokenError("TOKEN_INVALID")` for signature/user/course/shape mismatches.
- `context_hash_from_path`: build a **narrow** dict from the learning-path response — `{"next": nextLesson.lessonId|None, "review": reviewLessonId|None, "due": reviewDueCount, "blocked": sorted(blockedBy lessonIds)}` — then `sha256(json canonical).hexdigest()`. Deliberately excludes titles/messages so wording changes do not break tokens.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_p52_token.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recommendation_token_service.py backend/app/core/config.py backend/tests/test_p52_token.py
git commit -m "feat(p5.2): HMAC recommendation token mint/verify"
```

---

### Task 3: Exposure service (idempotent write + offline reward)

**Files:**
- Create: `backend/app/services/recommendation_log_service.py`
- Test: `backend/tests/test_p52_exposure_service.py`

**Interfaces:**
- Consumes: `RecommendationEvent` (Task 1), `recommendation_token_service.context_hash_from_path` (Task 2).
- Produces:
  - `POLICY_VERSION = "p5.0-rule-v1"`
  - `def derive_arm(path: dict) -> tuple[str, str, str]` → `(arm_kind, arm_id_uuid_str, reason_code)`; raises `NoArmError`
  - `async def record_exposure(db, *, user_id, course, path, lesson_content_version, now=None) -> dict` → `{"recorded": bool, "duplicate": bool, "exposureId": str|None, "reason": str|None}`
  - `async def reward_for_events(db, events, *, window_days=14) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
"""P5.2 exposure service — derive arm, idempotency, reward offline."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Course, Lesson, RecommendationEvent, Unit, User
from app.services import recommendation_log_service as svc


def _path(next_id: str | None, review_id: str | None = None) -> dict:
    return {
        "nextLesson": {"lessonId": next_id, "title": "T", "reason": {"code": "NEXT_IN_SEQUENCE"}}
        if next_id
        else None,
        "reviewLessonId": review_id,
        "reviewDueCount": 0,
        "blockedBy": [],
        "prerequisitesDag": {"nodes": [], "edges": []},
    }


def test_derive_arm_prefers_next_lesson():
    kind, arm, reason = svc.derive_arm(_path("lsn_" + str(uuid.uuid4())))
    assert kind == "next_lesson"
    assert reason == "NEXT_IN_SEQUENCE"


def test_derive_arm_review_uses_fallback_reason():
    kind, arm, reason = svc.derive_arm(_path(None, "lsn_" + str(uuid.uuid4())))
    assert kind == "review_lesson"
    assert reason == "FALLBACK_REVIEW_WEAKEST"


def test_derive_arm_raises_when_no_arm():
    import pytest

    with pytest.raises(svc.NoArmError):
        svc.derive_arm(_path(None, None))


async def _seed() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with SessionLocal() as db:
        user = User(external_id=f"p52-{uuid.uuid4().hex[:8]}", xp=0)
        db.add(user)
        await db.flush()
        course = Course(user_id=user.id, topic="P52", status="ready",
                        client_course_id=f"c-{uuid.uuid4().hex[:12]}")
        db.add(course)
        await db.flush()
        unit = Unit(course_id=course.id, order_index=0, title="U", blurb="")
        db.add(unit)
        await db.flush()
        lesson = Lesson(unit_id=unit.id, course_id=course.id, order_index=0,
                        title="L", content=[], content_version=3, status="ready")
        db.add(lesson)
        await db.commit()
        return user.id, course.id, lesson.id


async def test_record_exposure_is_idempotent():
    user_id, course_id, lesson_id = await _seed()
    path = _path(f"lsn_{lesson_id}")
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        first = await svc.record_exposure(db, user_id=user_id, course=course, path=path,
                                          lesson_content_version=3)
        assert first["recorded"] is True
        assert first["duplicate"] is False
        for _ in range(5):
            again = await svc.record_exposure(db, user_id=user_id, course=course, path=path,
                                              lesson_content_version=3)
            assert again["duplicate"] is True
            assert again["exposureId"] == first["exposureId"]
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(RecommendationEvent).where(RecommendationEvent.course_id == course_id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].propensity == 1.0
        assert rows[0].policy_version == svc.POLICY_VERSION


async def test_record_exposure_distinguishes_contexts():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        a = await svc.record_exposure(db, user_id=user_id, course=course,
                                      path=_path(f"lsn_{lesson_id}"), lesson_content_version=3)
        b = await svc.record_exposure(db, user_id=user_id, course=course,
                                      path=_path(None, f"lsn_{lesson_id}"),
                                      lesson_content_version=3)
        assert a["exposureId"] != b["exposureId"]
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(RecommendationEvent).where(RecommendationEvent.course_id == course_id)
        )).scalars().all()
        assert len(rows) == 2


async def test_reward_for_events_none_when_no_signal():
    user_id, course_id, lesson_id = await _seed()
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        res = await svc.record_exposure(db, user_id=user_id, course=course,
                                        path=_path(f"lsn_{lesson_id}"),
                                        lesson_content_version=3)
    async with SessionLocal() as db:
        events = (await db.execute(
            select(RecommendationEvent).where(RecommendationEvent.course_id == course_id)
        )).scalars().all()
        rewards = await svc.reward_for_events(db, events)
        assert rewards[0]["reward"] is None
        assert rewards[0]["rewardSource"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_p52_exposure_service.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the service**

Pin these behaviours:
- `derive_arm`: next lesson wins; else review lesson with reason `FALLBACK_REVIEW_WEAKEST`; else raise `NoArmError`. Parse ids with `course_service.parse_prefixed_uuid` and raise `NoArmError` if unparseable.
- `record_exposure`: compute `context_hash` via the token service, `arm = derive_arm(path)`; check for an existing row with the same `(user_id, course_id, context_hash, arm_kind, arm_id)`; if present return it with `duplicate=True`. Otherwise insert inside `async with db.begin_nested():`, catch `IntegrityError` → rollback the savepoint, re-select the winner, return `duplicate=True`. **Never** commit the outer transaction; the caller owns it.
- `reward_for_events`: for each event, query the **first** attempt after `exposed_at` within `window_days` matching `lesson_id == arm_id AND content_version == lesson_content_version`; if none, query the first `ReviewEvent` joined through `ReviewCard` with `ReviewCard.lesson_id == arm_id AND ReviewEvent.reviewed_at > exposed_at`; emit `{"exposureId", "reward": float|None, "rewardSource": "attempt"|"review"|None, "latencyHours": float|None}`. Use a read-only session; never write.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_p52_exposure_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/recommendation_log_service.py backend/tests/test_p52_exposure_service.py
git commit -m "feat(p5.2): idempotent exposure write and offline reward derivation"
```

---

### Task 4: API — token on GET, POST endpoint, flag gating

**Files:**
- Modify: `backend/app/schemas/schemas.py` (`LearningPathOut.recommendationToken`, new request/response models)
- Modify: `backend/app/api/v1/learner.py` (GET mints token; POST route)
- Test: `backend/tests/test_p52_api.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `POST /v1/courses/{course_id}/recommendation-events` → 503 when either flag is off, else `{"recorded","duplicate","exposureId","reason"}`.

- [ ] **Step 1: Write the failing test**

```python
"""P5.2 API — flag gating, ownership, CSRF, rate limit, token, idempotency."""

import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import RecommendationEvent

PASSWORD = "Passw0rd!123"


def csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


async def _register(client) -> str:
    email = f"p52-{uuid.uuid4().hex[:8]}@test.dev"
    r = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return email


async def _course_with_token(client) -> tuple[str, str | None]:
    """Tạo course ready + learning path; trả (courseId, recommendationToken)."""
    # Dùng helper seed sẵn có: xem tests/test_p50_api.py::_seed_course_with_lesson
    ...


async def test_post_requires_flag(client):
    await _register(client)
    course_id, _ = await _course_with_token(client)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": "x"},
        headers=csrf(client),
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "P52_NOT_ENABLED"


async def test_post_happy_path_then_duplicate(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "p52_exposure_enabled", True)
    monkeypatch.setattr(s, "p50_enabled", True)
    await _register(client)
    course_id, token = await _course_with_token(client)
    assert token
    first = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert first.status_code == 200, first.text
    assert first.json()["recorded"] is True
    second = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True


async def test_post_rejects_extra_fields(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "p52_exposure_enabled", True)
    monkeypatch.setattr(s, "p50_enabled", True)
    await _register(client)
    course_id, token = await _course_with_token(client)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token, "arm": "forged", "propensity": 0.5},
        headers=csrf(client),
    )
    assert r.status_code == 422


async def test_post_requires_csrf(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "p52_exposure_enabled", True)
    monkeypatch.setattr(s, "p50_enabled", True)
    await _register(client)
    course_id, token = await _course_with_token(client)
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
    )
    assert r.status_code == 403


async def test_post_cross_user_is_404(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "p52_exposure_enabled", True)
    monkeypatch.setattr(s, "p50_enabled", True)
    await _register(client)
    course_id, token = await _course_with_token(client)
    await client.post("/v1/auth/logout", headers=csrf(client))
    await _register(client)  # user B
    r = await client.post(
        f"/v1/courses/{course_id}/recommendation-events",
        json={"recommendationToken": token},
        headers=csrf(client),
    )
    assert r.status_code == 404


async def test_get_includes_null_token_when_flag_off(client):
    await _register(client)
    course_id, token = await _course_with_token(client)
    assert token is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_p52_api.py -q`
Expected: FAIL — 404/route missing.

- [ ] **Step 3: Implement**

Schemas:
```python
class RecommendationEventRequest(BaseModel):
    recommendationToken: str = Field(min_length=8, max_length=4096)
    model_config = {"extra": "forbid"}

class RecommendationEventOut(BaseModel):
    recorded: bool
    duplicate: bool = False
    exposureId: str | None = None
    reason: str | None = None
```
Add `recommendationToken: str | None = None` to `LearningPathOut`.

Route changes in `learner.py`:
- In `get_learning_path`, after computing `payload`, if `settings.p52_exposure_enabled` and `payload` has an arm, mint a token and set `payload["recommendationToken"]`; wrap minting in `try/except Exception` → log warning, set token `None` (a token failure must never break the learning-path response).
- New route: check `p52_exposure_enabled` (503 `P52_NOT_ENABLED`) → check `p50_enabled` (503 `P50_NOT_ENABLED`) → `verify_csrf` → `rate_limit` → `get_owned_course` (404) → `verify` token with the same `user.id`/`course.id` (on `TokenError` return `Recorded(False, reason=exc.reason)`) → rebuild the learning path → compare token `ctx`/`cv` against the freshly computed `context_hash` and the arm's `lesson.content_version` (mismatch ⇒ `recorded=False, reason="CONTEXT_STALE"`) → `record_exposure` → commit → return `f"rce_{row_id}"`.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_p52_api.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/schemas.py backend/app/api/v1/learner.py backend/tests/test_p52_api.py
git commit -m "feat(p5.2): recommendation-events endpoint and signed learning-path token"
```

---

### Task 5: Readiness evaluation + flag plumbing + frontend

**Files:**
- Create: `backend/evals/p52_readiness.py`
- Modify: `.env.example`, `docker-compose.yml` (3 services: backend, worker, beat)
- Modify: `frontend/src/lib/api.ts` (type + `recordRecommendation`)
- Modify: `frontend/src/app/course/[courseId]/page.tsx` (one effect)

**Interfaces:**
- Consumes: `mastery_dataset.detect_tables`/`redact_dsn`, `recommendation_log_service.POLICY_VERSION`.

- [ ] **Step 1: Write the readiness eval**

CLI: `python -m evals.p52_readiness [--database-url …] [--json] [--save]`. Read-only; reuse the P5.1 engine pattern (`create_async_engine(dsn)` + `detect_tables` + `run_sync(inspect)`); never `create_all`.

Metrics (SQL that works on SQLite **and** PostgreSQL):
- `attempts`, `usersWithAttempts`, `maxAttemptsPerUser`, and user counts at 5/10/20 via a subquery + `CASE WHEN`.
- `sequencesGe5` via `mastery_dataset.load_sequences(...)`.
- `coursesWithGe2Users` via `SELECT COUNT(*) FROM (SELECT c.id FROM courses c JOIN units u ON u.course_id=c.id JOIN lessons l ON l.unit_id=u.id JOIN lesson_attempts a ON a.lesson_id=l.id GROUP BY c.id HAVING COUNT(DISTINCT a.user_id) >= 2)`.
- Exposure metrics guarded by table presence: `exposureRows`, `distinctPolicies`, `distinctArms` (subquery `SELECT DISTINCT arm_kind, arm_id`), `propensityMin/Max`.

Thresholds (PROPOSAL, in `--help`): DKT needs `usersGe10 >= 500`, `sequencesGe5 >= 200`, `coursesWithGe2Users >= 50`; bandit needs `exposureRows >= 5000`, `distinctPolicies >= 2`, `distinctArms >= 3`, and `propensityMax - propensityMin >= 0.1`. Emit `{"status","dkt":{"verdict","reasons"},"bandit":{"verdict","reasons"},"metrics","opeSupported": false}`.

- [ ] **Step 2: Run the readiness eval against the real DB**

```bash
cd backend
python -m evals.p52_readiness --database-url "postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp"
```
Expected: exit 0, both verdicts `BLOCKED` with quantitative reasons, `opeSupported=false`. Do not fabricate thresholds that pass.

- [ ] **Step 3: Add flags to env plumbing**

`.env.example`: append a P5.2 block documenting `P52_EXPOSURE_ENABLED=false` and `P52_TOKEN_TTL_SECONDS=900`, each with a one-line Vietnamese note that off-by-default keeps behaviour unchanged and that propensity is 1.0 (no OPE yet). `docker-compose.yml`: add both variables to the `backend`, `worker`, and `beat` service environments, mirroring how the P5.0 variables are wired.

- [ ] **Step 4: Wire the frontend**

`frontend/src/lib/api.ts`: add `recommendationToken: string | null` to `LearningPath`; add

```ts
export function recordRecommendation(
  courseId: string,
  recommendationToken: string
): Promise<{ recorded: boolean; duplicate: boolean; exposureId: string | null; reason: string | null }> {
  return api(`/v1/courses/${courseId}/recommendation-events`, {
    method: "POST",
    body: JSON.stringify({ recommendationToken }),
  });
}
```

`frontend/src/app/course/[courseId]/page.tsx`: a `useRef<string | null>` holding the last token sent; a `useEffect` that, when `learningPath.data?.recommendationToken` exists and differs from the ref, sets the ref and calls `recordRecommendation(...).catch(() => {})`. No loading/error UI, no cache invalidation.

- [ ] **Step 5: Verify frontend**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: 0 type errors; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add backend/evals/p52_readiness.py .env.example docker-compose.yml frontend/src/lib/api.ts "frontend/src/app/course/[courseId]/page.tsx"
git commit -m "feat(p5.2): readiness evaluation, flag plumbing and exposure instrumentation"
```

---

### Task 6: Docs, plan amendment, phase report

**Files:**
- Create: `docs/specs/24-P52-ADAPTIVE-READINESS.md`
- Modify: `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` (§3 table row, §18 split, §26 decision log)
- Modify: `docs/specs/12-ADAPTIVE-LEARNING.md`
- Modify: `docs/development-progress.md`

- [ ] **Step 1: Write the spec** covering: why P5.2 is split into a/b, the readiness metrics and thresholds, the exposure schema with the explicit "one exposure per (context, arm), not impression count" decision, the token design, `propensity=1.0` and `opeSupported=false`, the reward join paths (attempt + review-through-card), the CASCADE exception to append-only, and the readiness output from Task 5 Step 2 verbatim.

- [ ] **Step 2: Amend the master plan** — §3 row becomes `P5.2a DONE (research) / P5.2b DONE (flag off)`; §18 splits into two sub-lists with honest checkboxes (`[x]` for what shipped, `[ ]` for "huấn luyện DKT/bandit" with `BLOCKED`); §26 gets the dated decision row recording the user's approval of the runtime part and the reason.

- [ ] **Step 3: Update `docs/specs/12-ADAPTIVE-LEARNING.md`** — extend the BKT block with a P5.2 paragraph: no model shipped, exposure logging exists but is off, propensity 1.0 means no OPE yet.

- [ ] **Step 4: Add the phase report** to `docs/development-progress.md` using the repo's template, with the real command output: readiness metrics, `python -m pytest -q` counts from this session, migration evidence, and `PHASE GATE`.

- [ ] **Step 5: Commit**

```bash
git add docs
git commit -m "docs(p5.2): adaptive readiness evidence and exposure logging status"
```

---

### Task 7: PostgreSQL migration + concurrency verification

**Files:** none (verification only; record results in the progress doc).

- [ ] **Step 1: Verify migration on a throwaway PostgreSQL database**

```bash
docker compose exec -T db psql -U ailp -d postgres -c "CREATE DATABASE p52_migration_check;"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p52_migration_check" python -m alembic upgrade head
docker compose exec -T db psql -U ailp -d p52_migration_check -c "\d recommendation_events"
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p52_migration_check" python -m alembic downgrade -1
docker compose exec -T db psql -U ailp -d p52_migration_check -c "\d recommendation_events"
```
Expected: table with the three named constraints/indexes after upgrade; `Did not find any relation named "recommendation_events"` after downgrade; `users`/`courses` still present. Then `DROP DATABASE p52_migration_check;` (throwaway DB only — never the main one).

- [ ] **Step 2: Concurrency test for idempotent exposure**

Add `backend/tests/test_p52_postgres_concurrency.py` following `test_p50_postgres_concurrency.py`'s pattern (skip when `POSTGRES_TEST_URL` is unset): fire 6 concurrent `record_exposure` calls for the same path, assert exactly one row and that every task returned without raising. Run:

```bash
POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p52_race_check python -m pytest tests/test_p52_postgres_concurrency.py -q
```
Expected: all pass. Drop the throwaway database afterwards.

- [ ] **Step 3: Full suite**

Run: `cd backend && python -m pytest -q`
Expected: all green; record the exact counts.

- [ ] **Step 4: Commit any fix + update the progress report with these results**

---

## Self-Review Notes

- Spec coverage: §5 → Task 5 Step 1; §6.1 → Task 1; §6.2 → Task 3; §6.3 → Task 4; §7 → Task 3 `reward_for_events` + Task 5; §8 file list → Tasks 1–6; §9 security → Tasks 1/3/4 assertions; §10 acceptance → Tasks 4/7.
- Review Focus mapping: (1) token cross-user → `test_post_cross_user_is_404` + token `verify` tests; (2) concurrent duplicate → Task 7 Step 2; (3) stale token → `CONTEXT_STALE` path in Task 4 Step 3, asserted via a mismatch test added in Task 4; (4) flag-off without table → `test_post_requires_flag` runs before any migration in the SQLite suite; (5) review reward join through `review_cards` → Task 3 implementation note + a reward test that seeds a `ReviewCard`/`ReviewEvent` pair.
- Type consistency: `record_exposure` returns the same dict shape in Tasks 3 and 4; `exposureId` is `rce_<uuid>` in both the service payload and the API response.
- Nothing in the plan trains a model, changes recommendation order, or adds a dependency.
