# 03 — System Architecture & Deployment Boundaries

**Trạng thái:** Kiến trúc hiện hữu theo tiến độ; thay đổi phase mới là PROPOSAL. Không thay stack khi chưa audit repo.

## 1. Logical topology

```text
Browser (Next.js 15 / TypeScript / TanStack Query)
      | HTTPS/JSON; POST fetch streaming SSE (Tutor sau)
      v
FastAPI application (Pydantic schemas + service-level authorization)
      |-- PostgreSQL 16 (SQLAlchemy async; Alembic migration)
      |-- Redis 7 (Celery broker, result backend; shared rate-limit sau)
      |-- LLMProvider registry (MockProvider | OpenAI-compatible via server-only keys)
      `-- Job dispatch + persistent outbox
               |
               v
          Celery worker + beat reconciler
               |-- Course generation (reported implemented)
               `-- Document ingest/embedding (P4 proposed)

Object storage S3-compatible (P4 proposed) -> PDF bytes (private)
pgvector + lexical search (P4 proposed) -> source chunks and retrieval
```

## 2. Repository conventions

- **Giữ `frontend/`**: App Router routes, UI components, API client, session-scoped TanStack Query keys.
- **Giữ `backend/`**: `app/api/v1`, `app/services`, `app/models`, `app/providers`, `app/worker`, `app/core`, `alembic/`, `tests/`, `e2e_acceptance.py`.
- `docker-compose.yml`: `db`, `redis`, `backend`, `worker`, `beat` và frontend theo compose thực tế (không giả định đếm service chính xác trên mọi checkout).
- Không tự chuyển thành `apps/web`, `services/api` hoặc thay Celery khi tác vụ không yêu cầu.

## 3. Trust boundaries

- **Browser untrusted**: mọi `id`, `contextRef`, progress, `correct`, claimed owner, metadata đều chưa đáng tin.
- **API authoritative**: auth cookie/JWT, CSRF, Pydantic input validation, DB owner check, grading, quota reservation, citation validation.
- **Worker trusted compute, not trusted input**: nhận job id từ queue, re-resolve job + proposal version ở DB, claim atomically; không tin task payload chứa owner.
- **LLM external/untrusted**: output JSON phải qua schema + semantic validation; prompt/model không có quyền đọc DB tự do; tool outputs/untrusted document text không là chỉ dẫn hệ thống.
- **Storage private**: random object keys và signed/private access; không expose local file paths.

## 4. Domain boundaries

| Module | Trách nhiệm | Không làm |
|---|---|---|
| Auth | user identity, cookie, CSRF | chấm quiz |
| Courses/Interview/Proposal | state machine, version, approve | trực tiếp chạy LLM trong transaction dài |
| Generation/Job | claim, retry, outbox, stage, write lessons | tin status từ client |
| Lesson/Quiz/Progress | public lesson projection, private answer key, attempt/XP | chấm bằng client hoặc cho LLM tự quyết quiz đóng |
| AI Provider | generate/stream interface, validation, cost guard | xử lý ownership thay cho service |
| Tutor (P3) | threads, context grounding, streaming, bounded tools | tùy ý gọi external network/code |
| Source/RAG (P4) | ingest, source provenance, hybrid search, citations | bịa trang/chunk |

## 5. Async consistency

- Course status và generation job status lưu trong **PostgreSQL**, không chỉ Celery result backend.
- `approve` ghi proposal version + job `queued` trong transaction. Dispatch có thể lỗi sau commit; `dispatched_at IS NULL` được beat/reconciler tìm lại.
- Worker `claim` atomically, lease/heartbeat, bounded retry và upsert units/lessons; job bị superseded không ghi đè bản mới.
- Thiết kế là **at-least-once delivery, idempotent effects**, **không** claim exactly-once billing/provider invocation tuyệt đối.
- P4 ingest dùng cùng nguyên tắc source version + pipeline version + checksum.

## 6. Backend infrastructure decisions

- API response dùng Pydantic; route prefix `/v1` theo hồ sơ; OpenAPI sinh từ code là contract hiện tại.
- Feature flags an toàn: `LLM_PROVIDER=mock` mặc định; `RAG_ENABLED=false` trước P4; source ingestion/tutor tools chỉ bật khi có data model và test.
- Env secrets không commit, không để `NEXT_PUBLIC_*`; redact logs. Coding agent OpenCode credentials **không** tự chuyển vào SopiSkill backend.
- Browser SSE dùng `fetch` POST với cookie+CSRF, `AbortController`; EventSource không hỗ trợ POST body theo contract đề xuất.

## 7. Môi trường và vận hành

- Developer: Windows + Docker Desktop/WSL2, Node, Python; check port `127.0.0.1:8001` cho API theo runbook, Next.js :3000 nếu compose config hiện tại phù hợp.
- Local tests: PostgreSQL test DB riêng cho race/migrations, SQLite cho unit logic; không xóa Docker volume dữ liệu.
- Production: HTTPS, secure cookies, reverse proxy allowlist, backups, observability và secret management thuộc P6; chưa giả định đã có.
