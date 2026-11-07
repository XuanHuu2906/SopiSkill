# P5.1 — Bayesian Knowledge Tracing (research-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline, pure-Python BKT module plus a read-only dataset extractor and evaluation harness that honestly reports `INSUFFICIENT_DATA` on the current database while validating the algorithm on clearly-labelled simulated sequences — without touching runtime, schema, or APIs.

**Architecture:** Three additive files under `backend/app/services/bkt.py` (pure math), `backend/evals/mastery_dataset.py` (read-only DB extraction with capability detection), and `backend/evals/bkt_eval.py` (CLI: real vs simulated, user/time splits, Brier/log-loss/AUC/ECE/drift, gate evaluation). Two new test files exercise the math and the extractor on SQLite in-memory at both the pre-P5.0 (`0012`) and post-P5.0 (`0015`) table shapes. No Alembic revision, no model changes, no routes, no config flags, no frontend.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async (aiosqlite/asyncpg), pytest + pytest-asyncio, stdlib only for math (no numpy/sklearn).

**Spec:** `docs/superpowers/specs/2026-11-02-p51-bkt-research-design.md`

## Global Constraints

- **No runtime change:** do not modify `backend/app/models/models.py`, `backend/alembic/`, `backend/app/api/`, `backend/frontend`, `backend/app/core/config.py`, `backend/app/services/learner_profile_service.py`, `backend/app/services/learning_path_service.py`.
- **No new dependencies.** `backend/requirements.txt` must remain byte-identical. Pure-Python math only.
- **Read-only extraction.** `mastery_dataset.py` and `bkt_eval.py` must never call `Base.metadata.create_all`, `conn.commit()`, or any INSERT/UPDATE/DELETE. Connect to the DSN given by `--database-url` or `DATABASE_URL`.
- **`inspect()` on async engines is invalid.** Always use `await engine.connect()` + `await conn.run_sync(lambda s: inspect(s).get_table_names())`.
- Aligned with P5.0's version policy: only attempts where `lesson_attempts.content_version == lessons.content_version` and `score_total > 0` become events.
- Target variable for both models is **soft** `y = score_correct / score_total` in `[0, 1]`. Brier is `(p - y)²`.
- All probabilities clamped to `[1e-9, 1 - 1e-9]`. `BktParams` validation: `0 < p < 1` for each; `p_guess + p_slip < 1`.
- `predict_sequence(observations)[i]` may only use `observations[:i]` (no future leakage, no fitting on test).
- Split leakage check is mandatory: no `user_id` may appear in both train and test; report must contain `leakage: 0`.
- All timestamps normalized to timezone-aware UTC before arithmetic.
- Output and docstrings in Vietnamese, matching the repo convention; machine-readable keys (`status`, `gate`, `dataSource`) stay English.
- Report JSON goes to `backend/evals/reports/` (already gitignored). Console output must be Windows-safe: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in a `try/except`.
- No secrets in logs: redact the DSN password before printing.
- Deterministic: simulated mode takes `--seed` (default `20261102`); grid search is fixed and ordered.

## Review Focus

1. **Empty/short sequences** (0 or 1 event): extractor must not crash, and the evaluator must count them as insufficient rather than dividing by zero.
2. **Stale `content_version` attempts** (90 of 127 in the current DB): must be excluded from events, and the report must show both raw and filtered counts so the exclusion is auditable.
3. **Schema at `0012`** (no `skills`/`lesson_skills` tables): extractor must detect this, fall back to lesson granularity, and set `skillGranularity=false` — not raise.
4. **Utterly insufficient real data** (0 sequences ≥ min length): `bkt_eval --dataset real` must print `INSUFFICIENT_DATA` with the exact failing threshold and exit 0, never `PASS`.
5. **Simulated data that does not match the model** (e.g. sequence generated with `p_learn=0`): the report must show BKT not beating baseline, and must never claim deployment value.

---

### Task 1: Pure BKT math module

