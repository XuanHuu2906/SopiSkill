# 05 — HTTP API & Contract Policy

**Quy tắc:** Các route dưới mục 1 được **ghi nhận từ tài liệu dự án**, không phải OpenAPI đã kiểm tra ở HEAD. Ví dụ payload mục 2–4 là **PROPOSAL** nếu chưa có chứng cứ source; agent phải so với Pydantic/OpenAPI hiện tại trước khi tạo hoặc sửa.

## 1. Endpoint inventory đã được ghi nhận

| Method & path | Ý nghĩa | Auth / trạng thái |
|---|---|---|
| `POST /v1/auth/register` | Đăng ký | public; rate limit, CSRF policy xem code |
| `POST /v1/auth/login` | Đăng nhập, phát HttpOnly JWT cookie | public; rate limit |
| `POST /v1/auth/logout` | Đăng xuất | session/cookie, CSRF |
| `GET /v1/me` | Profile identity + XP | authenticated |
| `GET /v1/courses?limit=&offset=` | Danh sách course của user | authenticated, limit 1..50; offset ≥0 |
| `POST /v1/courses` | Tạo course từ topic (idempotent) | authenticated; CSRF |
| `POST /v1/courses/{courseId}/interview/answer` | Lưu một câu trả lời | owner, CSRF |
| `GET /v1/courses/{courseId}/proposal` | Đề cương mới nhất | owner |
| `POST /v1/courses/{courseId}/approve` | Approve proposal + tạo generation job | owner, CSRF |
| `GET /v1/courses/{courseId}/generation` | Status/stage/job progress | owner |
| `POST /v1/courses/{courseId}/retry` | Retry tạo job mới | owner, CSRF |
| `GET /v1/courses/{courseId}` | Chi tiết course/units/lessons/progress | owner |
| `GET /v1/lessons/{lessonId}` | Public lesson blocks | owner |
| `POST /v1/lessons/{lessonId}/attempts` | Chấm và ghi attempt | owner, CSRF |
| `GET /health` | Liveness | local health |

`GET /v1/courses` không nhận `userId` từ client để tăng quyền. Tất cả GET details phải dùng identity từ session và kiểm tra owner; cross-owner trả 404 theo hành vi đã được báo cáo.

## 2. Core request/response shapes cần xác nhận theo code

### Create course (illustrative, theo architecture)

```json
{"topic":"Python cho người mới","clientCourseId":"uuid-from-client"}
```

Response về mặt nghiệp vụ: course ID, status `interview`, danh sách/đầu mối lấy interview questions. **Không coi field names sau là API chắc chắn** cho đến khi so với Pydantic output.

### Generation status (conceptual)

```json
{"status":"running","stage":"lessons","lessonsDone":2,"lessonsTotal":4,"attempts":1,"dispatched":true,"lastErrorCode":null}
```

Job status `queued/running/ready/failed`; response chỉ trả tiến độ thực (không hiển thị tỷ lệ giả). Poll 2s là hành vi frontend, không phải nghĩa vụ backend realtime.

### Attempt submission (conceptual)

```json
{
  "clientAttemptId":"attempt-uuid",
  "contentVersion":1,
  "results":[{"blockIndex":1,"type":"mc","answer":2}]
}
```

**Cần đối chiếu** field `blockIndex`/`index`, mapping `order/match` theo public block IDs, answer types và response `solution`. Server bỏ qua hoặc reject mọi trường `correct` do client gửi; response 422 nếu invalid schema, 409 nếu stale version.

## 3. Contract cho thay đổi P2.1 (PROPOSED)

Đề xuất **không tạo endpoint mới** khi có thể dùng đường hiện có. Thêm optional versioned response fields từ `GET /proposal`: `learnerProfileSummary` (non-sensitive), `curriculumGraph` (nodes/edges), `schemaVersion`, `generationEstimate` nếu có cách tính. Lưu ý:

- Legacy proposals không có graph vẫn hiển thị; server phải support version cũ trong quá trình rollout.
- Editing/revising proposal là yêu cầu product chưa chốt: **không tự tạo** `PUT /proposal` trước khi thống nhất version conflict/idempotency/approval resets.
- Approve chỉ chấp nhận phiên bản proposal hiện hành, không phê duyệt nội dung đã đổi sau khi user xem.

## 4. New endpoints — PROPOSED ONLY

### Tutor P3

| Method & path | Request | Response / note |
|---|---|---|
| `POST /v1/courses/{courseId}/tutor/messages` | `{clientMessageId,threadId?,text,contextRef:{lessonId,blockIndex}}` | `text/event-stream` (`delta`,`done`,`error`) |
| `GET /v1/courses/{courseId}/tutor/threads` | pagination params | owner-scoped list |
| `GET /v1/courses/{courseId}/tutor/threads/{threadId}` | path | thread/messages, no cross-owner data |
| `POST /v1/courses/{courseId}/tutor/messages/{messageId}/stop` | optional reason | best-effort cancel, P3.1 |
| `GET /v1/tutor/usage` | none | user allowance, P3.1; có thể scope theo course nếu cần |

### Source & RAG P4

| Method & path | Ý nghĩa |
|---|---|
| `POST /v1/sources` | Upload PDF (multipart/stream) và tạo ingestion job |
| `GET /v1/sources` | Danh sách private sources của user |
| `GET /v1/sources/{sourceId}` | Status/metadata, owner-scoped |
| `DELETE /v1/sources/{sourceId}` | Soft-delete/revocation semantics phải chốt |
| `GET /v1/sources/{sourceId}/pages/{pageNumber}` | Authorized source/page access qua private storage, nếu thực sự cần |

Không đặt search endpoint public cho raw chunks. API trả citation pointers **đã validate** theo user/course/source.

## 5. HTTP semantics & errors

- `201` create resource mới; `200` read/retry replay; `202` job accepted; `400/422` bad input; `401` unauthenticated; `403` CSRF/forbidden action; `404` not found hoặc không sở hữu; `409` conflict (`JOB_ALREADY_ACTIVE`, stale content version, proposal-version mismatch); `429` quota/rate limit; `503` provider/broker unavailable tùy policy.
- Tài liệu `llm-provider.md` đã ghi `503 PROVIDER_NOT_CONFIGURED` khi provider lạ/thiếu key/base URL/model, **không mock fallback**.
- **Proposed** normalized error envelope cho API mới:

```json
{"error":{"code":"TUTOR_LIMIT_REACHED","message":"Đã hết lượt hỏi trong kỳ này.","requestId":"req_abc"}}
```

Trước khi áp dụng, audit error envelope hiện hữu và giữ backward compatibility; không thay global format chỉ vì ví dụ này.

## 6. Idempotency and concurrency

| Operation | Key | Quy tắc |
|---|---|---|
| Create course | `(userId, clientCourseId)` | Retry trả lại cùng course; không sinh course mới |
| Submit attempt | `(userId, lessonId, clientAttemptId)` | Same ID → same recorded result/reward; unique DB |
| Approve | `(courseId, activeJob)` + pinned proposal | Concurrent approve không tạo 2 active jobs; 409 hoặc safe replay theo current contract |
| Generation job | `generationJobId`, atomic claim + lease | Redelivery no-op; effects upsert theo stable ordering |
| Tutor message P3 | `(userId, threadId, clientMessageId)` | Không tạo user message/LLM call trùng |
| Source ingest P4 | `(sourceId, checksum, pipelineVersion)` | Retry không nhân chunks |

## 7. API evolution policy

- OpenAPI/Pydantic/TS client đều cập nhật trong cùng PR khi thay contract.
- List pagination stable ordering + capped limit; filter user scope phía DB.
- Không cung cấp raw error từ provider, secrets, prompt hay stacktrace; dùng requestId tương quan.
- Dùng `429 Retry-After` cho rate-limit nếu có cơ sở, không gửi mốc thời gian giả.
- Mọi mutating endpoint dùng cookie auth phải qua CSRF theo implementation hiện hữu.
