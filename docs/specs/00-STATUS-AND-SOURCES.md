# 00 — Hiện trạng, evidence và quy tắc quản lý specification

**Trạng thái:** Đã cập nhật ngày **2026-11-22** theo mã nguồn sống tại branch `feat/p6.0-ci-pipeline`, HEAD `d747e78` **cộng working tree chưa commit** (27 file tracked thay đổi nội dung + các bộ test/frontend/audit untracked). Các mục chưa triển khai vẫn giữ rõ nhãn `PROPOSAL / NOT IMPLEMENTED`.

> **Lưu ý xác minh:** Đợt cập nhật spec ngày `2026-11-22` kiểm chứng trực tiếp cấu trúc code, routes, models, migrations và config; **không** chạy lại `pytest`, `npm run build` hay Docker E2E trong phiên này. Mọi số liệu test dưới đây là `REPORTED TESTED` từ `docs/development-progress.md` và `docs/audits/**`.

## 1. Source-of-truth hierarchy

1. **Repository được checkout tại thời điểm triển khai**: code (`backend/app/**`, `frontend/src/**`), migrations (`0001`–`0016`), route definitions, test output chạy thật, Git diff.
2. **`docs/development-progress.md` và `docs/audits/**`**: lịch sử test/audit được báo cáo có ngày, lệnh, kết quả; không tương đương test vừa chạy sau chỉnh sửa mới.
3. **`docs/llm-provider.md`, `docs/migration-runbook.md`, `docs/frontend-reference/**`**: hành vi vận hành và đối chiếu giao diện đã ghi nhận.
4. **`docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`, `docs/architecture.md`, `docs/database-design.md`**: định hướng kiến trúc ban đầu (nhiều mục cũ hơn code hiện tại).
5. **Báo cáo nghiên cứu PolySkill (`polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md`)**: chỉ là bối cảnh đối chiếu hành vi (`OBSERVED_STATIC`/`OBSERVED_RUNTIME`), **không** là chứng cứ xác định backend SopiSkill và **không** tự động trở thành hợp đồng SopiSkill.

## 2. Baseline thực tế của SopiSkill (2026-11-22)