**Files:**
- Create: `backend/app/services/bkt.py`
- Test: `backend/tests/test_p51_bkt.py`

**Interfaces:**
- Produces:
  - `class BktParams` frozen dataclass with `p_init=0.3, p_learn=0.2, p_guess=0.2, p_slip=0.1`
  - `validate(params: BktParams) -> None` (raises `ValueError`)
  - `observe(prior: float, y: float, params: BktParams) -> float`
  - `apply_learning(posterior: float, params: BktParams) -> float`
  - `predict_correct(priors: Sequence[float], params: BktParams) -> list[float]`
  - `predict_sequence(observations: Sequence[float], params: BktParams) -> list[float]`
  - `fit_grid(train: Sequence[Sequence[float]], grid: Sequence[BktParams]) -> tuple[BktParams, float]` returns best params + train Brier
  - `brier(preds: Sequence[float], targets: Sequence[float]) -> float`
  - `EPS = 1e-9`

- [ ] **Step 1: Write the failing test**

```python
"""P5.1 BKT thuần — clamp, công thức, hội tụ, chống leakage."""
import math
import pytest
from app.services import bkt


def _seq_to_events(obs):
    return list(obs)


def test_validate_rejects_out_of_range():
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_init=0.0))
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_learn=1.0))
    with pytest.raises(ValueError):
        bkt.validate(bkt.BktParams(p_guess=0.6, p_slip=0.5))


def test_observe_clamps_extremes():
    params = bkt.BktParams()
    # quan sát mềm với y=1 và prior thấp: posterior phải < 1 tuyệt đối
    p = bkt.observe(0.01, 1.0, params)
    assert bkt.EPS <= p <= 1 - bkt.EPS
    p0 = bkt.observe(0.99, 0.0, params)
    assert bkt.EPS <= p0 <= 1 - bkt.EPS


def test_observe_hard_limits_match_bayes():
    # slip=0.1, guess=0.2, prior=0.5, y=1 -> 0.9*0.5 / (0.9*0.5 + 0.2*0.5) = 0.8181...
    params = bkt.BktParams(p_guess=0.2, p_slip=0.1, p_learn=0.0, p_init=0.5)
    got = bkt.observe(0.5, 1.0, params)
    assert got == pytest.approx(0.9 * 0.5 / (0.9 * 0.5 + 0.2 * 0.5))


def test_apply_learning_monotone_and_clamped():
    params = bkt.BktParams(p_learn=0.2)
    out = bkt.apply_learning(0.5, params)
    expected = 0.5 + (1 - 0.5) * 0.2
    assert out == pytest.approx(expected)
    assert out > 0.5
    assert bkt.apply_learning(1 - bkt.EPS, params) <= 1 - bkt.EPS


def test_predict_correct_formula():
    params = bkt.BktParams(p_guess=0.2, p_slip=0.1)
    probs = bkt.predict_correct([0.5], params)
    assert probs[0] == pytest.approx(0.5 * 0.9 + 0.5 * 0.2)


def test_predict_sequence_no_future_leakage():
    params = bkt.BktParams()
    first = bkt.predict_sequence([1, 1, 1, 1], params)
    # đổi các quan sát sau vị trí 0 không được đổi dự đoán vị trí 0
    changed = bkt.predict_sequence([1, 0, 0, 0], params)
    assert first[0] == pytest.approx(changed[0])


def test_predict_sequence_all_correct_increases():
    params = bkt.BktParams()
    preds = bkt.predict_sequence([1.0] * 6, params)
    assert all(preds[i] <= preds[i + 1] for i in range(len(preds) - 1))


def test_predict_sequence_all_wrong_decreases():
    params = bkt.BktParams()
    preds = bkt.predict_sequence([0.0] * 6, params)
    assert all(preds[i] >= preds[i + 1] for i in range(len(preds) - 1))


def test_soft_observation_converges_to_hard():
    params = bkt.BktParams()
    hard = bkt.predict_sequence([1.0] * 5, params)
    soft = bkt.predict_sequence([0.999999] * 5, params)
    for a, b in zip(hard, soft):
        assert a == pytest.approx(b, abs=1e-4)


def test_brier_bounds():
    assert bkt.brier([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert bkt.brier([0.0, 1.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_fit_grid_is_deterministic_and_returns_train_brier():
    train = [[1.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 0.0]]
    grid = [bkt.BktParams(p_learn=x) for x in (0.05, 0.2, 0.5)]
    first = bkt.fit_grid(train, grid)
    second = bkt.fit_grid(train, grid)
    assert first[0] == second[0]
    assert first[1] == pytest.approx(second[1])
    assert first[1] >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p51_bkt.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.bkt'`

