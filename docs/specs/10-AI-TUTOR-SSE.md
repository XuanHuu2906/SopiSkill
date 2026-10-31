# 10 — AI Tutor: Context Grounding, SSE, Tools & Usage

**Trạng thái:** **P3.0 = IMPLEMENTED + TESTED (mock streaming)**; P3.1 (tools/cancel/quota) vẫn **PROPOSAL**.

Đã có code: `tutor_threads`/`tutor_messages` (revision `0008_p30_tutor_core`), `POST .../tutor/messages` (SSE),
`GET .../tutor/threads[/{id}]`, provider `stream_tutor_reply` (mock deterministic + OpenAI-compatible SSE),
TutorPanel trong lesson. **Chưa** có: tool allowlist, endpoint stop server-side, `Last-Event-ID` replay, quota đầy đủ.
Sự thật đã kiểm chứng nằm ở `docs/development-progress.md` (mục `P3.0 AI Tutor Core`).

## 1. Scope & user goal

Người học đặt câu hỏi khi đang học lesson, nhận giải thích gắn đúng block, có lịch sử sau reload và quota rõ. Tutor ưu tiên **gợi mở từng bước**, đặt câu hỏi kiểm tra hiểu, không luôn đưa đáp án quiz đang làm; từ chối bịa citation hoặc giả vờ biết tài liệu.

## 2. Requirements

| ID | Yêu cầu | Phase |
|---|---|---|
| TUTOR-001 | Thread & messages lưu bền vững và owner-scoped | P3.0 |
| TUTOR-002 | `contextRef` gồm `lessonId`, `blockIndex`, được resolve từ DB qua course owner | P3.0 |
| TUTOR-003 | SSE `delta`, `done`, `error`, ordering/id rõ ràng, heartbeat | P3.0 |
| TUTOR-004 | `clientMessageId` unique, duplicate requests không sinh 2 messages/calls | P3.0 |
| TUTOR-005 | Lesson + bounded history grounding, chưa có source thì không cite | P3.0 |
| TUTOR-006 | Tool allowlist read-only, validate từng tool call, audit | P3.1 |
| TUTOR-007 | Stop/cancel best-effort với status server minh bạch | P3.1 |
| TUTOR-008 | Usage limits/rate limit, không gọi model khi quota hết | P3.1 |
| TUTOR-009 | Replay/resume chỉ nếu có persisted ordered event log | P3.1 optional |
| TUTOR-010 | Khi RAG ready, `read_source` có citation verified | Sau P4.1 |

## 3. Proposed API contract

```http
POST /v1/courses/{courseId}/tutor/messages
Cookie: <HttpOnly session>
X-CSRF-Token: <double-submit token>
Accept: text/event-stream
Content-Type: application/json

{
  "clientMessageId":"uuid",
  "threadId":null,
  "text":"Vì sao vòng lặp này dừng?",
  "contextRef":{"lessonId":"lsn_<id>","blockIndex":3}
}
```

- Server kiểm tra message text length/rate limits, course owner, lesson.course_id, block index valid, thread user/course match.
- **Không nhận** `systemPrompt`, `toolResults`, raw lesson content, ownerId hay user-supplied citations trong request.
- Response `Content-Type: text/event-stream` với ví dụ tại `examples/tutor-stream.proposed.sse`.
- Thread history `GET /v1/courses/{courseId}/tutor/threads/{threadId}`; user A→B 404.

## 4. Proposed SSE events

| Event | JSON data required | Semantics |
|---|---|---|
| `delta` | `streamId`, `messageId`, `seq`, `text` | Incremental text; seq tăng đơn điệu |
| `done` | `streamId`, `messageId`, `seq`, `finishReason`, `usage?` | Terminal success; final message persisted |
| `error` | `streamId`, `messageId?`, `seq`, `code`, `message`, `retryable` | Terminal failure, no raw exception |
| `heartbeat` | timestamp/empty payload | Keepalive; không chứa user content |
| `tool` (P3.1) | name, status, safe summary | Thông tin tool gọi, không gửi raw args bí mật |
| `confirm` (P3.1, nếu có hành động cần user) | action metadata | Chưa bật khi chỉ read-only tools |

