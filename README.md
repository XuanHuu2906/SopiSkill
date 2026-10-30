# AI Learning Platform

Nền tảng học tập dùng AI: biến chủ đề thành khóa học có cấu trúc (phỏng vấn → proposal → generation) kèm bài học tương tác và chấm điểm tự động.

> Xây dựng độc lập, tham khảo phát hiện hành vi/giao thức từ hai báo cáo phân tích (`polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md`). Không sao chép mã nguồn hay tài sản của hệ thống được phân tích.

## Kiến trúc

- **Frontend:** Next.js 15 + TypeScript + TanStack Query
- **Backend:** FastAPI + Python 3.13 + SQLAlchemy (async) + Alembic
- **DB:** PostgreSQL 16 (pgvector khi triển khai RAG)
- **Background:** Redis + Celery
- **LLM:** Provider abstraction — MockProvider (mặc định, deterministic) / adapter thật qua env

Chi tiết: `docs/architecture.md`, `docs/database-design.md`.

## Chạy local (Docker Compose)

```bash
cp .env.example .env
# BẮT BUỘC: sinh JWT secret
python -c "import secrets; print(secrets.token_urlsafe(48))"   # dán vào JWT_SECRET trong .env
docker compose up --build -d
```

- Frontend: http://localhost:3000 (truy cập bằng `127.0.0.1` nếu `localhost` chậm trên Windows)
- Backend API: http://localhost:8001 (docs: `/docs`)
- PostgreSQL host: port **5433** (tránh xung đột PostgreSQL local), Redis: 6379
- **Auth bắt buộc:** mở `/login` để đăng ký/đăng nhập (email + mật khẩu ≥ 8 ký tự). Session bằng HttpOnly cookie.
- Demo header `X-User-Id` **mặc định tắt** — chỉ bật bằng `ALLOW_DEMO_HEADER=true` + `ENV=development` cho local.

> Lưu ý Windows: `localhost` có thể ưu tiên IPv6 `[::1]` gây chậm ~8s/request khi truy cập port do Docker publish. Dùng `http://127.0.0.1:8001` / `http://127.0.0.1:3000`.

## Chạy local (không Docker)

```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
# cần PostgreSQL + Redis đang chạy, hoặc dùng chế độ fallback:
uvicorn app.main:app --reload --port 8000

# Worker (nếu có Redis)
celery -A app.worker.celery_app worker --loglevel=info --pool=solo

# Frontend
cd frontend
npm install
npm run dev
```

Backend có **fallback mode**: nếu `REDIS_URL` không cấu hình/không kết nối được, generation task chạy inline trong request thread (vẫn bất đồng bộ về mặt trạng thái job — client vẫn poll).

## Luồng dùng thử

1. Mở http://localhost:3000/login → đăng ký tài khoản (email + mật khẩu).
2. Nhập chủ đề, ví dụ "Python cho người mới".
3. Trả lời 5 câu phỏng vấn.
4. Xem proposal → Approve.
5. Màn hình generating tự poll mỗi 2s → khóa học sẵn sàng.
6. Mở bài học → làm quiz → xem điểm + XP.
7. Tải lại trang / đăng nhập lại — dữ liệu vẫn còn (lưu DB theo user).

## Kiểm thử

```bash
cd backend
pytest -v

# E2E acceptance (cần Docker stack đang chạy; mặc định http://127.0.0.1:8001)
E2E_BASE=http://127.0.0.1:8001 python e2e_acceptance.py
```

Kết quả hiện tại: **119 unit+integration tests pass (+6 PostgreSQL race tests riêng); 35/35 E2E acceptance pass trên Docker Compose stack**. Mock provider vẫn là mặc định. Adapter LLM thật (OpenAI-compatible) có **28 mocked tests** và đã smoke test thật 3 request qua Deploy.com/DeepSeek (xem `docs/llm-provider.md`); tự động hoá real-provider trong CI vẫn **BLOCKED**. Chi tiết: `docs/development-progress.md`, `docs/llm-provider.md`.

## Alembic migration

- Backend container tự chạy `alembic upgrade head` trước khi start (idempotent).
- DB cũ tạo bằng `create_all()`: xem runbook `docs/migration-runbook.md` (backup → so khớp schema → stamp → upgrade, không mất dữ liệu).
- Tạo migration mới: `cd backend && alembic revision --autogenerate -m "..."` (kiểm tra lại trước khi chạy).

## API chính (v1)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/v1/auth/register` | Đăng ký `{email, password}` → 201 + session cookie |
| POST | `/v1/auth/login` | Đăng nhập → session cookie (HttpOnly) |
| POST | `/v1/auth/logout` | Đăng xuất (cần CSRF) |
| GET | `/v1/auth/me` | User hiện tại (401 nếu chưa đăng nhập) |
| POST | `/v1/courses` | Tạo course `{topic, clientCourseId}` (idempotent, cần CSRF) |
| POST | `/v1/courses/{id}/interview/answer` | Trả lời câu `{position, answer}` (0..4) |
| GET | `/v1/courses/{id}/proposal` | Proposal hiện tại |
| POST | `/v1/courses/{id}/approve` | Duyệt → tạo generation job |
| GET | `/v1/courses/{id}/generation` | Trạng thái job (poll 2s) |
| POST | `/v1/courses/{id}/retry` | Thử sinh lại |
| GET | `/v1/courses` | **Dashboard**: danh sách course của chính user (limit/offset, tiến độ, resume) |
| GET | `/v1/courses/{id}` | Course + path |
| GET | `/v1/lessons/{id}` | **Public blocks** (không có answer key; order/match trả id đã shuffle) |
| POST | `/v1/lessons/{id}/attempts` | Nộp quiz — chấm deterministic từ private key trong DB; idempotent theo `clientAttemptId` |

## Trạng thái triển khai

Xem `docs/development-progress.md`. Tóm tắt: Course Generator + Lesson Engine + **Auth (JWT/Argon2id/CSRF)** + **Alembic migration** **IMPLEMENTED + TESTED**; Tutor/RAG **NOT IMPLEMENTED** (thiết kế có); Mock provider **không phải AI thật**.

## Tài liệu

- `docs/architecture.md` — kiến trúc và luồng nghiệp vụ
- `docs/database-design.md` — schema PostgreSQL
- `docs/migration-runbook.md` — runbook chuyển DB cũ sang Alembic
- `docs/implementation-plan.md` — kế hoạch slice
- `docs/development-progress.md` — nhật ký tiến độ + giới hạn
- `docs/llm-provider.md` — cấu hình provider LLM, taxonomy lỗi, rollback về mock
