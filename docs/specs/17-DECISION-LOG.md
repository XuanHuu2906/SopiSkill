# 17 — Decision Log & Open Questions

**Trạng thái (`2026-11-22`):** Chỉ các mục có quyết định/bằng chứng triển khai rõ ràng mới đánh dấu `ACCEPTED`. Các câu hỏi mới phát sinh sau eval thật và đối chiếu PolySkill `2026-11-22` được giữ rõ ở mục `OPEN`.

## 1. Core & Phase Decisions

| ID | Decision | Status | Evidence / Ghi chú |
|---|---|---|---|
| DEC-001 | SopiSkill xây độc lập, không sao chép code/UI/assets/prompts PolySkill | **ACCEPTED** | Project rule (`AGENTS.md`, `00-STATUS-AND-SOURCES.md`) |
| DEC-002 | Giữ stack Next.js 15 / FastAPI / PostgreSQL 16 / Redis 7 / Celery / MinIO (`frontend/`, `backend/`) | **ACCEPTED · IMPLEMENTED** | Live repo & `docker-compose.yml` |
| DEC-003 | `MockProvider` mặc định, real provider fail-fast (`503 PROVIDER_NOT_CONFIGURED`) | **ACCEPTED · IMPLEMENTED** | `config.py`, `providers/`, P2.0 |
| DEC-004 | Auth HttpOnly JWT cookie + CSRF double-submit + Argon2id; `ALLOW_DEMO_HEADER=false` | **ACCEPTED · IMPLEMENTED** | `api/v1/auth.py`, P0.5 |
| DEC-005 | Quiz server-authoritative 100%, `public_block()` không bao giờ lộ đáp án; HMAC shuffle key (`LESSON_SHUFFLE_SECRET`) | **ACCEPTED · IMPLEMENTED** | `lesson_content.py`, P1.1 + P6.1 |
| DEC-006 | Generation job at-least-once + atomic claim/lease/outbox + stale-dispatch recovery + `visibility_timeout=3600` | **ACCEPTED · IMPLEMENTED · DEPLOYED** | `job_service.py`, `celery_app.py`, `RELIABILITY-CELERY-01/02` |
| DEC-007 | Course completed lesson threshold `≥80%` | **INCUMBENT / PRODUCT APPROVAL PENDING** | `lesson_service.py`; chưa chốt chính sách lâu dài |
| DEC-008 | XP policy (`10/câu đúng + 20 bonus`, cap theo `(user, lesson, contentVersion)`) | **INCUMBENT / PRODUCT APPROVAL PENDING** | `lesson_service.py`; cần chốt public policy |
| DEC-009 | Real smoke & 12-topic eval Deploy.com DeepSeek | **SCOPED APPROVAL ONLY** | Chỉ áp dụng cho các lượt đã duyệt; không là blanket budget |
| DEC-010 | Curriculum prerequisite DAG (`skills`, `prerequisites`) & Bloom outcomes lưu versioned trong `course_proposals.payload` | **ACCEPTED · IMPLEMENTED** | `schemas.py`, `pedagogy.py`, P2.1 (`test_p21_pedagogy.py`) |
| DEC-011 | Hybrid RAG offline-first (Phương án A): PostgreSQL FTS + JSON exact cosine (`hashing` default, `openai_compatible` opt-in), **hoãn `pgvector`** tới khi benchmark model thật | **ACCEPTED · IMPLEMENTED** (`RAG_ENABLED=false`) | Duyệt `2026-10-31`, `20-P41-HYBRID-RAG.md`, `0012_p41_rag` |
| DEC-012 | AI Tutor SSE + server-side deterministic read-only tools (`read_lesson`, `explain_deeper`, `read_source`) + quota + best-effort stop | **ACCEPTED · IMPLEMENTED** (`TUTOR_ENABLED=false`) | `0008`–`0010`, `10-AI-TUTOR-SSE.md`, `TUTOR-MOCK-01` |
| DEC-013 | P5.0 (Phương án B: snapshot bền vững + `fsrs` + UI `/review`); P5.1 BKT research-only; P5.2 readiness gate + HMAC exposure logging | **ACCEPTED · IMPLEMENTED** (`P50_ENABLED=false`, ML deploy BLOCKED) | `0015`–`0016`, `22-P50`, `23-P51`, `24-P52` |
| DEC-014 | Production deployment, billing, entitlements, paid plans | **NOT APPROVED / DEFERRED** | Manual gate P6.2+ / P7 |
| DEC-015 | Tự host 21 `.woff2` fonts (Manrope/Inter/JetBrains Mono) thay `next/font/google` để đảm bảo build webpack offline ổn định | **ACCEPTED · IMPLEMENTED** (FR-4, D-12) | `frontend/src/app/fonts.css`, `frontend/public/fonts/` |
| DEC-016 | Tutor rail **dock `400px`** cạnh bài học ở desktop `≥1024px` (phi modal) và **modal overlay** có focus trap + `inert` ở `<1024px`; dùng `<div role="dialog">` thay `<aside>` | **ACCEPTED · IMPLEMENTED** (FR-4b, FR-5) | `TutorPanel.tsx`, `useModalPanel.ts`, axe-core 0 violations |
| DEC-017 | `P1-QUIZ-BLANK`: reject ngay (severity `error`) mọi `blank` có ≠1 chỗ trống thay vì multi-blank hoặc `warning`; không rewrite 7 bài cũ trong DB | **ACCEPTED · IMPLEMENTED** (`2026-11-04`) | `validation.py`, `worker/generation.py`, `test_quiz_blank.py` |
| DEC-018 | `P4.3` OCR opt-in cục bộ (`rapidocr` & `vietocr`, mặc định TẮT), tách `pipelineVersion` để bảo toàn citation lịch sử | **ACCEPTED · IMPLEMENTED** (`OCR_ENABLED=false`) | `21-P43-OCR.md`, `0014_p43_ocr` |

