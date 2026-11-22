# 14 — Nonfunctional Requirements, Observability & Operations

**Trạng thái (`2026-11-22`):** **P6.1 CI Pipeline** đã **IMPLEMENTED · REPORTED TESTED** (GitHub Actions run `41583115455`, 5/5 jobs xanh — chi tiết `25-P61-CI-PIPELINE.md`) và **RELIABILITY-CELERY-01/02** đã deployed/live-verified. Các cổng production **P6.2+** (staging TLS/CSP, distributed Redis rate-limit, backup-restore drill, retention/deletion policy, real-provider budget/rollout) vẫn là **PLANNED / NOT VERIFIED**.

## 1. Reliability & Operations Requirements

| ID | NFR | Trạng thái (2026-11-22) |
|---|---|---|
| OPS-001 | DB là source of truth cho trạng thái course/job/progress/source | **IMPLEMENTED · TESTED** |
| OPS-002 | At-least-once queue + idempotent writes, worker crash/stale-dispatch recovery (`visibility_timeout=3600`) | **IMPLEMENTED · TESTED · DEPLOYED** (`RELIABILITY-CELERY-01/02`) |
| OPS-003 | Timeout/retry bounded cho provider, tools, ingest, web fetch, OCR | **IMPLEMENTED · TESTED** |
| OPS-004 | Token/cost quota đo được (`llm_usage_events`, `tutor_usage_events`) và guard trước gọi model | **IMPLEMENTED · TESTED** |
| OPS-005 | `/health` liveness + Docker Compose healthchecks (`db`, `redis`, `minio`) | **IMPLEMENTED** (chưa có `/ready` kiểm tra deep dependencies) |
| OPS-006 | Logs/metrics không chứa secrets, cookies, raw prompts hoặc answer keys | **IMPLEMENTED · TESTED** |
| OPS-007 | Backup định kỳ + restore drill; migration expand-only kiểm thử trên Postgres rỗng | **PARTIAL** — migration CI PASS; backup/restore drill **NOT TESTED** |
| OPS-008 | HTTPS, `COOKIE_SECURE=true`, CSP/HSTS, trusted proxy, distributed Redis rate-limit | **PLANNED / NOT IMPLEMENTED** (rate-limit hiện là in-memory per-process) |
| OPS-009 | Automated CI gates (backend tests, migrations, Postgres races, frontend build, Bandit/pip-audit) | **IMPLEMENTED · TESTED** (`P6.1`) |

## 2. Proposed SLO starting points (mục tiêu tham chiếu — chưa benchmark tải)

- API non-AI read/write p95 ≤ 500 ms ở staging (chưa đo tải).
- Beat reconciler quét 30s; stale dispatch thu hồi sau `300s` (max `5` lần → `DISPATCH_EXHAUSTED`).
- Integrity gate: 100% displayed citations phải resolve được chunk thuộc quyền user; 0% answer key leak trên `GET /v1/lessons/{id}`.
- Chất lượng LLM thật: theo dõi từ eval 12 topics (baseline `3.17/4`, mục tiêu sau fix P1: `language_quality` & `level_fit` ≥ `3.0/4`, `0` truncation).

## 3. CI Pipeline hiện hữu (`P6.1` — `.github/workflows/ci.yml`)

5 automated jobs chạy trên Linux runner + PostgreSQL 16 (không gọi LLM trả phí):
1. Backend unit/integration suite (`pytest`).
2. Alembic migration `upgrade head` trên PostgreSQL rỗng + `downgrade -1` + `upgrade head`.
3. PostgreSQL real concurrency/race tests (`POSTGRES_TEST_URL`).
4. Frontend `npm run lint` (`--max-warnings=0`), `npm run typecheck` (`tsc --noEmit`), `npm run build`.
5. Security scans (`bandit`, `pip-audit`, `npm audit`).

**Ghi nhận vận hành quan trọng (`RELIABILITY-CELERY-02`):**
- Không chạy `pytest` trong long-lived worker container (gây xung đột asyncpg event loop và thiếu `.github/`). Gate đúng là host/CI pytest + live E2E.
- Tránh để chạy song song host Celery worker với Docker worker cùng nối 1 Redis queue (từng gây stale orphan job; đã có quy trình kiểm `celery inspect ping` phải đúng `1 node online`).
- Hiện tại `P1-PEDAGOGY` đã sửa trong working tree nhưng **chưa rebuild/deploy** vào container backend/worker/beat.

## 4. Hạng mục bắt buộc trước Production Release (`P6.2+` — OPEN)

- Chuyển rate-limiter từ in-memory sang **Redis distributed** (`M1-SEC-LIMITER`).
- Bổ sung **Playwright E2E** vào CI để kiểm chứng browser UI thật (hiện `tsc`/`build` chỉ chứng minh biên dịch).
- Thiết lập staging TLS + `COOKIE_SECURE=true` + CSP/HSTS + CORS allowlist.
- Thực hiện **backup & restore drill** có bằng chứng trên DB tách biệt.
- Chốt **data retention / account deletion (`DELETE /v1/me`) / external LLM privacy policy** và ngân sách provider thật trước khi bật `LLM_PROVIDER=openai_compatible` hoặc `TUTOR_ENABLED=true` cho người dùng thật.
