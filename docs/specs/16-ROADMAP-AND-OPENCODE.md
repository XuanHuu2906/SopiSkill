# 16 — Roadmap & OpenCode Execution Specification

**Trạng thái:** DRAFT handoff, ưu tiên cập nhật theo progress 2026-10-30; không chạy code/migration/real API trong lần soạn specs.

## 1. Phase roadmap theo trạng thái tài liệu

| Phase | Mục tiêu | Hiện trạng theo `development-progress.md` | Gate |
|---|---|---|---|
| P0–P1 | Foundation + core course/quiz/auth | REPORTED IMPLEMENTED/TESTED | Regression |
| G0 | Audit + Alembic consistency | REPORTED DONE | Verify HEAD |
| P1.1 | Quiz/XP/progress/version | REPORTED DONE | Regression |
| P1.2 | Celery reliability/outbox | REPORTED DONE | Regression |
| P1.3 | Frontend/session isolation | REPORTED DONE | Regression |
| P2.0 | Real LLM adapter infrastructure | REPORTED PARTIAL: mocked tested + 3 real smoke; CI real blocked | Regression / cost permission |
| **P2.1** | **Course Generator thật + learner profile + DAG + hierarchical lessons** | **NEXT; chưa xác nhận có code** | Schema/DAG/Mock E2E/authorized real subset |
| P2.2 | AI quality eval, costs & quality gates | TODO | Eval 10 topics, measured metrics |
| P3.0 | Tutor thread/context/SSE | **DONE** (mock streaming; real provider NOT TESTED) | Session/cross-owner/stream E2E đã chạy |
| P3.1 | Tools/limit/cancel/replay policy | TODO | Allowlist, quota, safety |
| P4.0 | PDF text ingest, provenance | TODO | Owned PDF source correctly parsed |
| P4.1 | Hybrid RAG/citation validation | TODO | 30 eval queries, valid citations |
| P4.2/P4.3 | URL/arXiv, OCR | OPTIONAL | Rights/security/corpus |
| P5 | Personalization, FSRS, BKT conditional | LATER | Evidence beyond rules |
| P6 | Production readiness, CI/backup/security | TODO | Explicit approval |
| P7 | Billing/gamification | FUTURE | Separate PRD/budget approval |

## 2. Immediate implementation slice — P2.1

**Context:** Existing `backend/`, `frontend/`, PostgreSQL 16, Redis/Celery; real-compatible adapter P2.0 + mock. Latest reported revision `0004_p12_job_reliability`.  
**In scope:** profile normalization from 5 answers, versioned curriculum DAG/outcomes, hierarchical generation consistent with approved proposal, validation, metadata and test coverage.  
**Out of scope:** Tutor/RAG, paid AI calls without approval, rewriting auth/jobs, new billing, modifying existing deployed migrations.

### File/module targets (verify existence/paths first)

- `backend/app/providers/` (base/mock/openai-compatible/validation).
- `backend/app/services/course_service.py`, `job_service.py`, new `curriculum_service.py` only if necessary.
- `backend/app/worker/generation.py`, `backend/app/schemas/schemas.py`, models/migration if schema added.
- `frontend/src/app/new/interview`, `new/proposal`, `new/generating`; `frontend/src/lib/api.ts`.
- `backend/tests/`, `backend/evals/` (new), `backend/e2e_acceptance.py`, docs.

### Ordered tasks

1. **Audit:** HEAD/branch/status, AGENTS.md, schema/routes/providers, existing tests; identify P2.1 changes already present, record no-op/reuse.
2. **Design:** freeze existing contract; propose optional profile/DAG schema with backward compatibility and migration impact; no code until clear acceptance.
3. **Test-first:** learner profile parsing, DAG cycle detection, schema invalid, lesson alignment, negative cases, old proposal compatibility.
4. **Implement smallest slice:** profile normalization + graph validator + versioned mock proposal; maintain `LLM_PROVIDER=mock` for tests.
5. **Integrate generator:** pinned proposal version, per-unit/lesson plan, no worker duplicate, answer key privacy, bounded costs/retries.
6. **UI:** show valid graph/outcomes if data exists, fallback for legacy proposal; no fake proposal editing.
7. **Verify:** pytest, frontend build, PostgreSQL race tests, Docker E2E, migration on temp DB, review secrets/data.
8. **Report/checkpoint:** docs/development-progress.md with exact commands/results, files, Git SHA, risks, gate. Real provider subset ONLY after explicit budget/data approval.

