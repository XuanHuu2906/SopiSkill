# 03 — System Architecture & Deployment Boundaries

**Trạng thái (`2026-11-22`):** Đã đồng bộ theo mã nguồn thực tế (`backend/`, `frontend/`, `docker-compose.yml`). Các mục gắn nhãn `PLANNED` thuộc P6.2+ production hardening.

## 1. Logical topology (hiện hữu trong repo)

```text
Browser (Next.js 15.5.28 / React 19 / TypeScript / TanStack Query v5 / self-hosted fonts)
      | HTTP(S) JSON (HttpOnly JWT cookie + CSRF)
      | POST fetch streaming SSE (AI Tutor, AbortController)
      v
FastAPI application (45 endpoints /v1/* + /health; Pydantic v2 + service-level authz)
      |-- PostgreSQL 16 (SQLAlchemy async; 27 tables; 16 Alembic migrations 0001..0016)
      |-- Redis 7 (Celery broker & result backend; distributed rate-limit PLANNED)
      |-- MinIO / S3-compatible private object storage (P4.0 PDF bytes)
      |-- LLMProvider registry (MockProvider default | OpenAI-compatible fail-fast)
      |-- EmbeddingProvider registry (Hashing lexical default | OpenAI-compatible fail-fast)
      `-- Persistent outbox + job/ingest dispatch
               |
               v
          Celery worker (--pool=solo, visibility_timeout=3600, time_limit=2400)
          + Celery beat reconciler (30s)
               |-- Course & lesson generation (P1.2–P2.2, RELIABILITY-CELERY-01/02)
               |-- Source ingest: PDF / Web / arXiv / optional OCR (P4.0, P4.2, P4.3)
               `-- Embedding reconciliation (P4.1)

Hybrid Retrieval (P4.1):
      |-- PostgreSQL FTS (`to_tsvector('simple')` + `ts_rank_cd`; SQLite token-overlap in tests)
      `-- Exact cosine similarity over `source_chunk_embeddings` (JSON vector; pgvector DEFERRED)