**SSE frames** phải escape newlines đúng chuẩn, UTF-8, no-store, proxy buffering disabled ở path stream khi deploy.

## 5. Persistence & idempotency semantics

- Transaction tạo user message (`clientMessageId` unique) + pending assistant message, reserve quota **trước** provider call.
- Duplicate same id + message completed: trả kết quả đã lưu qua history hoặc một deterministic completed response theo contract được chọn; **không gọi LLM lần hai**.
- Duplicate while in progress: HTTP `409 MESSAGE_IN_PROGRESS` hoặc attach existing stream **chỉ khi thực sự có multiplexing**; P3 MVP chọn 409 + GET history để đơn giản và an toàn.
- Disconnect không tự tuyên bố cancel server-side; status pending/running được reconciliation; retry same id không sinh double charge.
- **MVP không hỗ trợ `Last-Event-ID` replay** khi chưa có event storage. Nếu client mạng mất giữa stream, hiển thị trạng thái gián đoạn, GET history sau completion; không hứa khôi phục byte-by-byte.

## 6. Tutor grounding & teaching rules

- Build context từ **server-owned** course, lesson title, current block, progress snapshot nếu cần, và số message history giới hạn.
- Không chuyển nguyên toàn bộ bài/hồ sơ sang provider nếu không cần; cap tokens và redact metadata.
- Answer nên: hỏi làm rõ nếu cần, gợi ý, giải thích theo mức học viên, ví dụ mới, check understanding. Không bịa học lực, không để user text override system/tools.
- Khi user hỏi không liên quan bài: phân biệt general knowledge với lesson-grounded; với RAG yêu cầu evidence thì nói không có evidence.

## 7. Tools P3.1

| Tool | Read-only contract | Authorization |
|---|---|---|
| `read_lesson` | Đọc lesson đã xác minh (public/pedagogical view) | course + lesson owner |
| `explain_deeper` | Mở rộng giải thích từ selected block và context | đúng lesson/block |
| `read_source` | Trả chunks có provenance khi P4.1 enabled | source owner + retrieval IDs allowlist |

- Max tool iterations/tokens/time per message; unknown tool name/invalid args → error audited; không execute code, không arbitrary URL fetch, không write lesson/progress.
- Audit metadata (tool name, duration, outcome, redacted argument summary); tool results untrusted.

## 8. Stop, quotas, errors

- `POST /v1/courses/{courseId}/tutor/messages/{messageId}/stop`: server set cancellation flag; upstream provider cancel best effort; status `cancel_requested/cancelled/completed` (cần chốt event races).
- Quota atomic per user/window, check trước gọi provider; response `429 TUTOR_LIMIT_REACHED`, optional Retry-After khi xác định được.
- Errors `TUTOR_CONTEXT_INVALID`, `TUTOR_LIMIT_REACHED`, `MESSAGE_IN_PROGRESS`, `TUTOR_PROVIDER_ERROR`, `TUTOR_CANCELLED` là **proposed names**, không áp đặt vào code cũ.
- Bảo đảm stop không hoàn trả giả chi phí đã phát sinh; token đã generated có thể tính phí bên provider.

## 9. Acceptance tests (gate)

- Stream full `delta`→`done` và history reload; invalid blockIndex/course/foreign lesson reject.
- Hai user dùng cùng `threadId` giả không lộ data; concurrent same clientMessageId chỉ 1 message/LLM call.
- Disconnect/duplicate/timeout/invalid SSE/stop+done race có kết quả rõ, không orphaned running forever.
- Quota 0 không gọi provider; tool allowlist block arbitrary calls; no raw prompts/keys trong logs.
- Real provider streaming chỉ đánh dấu TESTED khi có quyền API, output & usage; test mock không thay thế chứng cứ real.