## 2. Decisions lịch sử đã chốt ở P3.1 (bảo toàn + cập nhật trạng thái)

- **`DEC-P31-A1` (ACCEPTED):** Tutor SSE replay = **explicit restart** (`replaySupported=false`, không chấp nhận `Last-Event-ID`).
- **`DEC-P31-A2` (ACCEPTED):** Stop = **best-effort server cancellation** (`cancel_requested_at`, `providerStopGuaranteed=false`), không hứa hoàn tiền token đã sinh.
- **`DEC-P31-B1` (ACCEPTED):** Tutor tools = **server-side deterministic JSON** qua `plan_tutor_tool`, không dùng native `tool_calls`.
- **`DEC-P31-B2` (SUPERSEDED BY P4.1):** Ở P3.1, `read_source` được để `available=False`; từ **P4.1** đã chuyển `available=True` nhưng chỉ thực thi khi `RAG_ENABLED=true` và có `source_reader` đã scope quyền, ngược lại từ chối sạch không bịa citation (`backend/app/services/tutor_tools.py`).

## 3. Câu hỏi mở cần owner chốt (OPEN — tính đến 2026-11-22)

1. **Kích hoạt tính năng đã code:** Có bật `TUTOR_ENABLED=true`, `P50_ENABLED=true`, `P52_EXPOSURE_ENABLED=true` trên môi trường dev/staging không? Định mức `TUTOR_MESSAGES_PER_DAY` / `TUTOR_TOKENS_PER_DAY` mong muốn là bao nhiêu?
2. **Real LLM & Embedding Provider:** Chọn provider/model/ngân sách nào cho (a) tái đánh giá 12 topics sau khi sửa `P1-CONTENT-TRUNC` + `P1-LANG` + `P1-LEVEL-FIT`, (b) real streaming Tutor smoke, và (c) semantic embedding thật thay `hashing-ngram-v1` (và có chuyển sang `pgvector` sau benchmark hay không)?
3. **Ngôn ngữ (`P1-LANG` & `GAP-21`):** Chỉ thêm `language` (`vi`/`en`) trên course trước, hay triển khai luôn `PATCH /v1/me` tách `appLanguage` và `lessonLanguage`?
4. **Proposal revision (`GAP-08`):** Chọn `PATCH /v1/courses/{id}/proposal` (form sửa trực tiếp có version conflict) hay `PlanChat` hội thoại qua Tutor với tool `revise_proposal`?
5. **Chấm từng câu & Tự luận AI (`GAP-11`):** Có bổ sung `POST /v1/lessons/{id}/blocks/{index}/grade` (giữ server-authoritative) và AI rubric grader cho `short` (`got_it | almost | not_yet` + `dispute`), hay giữ cơ chế nộp 1 batch cuối bài?
6. **Chính sách sản phẩm & Gamification (`DEC-007/008`, `GAP-03`):** Chốt chính thức ngưỡng `≥80%`, công thức XP, và phạm vi `/v1/me/stats` (streak/hearts/weekly chart) hay giữ tối giản.
7. **Phạm vi dài hạn (`GAP-16`, `GAP-17`, `GAP-22`, `GAP-23`):** Xác nhận giữ **DEFERRED** cho Narrated Reel Engine, `SpeedRound`, Offline SQLite Outbox, Leagues và Billing (Polar/SePay) cho tới sau Production Release.
8. **P6.2 Production & Privacy:** Chính sách retention/deletion (`DELETE /v1/me`), đồng thuận dữ liệu gửi tới external LLM, Redis rate-limit, và lịch backup-restore drill.

## 4. Format ghi quyết định mới

```text
DEC-0XX: <short title>
Date / reviewer: <date, role>
Status: ACCEPTED | REJECTED | SUPERSEDED | PENDING
Context: <facts and constraints>
Options: <alternatives and risks>
Choice: <explicit user decision>
Consequences: <schema/api/rollout/tests>
Evidence: <issue/PR/commit/log>
```