| Hạng mục | Trạng thái | Bằng chứng / ghi chú vận hành |
|---|---|---|
| Repo & Git state | `feat/p6.0-ci-pipeline` · HEAD `d747e78` (**DIRTY tree**) | 27 file tracked thay đổi (bỏ CRLF) + frontend primitives/fonts + tests + audit docs chưa commit. |
| Stack | **IMPLEMENTED** | `backend/` FastAPI + SQLAlchemy async + PostgreSQL 16 + Redis 7 + Celery + MinIO (45 endpoints, 27 bảng, 16 migrations, 65 file pytest); `frontend/` Next.js 15.5.28 + React 19 + TanStack Query v5 (10 route pages). |
| Auth & session (`P0.5`) | **IMPLEMENTED · REPORTED TESTED** | Email/password (Argon2id), JWT HttpOnly cookie, CSRF double-submit, `ALLOW_DEMO_HEADER=false`, owner scoping (404 cross-user). Rate limit vẫn in-memory per-process. |
| Course → 5 interview → Proposal → Approve → Generation → Quiz (`Slice 0–P1.3`) | **IMPLEMENTED · REPORTED TESTED (mock)** | `LLM_PROVIDER=mock` mặc định (**không phải AI thật**). Server-authoritative grading, `public_block()` không lộ đáp án, HMAC shuffle key (`LESSON_SHUFFLE_SECRET`, P6.1), XP chống farm (`10/câu + 20 bonus`). |
| Celery reliability (`P1.2`, `RELIABILITY-CELERY-01/02`) | **IMPLEMENTED · REPORTED TESTED · DEPLOYED** | Atomic claim, lease, stale-dispatch recovery nhánh 3, `broker_transport_options.visibility_timeout=3600` (`task_time_limit=2400`). Live-verified `2026-11-05`. |
| Quiz blank integrity (`P1-QUIZ-BLANK`) | **IMPLEMENTED · REPORTED TESTED (uncommitted)** | `BLANK_SLOT_COUNT=1`, `_count_blank_slots()`, `validate_lesson()` ở ranh giới worker (`backend/tests/test_quiz_blank.py`). 7 bản ghi cũ trong DB cố tình giữ nguyên không rewrite. |
| Learner profile parser (`P1-PEDAGOGY`) | **IMPLEMENTED · REPORTED TESTED (uncommitted, NOT DEPLOYED)** | Fix bỏ dấu tiếng Việt + word boundary + `gio/phut/tieng/hiểu sâu/đồ thị` (`backend/tests/test_p1_pedagogy.py`, 54 tests; full suite reported `774 passed, 29 skipped` ngày `2026-11-05`). Container chưa rebuild sau fix này. |
| Real LLM adapter, DAG & Cost (`P2.0–P2.2`) | **IMPLEMENTED · TESTED (mock/offline)** | OpenAI-compatible fail-fast, curriculum DAG, `llm_usage_events`, job token/cost caps (`0007`), **Wave 2 fixes đã code & test offline (`P1-LEVEL-FIT`, `P1-LANG` migration `0017`, `P1-CONTENT-TRUNC` + completeness lint)**. Chờ owner duyệt ngân sách để chạy lại real-LLM eval 12 topics (baseline trước fix: `3.17/4`). |
| Source Registry & Research Agent (`P3.0b`, `P2.SR`) | **IMPLEMENTED · DEFAULT-OFF (research)** | Migrations `0005`, `0006`; `SOURCE_RESEARCH_ENABLED=false`, provider mặc định `mock`/`curated` (offline). |
| AI Tutor SSE + Tools (`P3.0–P3.1`, `TUTOR-MOCK-01`) | **IMPLEMENTED · REPORTED TESTED (mock) · DEFAULT-OFF** | Migrations `0008`–`0010`; 5 endpoints, stop best-effort, daily quota, 3 read-only tools (`read_lesson`, `explain_deeper`, `read_source`). `TUTOR_ENABLED=false` & `TUTOR_TOOLS_ENABLED=false` mặc định. Gate `TUTOR-MOCK-01` pass `71/71` E2E trên mock; streaming với LLM thật **NOT TESTED**. |
| PDF/Web/arXiv Ingest, Hybrid RAG, OCR (`P4.0–P4.3`) | **IMPLEMENTED · ĐA SỐ DEFAULT-OFF** | Migrations `0011`–`0014`. `SOURCE_INGEST_ENABLED=true` (MinIO/S3); `RAG_ENABLED=false` (embedding mặc định `hashing-ngram-v1` lexical, JSON cosine exact, chưa pgvector); `WEB_INGEST_ENABLED=false` (allowlist rỗng, `PinnedNetworkBackend` chống SSRF/DNS rebinding); `OCR_ENABLED=false` (`rapidocr` & `vietocr`, CER VI `vietocr` ≈ 0.4% trên synthetic). |
| Mastery, FSRS, BKT, Readiness (`P5.0–P5.2`) | **IMPLEMENTED · DEFAULT-OFF / BLOCKED** | Migrations `0015`–`0016`. `P50_ENABLED=false` (mastery rule-based + `fsrs` `/review` + learning-path); `P5.1` BKT research-only (**deploy BLOCKED**: thiếu dữ liệu); `P5.2` readiness **BLOCKED** + exposure logging `P52_EXPOSURE_ENABLED=false` (HMAC token). |
| CI Pipeline (`P6.1`) | **IMPLEMENTED · REPORTED TESTED** | `.github/workflows/ci.yml`: GitHub Actions run `41583115455` báo **5/5 jobs xanh** (backend tests, Postgres migration up/down, Postgres race tests, frontend lint/typecheck/build, Bandit/pip-audit). |
| Frontend Reconstruction (`FR-1..FR-5`) + Playwright E2E | **IMPLEMENTED · TESTED (mock)** | Design tokens light/dark, 21 self-hosted `.woff2` fonts, step-by-step lesson player, `OutlineSheet` + docked `TutorPanel` ≥1024px / modal `<1024px`, selector ngôn ngữ khóa học (`vi`/`en`), **Playwright E2E + axe-core (`3/3` PASS trên `1440`/`768`/`390`) + job `frontend-e2e` trong CI**. **NOT TESTED:** screen reader thật (NVDA/VoiceOver). |
| Production hardening (`P6.2+`) & Billing/Gamification (`P7`) | **PLANNED / NOT IMPLEMENTED** | Chưa có distributed Redis rate-limit, staging TLS/CSP, backup-restore drill, retention/deletion policy, billing/entitlements, gamification mở rộng, Reel engine. |

