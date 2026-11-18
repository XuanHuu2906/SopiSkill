# GATE RELIABILITY-CELERY-02 — PHASE A preflight (READ-ONLY)

- **Date:** 2026-11-05
- **Branch:** `feat/p6.0-ci-pipeline` · **HEAD:** `d747e78` (no commit, no push)
- **Actions taken:** read-only only. **No process killed, no container restarted, no image rebuilt, no DB/Redis/volume mutation, no paid provider call.**
- **Classification:** PREFLIGHT COMPLETE — **awaiting explicit owner approval for PHASE B.**

---

## 1. Documents read

| File | Used for |
|---|---|
| `AGENTS.md` | Mandatory rules: no destructive DB/volume ops, no PASS without executed evidence, select `sopi-celery-reliability`. |
| `docs/audits/reliability-celery-01-2026-11-04/RELIABILITY-CELERY-01-RESULT.md` | Prior gate: fix implemented+tested, **§6 runtime gap** (containers pre-fix). |
| `docs/audits/p1-quiz-blank-2026-11-04/CELERY-STALE-WORKER-REPORT.md` | Original orphan report + §7 addendum. |
| `backend/app/services/job_service.py`, `backend/app/worker/celery_app.py`, `backend/app/worker/reconcile.py`, `backend/app/core/config.py`, `docker-compose.yml` | Source of truth for the fix, scheduler wiring, and service topology. |

`docs/development-progress.md` was read previously and re-checked via `git status` (it is dirty — a ledger update, not code).

---

## 2. Git state — untouched

```
branch : feat/p6.0-ci-pipeline
HEAD   : d747e78   (no new commit, nothing pushed)
```

Dirty **backend** files (this is what a rebuild would ship — **6 files, not 3**):

| File | Origin | Δ |
|---|---|---|
| `backend/app/services/job_service.py` | RELIABILITY-CELERY-01 | +29 / −1 |
| `backend/app/core/config.py` | RELIABILITY-CELERY-01 | +4 |
| `backend/app/worker/celery_app.py` | RELIABILITY-CELERY-01 | +12 / −3 |
| `backend/tests/test_job_reliability.py` | RELIABILITY-CELERY-01 | +193 (6 tests) |
| **`backend/app/providers/validation.py`** | **P1-QUIZ-BLANK** | **+33 / −13** |
| **`backend/app/worker/generation.py`** | **P1-QUIZ-BLANK** | **+4** |

> ⚠️ **Decisive planning fact:** the two P1-QUIZ-BLANK files are *not* part of this gate but **would ride along in any image rebuild**. They add strict single-blank validation (`BLANK_SLOT_COUNT = 1`) and call `validate_lesson(content)` in the lesson write path. This changes generation-failure behaviour for real providers. **Owner must decide: ship them together, or stash them for an isolated rollout (see §7.2).**

Dirty frontend files (~16) and untracked docs do not affect backend images.

---

## 3. Runtime topology

```
SERVICE    NAME                          STATUS
backend    reverseengineer-backend-1     Up 2 hours
beat       reverseengineer-beat-1        Up 26 hours
db         reverseengineer-db-1          Up 34 hours (healthy)
frontend   reverseengineer-frontend-1    Up 26 hours
minio      reverseengineer-minio-1       Up 34 hours (healthy)
redis      reverseengineer-redis-1       Up 34 hours (healthy)
worker     reverseengineer-worker-1      Up 2 hours
```

Celery version in the worker container: **5.6.3** — the version where `worker_visibility_timeout` is silently ignored.

---

## 4. THE FIX IS NOT LIVE — proven, not inherited

The worker/backend containers were **restarted 2 hours ago**, yet still carry pre-fix code:

```console
$ docker compose exec -T worker sh -c "ls -l /app/app/services/job_service.py ...; grep -c ..."
-rwxr-xr-x 1 root root 13851 Oct 31 11:21 /app/app/services/job_service.py
-rwxr-xr-x 1 root root  3102 Nov  2 08:58 /app/app/worker/celery_app.py
--- stale branch count ---   0
--- transport opts ---       0
```

Same `0` for `backend` and `beat`.

**Why a restart cannot fix this:** `docker-compose.yml` defines **no volumes** for `backend`, `worker`, or `beat` — the source is *baked into the image*. A plain restart re-runs the same old image. **`docker compose build` is mandatory.**

---

## 5. Host PID 23280 — live, and actively degrading the queue

| Fact | Value |
|---|---|
| PID | **23280** (python, 64-bit CPython 3.13) |
| Start | 2026-11-03 14:31:42 — **~47 h** at check time |
| CPU | 256.8 s |
| Command | `python -m celery -A app.worker.celery_app:celery_app worker --loglevel=info --pool=solo` |
| Broker sockets | **11 established connections to `127.0.0.1:6379`** |
| Log | `...\Temp\opencode\ps-recon\celery-ui.log`, **870 613 B**, last write `2026-11-05 00:23:05` |
| Recent activity | **1 332** `succeeded in …` lines in the log tail |
| Latest tasks | `reconcile_ingest[…] succeeded in 21.179/21.237/21.221 s: []` at 00:22:18 / 00:22:50 / 00:23:22 |