### P2.1 acceptance criteria

- C1: 5 answers -> structured profile with unknown fields not fabricated.
- C2: `curriculumGraph` DAG acyclic, every edge references known nodes, lesson mappings valid.
- C3: Proposal version pinning means approving vN cannot silently generate vN+1.
- C4: Generated lesson public API contains no grading keys; quiz progress unaffected.
- C5: Duplicates / crash / timeout do not multiply persisted lessons or corrupt attempts.
- C6: Offline tests/Mock E2E + frontend build pass; real provider evidence separately labeled, or BLOCKED.

## 3. One-shot OpenCode kickoff prompt

> Nội dung dưới đây có thể copy nguyên văn cho OpenCode, sau khi đặt folder `specs/` vào repository và kiểm tra `AGENTS.md` hiện có.

```text
Bạn đang làm việc trong repo SopiSkill trên Windows.
Đọc AGENTS.md, specs/README.md, specs/00-STATUS-AND-SOURCES.md,
specs/03-SYSTEM-ARCHITECTURE.md, specs/04-DATA-MODEL.md,
specs/05-API-CONTRACTS.md, specs/06-AUTH-AND-SECURITY.md,
specs/07-COURSE-INTERVIEW-PROPOSAL.md,
specs/08-GENERATION-AND-LLM.md,
specs/09-LESSON-QUIZ-PROGRESS.md,
specs/15-TEST-PLAN.md, specs/16-ROADMAP-AND-OPENCODE.md,
specs/19-PEDAGOGY-AND-EVALUATION.md và docs/development-progress.md.

BẮT BUỘC audit git status, branch, HEAD, file tree, code/routes/tests thực tế.
Đối chiếu trạng thái mới nhất thay vì làm lại P0/P1/P2.0 nếu code đã có.
Chỉ bắt đầu phase P2.1, chia thành các task nhỏ theo specs/16 mục 2.

Trước sửa: báo context, scope, module/files, thứ tự, API/schema impact,
acceptance tests, rủi ro, rollback, thứ không làm. Giữ stack/contract hiện có.
Không tự viết lại migration 0001–0004, không xóa volume/DB thật.
Không dùng key từ OpenCode, không gửi dữ liệu hoặc trả phí API thật nếu
chưa có duyệt về provider/model/budget/dataset; mặc định MOCK.
Không làm Tutor/RAG/billing trong P2.1.

Thực hiện test-first, implement tối thiểu, validate auth/owner/CSRF,
private answer keys, idempotency/concurrency, JSON schema, DAG,
provider timeout/cost guards, redacted logs. Chạy pytest, frontend build,
PostgreSQL race tests, Docker E2E khi môi trường cho phép.

Sau mỗi checkpoint cập nhật docs/development-progress.md, ghi chính xác
IMPLEMENTED / TESTED / NOT TESTED / BLOCKED, lệnh/output/exit code,
file/migration/Git SHA, known issues và phase gate. Không báo PASS nếu chưa
thực chạy, không gọi mock là AI thật. Dừng ở quyết định rủi ro hoặc chi phí.
```

## 4. Phase exit gate protocol

- Mỗi phase: audit → plan → contracts → failing tests → code → security → verify → review → report.
- `GATE-PASS` khi toàn bộ criteria bắt buộc có evidence; `PARTIAL` khi còn test/permission; `BLOCKED` khi không có environment/decision.
- Không tự push `main`, deploy, destructive migrations, gửi private PDF ra provider hoặc bật subscription.
- Nếu OpenCode báo kết quả, reviewer phải đọc diff/commands/logs và cập nhật spec theo thực tế.
