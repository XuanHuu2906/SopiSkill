# 15 — Verification Strategy, Test Matrix & Acceptance Scenarios

**Trạng thái (`2026-11-22`):** Repo hiện có **65 file pytest** (`backend/tests/test_*.py`), script E2E `backend/e2e_acceptance.py`, CI 5 jobs (`.github/workflows/ci.yml`) và bộ eval (`backend/evals/`). Kết quả gần nhất được ghi nhận (`2026-11-05`, `P1-PEDAGOGY-RESULT.md`): **`774 passed, 29 skipped`** (tất cả 29 skip là `POSTGRES_TEST_URL`-gated trên SQLite host; CI Linux chạy PostgreSQL thật). **Trong lần cập nhật spec ngày `2026-11-22` không chạy lại test.**

## 1. Test layers

- **Unit & API integration (`backend/tests/`):** 65 file pytest phủ auth, course/interview/proposal, pedagogy (`test_p1_pedagogy.py`, `test_p21_pedagogy.py`), grading/quiz (`test_grading.py`, `test_quiz_blank.py`, `test_quiz_integrity.py`), Celery reliability (`test_job_reliability.py`), LLM provider & cost (`test_llm_provider.py`, `test_p22_cost_budget.py`), Source Research (`test_source_research_agent.py`), Tutor SSE/controls/tools (`test_p30_tutor*.py`, `test_p31_tutor*.py`), PDF/RAG/Web/OCR (`test_p40_*`, `test_p41_*`, `test_p42_*`, `test_p43_*`), Mastery/FSRS/BKT/Exposure (`test_p50_*`, `test_p51_*`, `test_p52_*`), CI contract (`test_p61_ci_contract.py`).
- **PostgreSQL race & migration contracts:** chạy thật trên PostgreSQL 16 trong CI (`POSTGRES_TEST_URL`); skip khi chạy SQLite cục bộ.
- **Live HTTP E2E (`backend/e2e_acceptance.py`):** chạy trên stack mock (`61/61 PASS` khi Tutor tắt; `71/71 PASS` khi bật `TUTOR_ENABLED=true` trong `TUTOR-MOCK-01`).
- **Frontend checks:** `npm run lint`, `npm run typecheck`, `npm run build` (11 routes/static targets). **Chưa có** Playwright/Vitest E2E tự động.
- **Real AI evaluation (`backend/evals/`):** chạy thủ công có duyệt ngân sách (`p22_real_eval.log`, `rag_eval.py`, `ocr_eval.py`, `bkt_eval.py`, `p52_readiness.py`). Không chạy trong CI.

## 2. Critical cross-phase test matrix (đã chuẩn hóa T-IDs)

