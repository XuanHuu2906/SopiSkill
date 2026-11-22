# 01 — Repo and tool baseline

**Audit date:** 2026-11-04 (Asia/Ho_Chi_Minh, UTC+07)
**Mode:** AUDIT-ONLY. No product source, config, database, migration, or deployment was modified.
**Evidence label legend:** `FACT` / `INFERENCE` / `UNKNOWN` / `PROPOSAL` × `STATIC` / `RUNTIME` / `SOPISKILL_CODE` / `SOPISKILL_TEST` / `REPORTED`.

---

## 1.1 SopiSkill repository identity

| Field | Value | Label |
|---|---|---|
| Working directory | `D:\Reverse Engineer` | FACT / RUNTIME |
| Branch | `feat/p6.0-ci-pipeline` | FACT / RUNTIME |
| HEAD | `d747e78ee8392a354db79805fe73b1477bc0c531` | FACT / RUNTIME |
| HEAD subject | `docs(p6.1): record the real GitHub Actions run and close the CI gate` | FACT / RUNTIME |
| Remote `origin` | `git@github.com:XuanHuu2906/SopiSkill.git` | FACT / RUNTIME |
| Divergence vs `origin/main` | `0` behind, `38` ahead (`git rev-list --left-right --count origin/main...HEAD`) | FACT / RUNTIME |
| Working tree | **DIRTY** — 15 modified tracked files, 8 untracked paths | FACT / RUNTIME |

**Command provenance:** `git log --oneline -25`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `git remote -v`, `git rev-list --left-right --count origin/main...HEAD`, `git status --porcelain=v1`, `git diff --stat` — all run 2026-11-04 ~17:20 +07.

### Dirty-tree inventory (FACT / RUNTIME)

Modified (insertions/deletions from `git diff --stat`):

| File | Δ |
|---|---:|
| `docs/development-progress.md` | +567 |
| `frontend/src/app/globals.css` | +4116 / −… |
| `frontend/src/app/lesson/[lessonId]/page.tsx` | 829 changed lines |
| `frontend/src/app/course/[courseId]/page.tsx` | 391 |
| `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx` | 394 |
| `frontend/src/app/new/proposal/page.tsx` | 328 |
| `frontend/src/app/page.tsx` | 267 |
| `frontend/src/app/sources/page.tsx` | 244 |
| `frontend/src/app/new/interview/page.tsx` | 195 |
| `frontend/src/app/new/generating/page.tsx` | 168 |
| `frontend/src/app/login/page.tsx` | 160 |
| `frontend/src/app/review/page.tsx` | 129 |
| `frontend/src/app/new/page.tsx` | 100 |
| `frontend/src/app/providers.tsx` | 26 |
| `frontend/src/app/layout.tsx` | 8 |

Total diff: **+6574 / −1348 across 15 files**. All 15 modified files are frontend or frontend-adjacent documentation; **no backend file is modified**.

Untracked: `docs/CLAUDE_CODE_REA_POLYSKILL_PARITY_AUDIT.md`, `docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`, `docs/frontend-reconstruction-log.md`, `docs/frontend-reference/`, `frontend/.dockerignore`, `frontend/public/`, `frontend/src/app/fonts.css`, `frontend/src/components/`.

> **Caveat that must follow every frontend claim in this audit:** the frontend that runs in the container (built from HEAD `d747e78`) is **not** the working-tree frontend. Any statement about frontend behaviour below is marked either `HEAD/BUILD` (the built image, verifiable via `npm run build` + HTTP on :3000) or `WORKING_TREE` (source on disk, uncommitted). Where the two differ, the audit reports both and does not merge them.

## 1.2 Repository layout (FACT / RUNTIME)

Top level: `.agents/ .claude/ .github/ .opencode/ .superpowers/ backend/ docs/ frontend/ research/`, plus `docker-compose.yml` (25.4 KB), `README.md`, `AGENTS.md`, `.env.example` (14.0 KB), 5 `backup_pre_p*.sql` dumps, and 3 historical PolySkill analysis documents (`polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md`, `polyskill_blackbox_test_plan.md`).

- **No `apps/web`, no `services/api`, no monorepo workspace file.** Layout is a two-directory split: `backend/` (FastAPI) + `frontend/` (Next.js). Mandate §Phase A asks to confirm this explicitly — confirmed.
- `backend/`: `app/` (81 `.py` files, **20,680 lines**), `alembic/versions/` (16 migrations), `tests/` (**68** `.py` files), `evals/` (15 modules), `scripts/`, `e2e_acceptance.py` (48.5 KB), `pytest.ini`, 4 requirements files.
- `frontend/`: `src/` (**28** `.ts`/`.tsx` files, **6,302 lines**), `package.json`, `next.config.ts`, `Dockerfile`.
- `.github/workflows/ci.yml` (8.4 KB) — 5 jobs.

