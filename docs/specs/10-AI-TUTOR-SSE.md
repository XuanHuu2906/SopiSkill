# 10 — AI Tutor: Context Grounding, SSE, Tools & Usage

**Trạng thái (`2026-11-22`):**
- **P3.0** (`0008_p30_tutor_core`), **P3.1 lát A** (`0009_p31_tutor_controls`), **P3.1 lát B** (`0010_p31_tutor_tools`), **P4.1 `read_source` wiring**, và **FR-5 docked Tutor rail** đều đã **IMPLEMENTED · REPORTED TESTED (mock)**.
- **Trạng thái vận hành mặc định:** **DEFAULT-OFF** (`TUTOR_ENABLED=false`, `TUTOR_TOOLS_ENABLED=false`, `RAG_ENABLED=false`).
- **Gate `TUTOR-MOCK-01` (`2026-11-04`):** `PRODUCT_E2E_PASS` trên mock (`71/71` E2E + `31/31` raw SSE probes + disconnect probe). **NOT TESTED:** streaming với LLM thật, tool quality với LLM thật, browser UI E2E tự động.

## 1. Scope & user goal

Người học đặt câu hỏi ngay trong bài học (`/lesson/[lessonId]`) với `TutorPanel` (dock cạnh phải `400px` ở desktop `≥1024px`, overlay modal có focus trap + `inert` ở `<1024px`). Tutor trả lời có ngữ cảnh đúng block, lưu lịch sử bền vững theo owner, có quota và nút dừng rõ ràng; tuyệt đối không bịa citation hay tiết lộ answer key.

## 2. Requirements

| ID | Yêu cầu | Trạng thái (2026-11-22) |
|---|---|---|
| TUTOR-001 | Thread & messages lưu bền vững và owner-scoped | **IMPLEMENTED · TESTED (mock)** |
| TUTOR-002 | `contextRef {lessonId, blockIndex}` resolve từ DB qua course owner | **IMPLEMENTED · TESTED** |
| TUTOR-003 | SSE `delta`, `done`, `error`, `cancelled`, `heartbeat`, `tool` với `seq` đơn điệu | **IMPLEMENTED · TESTED (mock)** |
| TUTOR-004 | `clientMessageId` unique, duplicate replay không gọi LLM lần 2 | **IMPLEMENTED · TESTED** |
| TUTOR-005 | Lesson + bounded history grounding, chưa có source thì không cite | **IMPLEMENTED · TESTED** |
| TUTOR-006 | Tool allowlist read-only, validate args/bounds, audit metadata-only | **IMPLEMENTED · TESTED (mock)** |
| TUTOR-007 | Stop/cancel best-effort với trạng thái server minh bạch (`providerStopGuaranteed=false`) | **IMPLEMENTED · TESTED** |
| TUTOR-008 | Allowance 24h (messages, tokens, concurrent streams) chặn trước khi gọi provider | **IMPLEMENTED · TESTED** |
| TUTOR-009 | Replay/resume semantics | **DECIDED (DEC-P31-A1):** explicit restart, `replaySupported=false`, không hỗ trợ `Last-Event-ID` |
| TUTOR-010 | Khi `RAG_ENABLED=true`, `read_source` & RAG grounding trả citation verified (`chk_*`) | **IMPLEMENTED · TESTED (offline baseline, flag OFF)** |

## 3. API contract thực tế (`backend/app/api/v1/tutor.py`)

```http
POST /v1/courses/{courseId}/tutor/messages
Cookie: <HttpOnly session>
X-CSRF-Token: <double-submit token>
Accept: text/event-stream
Content-Type: application/json

{
  "clientMessageId": "uuid-8..64",
  "threadId": null,
  "text": "Vì sao vòng lặp này dừng?",
  "contextRef": {"lessonId": "lsn_<id>", "blockIndex": 3}
}
```
- Headers response gồm `X-Tutor-Thread-Id`, `X-Tutor-Message-Id` trước byte SSE đầu tiên.
- `TutorMessageRequest` đặt `extra="forbid"`: từ chối `userId`, `courseId`, `systemPrompt`, `lessonContent`, `sources`, `ownerId`.
- Khi `TUTOR_ENABLED=false` → tất cả 5 endpoints trả `503 TUTOR_DISABLED`.
- 4 endpoints còn lại: `POST .../messages/{messageId}/stop`, `GET .../tutor/usage`, `GET .../tutor/threads`, `GET .../tutor/threads/{threadId}`.

## 4. SSE events (IMPLEMENTED)