- [ ] **Step 3: Implement `backend/app/services/bkt.py`**

Docstring must state: this is research-only, never imported by runtime paths, target is soft `y`, and `p_learn` applies after each observation.

Soft-Bayes definitions (put these in the docstring, implement exactly):
- `_likelihood_mastered(y, p)` = `(1 - slip) * y + slip * (1 - y)`
- `_likelihood_not(y, p)` = `guess * y + (1 - guess) * (1 - y)`
- `observe(prior, y)`: `num = _likelihood_mastered * prior`, `den = num + _likelihood_not * (1 - prior)`, return `clamp(num/den)` (guard `den <= 0` by returning clamped prior).
- `apply_learning(post)` = `clamp(post + (1 - post) * p_learn)`
- `predict_correct(priors)` = `[clamp(p * (1 - slip) + (1 - p) * guess) for p in priors]`
- `predict_sequence(obs)`: `priors = [p_init]`; loop: predict from current prior via `predict_correct([prior])[0]`, then `prior = apply_learning(observe(prior, y))`; append next prior.
- `fit_grid`: for each param set in given order, flatten all train sequences through `predict_sequence`, compute `brier`; keep the lowest; ties go to the earlier grid entry.
- `brier`: `sum((p - t) ** 2) / n`, raise on empty.

Also clamp inputs: `y` and `prior` clamped into `[EPS, 1-EPS]` before arithmetic.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_p51_bkt.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bkt.py backend/tests/test_p51_bkt.py
git commit -m "feat(p5.1): pure-python BKT math module with soft targets"
```

---

### Task 2: Read-only dataset extractor

**Files:**
- Create: `backend/evals/mastery_dataset.py`
- Test: `backend/tests/test_p51_dataset.py`

**Interfaces:**
- Produces:
  - `@dataclass class Sequence: user_id: str; key: str; events: list[tuple[datetime, float]]`
  - `@dataclass class DatasetReport: database: str; skill_granularity: bool; users: int; sequences: int; raw_attempts: int; versioned_attempts: int; length_histogram: dict[str,int]; sequences_ge: dict[str,int]`
  - `async def detect_tables(engine) -> set[str]`
  - `async def load_sequences(engine, granularity: str = "skill", min_sequence: int = 5) -> tuple[list[Sequence], DatasetReport]`
  - `def redact_dsn(dsn: str) -> str`
  - `def summarize(report: DatasetReport, thresholds: dict) -> dict`

- [ ] **Step 1: Write the failing test**

```python
"""P5.1 extractor — read-only, chịu schema 0012 và 0015, lọc contentVersion."""
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from evals import mastery_dataset as md


DDL_0012 = [
    "CREATE TABLE users (id TEXT PRIMARY KEY, external_id TEXT, email TEXT)",
    "CREATE TABLE courses (id TEXT PRIMARY KEY, user_id TEXT, topic TEXT)",
    """CREATE TABLE units (id TEXT PRIMARY KEY, course_id TEXT, order_index INTEGER, title TEXT)""",
    """CREATE TABLE lessons (
        id TEXT PRIMARY KEY, unit_id TEXT, course_id TEXT, order_index INTEGER,
        title TEXT, content_version INTEGER, status TEXT)""",
    """CREATE TABLE lesson_attempts (
        id TEXT PRIMARY KEY, lesson_id TEXT, user_id TEXT, client_attempt_id TEXT,
        content_version INTEGER, score_correct INTEGER, score_total INTEGER,
        duration_ms INTEGER, results TEXT, xp_awarded INTEGER, created_at TEXT)""",
]