## 1.3 Toolchain actually usable on this host (FACT / RUNTIME)

| Tool | Result | Consequence for the audit |
|---|---|---|
| `rea` CLI | `bash: rea: command not found` (also `where rea` → not found) | **CLI unavailable.** All REA work in this audit used the **REA MCP server** tool surface instead. No CLI `--version`, `--help`, or `rea doctor` output can be produced, and none is fabricated. Note the version delta: the historical reports (`polyskill-analysis-report.md`, `phase3-sse-citation-difficulty.md`) cite **REA 6.7.0 at `C:\nvm4w\nodejs\rea.cmd`**, which no longer exists on this host. |
| Python | `3.13.7` | Backend tests run on this interpreter. |
| Node | `v24.22.2` | Frontend typecheck/build run on this runtime. |
| npm | `11.19.1` | |
| Docker | `29.2.0, build 0b9d198` | Compose stack inspected live. |
| Git | `2.52.0.windows.1` | |
| `rg` (ripgrep) | **not on PATH** — every grep emits `rtk: Failed to resolve 'rg' … falling back to direct exec` | Greps still produced results via fallback. The noise line appears in raw command output and is not a failure. |
| Platform | `win32` (Windows 11 Home Single Language, 10.0.26200) | Shell is PowerShell; some Bash-tool invocations ran through Git Bash. |

**REA MCP provider status (FACT / RUNTIME):** the MCP server is connected and exposes the full tool set. `mcp__rea__binary_session` reported:

```text
server_identity.name     = "rea"
server_identity.version  = "6.8.0"
package                  = "rea-agents" 6.8.0
started_at               = 2026-11-03T14:00:45.169Z
sdk                      = 2.3.1 (server / client_test / core)
protocol_version         = 2025-11-25
client                   = claude-code 2.1.128
client_features          = { elicitation_form: true, elicitation_url: false,
                             roots: true, sampling: false }
open                     = false
cleanup_pending          = false
native-macos provider    = unsupported_host
```

This is the authoritative REA identity for the audit: **`rea-agents` 6.8.0 via MCP**, not the CLI version the earlier PolySkill reports name. Every PolySkill capture from 2026-10-30/31 was produced by REA 6.7.0 and is therefore `REPORTED`, not reproducible in this audit's tool version — record that delta wherever those captures are cited.

## 1.4 Backend dependency baseline (FACT / STATIC, `backend/requirements.txt`)

Direct pins/constraints relevant to parity claims:

