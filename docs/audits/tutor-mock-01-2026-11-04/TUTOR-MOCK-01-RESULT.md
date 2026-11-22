# TUTOR-MOCK-01 Result

- **Timestamp:** 2026-11-04T14:43Z (Asia/Saigon 21:43)
- **Branch:** `feat/p6.0-ci-pipeline`
- **HEAD:** `d747e78ee8392a354db79805fe73b1477bc0c531` (unchanged before/after)
- **Working tree before:** 15 modified + 8 untracked paths; `15 files changed, 6574 insertions(+), 1348 deletions(-)`; **0 backend files modified**
- **Working tree after:** identical — same 15 modified, same untracked set. No stash/reset/checkout/clean/commit/push.
- **Backend image:** `reverseengineer-backend:latest` `sha256:4425e3e2…`, built 24 h before the gate (matches the container that served every probe).

## Source documents read

- `docs/SOPISKILL_CLAUDE_CODE_NEXT_PHASE_2026-11-04.md` (task spec)
- `docs/audits/polyskill-parity-2026-11-04/00-executive-summary.md` (baseline figures)
- `backend/app/core/config.py`, `backend/app/api/v1/tutor.py`, `backend/app/services/tutor_service.py`
- `backend/app/services/tutor_context.py`, `tutor_tools.py`, `sse.py`, `app/core/limits.py`
- `backend/app/providers/mock_provider.py`, `providers/__init__.py`, `openai_compatible_provider.py`
- `backend/e2e_acceptance.py`, `backend/tests/conftest.py`, `test_p30_tutor.py`, `test_p31_tutor_controls.py`, `test_p30_tutor_stream_provider.py`
- `docker-compose.yml`, `backend/Dockerfile`, `frontend/package.json`, `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx`

## Root cause of 503

Four independent layers agree, so this is not inference:

1. `backend/app/core/config.py:95` — `tutor_enabled: bool = False`
2. `docker-compose.yml` lines 79 / 220 / 352 — `TUTOR_ENABLED: ${TUTOR_ENABLED:-false}` for backend, worker, beat
3. No `TUTOR_ENABLED` key exists in `.env`, so the compose default wins
4. Live container `printenv TUTOR_ENABLED` → `false`

`_require_enabled()` (`app/api/v1/tutor.py:93`) returns 503 `TUTOR_DISABLED` **before** any course lookup. Quota is *not* the cause: `_check_daily_quota` returns early when both limits are `<= 0`, and the live container has `TUTOR_MESSAGES_PER_DAY=0` / `TUTOR_TOKENS_PER_DAY=0` ⇒ **0 means unlimited**, exactly the trap the plan's §2.6 warned about.

## Environment / provider — proof it is MOCK

- `/health` → `{"status":"ok","env":"development","provider":"mock"}` (before, during, and after)
- Container env during the ON run: `TUTOR_ENABLED=true`, `LLM_PROVIDER=mock`, `TUTOR_TOOLS_ENABLED=false`, `RAG_ENABLED=false`
- Stream body begins: `"Mình là trợ giảng ở chế độ MOCK (không phải AI thật). …"` — the literal marker only `MockProvider` emits
- `MockProvider.stream_tutor_reply` (`app/providers/mock_provider.py:214`) performs **no network I/O and no sleep**; it splits a canned answer on spaces and yields words
- No real-provider key was used: `grep -cF "$LLM_API_KEY"` over the container log → **0 matches**

## Changes

Only new, untracked files. **No tracked file was edited.**

| Path | Purpose |
|---|---|
| `docs/audits/tutor-mock-01-2026-11-04/docker-compose.tutor-on.yml` | Ephemeral override: `TUTOR_ENABLED=true`, `LLM_PROVIDER=mock`, tools/RAG off. Backend service only. Applied via `-f`; never merged into `.env`. |
| `…/probe_tutor_off.py` | Criterion 1 probe |
| `…/probe_tutor_on.py` | Criteria 2–5 probe (+ C6 stop sub-checks) |
| `…/probe_tutor_disconnect.py` | Criterion 6 live mid-stream disconnect probe |
| `…/logs/*.log` | Raw outputs, hashed below |