def test_redact_dsn_hides_password():
    assert "secret" not in md.redact_dsn("postgresql+asyncpg://u:secret@h:5432/db")
    assert "h:5432" in md.redact_dsn("postgresql+asyncpg://u:secret@h:5432/db")


async def _build(tmp_path, with_skills: bool):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        for ddl in DDL_0012:
            await conn.execute(text(ddl))
        if with_skills:
            await conn.execute(text("CREATE TABLE skills (id TEXT PRIMARY KEY, course_id TEXT, key TEXT)"))
            await conn.execute(text("CREATE TABLE lesson_skills (lesson_id TEXT, skill_id TEXT)"))
    return engine


async def _seed(engine, *, version_match: bool, users: int, attempts: int):
    async with engine.begin() as conn:
        for u in range(users):
            uid = f"u{u}"
            await conn.execute(text("INSERT INTO users (id, external_id) VALUES (:i, :e)"), {"i": uid, "e": f"ext{u}"})
            await conn.execute(text("INSERT INTO courses (id,user_id,topic) VALUES (:c,:u,'t')"), {"c": f"c{u}", "u": uid})
            await conn.execute(text("INSERT INTO units (id,course_id,order_index,title) VALUES (:n,:c,0,'u')"), {"n": f"un{u}", "c": f"c{u}"})
            await conn.execute(text("INSERT INTO lessons (id,unit_id,course_id,order_index,title,content_version,status) VALUES (:l,:un,:c,0,'L',2,'ready')"), {"l": f"l{u}", "un": f"un{u}", "c": f"c{u}"})
        now = datetime(2026, 10, 1, tzinfo=UTC)
        for i in range(attempts):
            u = i % users
            cv = 2 if version_match else 1
            await conn.execute(
                text("""INSERT INTO lesson_attempts
                    (id,lesson_id,user_id,client_attempt_id,content_version,score_correct,score_total,duration_ms,results,xp_awarded,created_at)
                    VALUES (:id,:l,:u,:cid,:cv,4,5,100,'[]',0,:ts)"""),
                {"id": f"a{i}", "l": f"l{u}", "u": f"u{u}", "cid": f"c{i}", "cv": cv,
                 "ts": (now + timedelta(minutes=i)).isoformat()},
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
    assert {s.key for s in seqs} == {f"lesson:l0", f"lesson:l1"}
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
        await conn.execute(text("INSERT INTO skills (id,course_id,key) VALUES ('s0','c0','alpha')"))
        await conn.execute(text("INSERT INTO lesson_skills (lesson_id,skill_id) VALUES ('l0','s0')"))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p51_dataset.py -q`
Expected: FAIL with `ImportError` for `evals.mastery_dataset`.

- [ ] **Step 3: Implement `backend/evals/mastery_dataset.py`**

Key rules:
- `detect_tables`: `async with engine.connect() as conn: return set(await conn.run_sync(lambda s: inspect(s).get_table_names()))`. Never pass the engine to `inspect` directly.
- `redact_dsn`: parse with `urllib.parse.urlsplit`, replace `password` with `***` if present; keep scheme/host/port/db.
- `load_sequences`:
  - Accept `granularity in {"skill","lesson"}` (raise `ValueError` otherwise).
  - One SELECT joining `lesson_attempts` → `lessons` on `lesson_id` and filtering `a.content_version = l.content_version` and `a.score_total > 0`, ordered by `a.created_at, a.id`.
  - Raw count = `SELECT COUNT(*) FROM lesson_attempts`.
  - Versioned count = the joined count above.
  - When `granularity == "skill"` and tables `skills` + `lesson_skills` exist: LEFT JOIN through `lesson_skills`/`skills`; for attempts without a skill, use key `lesson:<lesson_id>` so no attempt is silently dropped (report `skill_granularity=true`). When tables are absent: fall back to lesson keys and `skill_granularity=false`.
  - Group into `Sequence` by `(user_id, key)`; events are `(created_at_utc, score_correct/score_total)`; clamp `y` into `[0,1]`; sort ascending.
  - `length_histogram` = `{str(len): count}`; `sequences_ge` = `{str(n): count of sequences with len >= n}` for `n` in `(1,2,3,5,10,20)`.
  - Empty DB/tables absent for `lesson_attempts` → return empty list and a report with zeros, but do **not** mask a column error: let `OperationalError` propagate with a clear message.
- `summarize(report, thresholds)`: returns `{"enough": bool, "reasons": [...], "metrics": {...}}`; each missing threshold produces `"min_sequences=30: chỉ có 0 chuỗi ≥5 event"` style reason. Compare against `report.sequences_ge["5"]` and `report.versioned_attempts`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_p51_dataset.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/evals/mastery_dataset.py backend/tests/test_p51_dataset.py
git commit -m "feat(p5.1): read-only mastery dataset extractor with schema fallback"
```

---

### Task 3: Evaluation harness with real/simulated modes

**Files:**
- Create: `backend/evals/bkt_eval.py`
- Test: `backend/tests/test_p51_eval.py`

**Interfaces:**
- Consumes: `bkt` (Task 1), `mastery_dataset` (Task 2).
- Produces:
  - `def split_by_user(keys: Sequence[str], ratio: float = 0.7) -> tuple[set[str], set[str]]`
  - `def split_by_time(rows: Sequence[tuple[str, datetime]], cutoff: datetime) -> tuple[set, set]`
  - `def evaluate(train: Sequence[Sequence], test: Sequence[Sequence]) -> dict`
  - `def simulate(seed: int, users: int, per_user: int, params: bkt.BktParams) -> list[Sequence]`
  - `def decide_gate(results: dict, thresholds: dict) -> dict`
  - `def main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Write the failing test**

```python
"""P5.1 eval — split không leakage, metric cơ bản, gate trung thực."""
from datetime import UTC, datetime, timedelta

import pytest

from app.services import bkt
from evals import bkt_eval as ev


def test_split_by_user_is_disjoint_and_deterministic():
    keys = [f"u{i}:s" for i in range(10)]
    train, test = ev.split_by_user(keys, ratio=0.7)
    assert train.isdisjoint(test)
    assert train | test == set(keys)
    assert ev.split_by_user(keys, ratio=0.7) == (train, test)
    assert len(test) == 3


def test_split_by_time_is_disjoint():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    rows = [(f"k{i}", t0 + timedelta(hours=i)) for i in range(6)]
    train, test = ev.split_by_time(rows, cutoff=t0 + timedelta(hours=3))
    assert train.isdisjoint(test)
    assert test == {"k3", "k4", "k5"}


def test_evaluate_reports_zero_leakage_and_metrics():
    params = bkt.BktParams(p_learn=0.2)
    train = [[1.0, 1.0, 0.0, 1.0], [1.0, 0.0, 1.0, 1.0]]
    test = [[1.0, 1.0, 1.0], [0.0, 1.0, 1.0]]
    res = ev.evaluate(train, test)
    for key in ("brierBkt", "brierBaseline", "logLossBkt", "aucBkt", "aucBaseline",
                "eceBkt", "driftBrier", "nTest", "leakage"):
        assert key in res
    assert res["leakage"] == 0
    assert res["nTest"] == 6


def test_evaluate_empty_test_is_safe():
    res = ev.evaluate([[1.0, 1.0]], [])
    assert res["nTest"] == 0
    assert res["aucBkt"] is None
    assert res["brierBkt"] is None


def test_simulate_is_deterministic_and_labelled():
    params = bkt.BktParams()
    a = ev.simulate(seed=7, users=3, per_user=5, params=params)
    b = ev.simulate(seed=7, users=3, per_user=5, params=params)
    assert [s.key for s in a] == [s.key for s in b]
    assert [s.events for s in a] == [s.events for s in b]
    assert len(a) == 3 and all(len(s.events) == 5 for s in a)


def test_simulate_mismatched_model_does_not_beat_baseline():
    # sinh dữ liệu toàn đúng -> BKT với learn=0 không thể tốt hơn baseline hằng số
    params = bkt.BktParams(p_learn=0.0, p_init=0.5, p_guess=0.2, p_slip=0.1)
    seqs = ev.simulate(seed=3, users=8, per_user=10, params=params, force_correct=True)
    half = len(seqs) // 2
    res = ev.evaluate([s.events for s in seqs[:half]], [s.events for s in seqs[half:]])
    assert res["leakage"] == 0
    assert res["brierBkt"] <= 0.25


def test_decide_gate_insufficient_when_too_few():
    result = {"nSequencesTrain": 0, "nSequencesTest": 0, "nEvents": 0}
    gate = ev.decide_gate(result, {"min_sequences": 30, "min_events": 300})
    assert gate["status"] == "insufficient_data"
    assert gate["gate"] == "NOT_MET"
    assert gate["reasons"]


def test_decide_gate_requires_better_brier():
    result = {
        "nSequencesTrain": 20, "nSequencesTest": 20, "nEvents": 600,
        "brierBkt": 0.30, "brierBaseline": 0.20, "eceBkt": 0.05,
        "aucBkt": 0.7, "driftBrier": 0.01, "leakage": 0,
    }
    gate = ev.decide_gate(result, {"min_sequences": 10, "min_events": 100})
    assert gate["gate"] == "NOT_MET"
    assert any("brier" in r.lower() for r in gate["reasons"])


def test_decide_gate_passes_when_all_criteria_met():
    result = {
        "nSequencesTrain": 20, "nSequencesTest": 20, "nEvents": 600,
        "brierBkt": 0.10, "brierBaseline": 0.20, "eceBkt": 0.05,
        "aucBkt": 0.75, "driftBrier": 0.01, "leakage": 0,
    }
    gate = ev.decide_gate(result, {"min_sequences": 10, "min_events": 100})
    assert gate["gate"] == "PASS"
    assert gate["status"] == "evaluated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_p51_eval.py -q`
Expected: FAIL with `ImportError` for `evals.bkt_eval`.

- [ ] **Step 3: Implement `backend/evals/bkt_eval.py`**

Implementation notes (signatures pinned by the test above):
- `split_by_user`: sort keys, take first `round(len * ratio)` as train; deterministic. Keys are `user_id` (not `user:skill`) so no user crosses splits; the evaluator then maps sequences to their user.
- `split_by_time`: keys with timestamp `< cutoff` go to train, `>= cutoff` to test.
- `evaluate(train_seqs, test_seqs)`:
  - `params, train_brier = bkt.fit_grid(train_seqs, DEFAULT_GRID)`; `DEFAULT_GRID = [BktParams(p_learn=l) for l in (0.02, 0.05, 0.1, 0.2, 0.35)]` (ordered).
  - For test: BKT prediction per event from `predict_sequence`.
  - Baseline as-of: maintain per-sequence history; for event `t`, use prior events (`< t`) in the same sequence; weights `0.5 ** (age_days / 30)`; if no history use the global train mean of `y` (document this).
  - Compute Brier, log loss (`-mean(y*ln(p)+(1-y)*ln(1-p))` with clamp), AUC on binary `y >= 0.8` (rank-based; if all labels equal return `None`), ECE with 10 equal-width bins (drop empty bins), drift = Brier on the later half of test minus earlier half.
  - `leakage`: count of user ids present in both train and test (compute from the `Sequence.user_id` values, not the key).
  - Return `None` (not `NaN`) for metrics over an empty test.
- `simulate(seed, users, per_user, params, force_correct=False)`: use `random.Random(seed)`; latent mastery starts at `p_init`; each step predict `P(correct)` then draw a row `y` = 1.0 or 0.0 (or fractional via 5-question quiz: draw 5 binomials to produce `k/5` for realistic soft targets). `force_correct=True` always yields `1.0`. Sequence keys `sim-u{i}`, timestamps anchored at `datetime(2026, 1, 1, tzinfo=UTC)` + `timedelta(hours=i)`; events as `(timestamp, y)`.
- `decide_gate(results, thresholds)`: thresholds keys with defaults `min_sequences=30`, `min_events=300`, `min_relative_brier_gain=0.02`, `max_ece=0.10`, `min_auc=0.60`, `max_drift=0.05`. Insufficient when `nSequencesTest < max(10, min_sequences // 3)` or `nEvents < min_events`; reasons are Vietnamese strings naming the failing threshold and actual value. If enough, mark `PASS` only when every criterion holds, else `NOT_MET` with one reason per failed criterion.
- `main`: argparse options exactly as in design §6.3 plus `--force-correct` for the simulation smoke path. Real mode: `load_sequences`, `summarize`, print report (redacted DSN), if not enough → `INSUFFICIENT_DATA` + reasons, `--save` still writes a report with `status="insufficient_data"`, exit 0. Simulated mode: `simulate` → split by user → `evaluate` → `decide_gate` with `dataSource="simulated"` recorded, `--save` writes JSON to `backend/evals/reports/bkt_<ts>.json`, exit 0 unless an exception.
- Always include `"dataSource"`, `"seed"`, `"params"`, `"grid"`, `"thresholds"`, `"gitHead"` (best-effort `git rev-parse HEAD`, `None` if unavailable), and `"database"` (redacted).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_p51_eval.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/evals/bkt_eval.py backend/tests/test_p51_eval.py
git commit -m "feat(p5.1): BKT evaluation harness with honest insufficient-data gate"
```

---

### Task 4: Run against the real database and record evidence

**Files:**
- Modify: `docs/specs/23-P51-BKT.md` (create)
- Test: none (manual run)

**Interfaces:**
- Consumes: Task 2 extractor + Task 3 CLI.

- [ ] **Step 1: Run on the real dev database**

```bash
cd backend
python -m evals.bkt_eval --dataset real \
  --database-url "postgresql+asyncpg://ailp:ailp@127.0.0.1:5433/ailp"
```

Expected: prints the redacted DSN, raw/versioned counts, length histogram and `INSUFFICIENT_DATA` with a quantitative reason. Exit code 0. Compare the printed counts against `psql` output; if they disagree, fix the extractor before continuing.

- [ ] **Step 2: Run on SQLite fallback to prove the 0012-schema path**

```bash
cd backend
python -m evals.bkt_eval --dataset real --database-url "sqlite+aiosqlite:///./ailp.db" --granularity lesson
```

Expected: either data or `INSUFFICIENT_DATA`; must not crash whether or not the file has tables.

- [ ] **Step 3: Run the labelled simulation and save the report**

```bash
cd backend
python -m evals.bkt_eval --dataset simulated --seed 20261102 --save
```

Expected: report path printed; summary shows `dataSource=simulated`, `leakage=0`, metrics present, and a gate decision. Do not present this as a quality claim.

- [ ] **Step 4: Write `docs/specs/23-P51-BKT.md`**

Include: purpose, why research-only, the exact formulas, the dataset/split/threshold decisions, the real-run output (counts + `INSUFFICIENT_DATA`), the simulated-run summary explicitly labelled, and a limitations section listing (a) soft target, (b) 1 skill per lesson inherits P2.1's coarse granularity, (c) no cross-course skill identity, (d) no fairness conclusion from small slices.

- [ ] **Step 5: Commit**

```bash
git add docs/specs/23-P51-BKT.md
git commit -m "docs(p5.1): BKT research spec with real-run insufficiency evidence"
```

---

### Task 5: Test isolation and full-suite verification

**Files:**
- Modify: `backend/tests/test_p51_dataset.py` and `backend/tests/test_p51_eval.py` only if isolation requires it (for example an `asyncio` marker or fixture).
- Test: the whole suite.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified green suite and a clean `git diff --stat` proving no runtime files changed.

- [ ] **Step 1: Confirm no runtime file changed**

Run: `git diff --stat main -- backend/app/models backend/alembic backend/app/api backend/app/core/config.py backend/app/services/learner_profile_service.py backend/app/services/learning_path_service.py backend/requirements.txt`
Expected: empty output.

- [ ] **Step 2: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all pass; record the exact passed/skipped counts from this run (do not reuse older numbers).

- [ ] **Step 3: Run the new files in isolation to prove no cross-test coupling**

Run: `cd backend && python -m pytest tests/test_p51_bkt.py tests/test_p51_dataset.py tests/test_p51_eval.py -q -p no:randomly`
Expected: all pass without needing PostgreSQL or network.

- [ ] **Step 4: Commit any test-isolation fixes**

```bash
git add backend/tests
git commit -m "test(p5.1): isolate BKT tests from shared session state"
```

(Skip the commit if Step 1–3 required no change.)

---

### Task 6: Documentation and phase report

**Files:**
- Modify: `docs/specs/12-ADAPTIVE-LEARNING.md`
- Modify: `docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md:262` (status table row P5.1–P5.2) and `:639-654` (section 18)
- Modify: `docs/development-progress.md` (new section at the top)

**Interfaces:**
- Consumes: evidence from Task 4/5.

- [ ] **Step 1: Update `docs/specs/12-ADAPTIVE-LEARNING.md`**

In section 5 (Statistical models), replace the BKT bullet with the implemented reality: module path, soft-target definition, research-only status, gate criteria, and a link to `docs/specs/23-P51-BKT.md`. Keep ADAPT-006 wording but add "research-only as of 2026-11-02".

- [ ] **Step 2: Update the master plan**

- Section 3 table: P5.1–P5.2 row → `P5.1 DONE (research-only) 2026-11-02` with note "no runtime change; real DB insufficient".
- Section 18 P5.1 bullets: mark the first two as `[x]` with the module/eval paths, and leave the deploy bullet `[ ]` with "BLOCKED: dataset below threshold (see `docs/specs/23-P51-BKT.md`)".

- [ ] **Step 3: Add the phase report to `docs/development-progress.md`**

Use the template from plan §23 with real command output: exact counts from Task 4 Step 1, the `INSUFFICIENT_DATA` reason, simulated report path, full-suite counts from Task 5 Step 2, and `PHASE GATE: GATE-PARTIAL (research-only; deploy BLOCKED)`.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs(p5.1): record research-only BKT status and gate evidence"
```

---

## Self-Review Notes

- Spec §6.1 ↔ Task 1; §6.2 ↔ Task 2; §6.3 ↔ Task 3; §6.4 ↔ `decide_gate` + Task 4; §6.5 (files) ↔ Tasks 1–3; §7 acceptance ↔ Tasks 1–5 — every acceptance item has an executable check.
- Review Focus items map to tests: (1) `test_evaluate_empty_test_is_safe`, `test_extractor_falls_back_on_0012_schema`; (2) `test_extractor_excludes_stale_versions` + report fields; (3) `test_extractor_falls_back_on_0012_schema`; (4) `test_decide_gate_insufficient_when_too_few` + Task 4 Step 1; (5) `test_simulate_mismatched_model_does_not_beat_baseline`.
- Types are consistent: `Sequence` and `DatasetReport` defined in Task 2 and consumed as `Sequence` in Task 3's `evaluate`/`simulate`.
- No task creates a migration, changes a model, or edits runtime config.
