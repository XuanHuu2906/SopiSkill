# 15 — Verification Strategy, Test Matrix & Acceptance Scenarios

**Trạng thái:** TEST PLAN / NOT EXECUTED in specs creation. Lịch sử test được ghi nhận ở `00-STATUS-AND-SOURCES.md`.

## 1. Test layers

- **Unit:** Pydantic validation, grading, normalization, proposal DAG, RRF/fusion, citation validator, quota logic với mock fixtures.
- **API integration:** FastAPI routes + auth cookie/CSRF + DB owner checks; SQLite cho behavior thuần, PostgreSQL thật cho transactions/unique/race.
- **Worker integration:** PostgreSQL + Redis + Celery; duplicate delivery, broker down, worker crash, lease expiry, bounded retry.
- **Frontend:** Next.js build/typecheck, browser E2E cho switching users, quiz UI, stream and citations (Playwright khi thiết lập).
- **Real AI evaluation:** có phê duyệt budget, key/PII controls, output + metadata; không chạy trong CI mặc định.
- **Security:** authorization matrix, key leakage scans, SSRF/file corruption, contextRef injection, prompt-injection fixtures.

## 2. Critical cross-phase matrix

| Scenario | Phase | Expected result |
|---|---|---|
| T-001 register/login/logout/me | All | Session đúng; JWT/CSRF/Argon2id hợp lệ |
| T-002 cross-owner resource access | All | 404 course/lesson/attempt/thread/source |
| T-003 5 interview and proposal | P2.1 regression | Exactly 5, valid schema, no duplicates |
| T-004 approve concurrency | P2.1 regression | One active generation job; proposal version pinned |
| T-005 worker duplicate/recovery | P2.1 regression | No duplicate lessons; state correct |
| T-006 invalid LLM output/timeout/429 | P2.1 | Correct code + bounded retries |
| T-007 quiz key privacy | All | GET lesson no answer key in 5 quiz types |
| T-008 attempt race & XP | All | Single logical attempt on same ID, no XP farm |
| T-009 content version/reload | All | Stale 409; old history preserved; progress current |
| T-010 DAG cycle/missing node | P2.1 | Invalid proposal rejected before approval/generation |
| T-011 10 topic pedagogy evaluation | P2.2 | Reproducible rubric report, failure cases captured |
| T-012 Tutor SSE full & disconnect | P3.0 | Ordered delta/done/error, persisted final state |
| T-013 Tutor idempotency/quota | P3.0–P3.1 | No double calls, quota prevents request |
| T-014 Tutor server-side stop | P3.1 lát A | Flag honoured while tokens flow; `cancelled` frame; partial kept; stop-vs-completed race |
| T-015 Tutor allowance accounting | P3.1 lát A | Message/token/concurrency limits block before provider; `quota` in error body |
| T-016 Tutor stale stream recovery | P3.1 lát A | Orphan `running` → `failed/TUTOR_STALE`, user not locked |
| T-017 Tutor tool allowlist | P3.1 lát B | Unknown tool/args/OOB blocked before execute; audit metadata-only |
| T-018 Tutor tool resilience | P3.1 lát B | Planner error/unsupported ⇒ turn still answers, no `tool` frame |
| T-014 Tool allowlist/cancel | P3.1 | Unauthorized tool blocked, stop semantics observed |
| T-015 PDF ingest failcases | P4.0 | Reject corrupt/oversize, no cross-user data |
| T-016 Citation integrity | P4.1 | All display citations resolve valid authorized chunks |
| T-017 RAG injection/no sources | P4.1 | No instruction hijack; abstain without evidence |
| T-018 URL SSRF/redirect | P4.2 optional | No private/internal fetch |
| T-019 Review schedule/timezone | P5 | Correct FSRS versioned dates, no synthetic history |
| T-020 Backup-restore staging | P6 | Recovery verified, schema/data intact |

## 3. End-to-end acceptance: current mock flow

**Given** fresh test user + isolated DB, `LLM_PROVIDER=mock`.

1. Register/login; GET `/v1/me` identity matches.
2. POST course `topic="Python cho người mới"`, retry same `clientCourseId` → same course.
3. Submit exactly 5 interview answers, GET proposal valid.
4. Approve twice concurrently, only one active job.
5. Poll generation (≤ workload cap) → ready, at least 2 lessons (mock hiện được báo 4).
6. GET lesson never includes private keys, submit correct quiz with private test fixture → correct score.
7. Reload/new session: attempt/progress/XP persisted; A logout/B login: no course A visible.
8. Fake user ID, stale contentVersion, double submit, wrong lesson owner and worker retry all rejected/handled correctly.

Record logs/commands/exit codes. Do **not** label mocked flow as real provider success.

## 4. P2.1 acceptance suite

- Each topic fixture returns normalized profile, proposal DAG acyclic and versioned.
- Lesson includes teach+quiz, nonempty pedagogical content, no duplicated options, answer keys only server-side.
- Provider failure taxonomy tested (config error, 429, 5xx, timeout, invalid JSON, budget).
- E2E job retry/cancel not corrupt old attempts, schema migrations backward compatible.
- External API evaluation runs only after explicit real cost/dataset approval; otherwise `BLOCKED REAL` and mock integration `TESTED MOCK` separately.

## 5. P3/P4 separate release gates

**Tutor gate:** SSE id/order, terminal event semantics, history persistence, 404 cross-user, quota block before provider, no duplicate call, tool allowlist/cancel behavior.

**P3.1 lát A evidence (2026-10-31):** `tests/test_p31_tutor_controls.py` (11),
`tests/test_p31_tutor_migration_contract.py` (5), `tests/test_p31_tutor_postgres_concurrency.py` (4,
cần `POSTGRES_TEST_URL`), E2E 61/61 (tutor on) và 52/52 (off). Tool allowlist (T-006) vẫn **NOT TESTED**
vì chưa triển khai.
**RAG gate:** pages/chunks traceable from owned PDF, no file/URL abuse, 30+ retrieval eval queries, 100% displayed citations resolve valid owned pointers, no-source abstention and injected text test.

## 6. Evidence report template

```text
Phase: P2.1
Git branch/HEAD/status: ...
Implemented modules: ...
Tests: <exact command>; <exit code>; <passed/failed/skipped>; environment...
NOT TESTED: ...
BLOCKED: ...
Migrations: revision, backup, temp DB upgrade/downgrade, result...
Security: owner/CSRF/answer key/secrets/cost...
Regression: ...
Phase gate: PASS | PARTIAL | BLOCKED
```

Không báo PASS khi chưa chạy; test đã báo trước đây không thay thế test sau code change.
