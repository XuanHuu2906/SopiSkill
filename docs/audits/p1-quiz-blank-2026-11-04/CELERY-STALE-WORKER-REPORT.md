# Reliability Report — stale Celery worker & permanently-stuck job

- **Date observed:** 2026-11-04 (first seen during GATE TUTOR-MOCK-01 preflight, still open at the time of P1-QUIZ-BLANK)
- **Action taken:** observation and code reading only. **No process killed, no data deleted or updated.**
- **Classification:** reliability defect — *separate from P1-QUIZ-BLANK*, reported here per instruction.

---

## 1. Symptoms

1. `celery inspect ping` reports **two** online worker nodes while only one should exist:
   - `celery@3b68eafd0ab0` — the containerised worker (correct)
   - `celery@LAPTOP-8DN2AGTV` — a **stale host process** outside Docker
2. A generation job sits `queued` forever with `dispatched_at` already set, so no retry path can
   reclaim it.

Measured at time of writing:

```
celery@3b68eafd0ab0: OK
celery@LAPTOP-8DN2AGTV: OK
2 nodes online.
```

```
status   | count
---------+------
ready    | 194
failed   | 1
queued   | 1        ← the stuck row
```

```
id                                       | status | dispatched_at                   | attempts
ce9d5596-8d62-4bed-9253-37b02fec255e     | queued | 2026-11-04 14:05:54.062715+00   | 0
created_at = 2026-11-04 14:05:54.007802+00
```

The job has been `queued` since creation (~8 h at observation time), with `attempts_count = 0` —
meaning no worker ever *claimed* it, it was only *dispatched*.

## 2. Root cause (two independent facts)

### 2.1 Two consumers on one queue
Both nodes consume from the same broker/queue. The host node was started 2026-11-03 14:31 (PID 23280)
and kept running after the containerised worker came up. A task dispatched from the API is a race
between the two consumers; whichever is prefetched first owns it. When the host worker received a
task and then died/stalled (or lost its result-backend connection), the message was consumed and
never completed — it was not returned to the queue.

### 2.2 The recovery query structurally cannot match this row
`backend/app/services/job_service.py:320-339` (`recover_stuck_jobs`) re-dispatches only:

```python
(GenerationJob.status == JobStatus.queued)
& GenerationJob.dispatched_at.is_(None)      # outbox: committed but never sent to broker
& (GenerationJob.created_at < now - grace)
```

and separately recovers `status == running` with an expired lease.

The orphan is `status = queued` **with `dispatched_at` set** — it matches *neither* branch:

| State | Recovered? |
|---|---|
| queued, `dispatched_at IS NULL` | ✅ outbox branch |
| running, lease expired | ✅ lease branch |
| running, lease alive | ✅ (worker is presumed alive) |
| **queued, `dispatched_at IS NOT NULL`** | ❌ **matches nothing** |

That last state means "we successfully handed the message to the broker, but no worker ever
acknowledged it." Nothing in the codebase watches for it, so the row is unrecoverable without manual
intervention.

## 3. Blast radius

- **Bounded:** only that one course/job. `recover_stuck_jobs` is called periodically and other jobs
  continue normally — the 194 `ready` jobs and the E2E runs in P1-QUIZ-BLANK confirm generation still
  works.
- **Permanent for this row:** it will never retry itself.
- **Not a data-loss event:** no lesson rows were destroyed; the job simply never produced content.
- **Future risk:** if a second stale worker is ever started, the same race can strand additional jobs.
  The window is during dispatch when two consumers are live.

## 4. Recommended remediation (owner decision — NOT performed)

Choose one; none requires touching lesson data.

### Option A — clean the environment, then clear the orphan (recommended, lowest risk)
1. Stop the stale host Celery worker and stale host uvicorn (PIDs observed 23280 / 27632) so only the
   container worker consumes the queue.
2. Re-queue the single orphan through the **supported** API path (`retry_course`) rather than a raw
   `UPDATE`, so `contentVersion`/outbox semantics stay intact.

### Option B — make the state recoverable (code change, small)
Extend `recover_stuck_jobs` with a third branch: `status = queued AND dispatched_at IS NOT NULL AND
created_at < now - stale_window` → treat as "broker acked but no worker claimed" and either
re-dispatch or fail with an explicit code (e.g. `DISPATCH_STALE`). This closes the structural gap for
future occurrences. It needs its own test and is **not** part of P1-QUIZ-BLANK.

### Option C — do nothing
Accept a single permanently-queued row. Only acceptable if the orphan course is not needed.

**Not recommended:** `UPDATE generation_jobs SET dispatched_at = NULL` directly — it bypasses the
outbox contract and can double-dispatch if the original message *is* still in the broker.

## 5. Evidence captured

| Item | Value |
|---|---|
| Stale worker node | `celery@LAPTOP-8DN2AGTV` (host, out-of-container) |
| Correct worker node | `celery@3b68eafd0ab0` (container) |
| Orphan job id | `ce9d5596-8d62-4bed-9253-37b02fec255e` |
| Orphan state | `queued`, `dispatched_at` set, `attempts_count = 0` |
| Job status distribution | 194 ready · 1 failed · **1 queued** |
| Recovery query | `job_service.py:320-339` |
| Impact on P1-QUIZ-BLANK | none — E2E passed 61/61 on a clean single-node ping |

## 6. Why this was not fixed here

The operator instruction for P1-QUIZ-BLANK was explicit: record the stale-worker issue as a separate
reliability problem and **do not kill processes or delete data**. Both remediation options above
involve either killing a host process (A) or shipping new worker semantics (B), so both are outside
this phase's approved scope.

---

## 7. Addendum — 2026-11-04 (GATE RELIABILITY-CELERY-01)

Independent re-verification in the later gate confirmed the root cause below and added two corrections:

1. **The host worker is still live, not historical.** PID **23280** is alive (~33 h) and its
   `cmd=brpop` is currently held on the shared Redis `celery` list alongside the container consumer;
   yet only 1 node answers `celery inspect ping`. The two-consumer race is live.
2. **`worker_visibility_timeout` is not a valid Celery 5 setting** and was silently ignored, so broker
   redelivery was never configured. Option B was implemented and tested (not deployed) in that gate.

Option B is now **implemented + tested** (31 reliability tests, 720 full suite, 61/61 live E2E) but
**not deployed** — deployment needs a worker/beat rebuild and killing PID 23280, both left for owner
approval. See `docs/audits/reliability-celery-01-2026-11-04/RELIABILITY-CELERY-01-RESULT.md`.