- `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `sqlalchemy[asyncio]>=2.0`, `pydantic>=2.7`, `alembic>=1.13`
- `celery>=5.4`, `redis>=5.0`
- `aiosqlite>=0.20` + `asyncpg>=0.29` + `psycopg[binary]>=3.1` → dual SQLite/PostgreSQL
- `argon2-cffi>=23.1` (password hashing), `pyjwt>=2.8`
- `pypdf>=5.0`, `python-multipart>=0.0.9`, `minio>=7.2`, `defusedxml>=0.7`
- **`fsrs==6.3.2`** — exact pin, comment states `scheduler_version` is persisted so an unpinned upgrade would make stored schedules irreproducible
- OCR is **deliberately excluded** from the default file (`requirements-ocr.txt`, `requirements-ocr-vietocr.txt` installed separately)
- `pytest>=8.0`, `pytest-asyncio>=0.23`

`backend/pytest.ini`: `asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = session`, `testpaths = tests`.

## 1.5 Frontend dependency baseline (FACT / STATIC, `frontend/package.json`)

`name: ailp-frontend`, version `0.1.0`, private. Dependencies are **only four**: `@tanstack/react-query ^5.62.0`, `next 15.5.28` (exact), `react ^19.0.0`, `react-dom ^19.0.0`. Dev: `@eslint/eslintrc 3.3.7`, `eslint ^9.39.5`, `eslint-config-next 15.5.28`, `typescript ^5`, `@types/*`, and an `overrides` pin of `postcss ^8.5.32`.

Scripts: `dev`, `build`, `start`, `lint` (`eslint . --max-warnings=0`), `typecheck` (`tsc --noEmit`).

**Parity-relevant absences (FACT / STATIC, from the dependency list alone):** no i18n library, no charting library, no animation library, no icon package, no form library, no state manager beyond TanStack Query, no MathJax/KaTeX. Components and icons are hand-rolled (see `frontend/src/components/` inventory in §1.7).

## 1.6 Configuration surface (FACT / STATIC + RUNTIME; **names only, no secret values**)

`backend/app/core/config.py` defines a pydantic-settings `Settings` class (403 lines) with `env_file=".env"`, `extra="ignore"`. `.env.example` declares **156 keys**. Grouped by feature gate:

- **Core:** `ENV`, `DATABASE_URL`, `REDIS_URL`, `CORS_ORIGINS`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_TTL_MINUTES`, `ALLOW_DEMO_HEADER`, `COOKIE_SECURE`, `LESSON_SHUFFLE_SECRET`
- **LLM:** `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_MAX_OUTPUT_TOKENS{,_INTERVIEW,_PROPOSAL,_LESSON,_JUDGE,_TUTOR}`, `LLM_MAX_INPUT_CHARS`, `LLM_MAX_SCHEMA_RETRIES`, `LLM_PRICING_JSON`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (legacy)
- **Generation:** `GENERATION_MAX_TOKENS_PER_JOB` (default 400,000), `GENERATION_MAX_COST_USD_PER_JOB` (default 0 = unlimited), `GENERATION_LEASE_SECONDS`, `GENERATION_MAX_ATTEMPTS`, `GENERATION_RETRY_BACKOFF_SECONDS`, `GENERATION_LESSON_TIMEOUT_SECONDS`, `GENERATION_RECONCILE_INTERVAL_SECONDS`, `GENERATION_ALLOW_INLINE_FALLBACK`, `GENERATION_INLINE_BLOCKING`
- **Tutor:** `TUTOR_ENABLED` (default `false`), `TUTOR_MESSAGES_PER_DAY` (default `0`), `TUTOR_TOKENS_PER_DAY` (default `0`), `TUTOR_MAX_CONCURRENT_STREAMS` (default 2), `TUTOR_STALE_STREAM_SECONDS`, `TUTOR_CANCEL_POLL_SECONDS`, `TUTOR_TOOLS_ENABLED` (default `false`), `TUTOR_TOOL_MAX_CALLS`, `TUTOR_TOOL_TIMEOUT_SECONDS`, `TUTOR_TOOL_MAX_RESULT_CHARS`, `TUTOR_HEARTBEAT_SECONDS`, `TUTOR_STREAM_TIMEOUT_SECONDS`, `TUTOR_CONTEXT_MAX_CHARS`, `TUTOR_HISTORY_MAX_MESSAGES`
- **Sources:** `SOURCE_INGEST_ENABLED` (default true), `SOURCE_MAX_PDF_BYTES` (20 MiB), `SOURCE_MAX_PDF_PAGES` (300), `SOURCE_STORAGE_{BACKEND,BUCKET,ENDPOINT,ACCESS_KEY,SECRET_KEY,REGION,SECURE,AUTO_CREATE_BUCKET}`, `SOURCE_DISCOVERY_ADAPTER` (`curated`), `SOURCE_CURATED_CATALOG`, `SOURCE_RESEARCH_*`
- **Web/arXiv:** `WEB_INGEST_ENABLED` (**default false**), `WEB_INGEST_ALLOWED_HOSTS` (**default empty**), `WEB_INGEST_REQUIRE_HTTPS`, `WEB_INGEST_RESPECT_ROBOTS`, `WEB_*` limits, `ARXIV_API_HOST`, `ARXIV_PDF_HOST`, `ARXIV_METADATA_SOURCE` (`abs`)
- **OCR:** `OCR_ENABLED` (**default false**), `OCR_ENGINE` (`rapidocr`), `OCR_LANG` (`vi`), `OCR_MODEL_VERSION` (**default empty ⇒ `ocr_configured` False**), `OCR_*` limits
- **Embedding/RAG:** `EMBEDDING_ENABLED` (default true), `EMBEDDING_PROVIDER` (**`hashing`**), `EMBEDDING_MODEL` (`hashing-ngram-v1`), `EMBEDDING_DIMENSION` (256), `EMBEDDING_VERSION` (`v1`); `RAG_ENABLED` (**default false**), `RAG_TOP_K` 6, `RAG_CANDIDATE_LIMIT` 2000, `RAG_MIN_LEXICAL_SCORE` 0.40, `RAG_VECTOR_ONLY_MIN_SIMILARITY` 0.40, `RAG_MAX_CITATIONS` 5
- **P5.0/P5.2:** `P50_ENABLED` (**false**), `P50_BACKFILL_ENABLED` (**false**), `MASTERY_PASS_THRESHOLD` 0.7, `MASTERY_RECENCY_HALF_LIFE_DAYS` 30, `FSRS_DESIRED_RETENTION` 0.9, `P52_EXPOSURE_ENABLED` (**false**), `P52_TOKEN_TTL_SECONDS` 900

**Gate defaults that matter for parity scoring (FACT / STATIC):** tutor, tutor tools, RAG, web ingest, OCR, P5.0 mastery and P5.2 exposure all default **off**. `LLM_PROVIDER` defaults to **`mock`**. `EMBEDDING_PROVIDER` defaults to **non-semantic `hashing`**. These are code defaults; §1.8 records what the **running** container actually reports.

## 1.7 Live runtime baseline (FACT / RUNTIME)

Verified against the Docker Compose stack actually running on this host:

- `docker compose config --quiet` → **exit 0**
- `docker compose ps` → **7 services Up**: `backend` (:8001), `worker`, `beat`, `db` (`postgres:16-alpine`, :5433, healthy), `redis` (`redis:7-alpine`, :6379, healthy), `minio` (:9000–9001, healthy), `frontend` (:3000)
- `curl http://127.0.0.1:8001/health` → **HTTP 200** `{"status":"ok","env":"development","provider":"mock"}`
- `curl http://127.0.0.1:3000/` → **HTTP 200**, `<html lang="vi">`, Next.js woff2 preload present
- `alembic current` inside the backend container → **`0016_p52_exposure (head)`**
- `GET /v1/sources/ingest-config` (unauthenticated) → **HTTP 401** `{"code":"NOT_AUTHENTICATED"}` — confirms auth is enforced before feature-gate disclosure

**The single most important runtime fact in this audit:** the running backend reports `provider: "mock"`. Every generation-quality statement in `08-ai-quality-evaluation.md` and every parity row that depends on real LLM output is therefore scoped to **mock**, not to a real provider.

## 1.8 Live API surface (FACT / RUNTIME — 39 paths)

Read from the running server's OpenAPI schema. `{id}`/`{message_id}`/etc. shown as the server names them.

```
GET  /health
POST /v1/auth/register      POST /v1/auth/login      POST /v1/auth/logout      GET /v1/auth/me
GET  /v1/courses            POST /v1/courses
GET  /v1/courses/{course_id}
POST /v1/courses/{course_id}/interview/answer
POST /v1/courses/{course_id}/approve
GET  /v1/courses/{course_id}/generation
GET  /v1/courses/{course_id}/interview
GET  /v1/courses/{course_id}/learning-path
GET  /v1/courses/{course_id}/mastery
GET  /v1/courses/{course_id}/proposal
POST /v1/courses/{course_id}/recommendation-events
GET  /v1/courses/{course_id}/research-runs   POST /v1/courses/{course_id}/research-runs
GET  /v1/courses/{course_id}/research-runs/{run_id}
POST /v1/courses/{course_id}/research-runs/{run_id}/accept
POST /v1/courses/{course_id}/retry
GET  /v1/courses/{course_id}/sources         POST /v1/courses/{course_id}/sources
GET  /v1/courses/{course_id}/sources/search
POST /v1/courses/{course_id}/tutor/messages
POST /v1/courses/{course_id}/tutor/messages/{message_id}/stop
GET  /v1/courses/{course_id}/tutor/threads
GET  /v1/courses/{course_id}/tutor/threads/{thread_id}
GET  /v1/courses/{course_id}/tutor/usage
GET  /v1/lessons/{lesson_id}
POST /v1/lessons/{lesson_id}/attempts
GET  /v1/reviews/due       POST /v1/reviews/{card_id}/grade
GET  /v1/sources           POST /v1/sources
POST /v1/sources/discover
GET  /v1/sources/ingest-config
DELETE|GET /v1/sources/{source_id}
GET  /v1/sources/{source_id}/document
GET  /v1/sources/{source_id}/documents
DELETE|GET /v1/sources/{source_id}/documents/{document_id}
GET  /v1/sources/{source_id}/evaluation
GET  /v1/sources/{source_id}/web-document
```

**Counted as 39 path objects.** Two prefix families coexist: `/v1/courses/...`, `/v1/lessons/...`, `/v1/reviews/...`, `/v1/sources/...`, `/v1/auth/...` and a bare `/health`.

**Absent from the live surface (FACT / RUNTIME, cross-checked against §1.9):** no billing/checkout/entitlement route, no OAuth/OIDC route, no refresh-token route, no profile/stats/streak route, no onboarding route, no paywall route, no course-delete route, no lesson-prefetch route, no client-side telemetry ingest route.

## 1.9 Migration and database state (FACT / RUNTIME + STATIC)

16 migrations, `0001_initial.py` → `0016_p52_exposure.py`, in phase order: `0003_p11_quiz_integrity`, `0004_p12_job_reliability`, `0005_p30_source_registry`, `0006_p2sr_source_research`, `0007_p22_eval_cost`, `0008_p30_tutor_core`, `0009_p31_tutor_controls`, `0010_p31_tutor_tools`, `0011_p40_source_ingest`, `0012_p41_rag`, `0013_p42_web_ingest`, `0014_p43_ocr`, `0015_p50_learner_profile`, `0016_p52_exposure`. Live DB head = `0016_p52_exposure (head)`, matching the directory's highest revision — no unapplied migration.

## 1.10 CI pipeline as declared (FACT / STATIC, `.github/workflows/ci.yml`)

Triggers: `push`, `pull_request`, `workflow_dispatch`. Permissions: `contents: read`. Concurrency group `ci-${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`.

Global env for jobs: `DATABASE_URL: sqlite+aiosqlite:///:memory:`, `LLM_PROVIDER: mock`, `REDIS_URL: ""`, `JWT_SECRET: ci-only-not-a-production-secret`, `ALLOW_DEMO_HEADER: "false"`, `GENERATION_INLINE_BLOCKING: "true"`, `SOURCE_STORAGE_BACKEND: memory`, `PYTHONUTF8: "1"`.

Five jobs: `backend-tests` (matrix over Python versions), `postgres-migrations` ("Alembic migrations on empty PostgreSQL"), `postgres-race` ("PostgreSQL concurrency tests"), `frontend` ("Frontend lint, typecheck, build"), `security` ("Static security and dependency audit").

> CI itself is `REPORTED` in the repo docs (HEAD commit message says the real GitHub Actions run was recorded). This audit did **not** re-trigger Actions; it reproduced the equivalent commands locally (§`09-command-and-test-log.md`). The claim "CI is green" is therefore **not** independently verified here.

## 1.11 Test inventory (FACT / STATIC)

68 `.py` files under `backend/tests/`, of which 4 are support modules (`conftest.py`, `support.py`, `pdf_fixtures.py`, `scan_fixtures.py`, `__init__.py`) and ~63 are test modules spanning: auth, API flow, grading, quiz integrity, job reliability, LLM provider, pedagogy, cost budget, eval, source research, source-first, tutor (core/controls/tools/stream-provider), PDF ingest, chunker, RAG, web ingest, OCR, learner profile, FSRS, learning path, mastery, BKT, P5.2 exposure/readiness/token/API, CI contract.

A recurring naming convention — `test_pNN_*_postgres_concurrency.py` and `test_pNN_*_migration_contract.py` — shows the suite separates SQLite-runnable behaviour from PostgreSQL-only concurrency/migration assertions. Under a SQLite run these are the modules expected to skip; §`09` records the exact skip count observed.

## 1.12 Phase B tooling status (FACT / RUNTIME — **BLOCKED**)

REA MCP call:

```
mcp__rea__list_browser_targets(
  cdp_endpoint="http://127.0.0.1:9222",
  allowed_origins=["https://web.polyskill.app"]
)
```

Result: `targets: []`, exclusion counters `{disallowed_origin: 0, unsupported_url: 0, non_page: 0}`, browser `Chrome/156.0.8078.76`, user agent `HeadlessChrome/156.0.0.0`, evidence id `ev_f7404a13cb326b015f9476383274536434b44305b7aea600b280ed8b4004da14`.

Interpretation (`FACT` + `INFERENCE`): the counters being all-zero while `targets` is empty means **no page target existed at all** — the filter is not what excluded anything. The endpoint was a bare headless Chrome with no tab opened on the reference product; a logged-in session on `web.polyskill.app` requires the account owner's interactive login, which this audit is not permitted to perform on their behalf.

**Consequence:** Phase B is recorded as `BLOCKED`, not as "PolySkill lacks feature X". All PolySkill-side evidence in this audit is `STATIC` (client bundle hashes from the prior session, bundle-observed contracts) or `REPORTED` (the three historical `polyskill-*.md` documents in the repo root), labelled as such in `02-reference-evidence.md`.

---

## Gate A verdict

**PARTIAL.** Baseline facts are complete and reproducible (branch/HEAD/dirty-tree, toolchain, 39-route live surface, migration head, config surface, CI declaration, test inventory). The mandated *reference-side runtime* gate is not achievable in this environment: Phase B is `BLOCKED` with recorded evidence. The audit therefore continues through Phases C and D and reports a **PARTIAL AUDIT** with an explicitly UNKNOWN/`BLOCKED` share of the parity weight, per mandate §7.2 — it does not silently substitute static bundle reading for runtime observation.
