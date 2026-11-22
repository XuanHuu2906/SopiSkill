# GATE RELIABILITY-CELERY-01 — Result

- **Date:** 2026-11-04
- **Branch:** `feat/p6.0-ci-pipeline`
- **HEAD:** `d747e78` (unchanged — no commit, no push)
- **Scope:** backend job-recovery + Celery config. **No frontend file edited. No migration. No public API change.**
- **Production files changed:** 3 · **Test files changed:** 1 (+6 tests)
- **Classification:** **IMPLEMENTED + TESTED (unit/integration + live E2E).** Runtime deployment of the fix is **BLOCKED by the gate's own no-restart constraint** — see §7.

---

## 1. Root cause — re-verified independently (not inherited)

The prior CELERY-STALE-WORKER report claimed the recovery query structurally cannot match the orphan.
That claim was re-derived from scratch at three levels, per the instruction not to accept it unverified.

### 1.1 Code level

`recover_stuck_jobs` matched exactly two shapes:

| State | Recovered by pre-fix code? |
|---|---|
| `queued` + `dispatched_at IS NULL` + past grace | ✅ outbox branch |
| `running` + lease absent/expired | ✅ lease branch |
| **`queued` + `dispatched_at IS NOT NULL`** | ❌ **matched no branch** |

Confirmed by reading `backend/app/services/job_service.py:311-377` at HEAD before any edit.

### 1.2 Behavioural level

The beat reconciler fires every ~30 s (`generation_reconcile_interval_seconds=30`) and returns `[]`.
The orphan held `dispatch_attempts = 1`, far below `generation_max_dispatch_attempts = 5` — so it
would have been re-dispatched had it matched the predicate. It never matched, so it never moved.

### 1.3 Broker level

```
LLEN celery            = 0
LRANGE unacked 0 -1    = (empty)
ZCARD unacked_index    = 0
```

The original message is **gone from the broker**. No redelivery path exists — the job can only be
recovered by application-level logic, which is what this gate adds.

**Verified root cause:** the job was broker-acked (`dispatched_at` set) but no worker ever claimed it,
and no recovery branch covered that state. This is *not* a lesson-data or provider failure.

---

## 2. Two new findings the prior report missed

### 2.1 The stale host worker is still live and still racing
`celery@LAPTOP-8DN2AGTV` (host) is **not** historical. At time of writing:

- Host process **PID 23280** (`python -m celery ... worker --pool=...`, created 2026-11-03 14:31) is alive, ~33 h old.
- Redis `CLIENT LIST` shows **two** `cmd=brpop` consumers on the shared `celery` list:
  - `addr=192.168.176.1` (host, `age=118903` s) — the stale worker
  - `addr=192.168.176.6` (container, `age=3291` s) — the correct worker
- `celery inspect ping` reports **only 1 node** (`celery@7901fae8ba26`), i.e. the host worker holds a
  queue socket but does **not** answer pidbox — the signature of a consumer that can take a message
  and never complete it.

The two-consumer race is therefore **live, not historical**. Root cause of the original orphan is
this race; the recovery-gap is why it never healed.

### 2.2 `worker_visibility_timeout` was never a valid Celery 5 setting
`celery_app.py` set `worker_visibility_timeout=...`. In Celery 5.6.3 this is not a recognised
setting and is **silently ignored**; Redis reads visibility only from
`broker_transport_options["visibility_timeout"]`. So broker redelivery was never configured, contrary
to the comment that claimed it was.

Confirmed by loading the app in the running worker before the fix:

```
worker_visibility_timeout: 3600     ← set, ignored
broker_transport_options.visibility_timeout: None   ← what Celery actually reads
```

---

## 3. What changed

### 3.1 `backend/app/services/job_service.py` (+28 / −1)
Third recovery branch plus row locking in `recover_stuck_jobs`:

```python
stale = timedelta(seconds=settings.generation_stale_dispatch_seconds)
...
# 3. Broker đã ack nhưng chưa ai claim quá lâu
(GenerationJob.status == JobStatus.queued)
& GenerationJob.dispatched_at.is_not(None)
& (GenerationJob.dispatched_at < now - stale)
& or_(GenerationJob.lease_expires_at.is_(None), GenerationJob.lease_expires_at < now),
...
.with_for_update(skip_locked=True)
```

The `dispatched_at < now - stale` guard ensures a message a worker has *just* received is left alone;
the lease guard ensures a live consumer is never pre-empted. The loop body is unchanged.

### 3.2 `backend/app/core/config.py` (+4)
```python
generation_stale_dispatch_seconds: int = 300
```
Deliberately ≫ `generation_dispatch_grace_seconds` (10 s) so re-dispatch cannot race a worker that is
still connecting.

### 3.3 `backend/app/worker/celery_app.py` (+9 / −3)
```python
broker_transport_options={
    "visibility_timeout": int(_settings.generation_lesson_timeout_seconds * 60),
},
```
Replaces the silently-ignored key. In the live config `task_time_limit=2400` s and the intended
`visibility_timeout=3600` s stays above it, so a live task is not redelivered.

### 3.4 `backend/tests/test_job_reliability.py` (+193, 6 new tests)
| Test | Guarantees |
|---|---|
| `test_reconciler_recovers_queued_job_dispatched_past_deadline` | orphan is recovered |
| `test_reconciler_leaves_recently_dispatched_job_alone` | fresh dispatch untouched |
| `test_reconciler_does_not_touch_queued_job_with_live_lease` | live consumer not pre-empted |
| `test_reconciler_fails_stale_dispatch_after_budget_exhausted` | budget → `DISPATCH_EXHAUSTED` + course `failed` |
| `test_two_reconcilers_do_not_double_dispatch_stale_job` | concurrent sweepers do not double-dispatch |
| `test_stale_recovery_then_generation_completes_without_duplicate_lessons` | recover → run twice → exactly 4 lessons, status `ready` |

### Why duplicate generation is impossible
`claim_job` is `UPDATE ... WHERE status='queued' OR lease expired ... RETURNING id`. Re-dispatch is
safe even if the original message is still in the broker: only one task wins the UPDATE; the rest
no-op. `with_for_update(skip_locked=True)` additionally stops two *reconcilers* from picking the same
row. On SQLite the lock clause is ignored and `claim_job` remains the guard.

---

## 4. Verification actually run

### 4.1 Unit / integration (in-process, isolated DB)
| Command | Result |
|---|---|
| `pytest tests/test_job_reliability.py` **before** fix | **3 failed / 7 passed** — reproduction confirmed |
| same, **after** fix | **31 passed** |
| anti-hollow: strip the new branch, re-run | **3 failed, exactly** |
| branch restored, re-run | **31 passed** |
| full suite `python -m pytest -q` | **720 passed, 29 skipped**, exit 0 (baseline 714/29 ⇒ +6 new) |

Logs: `logs/pytest-targeted.log`, `logs/pytest-full.log`, `logs/pytest-full-final.txt`.

### 4.2 Live E2E (real stack, docker compose, mock provider)
```bash
E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py
```
→ **61/61 PASS, exit 0**. Covers full generation chain, quiz, progress, sources/ingest, tutor-disabled,
auth/CSRF/isolation. Log: `logs/e2e.log`. **No regression** on topic/interview/proposal/quiz/progress/Tutor.

### 4.3 Read-only check of the new predicate against the *real* database
A dry-run of the exact new `SELECT` (no dispatch, no mutation) returned **matched=1**:
```
ce9d5596-8d62-4bed-9253-37b02fec255e | queued | dispatched_at=2026-11-04 14:05:54+00
                                     | dispatch_attempts=1 | lease=None
```
So the predicate would select the orphan — and it does not depend on any data repair.

### 4.4 Typecheck / build
Not applicable: all changes are backend Python. No frontend file was touched, so `tsc --noEmit` and
`npm run build` were not required and were not run for this gate.