Runtime change applied and reverted: `docker compose -f docker-compose.yml -f …/docker-compose.tutor-on.yml up -d --no-deps backend`, then `docker compose up -d --no-deps backend` to restore the default. `get_settings()` is `@lru_cache`d, which is why a recreate — not a reload — was required.

## IMPLEMENTED

- **Nothing in the product.** This gate was diagnosis + acceptance testing. The Tutor code already existed and was already correct on every path tested; the 503 was purely configuration.
- Two non-product artifacts were authored (probe scripts + ephemeral override), listed above.

## TESTED

| # | Command / probe | Environment | Exit | Result | Log |
|---|---|---|---|---|---|
| 1 | `probe_tutor_off.py` (flag off) | live backend :8001, mock | 0 | `status=503`, `detail.code=TUTOR_DISABLED` — **PASS** | `logs/probe-off.log` |
| 2 | `e2e_acceptance.py` full chain (flag **on**) | live backend, mock, real HTTP | **0** | **71/71 PASS**, incl. steps 12, 12b–12k, 12f, 12g | `logs/e2e-on2.log` |
| 3 | `probe_tutor_on.py` (criteria 2–5 + 6 stop) | live backend, mock, real SSE bytes | 0 | **31/31 PASS** | `logs/probe-on.log` |
| 4 | `probe_tutor_disconnect.py` (criterion 6) | live backend, mock | 0 | stream cut after 200 B → assistant persisted `cancelled` / `TUTOR_CANCELLED`, partial content kept (324 chars) | `logs/probe-disconnect.log` |
| 5 | `pytest` (backend suite) | SQLite in-memory, `LLM_PROVIDER=mock` | 0 | **699 passed, 29 skipped**, 165.73 s | `logs/pytest.log`, `logs/pytest-tail.txt` |
| 6 | `npx tsc --noEmit` | frontend working tree | 0 | No errors | — |
| 7 | `npm run build` | frontend working tree | 0 | Next 15.5.28, 8.7 s, **11/11 static pages** | — |
| 8 | Re-verify OFF after revert | live backend | 0 | `503 TUTOR_DISABLED` — **PASS** | `logs/probe-off-revert.log` |

### Criterion 2 — real bytes, not a stub

From `logs/probe-on.log`:

```
[PASS] C2 status 200 :: status=200
[PASS] C2 content-type is text/event-stream :: ctype='text/event-stream; charset=utf-8'
[PASS] C2 >=1 delta frame :: deltas=71
[PASS] C2 terminal frame is done :: kinds=['delta','delta','delta']...['delta','done']
[PASS] C2 seq monotonic from 0 :: n=72
[PASS] C2 X-Tutor-Thread-Id present :: thread=tth_c061b84b-…
[PASS] C2 X-Tutor-Message-Id present :: msg=tmsg_f8974c10-…
[PASS] C2 mock marker present (proves not real AI) :: head='Mình là trợ giảng ở chế độ MOCK (không phải AI thật). …'
[PASS] C2 RAG off -> no fabricated citation :: has_chk=False
```

### Criterion 3 / 5 — history and idempotency

```
[PASS] C3 history reload user+assistant :: roles=['user','assistant']
[PASS] C3 history content equals streamed text :: assistant_len=329 stream_len=329
[PASS] C3 replaySupported is false (no resume promise)
[PASS] C5 GET usage does not consume quota :: used=4->4
[PASS] C5 replay flagged replayed=true
[PASS] C5 replay reuses same messageId :: tmsg_f8974c10-… == tmsg_f8974c10-…
[PASS] C5 replay does not double-charge quota :: used=4->4
```

### Criterion 4 — authorization

```
[PASS] C4 user B reads A's thread -> 404
[PASS] C4 user B lists A's course threads -> 404
[PASS] C4 user B posts into A's course -> 404
[PASS] C4 missing CSRF -> 403
[PASS] C4 no session -> 401
[PASS] C4 blockIndex out of range -> 422 TUTOR_CONTEXT_INVALID
[PASS] C4 systemPrompt smuggle rejected (422)
```

## NOT TESTED

