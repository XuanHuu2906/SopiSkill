# Development Progress

> Ghi nhận trạng thái thực tế. Quy ước: **IMPLEMENTED** (có code) / **TESTED** (đã chạy và pass) / **NOT TESTED** (chưa chạy).

## 2026-10-30 (buổi 3) — P0.5.1 Auth & Migration Stabilization

### Sửa lỗi + hardening
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Hằng số HTTP sai `HTTP_422_UNAUTHORIZED` → `HTTP_422_UNPROCESSABLE_ENTITY` | IMPLEMENTED + TESTED | user_service.py; test_invalid_email_returns_422_not_401 (422 + không có WWW-Authenticate header) |
| **Bug rate limit dead-code:** `bucket.append(now)` nằm trong nhánh `if` sau `raise` → request hợp lệ không bao giờ được ghi bucket → rate limit không bao giờ block | IMPLEMENTED + TESTED | limits.py fix; test_login_rate_limited: 10× 401 rồi lần 11 → 429; test_register_rate_limited tương tự |
| Rate limit cho /auth/login (10/phút), /auth/register (10/phút), /auth/logout (30/phút) | IMPLEMENTED + TESTED | auth.py; 2 test trên |
| Rate-limit buckets clear giữa tests (fixture) | IMPLEMENTED + TESTED | conftest.py client fixture; test_rate_limit_buckets_reset_between_tests → 401 (không 429) |
| Auth resolution: deleted user + token hợp lệ → 401 USER_NOT_FOUND (không crash) | TESTED | test_valid_token_with_deleted_user_returns_401 |
| User scope trong session: /me trả đúng user đăng nhập, không leak giữa users | TESTED | test_me_after_login_same_user_no_crossuser_leak |

### Kiểm chứng migration/rollback (không đụng dữ liệu chính)
| Kiểm chứng | Kết quả |
|---|---|
| SQLite: upgrade head → downgrade base → upgrade head → current | 0002_auth_columns (head) — pass |
| PostgreSQL **temp DB riêng** `alembic_verify_tmp` (trong container db, KHÔNG phải DB chính): upgrade head → \d users có email+password_hash+uq_users_email → downgrade base → chỉ còn alembic_version | pass; temp DB đã DROP sau verify |
| DB chính `ailp`: 20 users giữ nguyên, không volume bị xóa | XÁC MINH sau verify |

### Regression P0.5.1 (Docker stack, code mới)
1. `pytest -q` → **40/40 passed** (33 cũ + 7 mới).
2. `npm run build` → ✓ Compiled successfully, 9 static pages.
3. `docker compose up -d --build backend worker` → started; `/health` → ok.
4. `e2e_acceptance.py` → **21/21 PASS**.

### Ràng buộc đã tôn trọng
- Migration 0001/0002 đã deploy **không bị sửa hash/content** — chỉ verify.
- Không xóa volume `reverseengineer_pgdata`, không mất dữ liệu (backup vẫn còn từ P0.5).
- Không tích hợp LLM thật / Tutor / RAG.

### Giới hạn còn lại
- Rate limit vẫn in-memory per-process (restart mất bucket) — distributed Redis để sau.
- `HTTP_422_UNPROCESSABLE_ENTITY` là deprecated alias trong Starlette mới (vẫn hoạt động); cân nhắc đổi sang `HTTP_422_UNPROCESSABLE_CONTENT` khi bump dependency.
- WEAK_PASSWORD của service layer hiện không thể trigger qua HTTP (Pydantic schema chặn trước với cùng điều kiện) — được test trực tiếp ở service level.

---

## 2026-10-30 (buổi 2) — P0.5 Authentication + Alembic Migration

### Backend — Auth (JWT HttpOnly cookie + Argon2id + CSRF)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| POST /v1/auth/register, /login, /logout, GET /me | IMPLEMENTED + TESTED | E2E steps 0, 0b, 0d pass; pytest test_auth.py 13/13 |
| Argon2id password hashing (không plaintext) | IMPLEMENTED + TESTED | test_register_login_me_flow assert `$argon2id$` prefix |
| JWT HS256 + iss/aud/exp validation, secret server-side only | IMPLEMENTED + TESTED | test_expired_token_rejected, test_wrong_issuer_or_audience_rejected, test_tampered_token_rejected |
| get_current_user dependency (user ID từ token, không từ client header) | IMPLEMENTED + TESTED | test_fake_x_user_id_header_does_not_authenticate → 401 |
| X-User-Id demo header chỉ khi ALLOW_DEMO_HEADER=true + ENV=development | IMPLEMENTED + TESTED | compose default false; pytest chạy với false |
| CSRF double-submit cho mutating requests | IMPLEMENTED + TESTED | test_csrf_missing_on_mutation_403; E2E step 0d → 403 |
| Cross-user access → 404 | IMPLEMENTED + TESTED | test_cross_user_access_denied; E2E B/B2 → 404 |
| Ownership + luồng học sau login/reload | IMPLEMENTED + TESTED | test_login_reload_and_continue; E2E step 9 pass |

