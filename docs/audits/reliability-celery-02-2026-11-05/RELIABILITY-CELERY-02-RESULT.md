# GATE RELIABILITY-CELERY-02 — Result

- **Date:** 2026-11-05
- **Branch:** `feat/p6.0-ci-pipeline` · **HEAD:** `d747e78` (unchanged — no commit, no push)
- **Owner approval:** PHASE B approved — Variant 2 (full dirty backend tree) + stop host PID 23280.
- **Provider during rollout:** `LLM_PROVIDER=mock` throughout (verified in §2).
- **Classification:** **IMPLEMENTED · TESTED · DEPLOYED · LIVE-VERIFIED.**

---

## 1. Image IDs — before / after

| Service | Before (pre-fix) | Rollback tag | After (deployed) |
|---|---|---|---|
| backend | `0ab6b46dd9ca` | `reverseengineer-backend:pre-celery02` = `sha256:0ab6b46dd9cacd05d8998e178c401cbeb7a4fa79b63febdb51b18e1a2c4b86d4` | `36a396d6d75a` (manifest `sha256:36a396d6d75acae42428f7c5da3deec9a1adc7f505544a1a4ac94d1f0bca49c9`) |
| worker | `435827193333` | `reverseengineer-worker:pre-celery02` = `sha256:43582719333372dd1a63be1ee759ec23e59fb3d70a87fb7ceab8a00b61a851d6` | `fbeddad2882a` (manifest `sha256:fbeddad2882a17ed960469bde6164b3b0e8c6975f91ea2a0c740f5850d6aa925`) |
| beat | `cb3713c9a11e` | `reverseengineer-beat:pre-celery02` = `sha256:cb3713c9a11e5d5597696fef33b28c9ad52fc19596a0d1324ad84ec29c54e78e` | `c7890e494d6c` (manifest `sha256:c7890e494d6c46ce1a84514fbed8d925ec33b3432dafad9b7b50073879615127`) |

**Untouched, as instructed:** `db` `721873c34ceb` (up 35 h), `redis` `8da19c7399dc` (35 h), `minio` `3f16527308ed` (35 h), `frontend` `b822295140a3` (27 h). Their uptimes were continuous across the rollout — none was rebuilt or restarted.

---

## 2. Deployed content

Built from the working tree at `d747e78` **with uncommitted changes**, exactly the 6 audited backend files:

| File | Origin |
|---|---|
| `backend/app/services/job_service.py` | RELIABILITY-CELERY-01 |
| `backend/app/core/config.py` | RELIABILITY-CELERY-01 |
| `backend/app/worker/celery_app.py` | RELIABILITY-CELERY-01 |
| `backend/tests/test_job_reliability.py` | RELIABILITY-CELERY-01 |
| `backend/app/providers/validation.py` | P1-QUIZ-BLANK |
| `backend/app/worker/generation.py` | P1-QUIZ-BLANK |

No other change was introduced. `LLM_PROVIDER=mock` confirmed inside the worker container.

---

## 3. Code presence — all three containers

`job_service.py` grew from **13 851 B (Oct 31)** to **15 650 B (Nov 4 16:17)** in `backend`, `worker`, **and** `beat`:

```console
=== backend ===   1 / 3 / 3     (stale-branch count / transport opts / BLANK_SLOT_COUNT)
=== worker ===    1 / 3 / 3
=== beat ===      1 / 3 / 3
```

> Note: PHASE A had recorded `0` for all three. A **restart alone never changed this** — only the rebuild did, proving the baked-image finding was correct.

---

## 4. Celery config — live app, not source

Read from the running Celery app in the worker container:

```
broker_transport_options  = {'visibility_timeout': 3600}
visibility_timeout        = 3600        ← what Redis actually reads
worker_visibility_timeout = None        ← the ignored key is gone
task_time_limit           = 2400        ← safely below visibility_timeout
task_acks_late            = True
prefetch_multiplier       = 1
```

`worker_visibility_timeout` now appears **only in comments** (lines 11, 12, 39, 40 of `celery_app.py`) — no active setting.

---

## 5. Host PID 23280 — stopped with identity verification

Verified immediately before the stop, per the owner's conditions:

| Check | Result |
|---|---|
| PID alive | yes, CPU 266.8 s |
| Executable | `C:\...\Python313\python.exe` ✅ matches expected |
| Command line | `-m celery -A app.worker.celery_app:celery_app worker --loglevel=info --pool=solo` ✅ |
| Start time | 2026-11-03 14:31:42 … 2 026-11-05 01:12 |
| Parent | `bash.exe` 26960 (dead opencode session) — **not** killed directly |
| In-flight task | none — log showed `received`→`succeeded` pairs with nothing open |
| Broker at stop | `queue=0`, `unacked=0`, `consumers=2` |

The guard script **aborted automatically** if the executable, command line, or match failed. Result:

```
RESULT: PID 23280 stopped
PID 26960 (parent bash) : gone (exited on its own)
remaining celery workers on host : none
consumers after stop = 1        ← container only
```

**Worker identity now:** `celery inspect ping` → `celery@bd4cd77b8cfd: OK` — **`1 node online.`**

---

## 6. Orphan recovery — real runtime evidence

The orphan was recovered **automatically by the reconciler**, not by any manual edit.

### 6.1 Before → after

| | Before | After |
|---|---|---|
| `status` | `queued` | **`ready`** |
| `dispatched_at` | 2026-11-04 14:05:54 | 2026-11-04 18:11:01 |
| `dispatch_attempts` | 1 | 2 |
| `attempts_count` | 0 | 1 |
| `lease_expires_at` | NULL | NULL (released normally) |
| `last_error_code` | – | NULL (no error) |
| Course `d3612197-…` | `generating` | **`ready`** |
| **Lessons for that course** | **4** | **4 — no duplicates** |

### 6.2 It went through the new third branch

The fix is proven by the task's **return value**, which lists exactly what the reconciler recovered:

```console
[18:11:01] Task app.worker.reconcile.reconcile_jobs[1233ec7d-…] succeeded in 0.312s: ['ce9d5596-8d62-4bed-9253-37b02fec255e']
[18:11:01] reconciler recovered jobs count=1
[18:11:01] Task app.worker.generation.run_generation_task[9dda1a20-…] received
[18:11:02] Task app.worker.generation.run_generation_task[9dda1a20-…] succeeded in 0.641s: None
```

The orphan was `queued` **with `dispatched_at` set** — the only branch that can match it is branch 3. Every subsequent tick returned `[]`, and `dispatch_attempts` stayed at 2 across ~7 ticks, so there is **no re-dispatch loop**.

### 6.3 The exhaustion path also fires in runtime

A synthetic job (`dispatch_attempts=5`, `max=5`, `dispatched_at` 10 min old) was inserted on an existing throwaway test course:

```
→ status=failed · last_error_code=DISPATCH_EXHAUSTED · course → failed
```

It correctly **did not dispatch**. The synthetic row was then deleted and the test course restored to `ready`; global counts returned exactly to baseline (§8).

---

## 7. No duplicate generation, no wrong charges

| Check | Before | After | Verdict |
|---|---|---|---|
| Lessons for orphan course | 4 | **4** | no duplication |
| `llm_usage_events` | 25 | **25** | no new usage rows |
| `sum(cost_estimate_usd)` | 0.06378 | **0.06378** | no cost incurred |
| Duplicate `(unit_id, order_index)` | – | none (UNIQUE index intact) | no collisions |

The mock provider was used for the whole rollout, so the zero cost delta is expected as well as correct.

---

## 8. Data integrity — the 7 legacy quizzes and everything else

**All stored lessons are byte-identical**, proven by content hashes rather than eyeballing:

```
all-lessons-before  ==  all-lessons-after   → IDENTICAL (350 lessons)
legacy7-before      ==  legacy7-after       → IDENTICAL
legacy7-before      ==  legacy7-final       → IDENTICAL (after E2E too)
```

Blank-block lint:

| When | `blank_blocks` | `invalid_gap` |
|---|---|---|
| After deploy | 345 | **7** (all pre-existing) |
| After E2E generation | 349 (+4 new) | **7** (same rows) |

The 7 are the same rows documented in P1-QUIZ-BLANK; **no new violation was created**, and the stricter validator did not touch or rewrite stored content.

### Counts across the rollout

| Point | courses | lessons | attempts | jobs | units | skills | usage | docs |
|---|---|---|---|---|---|---|---|---|
| Baseline | 100 | 350 | 144 | 199 | 172 | 0 | 25 | 33 |
| After recovery (+ synthetic cleanup) | 100 | 350 | 144 | 199 | 172 | 0 | 25 | 33 |
| After E2E | 101 | 354 | 146 | 202 | 174 | 0 | 25 | 35 |

