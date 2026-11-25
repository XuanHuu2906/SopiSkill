# Runbook P6.2 — Operations, Hardening & Controlled Feature Activation (Wave 3)

> Tài liệu vận hành cho các cổng **Wave 3 / P6.2**: Redis distributed rate-limiter, readiness probe `/ready`, backup & restore drill PostgreSQL, TLS/CSP/HSTS staging, và quy trình kích hoạt có kiểm soát (`TUTOR_ENABLED`, `P50_ENABLED`, `RAG_ENABLED`).

---

## 1. Distributed Rate-Limiter (`M1-SEC-LIMITER`)

- Module: `backend/app/core/limits.py` dùng **1 Lua script sliding-window nguyên tử trên Redis** (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` + `PEXPIRE`), trả header `Retry-After` khi vượt ngưỡng `429 RATE_LIMITED`.
- Chế độ cấu hình:
  - `RATE_LIMIT_BACKEND=auto` (mặc định): tự dùng Redis khi `REDIS_URL` được khai báo, fallback in-memory khi chạy SQLite/unit test không có Redis.
  - `RATE_LIMIT_BACKEND=redis` + `RATE_LIMIT_FAIL_CLOSED=true` (**khuyến nghị cho staging/production**): khi Redis mất kết nối, API trả `503 RATE_LIMITER_UNAVAILABLE` thay vì âm thầm giảm về giới hạn per-process.
  - `TRUST_PROXY_HEADERS=false` (mặc định): **không** tin `X-Forwarded-For` cho đến khi reverse proxy tin cậy đứng trước API đã lọc/ghi đè header này.

---

## 2. Liveness `/health` vs Deep Readiness `/ready` (`OPS-005`)

- `GET /health`: trả `200` nhanh (`{"status":"ok","env":...,"provider":...}`), dùng cho liveness probe.
- `GET /ready`: kiểm tra thật:
  1. `database`: `SELECT 1` trong giới hạn `READINESS_TIMEOUT_SECONDS` (mặc định `2.0s`).
  2. `redis`: `PING` (khi `REDIS_URL` được cấu hình; nếu không trả `"not_configured"`).
  3. `config`: chạy `app.core.activation.check_activation_readiness()` — kiểm tra các ràng buộc production & quota Tutor.
  - Trả `200 {"status":"ready",...}` khi mọi dependency bắt buộc khỏe, hoặc `503 {"status":"not_ready",...}` (không bao giờ lộ DSN/mật khẩu/traceback).
- Pre-flight check trước khi mở traffic:
  ```bash
  cd backend && python -m app.core.activation
  ```

---

## 3. Controlled Activation cho AI Tutor & P5.0 (Decision D7)

Mọi cờ tính năng trong `backend/app/core/config.py` và `docker-compose.yml` giữ **mặc định OFF**.

### Kích hoạt qua Docker Compose Override (`docker-compose.wave3.yml`)
File `docker-compose.wave3.yml` bật sẵn profile an toàn:
- `RATE_LIMIT_BACKEND=redis`, `RATE_LIMIT_FAIL_CLOSED=true`
- `TUTOR_ENABLED=true` kèm trần cứng mặc định:
  - `TUTOR_MESSAGES_PER_DAY=30`
  - `TUTOR_TOKENS_PER_DAY=100000`
  - `TUTOR_MAX_CONCURRENT_STREAMS=2`
- `P50_ENABLED=true`
- `RAG_ENABLED=false` *(giữ TẮT cho tới khi cấu hình & benchmark semantic embedding thật)*

```bash
# 1. Khởi chạy stack với Wave 3 override
docker compose -f docker-compose.yml -f docker-compose.wave3.yml up -d --build

# 2. Chạy migration (đảm bảo đã áp 0017_p1_course_language)
docker compose exec backend alembic upgrade head

# 3. Kiểm tra pre-flight guardrails và readiness
docker compose exec backend python -m app.core.activation
curl -fsS http://localhost:8001/ready
```

> **Điều kiện bắt buộc trước khi bật `RAG_ENABLED=true` ở production:**
> Chuyển `EMBEDDING_PROVIDER=openai_compatible` với model semantic thật, tái chạy `python -m evals.rag_eval` và hiệu chỉnh lại `RAG_MIN_LEXICAL_SCORE` / `RAG_VECTOR_ONLY_MIN_SIMILARITY` theo corpus thật (không chạy RAG production bằng `hashing` baseline).

---

## 4. Backup & Restore Drill PostgreSQL (`OPS-007`)

Công cụ: `backend/scripts/pg_backup_restore.py` (dùng `PGPASSWORD` qua env con, không ghi mật khẩu vào argv hay `.meta.json`).

### Quy trình backup định kỳ (không gây gián đoạn)
```bash
POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=ailp POSTGRES_DB=ailp \
  POSTGRES_PASSWORD=<secret> \
  python backend/scripts/pg_backup_restore.py backup --output-dir ./backups
```
Kết quả tạo 3 file: `<db>_<UTC>.dump`, `<file>.sha256`, `<file>.meta.json`.

### Quy trình verify checksum + header PGDMP
```bash
python backend/scripts/pg_backup_restore.py verify --backup ./backups/<file>.dump
```

### Quy trình diễn tập khôi phục trên DB tách biệt (`restore-drill`)
```bash
# 1. Tạo DB scratch tách biệt (TUYỆT ĐỐI không dùng DB chính)
docker compose exec db createdb -U ailp ailp_restore_drill

# 2. Chạy restore-drill (tự verify SHA-256 + pg_restore + kiểm đếm bảng/alembic_version)
POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=ailp \
  POSTGRES_PASSWORD=<secret> \
  python backend/scripts/pg_backup_restore.py restore-drill \
    --backup ./backups/<file>.dump \
    --target-db ailp_restore_drill

# 3. Dọn DB scratch sau khi đã ghi nhận bằng chứng
docker compose exec db dropdb -U ailp ailp_restore_drill
```

---

## 5. Staging / Production TLS, Cookie & Security Headers Checklist (`OPS-008`)

- **Backend & Frontend baseline headers** (đã tích hợp trong `backend/app/main.py` & `frontend/next.config.ts`):
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (tự bật khi `COOKIE_SECURE=true` hoặc `ENV=production`).
- **Biến môi trường bắt buộc ở `ENV=production`:**
  - `JWT_SECRET` (≥ 32 ký tự ngẫu nhiên) và `LESSON_SHUFFLE_SECRET` (hoặc dùng chung `JWT_SECRET`).
  - `COOKIE_SECURE=true`, `ALLOW_DEMO_HEADER=false`.
  - `CORS_ORIGINS=https://<staging-or-prod-domain>` (không wildcard `*`).
  - `TRUST_PROXY_HEADERS=true` chỉ khi Nginx/Caddy/ALB đứng trước ghi đè `X-Forwarded-For`.
- **Mẫu CSP tại Reverse Proxy (Nginx/Caddy) cho Next.js staging/prod:**
  ```text
  Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' https://<api-domain>; frame-ancestors 'none'; base-uri 'self'; form-action 'self'
  ```
  *(Khi nâng cấp nonce/strict-dynamic ở Next.js middleware, gỡ `'unsafe-inline'` khỏi `script-src`.)*
