# 16 — Roadmap & Execution Specification

**Trạng thái (`2026-11-22`):** Đã cập nhật toàn diện sau khi hoàn tất mã nguồn `P0.5` → `P6.1` (migrations `0001`–`0016`), đợt tái thiết kế UI `FR-1..FR-5`, các gate `TUTOR-MOCK-01`, `P1-QUIZ-BLANK`, `RELIABILITY-CELERY-01/02`, `P1-PEDAGOGY` và đợt đối chiếu tĩnh PolySkill bằng Craft Anything `0.6.1`.

## 1. Bảng tiến độ các Phase (đến 2026-11-22)

| Phase | Mục tiêu | Trạng thái thực tế | Ghi chú / Gate còn mở |
|---|---|---|---|
| P0.5–P1.3 | Auth cookie/CSRF, core course→quiz, Celery outbox, session cache isolation | **IMPLEMENTED · REPORTED TESTED** | Regression xanh |
| P2.0–P2.2 | OpenAI-compatible adapter, learner profile, DAG, usage/cost budget, eval 12 topics | **IMPLEMENTED · REPORTED TESTED** | Real eval `3.17/4` lộ 3 lỗi P1 còn mở (`TRUNC`, `LANG`, `LEVEL-FIT`) |
| P2.SR | Source Research Agent offline (`0006`) | **IMPLEMENTED · DEFAULT-OFF** | `SOURCE_RESEARCH_ENABLED=false` |
| P3.0–P3.1 | AI Tutor SSE, stop, quota, 3 read-only tools + audit (`0008`–`0010`) | **IMPLEMENTED · DEFAULT-OFF** | `TUTOR-MOCK-01` PASS mock (`71/71`); real streaming **NOT TESTED** |
| P4.0–P4.3 | PDF/MinIO ingest, Hybrid RAG, Web/arXiv SSRF-safe, OCR `rapidocr`/`vietocr` (`0011`–`0014`) | **IMPLEMENTED · ĐA SỐ DEFAULT-OFF** | `SOURCE_INGEST_ENABLED=true`; `RAG`/`WEB`/`OCR` OFF; embedding là `hashing` |
| P5.0–P5.2 | Skill Mastery, FSRS `/review`, BKT research, Readiness + HMAC exposure (`0015`–`0016`) | **IMPLEMENTED · DEFAULT-OFF / BLOCKED** | `P50_ENABLED=false`; BKT & DKT/bandit deploy **BLOCKED** (thiếu dữ liệu) |
| P6.1 | CI Pipeline 5 jobs (tests, migrations, Postgres races, frontend, Bandit/audit) + HMAC shuffle | **IMPLEMENTED · REPORTED TESTED** | Actions run `41583115455`: 5/5 xanh |
| FR-1..FR-5 | Redesign UI tokens light/dark, self-hosted fonts, step player, modal contract, docked tutor | **IMPLEMENTED (uncommitted)** | Verified CDP thủ công; thiếu Playwright E2E & screen-reader test |
| Stability & P1 fixes | `TUTOR-MOCK-01`, `P1-QUIZ-BLANK`, `RELIABILITY-CELERY-01/02`, `P1-PEDAGOGY` | **IMPLEMENTED · REPORTED TESTED** | `RELIABILITY-CELERY-02` deployed; `P1-PEDAGOGY` **chưa deploy container** & chưa commit |
| **Next — Wave 1** | **Repo hygiene + Deploy sync + Playwright E2E** | **NEXT (ưu tiên ngay)** | Commit sạch dirty tree, rebuild container kèm `P1-PEDAGOGY`, thêm Playwright smoke E2E |
| **Next — Wave 2** | **Core AI Quality (`P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT`)** | **TODO** | Sửa triệt để 3 lỗi eval thật rồi chạy lại 12-topic eval (cần duyệt budget) |
| **Next — Wave 3** | **Feature Activation & Production Hardening (`P6.2+`)** | **TODO** | Chốt bật `TUTOR_ENABLED`, `P50_ENABLED`, semantic embedding + `RAG_ENABLED`; Redis rate-limit, staging TLS/CSP, backup-restore drill |
| **Next — Wave 4** | **High-value Product Gaps vs. PolySkill (`GAP-01..GAP-23`)** | **PROPOSAL / BACKLOG** | Ưu tiên: Glossary + `termKey`, Proposal revision, per-block / AI `short` grading, Figures/MathJax, `source.brief`, `/v1/me/stats` & `PATCH /v1/me` |
| Deferred (`P7+`) | Narrated Reel Engine, 5 Practice Formats (`SpeedRound`), Offline SQLite Outbox, Leagues, Polar+SePay Billing, Push | **DEFERRED** | Chỉ mở sau khi có PRD & quyết định kinh doanh riêng |

