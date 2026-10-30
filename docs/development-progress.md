# Development Progress

> Ghi nhận trạng thái thực tế. Quy ước: **IMPLEMENTED** (có code) / **TESTED** (đã chạy và pass) / **NOT TESTED** (chưa chạy).

## 2026-10-30 — Slice 0 + Slice 1 hoàn thành

### Backend (FastAPI + SQLAlchemy async + Celery)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| API: courses/interview/proposal/approve/generation/retry | IMPLEMENTED + TESTED | E2E 16/16 pass qua HTTP thật |
| API: lessons/attempts (grading server-side) | IMPLEMENTED + TESTED | Quiz 5/5 đúng; duplicate attempt idempotent |
| MockProvider (interview questions, proposal, lessons) | IMPLEMENTED + TESTED | Deterministic; schema validate Pydantic |
| Grading deterministic (mc/blank/order/match/short) | IMPLEMENTED + TESTED | Unit tests 9 case |
| Celery worker generation task | IMPLEMENTED + TESTED | Worker log: `Task ... succeeded in 0.11s`; 0 Traceback |
| Idempotency: course + attempt | IMPLEMENTED + TESTED | `test_duplicate_course_creation_idempotent`, `8b. Attempt idempotent` |
| Ownership check (course/lesson) | IMPLEMENTED + TESTED | User khác truy cập → 404 |
| Rate limit in-memory per-process | IMPLEMENTED + TESTED | 429 khi vượt ngưỡng (unit) |
| XP cơ bản | IMPLEMENTED + TESTED | xpEarned=70 cho 5/5 đúng (50 + 20 bonus) |
| Generation retry (upsert không trùng lesson) | IMPLEMENTED + TESTED | retry → 4 lessons unique |

### Frontend (Next.js 15 + TanStack Query)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Pages: /, /new, /new/interview, /new/proposal, /new/generating, /course/[id], /lesson/[id] | IMPLEMENTED | `npm run build` thành công, 8 routes |
| Poll generation 2s tự dừng khi ready/failed | IMPLEMENTED | refetchInterval logic |
| Quiz player 5 loại block | IMPLEMENTED | render + nộp + hiển thị kết quả/đáp án |
| Lưu userId localStorage (persistent identity) | IMPLEMENTED | reload giữ user |

### Kiểm chứng chạy thật (2026-10-30)
1. **Unit + integration tests:** `pytest tests` → **20/20 passed** (backend, SQLite in-memory).
2. **E2E local uvicorn:** `e2e_acceptance.py` → **16/16 PASS** (SQLite + inline fallback).
3. **E2E Docker Compose full stack:** `e2e_acceptance.py` → **16/16 PASS** (PostgreSQL + Redis + Celery worker thật; xác minh qua `docker compose logs worker` và query trực tiếp trong `db` container — courses/lessons/attempts/users/xp đều tồn tại trong PostgreSQL).
4. **Frontend build:** `npm run build` → thành công, serve tại :3000 (HTTP 200).
5. **Retry flow:** approve → ready → retry → job mới chạy → lessons upsert không trùng (4 unique).
6. **Cross-ownership:** user B truy cập course/lesson của user A → 404 (course + lesson).

### Các lỗi đã gặp và sửa trong quá trình
1. UUID parse lỗi vì id có prefix `crs_`/`lsn_` → thêm `parse_prefixed_uuid`.
2. SQLite in-memory mất bảng giữa các connection → `StaticPool`.
3. `asyncio.run()` trong running loop (FastAPI request) → `asyncio.create_task` fallback.
4. Pydantic union blocks không phân biệt theo `type` → `Annotated[..., Field(discriminator="type")]`.
5. SQLAlchemy relationships thiếu (`Course.units`, `Unit.lessons`) cho `selectinload`.
6. **asyncpg cross-loop:** Celery task dùng engine module-level → `RuntimeError: ... attached to a different loop` / `InterfaceError: another operation is in progress` → worker tạo engine riêng mỗi task, dispose sau. (Lỗi này đã xác minh: trước fix worker fail, sau fix `succeeded`.)
7. Celery CLI không nhận `:get_celery_app` function → tạo module `app.worker.celery_app.py`.
8. Windows host: `localhost:8001` trỏ IPv6 `[::1]` timeout 8s/conn → dùng `127.0.0.1`. (Môi trường, không phải bug app.)

### Chưa làm / giới hạn
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Auth JWT/OAuth | NOT IMPLEMENTED — demo user qua header `X-User-Id` |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Alembic migration | NOT IMPLEMENTED — dùng `create_all` (đủ cho slice này; migration cần khi schema ổn định) |
| Content versioning nâng cao (regenerate giữ attempts) | NOT IMPLEMENTED — contentVersion đã có trong schema |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process |
| HTTPS/deploy production | NOT IMPLEMENTED — local only |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic. Nhãn "AI" chỉ đúng khi bật adapter thật.
- Không kiểm chứng giả thuyết RAG hay thuật toán backend của hệ thống được phân tích — chỉ tham khảo hình thái nghiệp vụ (interview 5 câu, proposal, poll generation, batch attempts) từ 2 báo cáo REA.