## 3. Parity Audit & Chất lượng AI (tách riêng trục đánh giá)

- **Parity Audit `2026-11-04`** (`docs/audits/polyskill-parity-2026-11-04/00-executive-summary.md`): Measured Parity **74.7% (62/83)**, Evidence Coverage **53.0/100**, Conservative Floor **62.0/100** (trước khi giải mã thêm Reel, SpeedRound, Billing Polar+SePay, Offline SQLite ngày `2026-11-22`). Không dùng con số này như tỷ lệ hoàn thành sản phẩm.
- **Real-LLM Quality Eval** (`08-ai-quality-evaluation.md`): 12 topics trên DeepSeek (`N=11` scored) đạt mean **3.17/4**; tiêu chí thấp nhất là `language_quality` (`2.273`), `level_fit` (`2.364`), `answer_consistency` (`2.818`). Structural tests pass 12/12 nhưng vẫn có lỗi chất lượng thực tế ⇒ "JSON hợp lệ ≠ bài học tốt".

## 4. Những mâu thuẫn lịch sử đã giải quyết

- **Cấu trúc repo:** giữ `frontend/` và `backend/` (không đổi sang `apps/web` / `services/api`).
- **Auth endpoint:** đường dẫn thực tế trong `backend/app/api/v1/auth.py` là **`GET /v1/auth/me`** (một số spec cũ viết nhầm `/v1/me` — đã chuẩn hóa lại trong đợt cập nhật này).
- **Auth & demo mode:** JWT HttpOnly cookie + CSRF, `ALLOW_DEMO_HEADER=false` mặc định; không hồi quy về `X-User-Id`.
- **Policy `≥80%` & XP (`10/câu + 20 bonus`):** đang áp dụng (`INCUMBENT / PRODUCT APPROVAL PENDING`).
- **Vector store P4.1:** đã chốt phương án A offline-first (`hashing` + JSON cosine exact trong `source_chunk_embeddings`), chưa cài `pgvector` cho tới khi có benchmark embedding thật.
- **Proposal flow:** proposal được sinh và cho user xem/approve trước; worker sinh lessons từ snapshot proposal đã approve.

## 5. Quy tắc thay đổi spec

- Mỗi requirement giữ ID ổn định (`COURSE-001`, `TUTOR-004`, `RAG-006`, ...).
- Khi contract đang chạy khác đề xuất, viết kế hoạch tương thích/migration, không âm thầm phá API client đang dùng.
- Chỉ đánh dấu `ACCEPTED` trong `17-DECISION-LOG.md` khi có quyết định rõ ràng của owner/bằng chứng triển khai được duyệt.
- Mọi tính năng mới từ `polyskill-analysis-report.md` (`2026-11-22`, Craft Anything `0.6.1`, bundle SHA-256 `e7f84aaf…d4ce`) đều là **`OBSERVED_STATIC` / `PROPOSAL`**, không tự động thay đổi kiến trúc server-authoritative của SopiSkill.
