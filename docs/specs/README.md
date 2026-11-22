# SopiSkill / AI Learning Platform — Bộ Specification theo module

**Phiên bản:** 0.2 (đồng bộ theo repo thực tế + đối chiếu tham chiếu `2026-11-22`)  
**Ngày cập nhật:** 2026-11-22  
**Baseline đối chiếu:** Branch `feat/p6.0-ci-pipeline` · HEAD `d747e78` (+ uncommitted working tree gồm `FR-1..FR-5`, `P1-QUIZ-BLANK`, `RELIABILITY-CELERY-01/02`, `P1-PEDAGOGY`, `polyskill-analysis-report.md`).  
**Đối tượng:** Product owner, reviewer và kỹ sư triển khai trên Windows/WSL2/Linux.

## Bắt đầu đọc

1. [00 — Hiện trạng và quy tắc nguồn](00-STATUS-AND-SOURCES.md): đối chiếu chính xác trạng thái `IMPLEMENTED / REPORTED TESTED / DEFAULT-OFF / OPEN`.
2. [01 — Product requirements](01-PRODUCT-REQUIREMENTS.md): mục tiêu, phạm vi và tiến độ các PRD milestones.
3. [03 — System architecture](03-SYSTEM-ARCHITECTURE.md) + [04 — Data model](04-DATA-MODEL.md) + [05 — API contracts](05-API-CONTRACTS.md).
4. Các domain specs `06`–`15`, `19`–`25`.
5. [16 — Roadmap & Execution](16-ROADMAP-AND-OPENCODE.md) để chọn bước tiếp theo; [17 — Decision Log](17-DECISION-LOG.md) cho các quyết định đã chốt/đang mở; [18 — Traceability](18-REQUIREMENTS-TRACEABILITY.md) để nghiệm thu.

## Danh sách file

| File | Vai trò | Tình trạng hiện tại (2026-11-22) |
|---|---|---|
| `00-STATUS-AND-SOURCES.md` | Độ tin cậy, baseline, xung đột tài liệu | Đã đồng bộ theo repo `d747e78` + working tree |
| `01-PRODUCT-REQUIREMENTS.md` | PRD, MVP milestones, out-of-scope | Core + P2–P5 + P6.1 đã code (nhiều flag mặc định TẮT) |
| `02-USER-JOURNEYS.md` | Vai trò, user stories, happy/edge paths | A–B live mock; C–E IMPLEMENTED (flag-gated) |
| `03-SYSTEM-ARCHITECTURE.md` | Components, boundaries, jobs, flags | Đã đồng bộ stack thực tế (+ MinIO, self-hosted fonts) |
| `04-DATA-MODEL.md` | 27 bảng thực tế, constraints, 16 migrations | Đồng bộ `models.py` + `0001`–`0016` |
| `05-API-CONTRACTS.md` | Danh mục đầy đủ 45 endpoints `/v1` + policy | Đồng bộ code + mục đối chiếu PolySkill `2026-11-22` |
| `06-AUTH-AND-SECURITY.md` | Cookie/CSRF/authorization, HMAC shuffle, SSRF | Core + P4.2 + P5.2b + P6.1 IMPLEMENTED; rate-limit Redis còn mở |
| `07-COURSE-INTERVIEW-PROPOSAL.md` | 5 câu interview, profile, DAG, vòng đời | P2.1 + `P1-PEDAGOGY` IMPLEMENTED; `P1-LANG`/`P1-LEVEL-FIT`/revise còn mở |
| `08-GENERATION-AND-LLM.md` | Jobs, provider, DAG, cost, Celery reliability | P1.2–P2.2 + `RELIABILITY-CELERY-01/02` IMPLEMENTED; `P1-CONTENT-TRUNC` mở |
| `09-LESSON-QUIZ-PROGRESS.md` | 6 block types, server grading, XP, version | P1.1 + `P1-QUIZ-BLANK` + HMAC shuffle IMPLEMENTED; per-block/AI short grading là PROPOSAL |
| `10-AI-TUTOR-SSE.md` | Threads, SSE streaming, 3 tools, stop, quota | P3.0–P3.1 + `read_source` (P4.1) IMPLEMENTED (`TUTOR_ENABLED=false`) |
| `11-SOURCES-AND-RAG.md` | PDF/Web/arXiv ingest, Hybrid RAG, OCR | P4.0–P4.3 IMPLEMENTED (đa số `DEFAULT-OFF`) |
| `12-ADAPTIVE-LEARNING.md` | Skill mastery, FSRS, BKT, exposure logging | P5.0–P5.2 IMPLEMENTED (`P50_ENABLED=false`, BKT/DKT deploy BLOCKED) |
| `13-FRONTEND-UX.md` | 10 routes, design tokens, a11y, FR-1..FR-5 | IMPLEMENTED (uncommitted); thiếu Playwright E2E & screen-reader test |
| `14-QUALITY-AND-OPERATIONS.md` | NFR, logs, CI, backup, deployment | P6.1 CI IMPLEMENTED + TESTED; staging/prod hardening còn PLANNED |
| `15-TEST-PLAN.md` | Test matrix (65 pytest files) & acceptance | Đã chuẩn hóa T-IDs; phân tách REPORTED TESTED vs NOT TESTED |
| `16-ROADMAP-AND-OPENCODE.md` | Phase roadmap & next execution slices | Cập nhật sang backlog hậu-P6.1 (P1 quality, flags, E2E, gaps ưu tiên) |
| `17-DECISION-LOG.md` | Quyết định đã chốt và câu hỏi mở | Cập nhật `DEC-001..014`, `DEC-P31..P61` và câu hỏi mở hậu `2026-11-22` |
| `18-REQUIREMENTS-TRACEABILITY.md` | Mapping requirement → phase → test → status | Đồng bộ với `15-TEST-PLAN.md` |
| `19-PEDAGOGY-AND-EVALUATION.md` | Rubrics, DAG, eval 12 topics, guardrails | P2.1–P2.2 IMPLEMENTED; ghi nhận eval thật `3.17/4` |
| `20-P41-HYBRID-RAG.md` | Hybrid RAG + citation validation | P4.1 IMPLEMENTED (`RAG_ENABLED=false`, hashing baseline) |
| `21-P43-OCR.md` | OCR PDF scan (`rapidocr`/`vietocr`, opt-in) | P4.3 IMPLEMENTED (`OCR_ENABLED=false`) |
| `22-P50-LEARNER-PROFILE.md` | Mastery, FSRS, learning path | P5.0 IMPLEMENTED (`P50_ENABLED=false`) |
| `23-P51-BKT.md` | BKT research-only | P5.1 IMPLEMENTED (research-only, deploy BLOCKED) |
| `24-P52-ADAPTIVE-READINESS.md` | Exposure logging, OPE readiness | P5.2 IMPLEMENTED (`P52_EXPOSURE_ENABLED=false`, readiness BLOCKED) |
| `25-P61-CI-PIPELINE.md` | CI gates, static/dependency scanning | P6.1 IMPLEMENTED + TESTED (Actions run `41583115455`: 5/5 xanh) |
| `examples/` | JSON/SSE ví dụ tham khảo | **PROPOSED**, không phải OpenAPI hiện hành |