- **`NOT TESTED browser UI`** — no browser harness exists (`package.json` has no e2e/test script; no Playwright/Cypress/Vitest/Jest, no test directories). A CDP endpoint at :9222 responds (`Chrome/156.0.8078.76`, HeadlessChrome) but reports `targets: []` with all exclusion counters 0, so there was no page to drive. `tsc` + `build` prove compilation, not that the panel renders and streams in a real browser.
- **Mid-stream provider *error*** (as opposed to client disconnect) — not exercised live. `MockProvider` never raises. The behavior is covered only by unit tests `test_provider_error_becomes_sse_error_and_persists_failed` (`test_p30_tutor.py:551`) and `test_stream_http_status_maps_to_taxonomy` (`test_p30_tutor_stream_provider.py:135`), which are green but are not a live-stream observation.
- **Server-side timeout** (`tutor_stream_timeout_seconds=60`) — not triggered live; `MockProvider` returns in milliseconds.
- **Tutor tool loop** — off by design (`TUTOR_TOOLS_ENABLED=false`); live run correctly emitted no `tool` frame (step 12k).
- **RAG citation path** — off by design (`RAG_ENABLED=false`); verified the stream fabricates no `chk_` id.
- **`/v1/me/stats` and `/v1/me/entitlement` (404 baseline)** — untouched by this gate and not re-probed; they remain part of `M1-ME-SURFACE`.
- **PostgreSQL concurrency races** — all 29 skips are `POSTGRES_TEST_URL`-gated; no Postgres race test ran, so tutor concurrency under load is unverified.

## BLOCKED

- **Nothing blocked this gate.** The full-chain E2E that failed during preflight (`409 JOB_ALREADY_ACTIVE` at step 11g) passed on re-run once the stale host Celery node was gone.
- **Environment hazard recorded (not fixed):** during preflight, `celery inspect ping` showed two online nodes — container `celery@3b68eafd0ab0` and a stale host process `celery@LAPTOP-8DN2AGTV` (PID 23280, started 2026-11-03 14:31), alongside a stale host uvicorn (PID 27632, :8000). The stale worker consumed a dispatched task, leaving job `ce9d5596-8d62-4bed-9253-37b02fec255e` permanently `queued` with `dispatched_at` already set — `recover_stuck_jobs()` only re-dispatches rows where `dispatched_at IS NULL`, so it can never reclaim that row. That job still sits `queued` in the DB. **I did not kill the host processes** — they are owner environment state outside the approved scope. Before the re-run, `inspect ping` showed only `1 node online`, and the E2E then passed. Recommendation (owner decision, not performed): kill PID 23280/27632 and clear the orphan row.

## Security probes

| Probe | Expectation | Observed |
|---|---|---|
| User B reads A's thread | 404 | 404 |
| User B lists A's course threads | 404 | 404 |
| User B posts into A's course | 404 | 404 |
| POST without CSRF | 403 | 403 |
| POST with no session | 401 | 401 |
| Forged cookie (E2E step E) | 401 | 401 |
| `blockIndex` out of range | 422 `TUTOR_CONTEXT_INVALID` | 422 |
| `systemPrompt` / lesson-content smuggle | 422 | 422 |
| Duplicate `clientMessageId` | replay, no 2nd provider call | `replayed=true`, same messageId, quota unchanged |
| `GET /tutor/usage` | does not consume quota | `used=4→4` |
| Real API key in logs | absent | `grep -cF` → 0 matches |
| `_require_enabled()` / quota guard removed? | **no** | both intact; 503 re-proven after revert |

## E2E verdict

**`PRODUCT_E2E_PASS`** for the mock-provider, non-production scope of this gate.

Evidence: the full 71-step chain returned `EXITCODE=0` with `===== KET QUA: 71/71 PASS =====` against the live backend on the mock provider, including every tutor step. This is not an audit-driver exit-0 claim: the individual assertions are printed and all passed, and the tutor assertions were independently reproduced by `probe_tutor_on.py` at 31/31 reading raw SSE bytes.

