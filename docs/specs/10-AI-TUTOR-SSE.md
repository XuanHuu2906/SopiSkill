# 10 — AI Tutor: Context Grounding, SSE, Tools & Usage

**Trạng thái:** **P3.0 = IMPLEMENTED + TESTED (mock streaming)**; **P3.1 lát A (cancel/allowance/replay
semantics/safety/UI quota) = IMPLEMENTED + TESTED**; **P3.1 lát B (tool allowlist + audit) = IMPLEMENTED + TESTED
(mock planner)**.

Đã có code: `tutor_threads`/`tutor_messages` (revision `0008_p30_tutor_core`), `tutor_usage_events` +
`tutor_messages.cancel_requested_at` (revision `0009_p31_tutor_controls`), `tutor_tool_calls` (revision
`0010_p31_tutor_tools`), `POST .../tutor/messages` (SSE), `POST .../tutor/messages/{messageId}/stop`,
`GET .../tutor/usage`, `GET .../tutor/threads[/{id}]`, provider `stream_tutor_reply` + `plan_tutor_tool`
(mock deterministic + OpenAI-compatible), TutorPanel trong lesson.
**Không** hỗ trợ `Last-Event-ID` replay (quyết định tường minh). Sự thật đã kiểm chứng nằm ở
`docs/development-progress.md` (mục `P3.0`, `P3.1 lát A`, `P3.1 lát B`).

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
| TUTOR-006 | Tool allowlist read-only, validate từng tool call, audit | P3.1 lát B — DONE |
| TUTOR-007 | Stop/cancel best-effort với status server minh bạch | P3.1 lát A — DONE |
| TUTOR-008 | Usage limits/rate limit, không gọi model khi quota hết | P3.1 lát A — DONE |
| TUTOR-009 | Replay/resume chỉ nếu có persisted ordered event log | P3.1 — **quyết định: explicit restart, không resume** |
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
| `cancelled` | `streamId`, `messageId`, `seq`, `reason`, `partial` | Terminal do stop/abort; phần đã nhận được giữ |
| `tool` | `name`, `status` (ok/failed), `summary`, `durationMs`, `code?` | **P3.1 lát B**: tool read-only đã chạy/bị từ chối; không gửi raw args/nội dung nhạy cảm |
| `confirm` (P3.1 lát B, nếu có hành động cần user) | action metadata | Chưa bật khi chỉ read-only tools |

**SSE frames** phải escape newlines đúng chuẩn, UTF-8, no-store, proxy buffering disabled ở path stream khi deploy.

## 5. Persistence & idempotency semantics

- Transaction tạo user message (`clientMessageId` unique) + pending assistant message, reserve quota **trước** provider call.
- Duplicate same id + message completed: trả kết quả đã lưu qua history hoặc một deterministic completed response theo contract được chọn; **không gọi LLM lần hai**.
- Duplicate while in progress: HTTP `409 MESSAGE_IN_PROGRESS` hoặc attach existing stream **chỉ khi thực sự có multiplexing**; P3 MVP chọn 409 + GET history để đơn giản và an toàn.
- Disconnect không tự tuyên bố cancel server-side; status pending/running được reconciliation; retry same id không sinh double charge.
- **Quyết định P3.1.5 (đã chốt): KHÔNG hỗ trợ `Last-Event-ID` replay.** Không có event log bền
  vững, nên resume sẽ phải giả vờ. `id` frame vẫn là `streamId:seq` (đơn điệu) để sau này có thể
  thêm nếu thật sự lưu log; `replaySupported=false` trả trong thread detail; UI hướng dẫn "tải lại
  lịch sử". Muốn đổi quyết định này phải thêm bảng event log + test reconnect trước khi tuyên bố.

## 6. Tutor grounding & teaching rules

- Build context từ **server-owned** course, lesson title, current block, progress snapshot nếu cần, và số message history giới hạn.
- Không chuyển nguyên toàn bộ bài/hồ sơ sang provider nếu không cần; cap tokens và redact metadata.
- Answer nên: hỏi làm rõ nếu cần, gợi ý, giải thích theo mức học viên, ví dụ mới, check understanding. Không bịa học lực, không để user text override system/tools.
- Khi user hỏi không liên quan bài: phân biệt general knowledge với lesson-grounded; với RAG yêu cầu evidence thì nói không có evidence.

## 7. Tools P3.1 lát B — IMPLEMENTED (server-side deterministic)

| Tool | Read-only contract | Authorization | Trạng thái |
|---|---|---|---|
| `read_lesson` | Đọc public blocks của lesson hiện tại (hoặc một `blockIndex`) | course + lesson owner (resolve trước ở `prepare_turn`); `blockIndex` trong biên | DONE |
| `explain_deeper` | Mở rộng giải thích từ block được chọn + các đoạn `teach` lân cận | đúng lesson/block | DONE |
| `read_source` | Chỉ sau P4.1 (chunk ownership + provenance) | source owner + retrieval IDs allowlist | Allowlisted nhưng `TUTOR_TOOL_NOT_AVAILABLE` |