**Origin:** its parent is a leftover **opencode agent session** that ran
`cd backend && . .../backend-ui.env && python -m celery … worker --pool=solo > celery-ui.log &`.
It is **not** a user-launched service. It points at the **same** Redis (`localhost:6379`) and the **same** Postgres (`localhost:5433`) as the containers.

**Why every task costs ~21 s:** Redis holds **two** `brpop` consumers on the shared `celery` list. The host worker therefore wins a fair share of every scheduled message. Every task it takes blocks ~21 s — the Windows `localhost` → `::1` connect stall — then returns `[]` without doing the work. It also emits `missed heartbeat from celery@…` on the container every ~20 s.

**Brand-new measurement (15-min window):**

| Metric | Value |
|---|---|
| beat sends `recover-stuck-generation-jobs` | **28** |
| container worker receives `reconcile_jobs` | **30** |
| Container now receives reconcile tasks | ✅ yes (the deficit case is gone; reconcile is reaching the container) |

So recovery *is* currently running on the container — **it simply cannot match the orphan**, because the running code has only two branches. The race is still live for *ingest/embedding/skills* throughput: those task families are still split between the two consumers and slowed to ~21 s each.

**Conclusion:** PID 23280 is a genuine reliability defect with a **separate, ongoing cost** — but it is **not** the reason the orphan stayed stuck. The orphan stayed stuck because the third branch is not deployed. Both must be addressed; they are independent.

---

## 6. In-flight work, orphan, and broker residue

### 6.1 No in-flight work — restart is safe from a work-loss standpoint

```
celery inspect active    : - empty -
celery inspect reserved  : - empty -
celery inspect scheduled : - empty -
LLEN celery              : 0
generation_jobs running  : 0
```

### 6.2 The orphan is unchanged and unclaimed

```
ce9d5596-8d62-4bed-9253-37b02fec255e | queued
  dispatched_at     = 2026-11-04 14:05:54.062715+00
  dispatch_attempts = 1      (max = 5)
  attempts_count    = 0      ← no worker ever claimed it
  lease_expires_at  = NULL
```

Its course `d3612197-a430-4909-8b5b-c8aafa671648` is still `status='generating'` and **already has 4 lesson rows** — generation was partially written before the orphan stranded. Its job is the only non-terminal job in the system (`ready=197, failed=1, queued=1`).

### 6.3 Broker residue — one benign unacked delivery

```
ZCARD unacked_index = 1
delivery_tag = be0129c2-1301-4824-904e-ad6b22a426e0
task         = app.worker.ingest.reconcile_ingest
origin       = gen1@3460cbac498c     ← a container that no longer exists
```

`reconcile_ingest` is idempotent (it re-scans `queued`/expired documents). On redelivery it is a harmless no-op. **No action required, no data at risk.**

---

## 7. Rollout plan (PROPOSED — not executed)

### 7.1 Blast radius — services to touch

| Service | Action | Reason |
|---|---|---|
| `worker` | `build` + recreate | runs `job_service`, `celery_app` |
| `beat` | `build` + recreate | runs the reconciler every 30 s |
| `backend` | `build` + recreate | serves retry/approve; runs `generation.py` |
| **`db`, `redis`, `minio`, `frontend`** | **TOUCH NOTHING** | explicitly out of scope; no migration |

### 7.2 Two variants — owner picks one

**Variant 1 — isolated reliability rollout (RECOMMENDED).**
Temporarily stash the two P1-QUIZ-BLANK files so only this gate ships:

```bash
git stash push -- backend/app/providers/validation.py backend/app/worker/generation.py
docker compose build worker beat backend
docker compose up -d --no-deps worker beat backend
# … verify (Phase C) …
git stash pop        # restore P1-QUIZ-BLANK work to the tree afterwards
```

*Pro:* the deployed diff is exactly the gate's 4 files; a regression cannot be blamed on QUIZ-BLANK changes; rollback is unambiguous.
*Con:* `git stash pop` after the verify window must be run, or the QUIZ-BLANK work sits in a stash.

**Variant 2 — ship the whole dirty backend tree.**
`docker compose build worker beat backend && docker compose up -d --no-deps worker beat backend`
*Pro:* simpler, no stash juggling.
*Con:* P1-QUIZ-BLANK's stricter blank validation goes live in the same step; if a real-provider generation starts failing validation, the failure is entangled with this gate.

> Phase C would run with the **mock** provider only, so neither variant can incur cost. Variant 1 is recommended purely for clean attribution.

### 7.3 Retiring the stale host worker

Only after the rebuilt containers are healthy:

```powershell
Stop-Process -Id 23280            # the leftover opencode Celery worker
# parent bash.exe 26960 is the dead opencode session; confirm it exits on its own.
```

*Risk:* near zero — it holds no `active`/`reserved` tasks (§6.1) and the broker list is empty (`LLEN = 0`). Any message it prefetched is either already `dispatched_at`-marked or will be re-dispatched by the reconciler.
*Not done automatically:* requires explicit approval.

