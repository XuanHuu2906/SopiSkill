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
docker compose up --build
```

- Frontend: http://localhost:3000 (truy cập bằng `127.0.0.1` nếu `localhost` chậm trên Windows)
- Backend API: http://localhost:8001 (docs: `/docs`)
- PostgreSQL host: port **5433** (tránh xung đột PostgreSQL local), Redis: 6379
- Demo user: frontend tự sinh `X-User-Id` và lưu localStorage.

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

1. Mở http://localhost:3000 → nhập chủ đề, ví dụ "Python cho người mới".
2. Trả lời 5 câu phỏng vấn.
3. Xem proposal → Approve.
4. Màn hình generating tự poll mỗi 2s → khóa học sẵn sàng.
5. Mở bài học → làm quiz → xem điểm + XP.
6. Tải lại trang — dữ liệu vẫn còn (lưu DB).

## Kiểm thử

```bash
cd backend
pytest -v

# E2E acceptance (cần backend đang chạy; mặc định http://127.0.0.1:8001)
E2E_BASE=http://127.0.0.1:8001 python e2e_acceptance.py
```

Kết quả hiện tại: **20/20 unit+integration tests pass; 16/16 E2E acceptance pass** (cả local uvicorn lẫn Docker Compose stack với Celery). Chi tiết: `docs/development-progress.md`.

## API chính (v1)

| Method | Path | Mô tả |
|---|---|---|
| POST | `/v1/courses` | Tạo course `{topic, clientCourseId}` (idempotent) |
| POST | `/v1/courses/{id}/interview/answer` | Trả lời câu `{position, answer}` (0..4) |
| GET | `/v1/courses/{id}/proposal` | Proposal hiện tại |
| POST | `/v1/courses/{id}/approve` | Duyệt → tạo generation job |
| GET | `/v1/courses/{id}/generation` | Trạng thái job (poll 2s) |
| POST | `/v1/courses/{id}/retry` | Thử sinh lại |
| GET | `/v1/courses/{id}` | Course + path |
| GET | `/v1/lessons/{id}` | Blocks đầy đủ |
| POST | `/v1/lessons/{id}/attempts` | Nộp kết quả quiz (chấm server-side) |

## Trạng thái triển khai

Xem `docs/development-progress.md`. Tóm tắt: Course Generator + Lesson Engine **IMPLEMENTED**; Tutor/RAG **NOT IMPLEMENTED** (thiết kế có); Mock provider **không phải AI thật**.

## Tài liệu

- `docs/architecture.md` — kiến trúc và luồng nghiệp vụ
- `docs/database-design.md` — schema PostgreSQL
- `docs/implementation-plan.md` — kế hoạch slice
- `docs/development-progress.md` — nhật ký tiến độ + giới hạn
