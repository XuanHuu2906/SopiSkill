# 06 — Authentication, Authorization & Security Specification

**Trạng thái (`2026-11-22`):** Auth core, owner scoping, HMAC quiz shuffle (`P6.1`), SSRF/DNS-rebinding protection (`P4.2`), HMAC exposure tokens (`P5.2b`) và CI security gates (`P6.1`) đã **IMPLEMENTED · REPORTED TESTED**. Hardening production (`P6.2+`: distributed Redis rate-limit, refresh token/rotation, CSP/HSTS, retention/deletion) còn **PLANNED**.

## 1. Authenticated session (IMPLEMENTED)

- Endpoints: `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/auth/me` (`backend/app/api/v1/auth.py`).
- Password hash **Argon2id**, không lưu plaintext.
- JWT HS256 trong **HttpOnly cookie** (`SameSite=Lax`, `Secure` qua `COOKIE_SECURE`), kiểm tra `iss="sopiskill"`, `aud="sopiskill-web"`, `exp`; frontend gửi `credentials: "include"`.
- CSRF double-submit cookie/header bắt buộc cho mọi mutating endpoint (`verify_csrf`).
- `X-User-Id` demo header chỉ mở khi `ALLOW_DEMO_HEADER=true` ở non-prod; mặc định `false`.
- Token TTL mặc định **7 ngày** (`access_token_ttl_minutes = 10080`), chưa có refresh token rotation.
- **Rate-limit phân tán (`M1-SEC-LIMITER`, Wave 3):** `rate_limit()` trong `backend/app/core/limits.py` đã hỗ trợ **Redis atomic sliding-window Lua script** (`RATE_LIMIT_BACKEND=auto|redis|memory`, `RATE_LIMIT_FAIL_CLOSED=true` trả `503` khi Redis sập ở production, `TRUST_PROXY_HEADERS=false` mặc định) và trả header `Retry-After` khi `429`. Live test trên Redis container chờ bật Docker/staging.

## 2. Authorization rules (IMPLEMENTED)

| ID | Resource | Quy tắc server-side |
|---|---|---|
| AUTH-001 | Course, interview, proposal, generation, research-run | Owner resolve từ JWT session qua DB; client không thể chỉ định `userId` |
| AUTH-002 | Unit, lesson, attempt, mastery, learning-path, review-card | Resolve qua course/user sở hữu; `lessonId`/`cardId` chỉ là lookup key |
| AUTH-003 | Tutor thread, message, stop, usage, tool calls | User sở hữu course **và** thread/lesson, `blockIndex` trong biên public blocks |
| AUTH-004 | Source, document, chunk, RAG search, citation | Ownership filter nằm **ngay trong SQL** trước khi tính similarity; không thể cite chunk user khác |
| AUTH-005 | Cross-user access | Trả `404` để chống existence leak; frontend xóa sạch query cache theo `user.id + sessionEpoch` khi đổi tài khoản |

## 3. Input, Quiz Integrity & Prompt Safety (IMPLEMENTED)

- Pydantic v2 validate độ dài/kiểu/enum; đặt `extra="forbid"` ở các payload nhạy cảm (`TutorMessageRequest`, `AttemptAnswer`, `WebDocumentRequest`, `RagSearchRequest`, `RecommendationEventRequest`, `ResearchRequestIn`) và từ chối `bool` ở `AttemptAnswer.answer`.
- **Quiz answer-key isolation:** `public_block()` không bao giờ phát đáp án/solution trước submit; từ **P6.1**, seed shuffle của `order`/`match` ký bằng **HMAC (`LESSON_SHUFFLE_SECRET`, fallback `JWT_SECRET`)**, chấm dứt rủi ro client tự dựng lại hoán vị từ seed công khai.
- **Prompt & Tool safety:** nội dung người dùng, chunks nguồn và kết quả tool bọc delimiter tường minh (`<<<TOOL_BAT_DAU>>>`), đánh dấu dữ liệu không tin cậy; Tutor chỉ cho phép 3 tool read-only trong allowlist (`read_lesson`, `explain_deeper`, `read_source`), chặn tên tool lạ và tham số sai trước khi execute.
- **Recommendation token safety (`P5.2b`):** `learning-path` phát token ký HMAC (`jwt_secret`, TTL 900s), compare bằng constant-time; client không thể ghi khống `arm`/`propensity`/`contextHash`.

## 4. PDF, Web & arXiv Safety (IMPLEMENTED — P4.0/P4.2/P4.3)

- **PDF:** kiểm tra magic `%PDF-`, streaming byte limit (`20 MB`), giới hạn số trang (`300`), extract timeout (`120s`), lưu private key ngẫu nhiên trong MinIO/S3 (`STORAGE_NOT_CONFIGURED` nếu chưa cấu hình).
- **Web/arXiv (`P4.2`, mặc định TẮT):** chặn toàn bộ outbound nếu `WEB_INGEST_ENABLED=false` hoặc `WEB_INGEST_ALLOWED_HOSTS` rỗng; bắt buộc HTTPS port 443, không userinfo; chặn toàn bộ IP không global-unicast; `PinnedNetworkBackend` re-resolve ngay trong `connect_tcp` chống **DNS rebinding**; `follow_redirects=False` kiểm tra lại từng hop (max 3); tôn trọng `robots.txt` conservative; bắt buộc `userConfirmedRights=true`.
- **Giới hạn đã biết:** chưa có antivirus/malware scanner cho file tải lên; chưa có rate-limit distributed cho upload/fetch.

## 5. Secrets, CI Scanning & Privacy

- Secrets (`JWT_SECRET`, `LESSON_SHUFFLE_SECRET`, `LLM_API_KEY`, `EMBEDDING_API_KEY`, MinIO keys) chỉ nằm ở server env, không vào `NEXT_PUBLIC_*`, không ghi ra logs.
- **CI Security Gate (`P6.1`):** Bandit static scan (0 medium/high unannotated), `pip-audit` & `npm audit` chạy trong `.github/workflows/ci.yml`.
- **Quyết định còn mở trước public launch (`P6.2+`):** retention/deletion/export dữ liệu cá nhân (`DELETE /v1/me` chưa có), chính sách đồng thuận gửi dữ liệu tới real LLM provider, staging TLS/CSP/HSTS và distributed Redis rate limiter.

## 6. Security acceptance tests (REPORTED PASS)

- JWT giả/hết hạn/sai `iss`/`aud` → 401; thiếu CSRF → 403; cross-user A→B → 404 (đã kiểm chứng qua `test_auth.py`, `test_p30_tutor.py`, `test_p40_ingest.py`, `test_p41_rag.py`, `test_p50_mastery.py`, `test_p52_api.py`, và probes `S1–S8` trong audit `2026-11-04`).
- `GET /v1/lessons/{id}` 0 answer key leak trước submit; `bool` injection & smuggle field bị 422; duplicate attempt/tutor/review không nhân thưởng hoặc double-charge.
- SSRF/private IP/DNS rebinding/redirect tới nội bộ bị chặn trong `test_p42_web_ingest.py`.