| Scenario | Phase | Expected result | Trạng thái gần nhất (REPORTED) |
|---|---|---|---|
| T-001 register/login/logout/`/v1/auth/me` | P0.5 / All | Session đúng; JWT HttpOnly/CSRF/Argon2id hợp lệ | **TESTED (PASS)** |
| T-002 cross-owner resource access | All | 404 course/lesson/attempt/thread/source/review | **TESTED (PASS)** |
| T-003 5 interview + `LearnerProfile` + proposal | P2.1 + `P1-PEDAGOGY` | 5 câu, schema valid, parser tiếng Việt không dấu/unit chính xác | **TESTED (PASS — uncommitted)** |
| T-004 approve concurrency | P1.2 / P2.1 | 1 active generation job; proposal version pinned | **TESTED (PASS)** |
| T-005 worker duplicate / stale-dispatch / visibility timeout | P1.2 / Celery-01-02 | Không nhân đôi lesson; nhánh 3 thu hồi orphan + `DISPATCH_EXHAUSTED` | **TESTED · LIVE-VERIFIED** |
| T-006 invalid LLM output / timeout / 429 / budget cap | P2.0 / P2.2 | Đúng error taxonomy + bounded retry + fail-fast | **TESTED (PASS)** |
| T-007 quiz key privacy & HMAC shuffle | P1.1 / P6.1 | `GET /v1/lessons/{id}` 0 answer key; `order`/`match` ký bằng `LESSON_SHUFFLE_SECRET` | **TESTED (PASS)** |
| T-008 attempt race, `bool` reject & XP cap | P1.1 / `P1-QUIZ-BLANK` | 1 logical attempt trên cùng ID, không farm XP, `blank` đúng 1 chỗ trống | **TESTED (PASS)** |
| T-009 content version / reload / account switch | P1.1 / P1.3 | Stale 409; lịch sử cũ còn; A→B không rò cache | **TESTED (PASS)** |
| T-010 DAG cycle / missing node | P2.1 | Proposal lỗi DAG bị từ chối trước approve/generate | **TESTED (PASS)** |
| T-011 12-topic real pedagogy evaluation | P2.2 | Rubric report tái lập + failure taxonomy | **MEASURED (`3.17/4`, lộ lỗi P1)** |
| T-012 Tutor SSE full & client disconnect | P3.0 / `TUTOR-MOCK-01` | Ordered `delta`→`done`, disconnect lưu `cancelled` + partial | **TESTED MOCK · REAL NOT TESTED** |
| T-013 Tutor idempotency / allowance quota | P3.0–P3.1 | Replay không gọi lại; 429 kèm `detail.quota` | **TESTED MOCK** |
| T-014 Tutor server-side stop & stale reap | P3.1 lát A | `POST .../stop` → `cancelled`, giữ partial; stale → `TUTOR_STALE` | **TESTED MOCK** |
| T-015 Tutor tool allowlist & resilience | P3.1 lát B | Tool lạ/args sai/OOB bị chặn trước execute + audit; planner lỗi vẫn trả lời | **TESTED MOCK · REAL NOT TESTED** |
| T-016 PDF ingest failcases & private storage | P4.0 | Reject corrupt/oversize/scan (`no_text`), không cross-user | **TESTED (PASS)** |
| T-017 Hybrid RAG, citation integrity & abstention | P4.1 | 100% `chk_*` resolve chunk có quyền; không đủ căn cứ ⇒ abstain; chống injection | **TESTED OFFLINE (hashing baseline)** |
| T-018 Web/arXiv SSRF, DNS rebinding, robots & rights | P4.2 | Chặn private IP/redirect/thiếu `userConfirmedRights`; live probe `example.com` + arXiv | **TESTED (PASS)** |
| T-019 OCR opt-in (`rapidocr` / `vietocr`) | P4.3 | Chỉ OCR trang thiếu text; gắn `textSource="ocr"`, đo CER/WER | **TESTED SYNTHETIC** |
| T-020 Mastery, FSRS schedule, BKT eval & exposure token | P5.0–P5.2 | FSRS idempotent; BKT/readiness báo `BLOCKED` trung thực; HMAC token valid | **TESTED (PASS — flags OFF)** |
| T-021 CI pipeline 5 jobs (migration/race/build/security) | P6.1 | GitHub Actions 5/5 xanh trên Linux + Postgres 16 | **TESTED (run `41583115455`)** |
| T-022 Browser UI E2E (Playwright) & screen reader | FR-1..FR-5 | Flow tạo khóa → lesson → quiz → docked/overlay tutor + Tab/Focus + NVDA | **NOT TESTED** |
| T-023 Staging backup-restore & distributed rate-limit | P6.2+ | Recovery toàn vẹn + Redis rate-limit dưới multi-worker | **NOT TESTED / NOT IMPLEMENTED** |

## 3. Các vùng `NOT TESTED` bắt buộc ghi nhận trung thực

1. **Browser UI E2E tự động (`Playwright`):** chưa có trong `frontend/package.json`; `tsc`/`build` và chụp CDP thủ công không thay thế automated E2E.
2. **Real LLM streaming cho Tutor & real tool-calling quality:** toàn bộ Tutor mới verified trên `MockProvider`.
3. **Re-evaluation trên real provider sau `P1-QUIZ-BLANK` và `P1-PEDAGOGY`:** chưa chạy (chờ gộp cùng `P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT` và duyệt budget).
4. **Redis redelivery sau worker stall chủ đích** (`visibility_timeout=3600` đã verify live config nhưng chưa diễn tập stall).
5. **Screen reader thật (NVDA/VoiceOver)**, **load/stress testing**, và **backup-restore drill**.

## 4. Quy tắc báo cáo kiểm thử

Không báo `PASS` nếu chưa có lệnh chạy thực tế và output hiển thị; luôn ghi rõ `IMPLEMENTED / TESTED / NOT TESTED / BLOCKED`, nhánh/HEAD/trạng thái dirty tree, môi trường (`mock` hay real provider) và số lượng `passed / failed / skipped`.
