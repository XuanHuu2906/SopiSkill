# AI Learning Platform — Kiến trúc hệ thống

> **Trạng thái:** Bản thiết kế triển khai cho vertical slice đầu tiên.
> **Nguồn tham khảo:** `polyskill-analysis-report.md` và `polyskill-dynamic-analysis.md` — chỉ dùng phát hiện hành vi/giao thức làm tài liệu tham khảo nghiệp vụ, không sao chép mã nguồn, UI hay logic độc quyền.
> **Ngày:** 2026-10-30

## 1. Mục tiêu

Xây dựng nền tảng học tập dùng AI, độc lập, có các khả năng nghiệp vụ tương đương:

1. **Course Generator** — biến chủ đề thành khóa học có cấu trúc qua phỏng vấn + proposal do AI sinh.
2. **Lesson Engine** — bài học dạng block (teach/mc/blank/order/match/short) với content versioning và chấm điểm deterministic.
3. **AI Tutor** — streaming agent có tool-calling, context grounding và rate limit.
4. **RAG Engine** — pipeline tài liệu → chunks → embeddings → retrieval → citation thật.
5. **Progress & Gamification** — XP, streak, progress.

Phạm vi giai đoạn này: **Course Generator + Lesson Engine + foundation chung**. Tutor, RAG, gamification nâng cao chỉ thiết kế, chưa triển khai đầy đủ.

## 2. Tổng quan kiến trúc

```
┌─────────────────────────────────────────────────────────────────────┐
│ FRONTEND — Next.js 15 + TypeScript                                   │
│  App Router pages: /new → /new/interview → /new/proposal →           │
│  /new/generating → /course/[id] → /lesson/[id]                       │
│  TanStack Query (poll generation mỗi 2s), SSE client (tutor)         │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ REST JSON + SSE
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ BACKEND — FastAPI + Python 3.13                                      │
│  api/v1: courses, interview, approve, generation, lessons, attempts  │
│  services: course_service, interview_service, generation_service,    │
│            lesson_service, grading_service, tutor_service (sau)      │
│  providers: LLMProvider interface → MockProvider | OpenAI | ...      │
│  core: config (pydantic-settings), security (owner check)            │
└───────┬──────────────────────────────┬───────────────────────────────┘
        │ SQLAlchemy (async)           │ Celery task .delay()
        ▼                              ▼
┌───────────────────────┐    ┌─────────────────────────────────────┐
│ PostgreSQL 16         │    │ Redis 7                              │
│ + pgvector (sau)      │    │  - Celery broker + result backend    │
│  courses, interviews, │    │  - generation lock (SET NX EX)       │
│  proposals, lessons,  │    └────────────────┬────────────────────┘
│  attempts, users,     │                     ▼
│  progress, xp_events  │    ┌─────────────────────────────────────┐
└───────────────────────┘    │ Celery Worker                       │
                             │  generation_task:                   │
                             │  proposal → lessons → status ready  │
                             │  idempotent theo generation_job_id  │
                             └─────────────────────────────────────┘
```

## 3. Thành phần chính

### 3.1. Frontend (Next.js + TypeScript)

- **App Router** với các route phản chiếu luồng nghiệp vụ.
- **TanStack Query** quản lý server state; generation status poll 2s (tự dừng khi `ready`/`failed`).
- **SSE client** cho tutor (giai đoạn sau): xử lý event `delta`, `tool`, `confirm`, `done`, `error`; hủy qua `AbortController`; `clientMessageId` sinh phía client chống trùng.
- Không chứa logic chấm điểm; gửi attempts lên backend chấm.

### 3.2. Backend (FastAPI)

Phân tầng:

```
api/v1/        — routers, request/response models (Pydantic), status codes
services/      — business logic, validation quyền sở hữu, idempotency
providers/     — LLMProvider ABC + MockProvider (deterministic) + adapter sau
db/            — async engine, session dependency
models/        — SQLAlchemy ORM models
worker/        — Celery app + tasks
core/          — config, security
```

Nguyên tắc:

- **Chấm điểm trên backend** với logic xác định cho mc/blank/order/match (không dùng LLM). `short` trả kết quả "pending AI grading" ở giai đoạn này (mock provider sinh answer key khớp câu chấp nhận được chấm exact-match chuẩn hóa).
- **Xác thực quyền:** mọi endpoint scoped theo `user_id`; backend tra cứu ownership trong DB, **không tin `contextRef`/`courseId` từ client** ngoài việc dùng làm khóa tra cứu.
- **Idempotency:** khóa học và attempts dùng client-supplied id (`clientCourseId`, `clientAttemptId`) làm unique key; generation job dùng `generation_job_id` unique + Redis lock `SET NX EX` chống chạy song song.
- **Structured output:** proposal được validate bằng Pydantic schema; sai schema → provider được gọi lại (tối đa N lần) rồi fail job với lỗi rõ ràng.

### 3.3. LLM Provider Abstraction

```python
class LLMProvider(ABC):
    async def generate_proposal(topic, interview_answers, profile) -> ProposalSchema
    async def generate_lessons(proposal, existing_titles) -> list[LessonSchema]
    # giai đoạn sau:
    async def stream_tutor(...) -> AsyncIterator[TutorEvent]
    async def generate_rag_answer(...) -> ...
```

- **MockProvider:** deterministic, không network — dùng cho dev/test và acceptance E2E.
- Adapter OpenAI/Anthropic thêm sau với cùng interface; API key qua env, **không hardcode**.
- Sai schema → retry có giới hạn → job failed với error có cấu trúc.

### 3.4. Background Generation (Celery + Redis)

- `POST /courses/{id}/approve` → tạo `generation_job` (status `queued`) → `celery_task.delay(job_id)`.
- Worker: `SET NX EX` lock theo job_id → sinh proposal + lessons qua provider → ghi DB → `ready`. Thất bại → `failed` + error.
- Retry: client gọi `POST /courses/{id}/retry` → tạo job mới (job cũ giữ nguyên lịch sử), lessons sinh bởi job mới được upsert theo `(course_id, order)` nên không trùng lặp.
- Frontend poll `GET /courses/{id}/generation` mỗi 2s.

### 3.5. Dữ liệu & Vector (sau)

- PostgreSQL là nguồn dữ liệu chính. pgvector + RAG pipeline là giai đoạn 2; schema đã chừa chỗ mở rộng.

### 3.6. Source Registry & Evidence Contract (P3.0 — đã triển khai)

Source-first bổ sung lớp **truy vết nguồn** mà không đổi luồng interview/proposal/generation:

- `sources`: metadata nguồn (không chứa nội dung tài liệu) + mức xác thực **metadata**.
- `course_sources`: liên kết n–n course ↔ source + snapshot đánh giá.
- `lesson_citations`: provenance của bài học, snapshot `source_version`.
- `lessons.grounding`: `source_grounded` | `general_ai_knowledge`
  (`server_default='general_ai_knowledge'` để bài học cũ đọc được).

Bốn cấp kiểm chứng được tách biệt: metadata verified / locator verified / evidence supports
claim / claim corroborated. P3.0 **chưa ingest nội dung** nên không bao giờ tạo
`evidence_supported` và bài học luôn là `general_ai_knowledge`.

Chi tiết + lộ trình RAG P4: `docs/source-first-architecture.md`.

### 3.7. Source Research Agent (P2.SR — đã triển khai, mặc định TẮT)

Agent nghiên cứu nguồn chạy **trong sản phẩm**, độc lập với Course Orchestrator:

```
Topic → Interview → [Source Research Agent] → Source Registry → Proposal → Generation
```

- Package `backend/app/agents/source_research/` (agent, topic analysis, policies, ranking,
  allowlisted tools, adapters mock/curated-bridge). Không phụ thuộc DB, không gọi LLM.
- `services/source_research_service.py` giữ identity/ownership, idempotency (fingerprint sha256),
  persistence (`source_research_runs`) và chuyển nguồn đã kiểm tra metadata vào registry.
- Bốn trạng thái kiểm chứng vẫn tách biệt; agent chỉ được kết luận `discovered` /
  `metadata_verified` — `content_available` và `evidence_verified` cần ingestion (P4).
- Adapter `mock` deterministic, **không network**; `curated` đọc catalog env; `web` bị từ chối.
- Feature flag `SOURCE_RESEARCH_ENABLED=false` ⇒ endpoint trả 503 có mã, flow cũ không đổi;
  `SOURCE_RESEARCH_AUTO_LINK=false` ⇒ worker không tự chạy agent.

Chi tiết: `docs/source-research-agent.md`.

## 4. Luồng nghiệp vụ

### Course Generator (vertical slice này)

