# 06 — Authentication, Authorization & Security Specification

**Trạng thái:** Auth core báo cáo đã được TESTED; hardening production/P3/P4 còn PROPOSAL.

## 1. Existing authenticated session (reported)

- `POST /v1/auth/register`, `/login`, `/logout`, `GET /v1/me`.
- Password hash **Argon2id**, không plaintext.
- JWT HS256 qua **HttpOnly cookie**, kiểm tra `iss`, `aud`, `exp`; frontend `credentials: include`.
- CSRF double-submit cho mutating requests, frontend gửi CSRF header lấy từ token cookie hợp lệ.
- `X-User-Id` demo mode chỉ khi **`ALLOW_DEMO_HEADER=true` và environment development**; compose mặc định false; tuyệt đối không bật ở staging/prod.
- Login/register rate limit báo cáo 10/phút, logout 30/phút **in-memory per-process**. Không coi đây là distributed rate limiting.
- Token TTL 7 ngày theo nhật ký giai đoạn P0.5, chưa có refresh token/rotation.

## 2. Authorization rules

| ID | Resource | Quy tắc |
|---|---|---|
| AUTH-001 | Course, proposal, interview, generation | Owner được xác định từ auth, JOIN DB; client không thể chọn userId khác |
| AUTH-002 | Unit/lesson/attempt | Resolve qua course; `lessonId` chỉ là lookup key, không cấp quyền |
| AUTH-003 | Tutor thread/message | User sở hữu course **và** thread/lesson, `blockIndex` hợp lệ; scope tool call từng lần |
| AUTH-004 | Source/chunk/citation | Owner của source/lesson hoặc explicit grant được thiết kế; không được cite chunk user khác |
| AUTH-005 | Cross-user | Trả 404 với resource không có quyền nhằm giảm existence leak; không leak cached UI |

Admin/support access chưa được thiết kế, nên **không** thêm backdoor/impersonation.

## 3. Input & prompt safety

- Pydantic validate type/length/allowed enums; reject extra mutation fields nguy hiểm (`correct`, `status`, `ownerId`).
- Kiểm tra IDs theo parser có prefix, giới hạn `contextRef.blockIndex`, JSON size, title, topic, message lengths.
- LLM user input, retrieved PDF/web, provider tool outputs là **untrusted data**; dùng delimiting, tool allowlist, schema validation, deny arbitrary shell/URL/database query.
- Không cho user nhập arbitrary LLM base URL gây SSRF từ backend. Provider endpoint chỉ qua server env allowlist; kiểm tra host/TLS trước bật production.
- Quiz answer keys chỉ tồn tại private storage + post-submit policy; error messages không lộ đáp án câu khác.

## 4. PDF and URL safety (P4)

- Upload giới hạn byte/pages/time; verify magic/MIME, quarantine/sandbox parser, private object key, chống zip bombs/corrupt files.
- URL fetch (sau PDF): HTTPS policy, chặn localhost, RFC1918/link-local/metadata IP, DNS rebinding, redirects về địa chỉ nội bộ, kích thước/timeouts; tuân thủ quyền truy cập/robots/legal constraints.
- Không dùng vector search thiếu `owner_id` và `course_id/source_id` filter; kiểm thử cross-tenant ở query layer.

## 5. Secrets and privacy

- Keys JWT/provider/storage chỉ server environment/secret manager, không commit `.env`, không đưa `NEXT_PUBLIC_*` hoặc React bundle.
- Log metadata kỹ thuật: requestId, jobId, provider/model/promptVersion/tokens/latency/errorCode, **không** API key, cookie, raw prompt, raw PDF content hay full user text.
- Trước khi bật real provider: phê duyệt nhà cung cấp, model, dữ liệu gửi ra ngoài, ngân sách và mục đích; smoke test 3 requests trước đây **không phải** blanket approval.
- Chưa chốt retention/deletion/export policy; phải thiết kế trước public launch (P6) và mô tả bên điều khoản riêng tư.
- Chưa khẳng định phù hợp tiêu chuẩn pháp lý/pen-test nếu chưa kiểm chứng.

## 6. Abuse controls

- Quota request/tokens/job concurrency theo user, server-side transaction hoặc Redis/DB với race-safe behavior.
- Bounded retries/backoff, max tool iterations, timeout, cancel; tránh cost multiplication do retry/job redelivery.
- Rate limit distributed (Redis) trước nhiều replicas, với IP trust proxy policy rõ ràng.
- Không trả chính xác chi tiết cấu hình lỗi provider cho người dùng ngoài mã an toàn.

## 7. Security acceptance tests

- JWT giả/hết hạn/wrong issuer/wrong audience → 401; CSRF thiếu ở POST → 403; user B GET course/lesson/proposal/job A → 404.
- `X-User-Id` giả không cho đăng nhập khi demo header disabled; logout/login user khác xoá cache đúng.
- GET lesson không có đáp án/solution trước submit; forged quiz score ignored/rejected; duplicate attempt không nhân XP.
- Tutor contextRef giả/lesson owner khác/chunk owner khác bị từ chối, tool không chạy.
- PDF overlimit/malicious/URL SSRF/private DNS redirects bị block; citation không thể tham chiếu chunk không sở hữu.
- Log scanner không thấy cookie/JWT/API key/raw student input.
