# Implementation Plan

> Phân chia giai đoạn theo vertical slice. Mỗi slice kết thúc bằng kiểm chứng chạy thật.

## Slice 0 — Foundation ✅ DONE (đã kiểm chứng)
- [x] Repo setup: `backend/` (FastAPI), `frontend/` (Next.js), `docker-compose.yml`
- [x] Config qua pydantic-settings + `.env.example`
- [x] PostgreSQL 16 + Redis 7 qua Docker Compose (TESTED — containers healthy)
- [x] LLM Provider abstraction + MockProvider
- [x] Demo user (header `X-User-Id`) — auth đầy đủ để sau

## Slice 1 — Course Generator + Lesson Engine ✅ DONE (đã kiểm chứng)
- [x] `POST /v1/courses` (idempotent theo `clientCourseId`) — TESTED
- [x] Interview: 5 câu, `POST /interview/answer` từng câu — TESTED
- [x] Proposal sinh khi đủ 5 câu, validate Pydantic, version — TESTED
- [x] `POST /approve` → Celery task → sinh units + lessons (4 bài) → `ready` — TESTED (worker log: task succeeded)
- [x] `GET /generation` poll; `POST /retry` — TESTED (retry upsert không trùng lesson)
- [x] Lesson blocks: teach/mc/blank/order/match/short + `contentVersion` — TESTED
- [x] `POST /lessons/{id}/attempts`: chấm server-side deterministic, idempotent, XP — TESTED
- [x] Unit tests + integration tests: 20/20 pass — TESTED
- [x] E2E acceptance 16/16 pass qua HTTP thật (uvicorn local VÀ Docker stack với Celery) — TESTED

## Slice 2 — AI Tutor (kế tiếp)
- [ ] Tutor threads/messages; SSE events delta/tool/confirm/done/error
- [ ] Tool registry: read_lesson, explain_deeper, read_source (schema validated)
- [ ] `clientMessageId` idempotency; stop/cancel; last-event-id resume
- [ ] Allowance + rate limit (`TUTOR_LIMIT_REACHED`-style error shape)
- [ ] Backend tự xác thực contextRef (lessonId, blockIndex) — không tin client

## Slice 3 — RAG Engine
- [ ] `sources` upload/ingest pipeline: extract → chunk → embed → pgvector
- [ ] Retrieval + context assembly + citations thật (anchor → chunk)
- [ ] Không tạo citation giả — chỉ cite chunk tồn tại trong DB

## Slice 4 — Gamification & polish
- [ ] Streak logic đầy đủ, hearts/goal/levels, leaderboard tùy chọn

## Bài học kỹ thuật đã ghi nhận trong quá trình triển khai
1. **asyncpg + asyncio.run()**: engine/pool module-level không dùng được qua nhiều event loop → worker tạo engine riêng mỗi task, dispose sau khi xong.
2. **SQLite in-memory test**: cần `StaticPool` để chia sẻ connection giữa các request.
3. **Discriminated union**: Pydantic union cho blocks phải dùng `Field(discriminator="type")`.
4. **Celery CLI app**: cần module `app.worker.celery_app:celery_app` riêng cho `-A` flag.
5. **Windows + Docker port-forward**: `localhost` ưu tiên IPv6 `[::1]` gây ~8s timeout mỗi connection — dùng `127.0.0.1` phía client. Đây là đặc thù môi trường, không phải bug app.