| Event | Payload chính | Semantics |
|---|---|---|
| `delta` | `streamId`, `messageId`, `seq`, `text` | Incremental text; `seq` tăng đơn điệu, `id = streamId:seq` |
| `tool` | `name`, `status` (`ok`/`failed`), `summary`, `durationMs`, `code?` | Chỉ xuất hiện khi `TUTOR_TOOLS_ENABLED=true`; không chứa raw args/nội dung nhạy cảm |
| `done` | `streamId`, `messageId`, `seq`, `finishReason`, `replayed?`, `usage?`, `citations?` | Terminal success; persisted DB |
| `error` | `streamId`, `messageId?`, `seq`, `code`, `message`, `retryable`, `replayed?` | Terminal failure, không raw exception |
| `cancelled` | `streamId`, `messageId`, `seq`, `reason`, `partial` | Terminal do stop/disconnect; giữ nội dung đã nhận |
| `heartbeat` | keepalive | Tránh idle timeout (mặc định 15s) |

## 5. Persistence, Idempotency & Replay

- Transaction tạo user message (`clientMessageId` unique) + pending assistant message và kiểm quota **trước** khi gọi provider.
- Retry cùng `clientMessageId`: `completed` → replay không gọi provider; `failed`/`cancelled` → trả error terminal; `pending`/`running` → `409 MESSAGE_IN_PROGRESS`.
- Message `pending`/`running` quá `TUTOR_STALE_STREAM_SECONDS=180` bị reap thành `failed/TUTOR_STALE`.
- Client disconnect ⇒ generator hủy và detached task `_persist_cancelled` ghi `cancelled` + phần nội dung đã nhận (đã chứng minh live trong `TUTOR-MOCK-01` `probe_tutor_disconnect.py`).

## 6. Tools (P3.1 lát B + P4.1 — IMPLEMENTED, `TUTOR_TOOLS_ENABLED=false`)

| Tool | Contract read-only | Authorization | Trạng thái (`tutor_tools.py`) |
|---|---|---|---|
| `read_lesson` | Đọc public blocks của lesson hiện tại (không answer key) | Course + lesson owner; `blockIndex` trong biên | `available = True` |
| `explain_deeper` | Mở rộng giải thích cho `blockIndex` + các đoạn `teach` lân cận | Đúng lesson/block | `available = True` |
| `read_source` | Tìm trong tài liệu đã ingest của khóa học (`query?`) | Scope owner + course trong SQL; chỉ chạy khi `RAG_ENABLED=true` và có `source_reader`, ngược lại từ chối sạch không bịa | `available = True` (từ P4.1) |

- Dùng **server-side deterministic JSON** qua `plan_tutor_tool`, không dùng native `tool_calls` (DEC-P31-B1).
- Giới hạn: `TUTOR_TOOL_MAX_CALLS=2`, `TUTOR_TOOL_TIMEOUT_SECONDS=3.0`, `TUTOR_TOOL_MAX_RESULT_CHARS=3000`.
- Audit lưu tại `tutor_tool_calls` (chỉ metadata, không lưu nội dung bài/tài liệu).

## 7. Stop & Quota (IMPLEMENTED)

- `POST .../stop` ghi `cancel_requested_at` (owner-scoped, 404 `TUTOR_STOP_NOT_FOUND`); vòng stream poll cờ mỗi `TUTOR_CANCEL_POLL_SECONDS=1.0`.
- Allowance (`0` = không giới hạn, **không phải** "cấm dùng"): `TUTOR_MESSAGES_PER_DAY=0`, `TUTOR_TOKENS_PER_DAY=0`, `TUTOR_MAX_CONCURRENT_STREAMS=2`. Khi vượt trần trả `429` kèm `detail.quota`.
- `GET .../usage` không tiêu quota; `tokensKnown=false` cảnh báo trung thực khi provider chưa báo token usage.

## 8. Mở rộng đề xuất từ đối chiếu PolySkill (`PROPOSAL — NOT IMPLEMENTED`)

Xem `polyskill-analysis-report.md` §5.6 và `docs/frontend-reference/api-gap-register.md` (`GAP-07`, `GAP-08`, `GAP-20`):
- 3 loại thread (`course` / `anchor` / `task`) và 6 entry points (`tab`, `wrong_answer`, `teach_block`, `term`, `path_harder`, `proposal`).
- Tools mở rộng có ghi dữ liệu với **confirm gate**: `revise_proposal`, `flag_question` (`contentFlag`), và `regenerate_unit` (SSE `confirm` → `ChangeCard` → `POST .../actions/{actionId}/{confirm|decline}` → background rewrite job).
- Các mở rộng này đòi hỏi migration mới, bảng trạng thái action và review bảo mật riêng — **chưa triển khai**.