---

## 5. Not tested / not run

| Item | Status | Why |
|---|---|---|
| Recovery running **inside the live containers** | **NOT TESTED** | Running containers still carry pre-fix code (§6). Deploying needs a worker rebuild/restart, which the gate forbids. |
| Redis `visibility_timeout` end-to-end redelivery | **NOT TESTED** | Requires deploying 3.3 and inducing a worker stall; blocked by the same constraint. |
| Real paid provider | **NOT RUN** (by instruction) | mock only. |
| Frontend typecheck/build | **N/A** | no frontend change. |

---

## 6. Runtime gap — the running containers are pre-fix (important)

Verified by reading code *inside* the containers:

- `worker` (created 2026-11-04T15:38Z) still contains `worker_visibility_timeout=...` and **no**
  `broker_transport_options`.
- `beat` has `job_service.py` dated **Oct 31** — its reconciler runs the **old two-branch query**.
- `backend` likewise predates the edits.

The Python files were modified at **23:16–23:19 +07:00**, after every container was built/started.
So **the gate's fix is in the working tree and proven by tests, but is not live.** The orphan row
`ce9d5596-…` is therefore still `queued` and **will remain so until the worker/beat are rebuilt**.

This is stated plainly rather than claiming a production PASS. It is exactly the situation the
instruction rules out reporting as passing.

---

## 7. Legacy data — `ce9d5596-…` (NOT repaired)

The row is untouched, as instructed. Current facts:

```
status=queued  dispatched_at=2026-11-04 14:05:54Z  dispatch_attempts=1
attempts_count=0  lease_expires_at=NULL
```
Job totals: `ready=197, failed=1, queued=1`.

### Safe options (owner decision — none performed)
| Option | Effect | Risk |
|---|---|---|
| **A. Rebuild worker+beat, let reconciler heal it** *(recommended)* | With the fix deployed, the third branch matches this row within one reconcile tick and re-dispatches it | Low. Atomic claim prevents duplication. Needs a container rebuild = a restart, which this gate forbids — so it is a follow-up. |
| **B. Retry via supported API** (`retry_course`) | Creates a new job through normal outbox semantics | Low; still leaves the old row `queued` unless the course state is corrected |
| **C. Do nothing** | One permanently-queued row | Acceptable only if the course is not needed |
| ❌ raw `UPDATE dispatched_at=NULL` | — | **Not recommended**: bypasses the outbox contract, risks double dispatch |

**Also required for a durable fix:** stop the stale host worker **(PID 23280, out-of-container)** so
only the container consumes the queue. Otherwise the race that produced the orphan stays live and can
strand new jobs. Not killed here — forbidden by the gate.

---

## 8. Rollback

All changes are additive and confined to 3 backend files + 1 test file:

```bash
git checkout -- backend/app/services/job_service.py \
                backend/app/core/config.py \
                backend/app/worker/celery_app.py \
                backend/tests/test_job_reliability.py
```
No migration, no schema change, no data written ⇒ rollback is a pure source revert. The new config
key defaults to 300 s; removing it simply restores the old two-branch behaviour.

---

## 9. Classification

| Aspect | Status |
|---|---|
| Root cause verified in code + behaviour + broker | **YES** |
| Fix implemented (minimal, no API change) | **IMPLEMENTED** |
| Unit + integration proof, incl. anti-hollow | **TESTED** (31 passed; 720 full) |
| Live E2E regression (mock) | **TESTED** (61/61) |
| Fix deployed to running stack | **NOT DEPLOYED / BLOCKED** by no-restart constraint |
| Legacy orphan repaired | **NOT REPAIRED** (by instruction) |
| Stale host worker removed | **NOT KILLED** (by instruction) |

**Bottom line:** the reliability defect is fixed and proven in code; making it take effect on the
running system requires a worker/beat rebuild and killing host PID 23280 — both deliberately left for
owner approval.