Caveats that keep this from being a product-wide pass: it is **mock-provider only**, it is **non-production**, and `browser UI` is untested. The audit's measured parity (74.7 % = 62/83) and Evidence Coverage (53/100) are **unchanged by this gate** — this gate closes a configuration gap, it does not raise parity.

## Regression verdict

**PASS.** Backend `699 passed, 29 skipped` matches the audit baseline exactly (same counts, same skip reasons — all `POSTGRES_TEST_URL`-gated). Frontend `tsc` and `build` both exit 0 with 11/11 static pages. No backend file was modified, so the backend result is a true regression check on an unmodified tree.

## Rollback

Already applied. The backend container was recreated from the stock compose file (no override), and `printenv TUTOR_ENABLED` → `false`; `probe_tutor_off.py` re-confirmed 503 `TUTOR_DISABLED` (log hashed identical to the pre-change run: `fa7a9d82…`). `.env` was never touched. The override file remains on disk as an untracked audit artifact and has no effect unless explicitly passed with `-f`.

## No paid calls / no destructive operation proof

- `LLM_PROVIDER=mock` in `.env`, in the compose default, in the override, and in the live container. `MockProvider` does no network I/O.
- Provider budget was never engaged; `deepseek-ai/deepseek-v4.1-flash-1017` / `api-cdn.deploy.com` were configured but never called (stream body carries the MOCK marker).
- The container log contains **zero** occurrences of the configured `LLM_API_KEY` (24 chars, `grep -cF` → 0).
- No volume reset, no destructive migration, no push, no commit, no `git clean`/`stash`/`reset`/`checkout`.
- `TUTOR_TOOLS_ENABLED` and `RAG_ENABLED` stayed `false` throughout.

## Artifact hashes (SHA-256)

```
ccd112d4dd8700e50037e450cb98673f5b046b6da97f5e93b7e7448c026e07f2  logs/e2e-off.log
64a692ab63b0b2c9bd522f85431665c175b0a6a15b952ea365de6630f79dd1d2  logs/e2e-on2.log
aacb410ff4bc62d1b658349a2c71ac2179c8c3c404318b8579b6dad4f2b9c4b4  logs/probe-disconnect.log
fa7a9d8273536c03559163cd7d4a7516650bf290542d59f20b7ac96e28061ce2  logs/probe-off.log
fa7a9d8273536c03559163cd7d4a7516650bf290542d59f20b7ac96e28061ce2  logs/probe-off-revert.log
1da70a6f58ccbcf2ac99828441aa0121f02cc9ef84fa07b84fbef495cebc342d  logs/probe-on.log
ac7983a02f0cd3f3df490a6baabb84ada0390b5e125fac08ff329d14cc3b2907  logs/pytest.log
aadda8c53f4c94689718d40416c25b79c2f10b7ee8a01b61ada82816075e632c  probe_tutor_disconnect.py
f69387d326e9c4f0aae28d47097f09a573b6c5281277793eff7053e7d535efa6  probe_tutor_off.py
b807a6119073bba5e96e0e10963362f06b7e9318690e14260becc18172bfe40a  probe_tutor_on.py
b05dd395cb0c3e104759735c1cd751cb2d3aaf7bf311bb80ae65830de03dd92f  docker-compose.tutor-on.yml
```

## Next task proposed (do NOT self-start)

`P1-QUIZ-BLANK` — the smallest deterministic item in the §4 backlog: make the schema/lint require one answer per blank (or N answers for N placeholders), keep backward compatibility for single-blank, add unit + negative E2E coverage. It is size **S**, needs no provider budget, and is backed by the audit's 5/11 multi-blank defect rate.

Two owner decisions also surfaced that are **not** engineering tasks:

1. **Stale host processes** — kill PID 23280 (celery) and PID 27632 (uvicorn) on the Windows host, and clear the orphan job `ce9d5596-8d62-4bed-9253-37b02fec255e`. Until that job is cleared it permanently blocks retry on its own course; it does not affect new courses.
2. **Browser UI harness** — criterion 7 cannot ever pass without one. Starting HeadlessChrome with a real page target at :9222 would also unblock the REA reference-capture track.

**Stopping here per §3.4 / the plan's stopping point.**