```

## 2. Repository conventions

- **`frontend/`**: App Router (`src/app/**`), UI primitives & layout (`src/components/{ui,layout,landing}/`), API client (`src/lib/api.ts`), self-hosted fonts (`public/fonts/*.woff2`, `src/app/fonts.css`), session-scoped TanStack Query keys.
- **`backend/`**: `app/api/v1/{auth,routes,tutor,sources,research,learner}.py`, `app/services/` (35 modules), `app/agents/source_research/`, `app/models/models.py`, `app/schemas/schemas.py`, `app/providers/`, `app/worker/`, `app/core/`, `alembic/versions/` (`0001`–`0016`), `evals/`, `tests/` (65 files), `e2e_acceptance.py`.
- **`docker-compose.yml`**: 7 services — `db` (Postgres 16), `redis` (Redis 7), `minio`, `backend` (`:8001→8000`), `worker`, `beat`, `frontend` (`:3000`).
- Không chuyển sang monorepo `apps/web`/`services/api` hay thay Celery khi không có phê duyệt rõ ràng.

## 3. Trust boundaries

- **Browser untrusted**: mọi `id`, `contextRef`, progress, `correct`, `recommendationToken` tự tạo, `systemPrompt` đều bị từ chối/xác minh lại ở server.
- **API authoritative**: auth cookie/JWT, CSRF double-submit, Pydantic validation (`extra="forbid"` trên các request nhạy cảm), DB owner check (404 cross-user), HMAC shuffle (`LESSON_SHUFFLE_SECRET`), server grading, quota check, citation allowlist validation, HMAC recommendation token mint/verify.
- **Worker trusted compute, not trusted input**: nhận job/document ID từ queue, re-resolve bản ghi + pinned proposal version từ DB, atomic claim + lease; không tin payload chứa owner.
- **LLM & external documents untrusted**: output JSON qua Pydantic + `validate_lesson()` ở ranh giới worker; chunks/tool outputs bọc delimiter rõ ràng và đánh dấu dữ liệu không tin cậy; outbound web fetch đi qua `PinnedNetworkBackend` chống SSRF/DNS rebinding + allowlist host + `robots.txt`.
- **Storage private**: object key ngẫu nhiên trong MinIO/S3 private; không expose storage key hay local path ra API.

## 4. Domain boundaries

| Module | Trách nhiệm | Không làm |
|---|---|---|
| Auth (`api/v1/auth.py`, `user_service.py`) | Identity, Argon2id, HttpOnly JWT cookie, CSRF | Chấm quiz |
| Courses/Interview/Proposal (`course_service.py`, `pedagogy.py`) | State machine, 5 câu interview, profile rule-based, proposal DAG versioned | Chạy LLM trong DB transaction dài |
| Generation/Job (`job_service.py`, `worker/generation.py`) | Atomic claim, lease, outbox/stale-dispatch recovery, bounded retry, usage/budget cap | Tin status từ client |
| Lesson/Quiz/Progress (`lesson_service.py`, `lesson_content.py`) | `public_block()` projection, HMAC shuffle, server grading, XP cap | Lộ đáp án trước submit |
| AI Provider (`providers/`) | Generate/stream/tool-plan interface, schema/semantic lint, usage collector | Kiểm tra ownership thay service |
| Tutor (`api/v1/tutor.py`, `tutor_service.py`, `tutor_tools.py`) | Threads, grounding, SSE stream, best-effort stop, quota, 3 read-only tools + audit | Gọi mạng tự do, ghi sửa DB bài học |
| Source/RAG/OCR (`api/v1/sources.py`, `ingest.py`, `web_ingest.py`, `ocr.py`, `rag_service.py`, `retrieval_service.py`) | Upload/web/arXiv ingest, OCR opt-in, hybrid RRF, verified citations | Bịa chunk/page, bypass owner filter |
| Adaptive (`api/v1/learner.py`, `learner_profile_service.py`, `spaced_repetition_service.py`, `learning_path_service.py`, `bkt.py`) | Mastery baseline, FSRS schedule, DAG learning path, HMAC exposure logging, BKT eval | Huấn luyện/deploy DKT/bandit khi chưa qua readiness gate |

## 5. Async consistency & Celery reliability

- Course, generation job, và source document status lưu trong **PostgreSQL**, không phụ thuộc riêng Redis/Celery result backend.
- `approve` ghi `approved_at` + tạo job `queued` trong transaction. Beat reconciler chạy 30s thu hồi cả 3 nhánh: (1) chưa dispatch quá grace window, (2) lease hết hạn, (3) **stale dispatch** (broker ack nhưng không worker claim quá `GENERATION_STALE_DISPATCH_SECONDS=300`, tối đa `GENERATION_MAX_DISPATCH_ATTEMPTS=5` → `DISPATCH_EXHAUSTED`).
- Celery Redis config: `broker_transport_options={"visibility_timeout": 3600}`, `task_time_limit=2400` (`< visibility_timeout`), `task_acks_late=True`, `worker_prefetch_multiplier=1`.
- Thiết kế là **at-least-once delivery, idempotent DB effects**, không hứa exactly-once ở provider trả phí.

## 6. Feature flags mặc định (từ `backend/app/core/config.py`)

| Flag | Mặc định | Hành vi khi tắt |
|---|---|---|
| `LLM_PROVIDER` | `"mock"` | Deterministic offline mock, 0 network calls |
| `TUTOR_ENABLED` | `false` | Routes `/tutor/*` trả `503 TUTOR_DISABLED` |
| `TUTOR_TOOLS_ENABLED` | `false` | Không gọi tool planner, không phát frame `tool` |
| `SOURCE_INGEST_ENABLED` | `true` | Cần `SOURCE_STORAGE_BACKEND=s3` (hoặc `memory` non-prod) |
| `EMBEDDING_PROVIDER` | `"hashing"` | Lexical n-gram 256-dim offline baseline |
| `RAG_ENABLED` | `false` | `/sources/search` trả `503 RAG_NOT_ENABLED`, Tutor không retrieve |
| `WEB_INGEST_ENABLED` | `false` | + `WEB_INGEST_ALLOWED_HOSTS=""` → chặn toàn bộ outbound fetch |
| `OCR_ENABLED` | `false` | PDF scan trả `no_text` |
| `SOURCE_RESEARCH_ENABLED` | `false` | `/research-runs` trả `503` |
| `P50_ENABLED` | `false` | `/mastery`, `/learning-path`, `/reviews/*` trả `503` |
| `P52_EXPOSURE_ENABLED` | `false` | `recommendationToken=null`, `/recommendation-events` trả `503` |
| `ALLOW_DEMO_HEADER` | `false` | Từ chối `X-User-Id` |

## 7. Môi trường & vận hành

- **Local dev:** Windows/WSL2/Linux + Docker Compose (`backend` `:8001`, `frontend` `:3000`, `db` `:5433`, `redis` `:6379`, `minio` `:9000/:9001`). Lưu ý: `NEXT_PUBLIC_API_URL` được nướng vào bundle lúc `npm run build`.
- **CI (`P6.1`):** GitHub Actions 5 jobs trên Linux + PostgreSQL 16 (unit/integration, migration upgrade/downgrade, Postgres race tests, frontend lint/typecheck/build, Bandit/pip-audit).
- **Production (`P6.2+`, PLANNED):** HTTPS, `COOKIE_SECURE=true`, Redis distributed rate-limit, CSP/HSTS, backup-restore drill, secret manager, retention/deletion policy.