### Backend — Alembic
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Alembic setup (env.py sync driver, alembic.ini) | IMPLEMENTED + TESTED | `alembic upgrade head` SQLite: 9 bảng tạo thành công |
| Migration 0001_initial (full schema, viết tay khớp models) | IMPLEMENTED + TESTED | upgrade head + downgrade base sạch (SQLite) |
| Migration 0002_auth_columns (idempotent, batch mode cho SQLite) | IMPLEMENTED + TESTED | cycle upgrade→downgrade→upgrade pass; chạy thật trên PostgreSQL DB cũ |
| Backend container chạy `alembic upgrade head` trước start | IMPLEMENTED + TESTED | Dockerfile CMD; logs không lỗi DuplicateTable sau rebuild |
| create_all chỉ còn cho SQLite (dev/test) | IMPLEMENTED + TESTED | pytest 33/33 vẫn pass |
| Migration DB cũ không mất dữ liệu | IMPLEMENTED + TESTED | backup `backup_pre_migration_20261030_221411.sql`; stamp 0001 + upgrade → 16 users + 16 courses giữ nguyên; runbook `docs/migration-runbook.md` |

### Frontend
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| /login page (đăng nhập + đăng ký, toggle mode) | IMPLEMENTED + TESTED | `npm run build` pass; HTTP 200 trên Docker |
| Session bằng HttpOnly cookie (KHÔNG lưu token localStorage) | IMPLEMENTED + TESTED | api.ts `credentials: "include"`; không còn getUserId() |
| CSRF header tự gửi từ csrf_token cookie | IMPLEMENTED + TESTED | api.ts getCsrfToken(); E2E 21/21 pass |
| useAuth + AuthBar (hiển thị user + XP + logout) | IMPLEMENTED | providers.tsx |
| Trang chủ yêu cầu đăng nhập trước khi tạo course | IMPLEMENTED | page.tsx render /login link khi chưa auth |

### Kiểm chứng chạy thật (2026-10-30, Docker Compose full stack)
1. `pytest -q` → **33/33 passed** (20 cũ viết lại cho auth + 13 auth mới).
2. `npm run build` → **thành công** (9 routes, có /login).
3. `docker compose up --build -d` → 5/5 containers Up (db healthy, redis healthy).
4. `python e2e_acceptance.py` → **21/21 PASS** (đã cập nhật: đăng ký/đăng nhập, CSRF, unauth 401, token giả 401, cross-user 404, generation + quiz + reload).
5. Worker: `Task ... succeeded in 0.54s`, 0 Traceback.
6. DB xác minh: users có `password_hash` (argon2id), attempts + xp_events được ghi; dữ liệu cũ 16 users/16 courses giữ nguyên sau migration.

### Các lỗi đã gặp và sửa trong P0.5
1. Alembic CLI autogenerate không chạy được với URL async + greenlet → viết migration tay từ `Base.metadata` (render qua autogenerate API).
2. Migration 0002 duplicate column trên DB mới → chuyển sang idempotent check bằng SQLAlchemy inspector.
3. SQLite không hỗ trợ ALTER ADD/DROP CONSTRAINT → `batch_alter_table` (copy-and-move) khi dialect là sqlite.
4. httpx cookie per-request deprecated warnings — không ảnh hưởng kết quả.
5. Image cũ không chứa 0002 (build trước khi tạo file) → rebuild backend rồi upgrade.

### Chưa làm / giới hạn (cập nhật)
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Refresh token / token rotation | NOT IMPLEMENTED — access token TTL 7 ngày, đủ cho slice hiện tại |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process, identity theo user id |
| HTTPS/deploy production | NOT IMPLEMENTED — local only (COOKIE_SECURE cần bật khi có HTTPS) |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic.
- Token hết hạn sẽ bị từ chối (TESTED); chưa có refresh flow — user đăng nhập lại khi hết hạn.
- Chưa kiểm chứng security ở mức pen-test — chỉ các test case tự viết.

---

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