Baseline equality after recovery is exact. The E2E delta is the expected artifact of a real acceptance run creating its own course — and `usage` stayed flat, so it added **no cost**.

---

## 9. Test results — commands and exit codes

| Suite | Command | Result | Exit |
|---|---|---|---|
| Full backend (host) | `python -m pytest -q` | **720 passed** | **0** |
| Celery reliability | `pytest tests/test_job_reliability.py -q` | **31 passed** | **0** |
| Quiz + QUIZ-BLANK | `pytest tests/test_quiz_blank.py tests/test_quiz_integrity.py -q` | **27 passed** | **0** |
| Live E2E (mock) | `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` | **61/61 PASS** | **0** |

Logs: `logs/pytest-host-full.log`, `logs/pytest-reliability.log`, `logs/pytest-quiz.log`, `logs/e2e-postdeploy.log`, `logs/recovery-evidence.log`.

### ⚠️ A failure that must be reported, not hidden

Running the suite **inside the worker container** produced `287 failed, 419 passed, 31 skipped, 12 errors`. Both failure families are **environmental, not behavioural**:

1. `tests/test_quiz_integrity.py` → `RuntimeError: got Future attached to a different loop` — asyncpg connection pooled across event loops. A test-harness artifact of running pytest inside the long-lived container.
2. `tests/test_p61_ci_contract.py` → `AssertionError: thiếu workflow /.github/workflows/ci.yml` — `.github/` is not copied into the runtime image.

Evidence this is not a regression: the **same code passes 720/720 on the host**, the live E2E passes 61/61 against the redeployed containers, and the real database was verified untouched after the in-container run.

---

## 10. Residual risks

| # | Risk | Status |
|---|---|---|
| R1 | The 7 legacy multi-blank quizzes remain invalid | **Unchanged, by design** — remediation needs content rewrite, explicitly out of scope. They are not auto-modified (proven by hash). |
| R2 | The stricter validator may lower real-LLM pass rate | **Unmeasured** — measuring needs paid generation, forbidden here. P1-QUIZ-BLANK recommends adding "đúng một chỗ trống" to `LESSON_SYSTEM` (not done). |
| R3 | A future host worker could re-race the queue | Not prevented — the leftover opencode process is gone, but nothing stops another from starting. Consider a guard in the runbook. |
| R4 | `visibility_timeout` end-to-end redelivery not induced | **NOT TESTED** — would need a deliberate worker stall. Config is correct and safely ordered (2400 < 3600), but redelivery itself was not exercised. |
| R5 | In-container pytest is unusable as a gate | Discovered this run. Use the host suite + E2E as the real gate; do not read the container pytest result as a signal. |
| R6 | E2E leaves a course behind by design | Expected; counts recorded in §8. |

### Not tested
- Real paid provider (forbidden).
- Redis redelivery after an induced worker stall (R4).
- Browser UI (no e2e/browser harness in the repo; backend+frontend health both return 200).

---

## 11. Rollback status

**Not triggered** — every verification passed on first attempt.

Rollback remains available and is a pure re-pin, since the old images were tagged before the build:

```bash
docker tag reverseengineer-worker:pre-celery02  reverseengineer-worker:latest
docker tag reverseengineer-beat:pre-celery02    reverseengineer-beat:latest
docker tag reverseengineer-backend:pre-celery02 reverseengineer-backend:latest
docker compose up -d --no-deps worker beat backend
```

No migration exists, so nothing has to be reversed in the database. No volume, Redis key, or MinIO object was deleted at any point.

---

## 12. Classification

| Aspect | Status |
|---|---|
| Fix implemented | **IMPLEMENTED** (prior gate) |
| Built into images | **DONE** |
| Deployed to the three services only | **DONE** |
| Code present in all three containers | **VERIFIED** |
| `broker_transport_options.visibility_timeout` live | **VERIFIED** (3600, read from running app) |
| Stale-dispatch branch fires at runtime | **VERIFIED** (task return listed the orphan; exhaustion path also fired) |
| Legacy orphan recovered | **DONE** — `queued` → `ready`, 4 → 4 lessons |
| Duplicate lessons / charges / jobs | **NONE FOUND** |
| Stale host worker removed | **DONE** — 1 node online |
| Tests | **720 + 31 + 27 passed, E2E 61/61, all exit 0** |
| Rollback needed | **NO** |

**Bottom line:** the runtime gap flagged in RELIABILITY-CELERY-01 is closed and demonstrated on the live stack, with the orphan healed by the application's own reconciler rather than by manual SQL.