## Quy ước bắt buộc

- `FACT`: được xác minh trực tiếp từ mã nguồn/file trong repo tại lần cập nhật; `REPORTED TESTED`: được ghi trong `docs/development-progress.md` / `docs/audits/` nhưng **không chạy lại trong lần cập nhật spec này**; `DEFAULT-OFF`: code đã có nhưng feature flag mặc định tắt; `PROPOSAL`: thiết kế đề xuất chưa triển khai; `OBSERVED_STATIC`: quan sát tĩnh từ bundle sản phẩm tham chiếu, không phải cam kết triển khai.
- Repository đang checkout (code, migrations, Pydantic schemas, OpenAPI) luôn **ưu tiên hơn** tài liệu spec.
- Không sao chép mã nguồn, UI, tài sản thương hiệu, prompts hay bí mật của PolySkill. Mọi phân tích trong `polyskill-analysis-report.md` chỉ là bối cảnh đối chiếu hành vi.
- Mọi endpoint dữ liệu kiểm tra ownership ở server; không tin `courseId`, `lessonId`, `contextRef`, `sourceId`, `correct` từ client; không đưa secrets ra frontend; không gọi `MockProvider` là AI thật; không bịa citation.
- Không chạy migration phá dữ liệu, deploy, dùng provider trả phí hay push `main` khi chưa được phê duyệt.

## Nguồn đầu vào sử dụng

- Mã nguồn sống trong repo: `backend/app/**`, `backend/alembic/versions/0001..0016`, `frontend/src/**`, `docker-compose.yml`, `.github/workflows/ci.yml`.
- Nhật ký & hồ sơ audit trong repo: `docs/development-progress.md`, `docs/audits/polyskill-parity-2026-11-04/`, `docs/audits/tutor-mock-01-2026-11-04/`, `docs/audits/p1-quiz-blank-2026-11-04/`, `docs/audits/reliability-celery-01-2026-11-04/`, `docs/audits/reliability-celery-02-2026-11-05/`, `docs/audits/p1-pedagogy-2026-11-05/`, `docs/frontend-reference/api-gap-register.md`.
- Tài liệu tham chiếu sản phẩm: `polyskill-analysis-report.md` (cập nhật `2026-11-22` bằng Craft Anything `0.6.1`, `OBSERVED_STATIC`) và `polyskill-dynamic-analysis.md`.