### 7.4 Ordering that avoids a recovery race

1. **Build images first** (CPU-only, touches no runtime).
2. **Stop PID 23280 before `up -d`** — removes the second consumer so the rebuilt worker is the only one draining the queue during verification.
3. **`up -d --no-deps worker beat backend`** — the three services only; db/redis/minio/frontend untouched.
4. Let one reconcile tick (~30 s) run, then inspect.

---

## 8. Rollback plan

### 8.1 Code rollback (preferred)
Images are immutable and tagged `latest`; the pre-fix images remain on disk with known IDs:

| Service | Current (pre-fix) image ID |
|---|---|
| backend | `0ab6b46dd9ca` |
| worker | `435827193333` |
| beat | `cb3713c9a11e` |

Rollback is a **re-pin + recreate**, no rebuild:

```bash
docker tag 435827193333 reverseengineer-worker:rollback
docker tag cb3713c9a11e reverseengineer-beat:rollback
docker tag 0ab6b46dd9ca reverseengineer-backend:rollback
# point compose at :rollback (or `docker compose up -d --no-deps --force-recreate` after retagging :latest)
```

If Variant 1 was used, `git stash pop` restores the tree. **No database migration exists**, so no down-migration is needed.

### 8.2 Data rollback — none required, and none permitted
This gate performs **no schema change and no data write**. The orphan row is only ever touched by the *application's own* reconciler, through the normal outbox path. `docker compose down -v`, `DROP`, and volume deletion are **explicitly forbidden** by `AGENTS.md` and by this gate's instructions.

### 8.3 Recovery of the orphan if the rollout must be abandoned
The row is untouched by this gate. It can remain `queued` (harmless) or be retried through the supported API (`retry_course`) — never by a raw `UPDATE`.

---

## 9. Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Rebuild ships P1-QUIZ-BLANK changes unexpectedly | **High if Variant 2** | Use Variant 1 (stash), or acknowledge explicitly |
| R2 | Reconciler re-dispatches the orphan and generation writes **duplicate lessons** on the 4 existing rows | Low | `claim_job` is one atomic `UPDATE…RETURNING`; only one task wins. Must still be **measured** in Phase C. |
| R3 | Orphan is re-dispatched but `dispatch_attempts` already 1/5 — could exhaust and mark course `failed` | Medium | Phase C must watch `dispatch_attempts`; `DISPATCH_EXHAUSTED` is a terminal, non-destructive outcome |
| R4 | Host worker keeps stealing tasks during the verify window | **Certain unless stopped** | Stop PID 23280 in step 2 of §7.4 |
| R5 | `visibility_timeout` set too low would redeliver live tasks | Low | `task_time_limit = 2400 s`, intended `visibility_timeout = 3600 s` — the ratio is safe; Phase C must confirm the effective value from the live app |
| R6 | Restart during an unnoticed in-flight generation | **None** | §6.1 proves zero running jobs and an empty queue at check time; re-check immediately before acting |
| R7 | Windows `localhost`→`::1` stall persists for the container worker | Low | Containers use the service name `redis`, not `localhost` |

---

## 10. What Phase C must prove (contract for the next phase)

Only after approval:

1. All three containers report the **new** files (`grep` on baked source).
2. The **running** Celery app reports `broker_transport_options["visibility_timeout"] = 3600` and no `worker_visibility_timeout`.
3. The reconciler **actually invokes** the third branch — evidenced by a log line + a state change, not by unit tests.
4. Orphan `ce9d5596-…` reaches a **terminal** state (`ready` or `failed`), and lesson count for its course is reported **before and after**.
5. A **new** test job reproduces stale dispatch and is recovered within a bounded time.
6. No duplicate lessons, no extra `llm_usage_events`, no duplicate jobs.
7. `pytest` + E2E (mock) + negative/security cases with exit codes.
8. Before/after diff of §6 counts, with **every** failure shown.

---

## 11. Baseline for the before/after comparison (2026-11-05)

```
courses=100  lessons=350  attempts=144  jobs=199
units=172    skills=0     usage=25      docs=33
max lesson created_at = 2026-11-04 16:28:51.061227+00
jobs: ready=197  failed=1  queued=1
orphan: ce9d5596-8d62-4bed-9253-37b02fec255e (queued, attempts=0, dispatch_attempts=1)
course: d3612197-a430-4909-8b5b-c8aafa671648 (generating, 4 lessons)
```

---

## 12. Classification

| Item | Status |
|---|---|
| Preflight items 1–8 | **COMPLETE** |
| Anything killed / restarted / rebuilt / mutated | **NO — read-only throughout** |
| Fix live in containers | **NO** — proven by baked-file inspection |
| Rollout plan + rollback written | **YES** (§7, §8) |
| **PHASE B approval** | **PENDING — owner decision required** |

**Two decisions are needed before anything else happens:** (a) Variant 1 or Variant 2 in §7.2, and (b) approve stopping host PID 23280.