- **Không dùng native `tool_calls`**: model trả JSON `{tool, args}` qua `plan_tutor_tool`; server
  parse → validate → execute. Lý do: mock/provider thật dùng chung contract, server luôn quyết định.
- Tên tool ngoài allowlist ⇒ `TUTOR_TOOL_NOT_ALLOWED`, **không execute**, vẫn ghi audit.
- Args sai schema (`extra=forbid`) hoặc `blockIndex` ngoài biên ⇒ `TUTOR_TOOL_INVALID_ARGS`.
- Bounded loop: `TUTOR_TOOL_MAX_CALLS` (2), `TUTOR_TOOL_TIMEOUT_SECONDS` (3s) cho planner; dừng sau
  1 kết quả để không lặp vô hạn.
- Không execute code, không fetch URL, không ghi lesson/progress. Kết quả tool vào prompt trong
  delimiter `<<<TOOL_BAT_DAU>>>` và được dặn là dữ liệu không tin cậy.
- Audit `tutor_tool_calls`: name/ok/duration_ms/summary (server dựng)/error_code. **Không** lưu
  nội dung tool trả về hay prompt.
- Flag `TUTOR_TOOLS_ENABLED=false` (mặc định) ⇒ không gọi planner, không frame `tool`.

## 8. Stop, quotas, errors (P3.1 lát A — IMPLEMENTED)

- `POST /v1/courses/{courseId}/tutor/messages/{messageId}/stop` → ghi `cancel_requested_at`
  (owner-scoped, 404 `TUTOR_STOP_NOT_FOUND` nếu không thuộc user/course hoặc không phải assistant).
  Response: `{messageId, status: cancel_requested|completed|failed|cancelled,
  providerStopGuaranteed: false, notice}`. Endpoint **không** tự ghi `cancelled`; task stream còn sống
  mới ghi trạng thái cuối + nội dung đã nhận. Stop trên message đã xong trả trạng thái thật.
- Vòng stream kiểm cờ **theo thời gian** (`TUTOR_CANCEL_POLL_SECONDS`, mặc định 1s), không chỉ khi
  queue timeout — nếu không, provider trả token liên tục sẽ không bao giờ thấy stop.
- "Dừng" khi client đóng tab: `finally` của generator ghi `cancelled` (đường P3.0 giữ nguyên).
- Allowance: `TUTOR_MESSAGES_PER_DAY` (lượt/24h), `TUTOR_TOKENS_PER_DAY` (token/24h, từ
  `tutor_usage_events`), `TUTOR_MAX_CONCURRENT_STREAMS` (stream đồng thời/user). Kiểm **trước** khi
  tạo message/gọi provider; 429 kèm `detail.quota` có cấu trúc.
- `GET /v1/courses/{courseId}/tutor/usage` → `{used, limits, remaining, runningStreams, tokensKnown}`.
  `remaining: null` = không có trần; `tokensKnown=false` = provider chưa báo token ⇒ trần token
  **không** phản ánh chi phí thật.
- Message `pending/running` quá `TUTOR_STALE_STREAM_SECONDS` bị reap thành `failed/TUTOR_STALE`
  (server restart), tránh khóa user ở `MESSAGE_IN_PROGRESS` vĩnh viễn.
- Bảo đảm stop không hoàn trả giả chi phí đã phát sinh; token đã generated có thể tính phí bên provider.

## 9. Acceptance tests (gate)

- Stream full `delta`→`done` và history reload; invalid blockIndex/course/foreign lesson reject.
- Hai user dùng cùng `threadId` giả không lộ data; concurrent same clientMessageId chỉ 1 message/LLM call.
- Disconnect/duplicate/timeout/invalid SSE/stop+done race có kết quả rõ, không orphaned running forever.
- Quota 0 không gọi provider; tool allowlist block arbitrary calls; no raw prompts/keys trong logs.
- P3.1: stop giữa stream (provider trả liên tục) ⇒ frame `cancelled`, phần đã nhận giữ nguyên, trạng
  thái DB `cancelled`; stop-vs-completed race không ghi đè nội dung; quota token/lượt chặn trước
  provider; stale running được reap; usage event không chứa nội dung.
- P3.1 lát B: tool ngoài allowlist/args sai/blockIndex ngoài biên bị chặn **trước** execute và vẫn
  audit; planner lỗi hoặc không hỗ trợ ⇒ lượt hỏi vẫn trả lời bình thường; prompt chứa kết quả tool
  **không** chứa answer key; audit không chứa nội dung bài.
- Real provider streaming chỉ đánh dấu TESTED khi có quyền API, output & usage; test mock không thay thế chứng cứ real.