## 2. Immediate next slices (theo thứ tự rủi ro → giá trị)

### Slice A — Housekeeping, Deploy Sync & Browser E2E
- Rà soát và tách commit sạch cho working tree hiện tại trên `feat/p6.0-ci-pipeline` (frontend FR-1..FR-5, `P1-QUIZ-BLANK`, `RELIABILITY-CELERY-01/02`, `P1-PEDAGOGY`, docs/specs/audits).
- Rebuild container `backend`/`worker`/`beat` để đưa `P1-PEDAGOGY` vào bản chạy thực và xác minh `backend/e2e_acceptance.py` trên stack đồng nhất.
- Bổ sung **Playwright E2E** tối thiểu (register/login → course → interview → proposal → generating → step lesson → quiz → docked/overlay tutor → đổi tài khoản) để đóng lỗ hổng `NOT TESTED browser UI`.

### Slice B — Đóng 3 lỗi chất lượng LLM thật (P1 Quality Gate)
1. **`P1-CONTENT-TRUNC`:** phát hiện rõ `finish_reason == "length"`, ngăn lưu bài học bị cắt cụt, điều chỉnh budget/retry có kiểm soát.
2. **`P1-LANG`:** truyền tham số ngôn ngữ (`vi` mặc định, hỗ trợ `en` và từ chối/fallback rõ locale chưa hỗ trợ) xuyên suốt course → profile → proposal → lesson/quiz → tutor (expand-only migration nếu lưu cột `language` trên `courses`/`users`).
3. **`P1-LEVEL-FIT`:** siết hướng dẫn và validator mức độ trong `pedagogy.py` + prompts để tránh tự ép trình độ sang `advanced` trái với interview.
- **Gate:** Chạy lại real-provider eval (sau khi owner duyệt ngân sách) với mục tiêu `language_quality` & `level_fit` ≥ `3.0/4` và `0` lỗi truncation.

### Slice C — Kích hoạt có kiểm soát các phân hệ đã code & P6.2 Hardening
- Chuyển rate-limiter từ in-memory sang **Redis distributed** (`M1-SEC-LIMITER`).
- Bật & kiểm chứng live có kiểm soát: `TUTOR_ENABLED=true` (gồm real-provider streaming smoke), `P50_ENABLED=true`, và benchmark embedding thật trước khi bật `RAG_ENABLED=true`.
- Hoàn thiện backup-restore drill, staging TLS/CSP và chính sách retention/deletion (`DELETE /v1/me`).

### Slice D — Chọn lọc Product Gaps giá trị cao (additive, giữ server-authoritative)
Theo thứ tự tác động người học cao nhất từ `docs/frontend-reference/api-gap-register.md`:
1. **Glossary + inline `termKey`** (`GAP-06`, `GAP-14`) & **Proposal revision** (`GAP-08`: `PlanChat` + `revise_proposal` hoặc `PATCH /proposal` versioned).
2. **Per-block grading + AI Short-Answer Rubric Grader** (`GAP-11`, giữ đáp án ở server).
3. **Figures/Tables/MathJax** (`GAP-18`) + **Structured `source.brief`** (`P2-BRIEF`).
4. **User stats & settings** (`GET /v1/me/stats`, `PATCH /v1/me` tách `appLanguage`/`lessonLanguage`, `GAP-03`, `GAP-21`).

## 3. Phase exit gate protocol

- Quy trình chuẩn mọi slice: `audit → plan → contracts → failing tests → code → security → verify → review → report`.
- `GATE-PASS` khi toàn bộ criteria bắt buộc có lệnh chạy & bằng chứng; `PARTIAL` khi còn hạng mục chưa chạy; `BLOCKED` khi thiếu môi trường/phê duyệt ngân sách.
- Tuyệt đối không tự push `main`, deploy production, chạy migration phá dữ liệu, gửi tài liệu riêng tư ra provider ngoài hay bật billing khi chưa có phê duyệt tường minh.
