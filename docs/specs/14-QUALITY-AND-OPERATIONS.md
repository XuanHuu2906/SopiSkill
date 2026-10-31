# 14 — Nonfunctional Requirements, Observability & Operations

**Trạng thái:** PROPOSAL/P6 cho release; một số cơ chế job/auth được báo cáo đã có. Ngưỡng hiệu năng là **mục tiêu đề xuất**, không phải số đã benchmark.

## 1. Reliability & consistency

| ID | NFR | Xác minh |
|---|---|---|
| OPS-001 | DB là source of truth cho trạng thái course/job/progress | Reload/restart kiểm chứng |
| OPS-002 | At-least-once queue + idempotent writes, worker crash recovery | Failure injection |
| OPS-003 | Timeout/retry bounded cho provider, tools, ingest; no infinite loops | Unit/integration |
| OPS-004 | Token/cost quota đo được và có guard trước gọi model | Mock provider + usage test |
| OPS-005 | Health/liveness và readiness kiểm tra phụ thuộc thiết yếu | HTTP/stack smoke |
| OPS-006 | Log/metrics/traces không chứa secrets hoặc raw content cá nhân | Redaction scan |
| OPS-007 | Backup có restore drill; migration backward-compatible | Test DB riêng |
| OPS-008 | HTTPS/cookie secure/CSP/CORS/proxy policy có test staging | Security checks |
| OPS-009 | CI/test gates, review/rollback trước deployment | CI evidence |

## 2. Proposed SLO starting points (chưa cam kết)

- API non-AI read/write p95 ≤500 ms khi chạy staging gần mức tải mục tiêu; **phải đo baseline phần cứng và query trước**.
- Tutor first delta p95 ≤5 s trên provider đã chọn là mục tiêu thử nghiệm, **không bảo đảm** qua mạng/LLM; report theo model.
- Job `queued` bị broker unavailable phải được beat/reconciler phát hiện lại theo nhịp hiện tại báo cáo 30s; kiểm tra end-to-end với fail injection, không biến thành SLA production khi chưa benchmark.
- 100% displayed citations phải resolve được chunk có quyền; đây là **integrity gate**, không chứng minh factual correctness của mọi câu.
- Job success/timeout/cost baseline lấy từ eval set 10 topics và workload test trước khi chốt threshold release.

## 3. Observability schema proposal

- IDs: `requestId`, `traceId`, `userId` hashed/pseudonymous nếu cần, `courseId`, `generationJobId`, `providerRequestId` nếu có, promptVersion.
- Events: `course.created`, `interview.completed`, `proposal.approved`, `generation.queued/claimed/ready/failed`, `attempt.submitted`, `tutor.started/done/error`, `source.ready/failed`, `citation.validation_failed`.
- Metrics: error rate by endpoint/phase, job queue age, lease expiry/requeue, retries, LLM token/latency/cost estimate, streaming disconnects, source ingest errors, retrieval Recall@k on eval.
- Metrics aggregate/minimize personal data; không log full user input, content PDF, prompts hoặc answer key.

## 4. Deployment configuration (P6)

- CI: Python unit/integration tests, typecheck/lint khi config sẵn, Next.js build, Postgres migration on fresh DB, security/dependency scanning, OpenAPI diff check.
- Staging: TLS + `COOKIE_SECURE=true`, trusted proxy, allowlist CORS, CSP/HSTS, secret manager; không bật demo header.
- Rate-limit distributed (Redis) trước khi scale replicas; avoid relying on in-memory login limits.
- Backups encrypted + retention + restore tests; DB migrations staging-first và có stop condition cho destructive steps.
- Rollback: code rollback + data forward-compatibility; restore DB backup chỉ sau được người sở hữu phê duyệt.
- Release là manual gate, không để coding agent auto deploy/push main.

## 5. Privacy, safety and retention (open decisions)

- Quyết định thời gian lưu interview, course, tutor messages, PDF, embeddings, logs, usage; xóa account/source có cascade/revocation.
- Chính sách dữ liệu gửi tới external model/provider và user consent; cung cấp export/delete nếu sản phẩm cần và tuân thủ quy định áp dụng.
- Phải audit tool security/SSRF/file parser abuse và prompt injection trước public release.

## 6. Windows runbook for re-validation

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
docker compose config
docker compose ps
cd backend
python -m pytest -q
cd ..
cd frontend
npm run build
cd ..
$env:E2E_BASE = "http://127.0.0.1:8001"
python .\backend\e2e_acceptance.py
```

**Lưu ý:** Trước `docker compose up -d --build`/`alembic upgrade head` trên DB chứa dữ liệu cần giữ, inspect migrations & backup. Các lệnh này được đưa làm runbook, **không phải lệnh đã chạy trong phiên soạn specs**.