```
POST /v1/courses {topic, clientCourseId}      → 201 {courseId, status: interview}
POST /v1/courses/{id}/interview/answer ×5     → cập nhật answers, status
GET  /v1/courses/{id}/proposal                → proposal hiện tại (đã sinh khi đủ 5 câu)
POST /v1/courses/{id}/approve                 → 202 tạo generation job
GET  /v1/courses/{id}/generation              → {status, stage, lessonsDone, ...}
POST /v1/courses/{id}/retry                   → 202 job mới
GET  /v1/courses/{id}                         → course + units + lessons
GET  /v1/lessons/{id}                         → lesson blocks + grounding + citations
POST /v1/lessons/{id}/attempts                → chấm + lưu + rewards

// P3.0 Source Registry
POST /v1/sources                              → 201 tạo/reuse nguồn (luôn unverified)
GET  /v1/sources?limit&offset                 → nguồn public + của chính user
GET  /v1/sources/discover?topic&adapter       → candidate (curated/mock; không network)
GET  /v1/sources/{id}                         → metadata (private người khác ⇒ 404)
GET  /v1/sources/{id}/evaluation              → đánh giá deterministic metadata-only
POST /v1/courses/{id}/sources                 → liên kết nguồn với course
GET  /v1/courses/{id}/sources                 → danh sách nguồn đã liên kết

// P2.SR Source Research Agent (flag SOURCE_RESEARCH_ENABLED, default off ⇒ 503)
POST /v1/courses/{id}/research-runs           → 201 chạy/trả lại research run (deterministic)
GET  /v1/courses/{id}/research-runs           → danh sách run của course
GET  /v1/courses/{id}/research-runs/{runId}   → chi tiết (cross-user ⇒ 404)
POST /v1/courses/{id}/research-runs/{runId}/accept → link nguồn metadata_verified (mock ⇒ 409)
```

Trạng thái course: `interview → proposed → approved → generating → ready | failed`.

### Grading

- `mc`: so khớp index option đúng.
- `blank`: so khớp chuỗi chuẩn hóa (trim + casefold).
- `order`: so khớp dãy thứ tự.
- `match`: so khớp cặp ghép.
- `short`: exact-match trên answer key chuẩn hóa (mock provider sinh key); chấm bằng LLM là nâng cấp sau.
- Attempts là **batch**: client gửi `results[]` (index, type, answer, timing) kèm `clientAttemptId` + `contentVersion`.

## 5. Bảo mật

- Auth: JWT trong HttpOnly cookie + Argon2id, CSRF double-submit cho mọi request thay đổi trạng
  thái. Demo header `X-User-Id` mặc định tắt (chỉ `ALLOW_DEMO_HEADER=true` + `ENV=development`).
- Ownership check ở tầng service trên mọi truy cập course/lesson/source; truy cập trái quyền trả 404.
- Source private chỉ chủ sở hữu thấy; citation do server sinh từ registry, model không nhận/không
  trả `sourceId`.
- CORS cấu hình theo allowlist origin.
- Không log secret; provider API key chỉ qua env.

## 6. Giới hạn đã biết (giai đoạn này)

1. P3.0: Source Registry chỉ lưu **metadata**; chưa có ingestion nội dung, chunking, embedding hay
   vector search ⇒ bài học luôn `general_ai_knowledge` và citation chưa thể `locator_verified`.
2. Chưa có Tutor, RAG, gamification nâng cao (thiết kế trong docs, chưa code).
3. MockProvider sinh nội dung mẫu, không phải AI thật; gọi "AI thật" chỉ khi adapter provider thật được bật.
4. P2.SR: Source Research Agent tìm nguồn từ adapter `mock`/`curated` (không internet) và chỉ kiểm
   tra metadata; không đọc nội dung, không sinh citation, không tự verified.
5. Không có HTTPS/deploy config — chỉ local qua Docker Compose.

## 7. Khác biệt có chủ đích so với hệ thống được phân tích

- Không dùng Expo/RN Web; chọn Next.js để đơn giản hóa web-only.
- Không sao chép tên endpoint 1:1; đặt tên API theo chuẩn REST riêng nhưng giữ nguyên **hình thái nghiệp vụ** (interview 5 câu, proposal có units/lessons/outcomes, poll-based generation, batch attempts).
- LLM provider không biết tên cụ thể của hệ thống tham chiếu; adapter trung lập, cấu hình qua env.
