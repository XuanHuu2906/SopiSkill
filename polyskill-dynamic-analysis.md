# PolySkill — Báo cáo Giai đoạn 2: Dynamic AI Analysis

> **Phạm vi:** Quan sát hành vi runtime thực tế qua REA 6.7.0 + Chrome CDP (Chrome 156), trên tài khoản của người dùng, với các thao tác được thực hiện thủ công bởi chủ tài khoản.
> **Ngày quan sát:** 2026-10-30, 13:04–13:38 UTC.
> **Báo cáo liên quan:** `polyskill-analysis-report.md` (giai đoạn 1 — phân tích tĩnh, giữ nguyên).
> **Nguyên tắc:** Mọi nhận định được dán nhãn FACT / INFERENCE / UNKNOWN. Không token, cookie hay dữ liệu cá nhân nào được đưa vào báo cáo này.

---

## 0. Phương pháp & điều kiện thực nghiệm

- **Chuỗi quan sát:** 10 cửa sổ `rea inspect-web-page` qua CDP trên tab `F72683F5C84D9AD1B79C5D37975AC30F`.
- **Thao tác của người dùng (thủ công, có chủ đích):** hoàn tất onboarding, tạo khóa học mới, phỏng vấn + approve, mở bài học, làm quiz (POST attempts), nhắn tin cho AI tutor "Pol" 3 lần.
- **Lỗi đã phát hiện và sửa trong quá trình:** cờ `--allowed-origins` của REA phải lặp lại per-flag cho từng origin. Lượt 1–9 chỉ whitelist `web.polyskill.app` nên API requests tới `api.polyskill.app` bị REA loại với lý do `disallowed_origin` (số lượng bị loại vẫn được REA đếm và báo cáo — xem §2).
- **Giới hạn thu thập:** REA (cấu hình mặc định) **không lưu** headers, body, cookies, giá trị storage, payload WebSocket; với SSE (`text/event-stream`) không có shape giữ lại. Chỉ giữ **shape có cấu trúc không giá trị** (JSON body shapes: đường dẫn property + kiểu).
- **Không thực hiện:** bypass auth, gọi endpoint ngoài UI, đổi dữ liệu tài khoản, tải tài liệu (source ingest), gọi API có chi phí.

## 1. Kiến trúc AI quan sát được

```
┌──────────────────────────── CLIENT (web.polyskill.app) ─────────────────────────────┐
│  Expo SDK 57 / React Native Web / React 19.2.3 / Metro bundle 5.85 MB               │
│  ┌──────────────┐   ┌──────────────────┐   ┌─────────────────────────────────────┐  │
│  │ expo-router  │──►│ TanStack Query   │──►│ apiRequest() ──► api.polyskill.app  │  │
│  │ screens      │   │ (poll + cache)   │   │ zod schema validation               │  │
│  └──────────────┘   └──────────────────┘   │ Bearer token + refresh 401          │  │
│                                            └─────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                        │ HTTPS (fetch)
                                        ▼
┌──────────────────────────── BACKEND (api.polyskill.app/v1) ─────────────────────────┐
│  REST JSON + SSE streaming (text/event-stream)                                      │
│  ┌───────────────┐  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ Course        │  │ Lesson/Attempt  │  │ Tutor agent (threadId, toolCalls,    │   │
│  │ generation    │  │ scoring +       │  │ allowance limit, contextRef)         │   │
│  │ (poll-based)  │  │ gamification    │  │ SSE: delta/tool/confirm/done/error   │   │
│  └───────────────┘  └─────────────────┘  └──────────────────────────────────────┘   │
│  [Model LLM cụ thể: UNKNOWN — hoàn toàn server-side]                                │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**FACT:** Toàn bộ logic AI (sinh course, chấm điểm câu trả lời tự luận, tutor) nằm ở backend. Client chỉ: (1) gửi input có cấu trúc (topic, câu trả lời phỏng vấn, tin nhắn), (2) poll trạng thái, (3) render SSE stream.

## 2. Luồng request/response đã xác minh (runtime thật)

### 2.1. Bằng chứng từ metadata các lượt quan sát bị lọc origin

| Lượt | Cửa sổ | Sự kiện người dùng | Requests bắt được | Requests bị lọc (`disallowed_origin`) |
|---|---|---|---|---|
| 3 | 13:13:23–13:17:23 | Tạo khóa học + approve | 3 (PNG) | **82** (API calls tạo course) |
| 6 | 13:21:40–13:23:10 | Nhắn Pol lần 1 | 4 (PNG) | **11** (API calls tutor) |

**FACT:** 82 + 11 = 93 API requests thực sự xảy ra nhưng bị REA loại khỏi lưu trữ do cấu hình origins sai của tôi — các con số này chỉ chứng minh *khối lượng hoạt động*, không có nội dung.

### 2.2. Lượt 10 (13:31:51–13:37:51) — cấu hình đúng: 40 API requests, 0 bị loại

Thứ tự quan sát được (đã dedup OPTIONS preflight):

```
# --- Mở màn hình lesson (tab teach_block) ---
GET  /v1/lessons/lsn_01M66F9R898QKZV5VBH3TJ3H6A              200  2.6 KB
GET  /v1/courses/{courseId}/tutor?entryPoint=teach_block&... 200  328 B   (khởi tạo thread)
POST /v1/courses/{courseId}/tutor/messages                    200  10.8 KB (SSE — tin nhắn Pol #1)
GET  /v1/courses/{courseId}/path                              200  1.9 KB
GET  /v1/courses/{courseId}/tutor                             200  965 B   (poll lịch sử thread)

# --- Làm quiz ---
POST /v1/lessons/lsn_.../attempts                             201  533 B   (nộp kết quả)
GET  /v1/courses/{courseId}/path                              200          (refresh tiến độ)
GET  /v1/me/stats                                             200          (XP/streak/hearts)

# --- Điều hướng ---
GET  /v1/home                                                 200
GET  /v1/me/profile                                           200
GET  /v1/courses/{courseId}/glossary                          200  2.2 KB
GET  /v1/lessons/lsn_...BPHB4SKRE34BVV91E?prefetch=1          200  2.8 KB  (PREFETCH bài kế tiếp!)

# --- Nhắn Pol 3 lần nữa (mỗi lần: POST SSE → GET tutor refresh) ---
POST /v1/courses/{courseId}/tutor/messages  (SSE)  ×3
GET  /v1/courses/{courseId}/tutor               ×4
GET  /v1/courses/{courseId}/path                ×nhiều

# --- Về home ---
GET /v1/me/notifications, /v1/me/entitlement, /v1/home, /v1/me/stats
```

**FACT — cấu trúc request/response xác minh được (value-free shapes):**

**POST `/tutor/messages`** — request (SSE):
```json
{
  "clientMessageId": "<string>",       // idempotency phía client
  "entryPoint": "<string>",            // "teach_block" quan sát được
  "contextRef": {
    "lessonId": "<string: lsn_...>",
    "blockIndex": <number>
  },
  "text": "<string>",                  // tin nhắn người dùng
  "threadId": "<string>"               // có từ tin nhắn thứ 2 trở đi
}
```

**GET `/courses/{id}/tutor`** — response (thread state):
```
threadId: string, kind: string, sealed: boolean, title: null,
nextCursor: null,
messages[8]: {id, role, content, createdAt,
              contextLabel: string,       // CONTEXT GẮN VỚI BÀI HỌC — có ở TẤT CẢ 8 messages
              toolCalls: [4 items]: {name: string, summary: string, ok: boolean},
              action: null},
allowance: {limit, remaining},           // rate limit tutor
limit: {limit, remaining, resetAt}
```

**FACT — tool-calling XÁC NHẬN Ở RUNTIME:** 4 toolCalls thực sự được ghi lại trong thread history sau phiên nhắn Pol. Tên tool là enum client-side đã xác định ở giai đoạn 1: `regenerate_unit, flag_question, explain_deeper, read_lesson, revise_proposal, read_source` (không xác định được 4 calls thuộc tool nào — giá trị bị REA ẩn).

**POST `/lessons/{id}/attempts`** — request/response:
```
REQ: {clientAttemptId, contentVersion, durationMs, startedAt,
      results[]: {index, type, correct, timeMs, answer: {option}}}
RES (201): {attemptId, completedAt, duplicate,
      score: {correct, total},
      rewards: {xp, totalXp, streakDays, streakExtended, freezeBanked,
                hearts: {count, max, nextRefillAt},
                goal: {earnedToday, target, met},
                levelsEarned[], milestonesEarned[], flagged}}
```

**GET `/lessons/{id}?prefetch=1`** — response: `lesson.blocks[]` đầy đủ các loại block (teach/mc/blank/order/match/short) với `figure{kind, nodes, rows, head, edgeLabels, groupLabels}`, `paragraphs[]` có `termKey` (liên kết glossary), `terms[]`, `contentVersion` (versioning nội dung), `source: null` (khóa học này KHÔNG có source arxiv/web/pdf).

**GET `/courses/{id}/path`** — `units[]{kicker, blurb, tone, paywalled, nodes[]{kind, lessonId, state, ready, format, contentVersion}}`, `progress{completed,total,percent}`, `upNextLessonId`.

**GET `/me/entitlement`** — `tier, expiresAt: null, subscription: null, limits{courses{limit,used}, openUnits, tutorAllowance{limit,remaining}}`.

## 3. Sơ đồ pipeline tạo khóa học (runtime)

**FACT — từ UI + code + quan sát gián tiếp (lượt 3–5):**

```
/ new (nhập topic) ──► POST /v1/courses ──► /new/interview ──► POST .../interview/answer ×5
                                                                     │
        ┌────────────────────────────────────────────────────────────┘
        ▼
 /new/proposal ──► POST /v1/courses/{id}/approve
        │
        ▼
 /new/generating?courseId=crs_01M66F3X1K2J31Y00QJDTAP9R7
        │
        │   UI hiển thị 4 giai đoạn (accessibility tree, lượt 5):
        │   1. "Đọc câu trả lời của bạn"
        │   2. "Bổ sung kiến thức nền còn thiếu"
        │   3. "Phác thảo lộ trình"
        │   4. "Soạn bài học 1"
        ▼
 client poll: GET /v1/courses/{id}/generation  (refetchInterval 2s
              cho tới status ∈ {ready, failed} — code useGeneration)
        ▼
 /course/{id}  ("Khóa học đã sẵn sàng")
```

**Client orchestration vs backend orchestration:**
- **FACT:** Client orchestration *chỉ ở mức polling*: `useGeneration` query poll 2s/lần (xác nhận trong code module 1737: `refetchInterval` trả về 2000 trừ khi `ready`/`failed`; tương tự `usePlan`).
- **FACT:** Backend orchestrate toàn bộ pipeline AI — client không gửi yêu cầu từng bước; 4 giai đoạn hiển thị chỉ là status trả về từ endpoint generation.
- **INFERENCE:** Bước "Bổ sung kiến thức nền còn thiếu" gợi ý backend tự tra cứu/sinh context bổ sung ngoài input người dùng, nhưng cơ chế (search web? LLM knowledge? retrieval?) là **UNKNOWN**.

## 4. Sơ đồ AI Tutor (runtime, đã xác minh)

```
User mở lesson ──► GET /tutor?entryPoint=teach_block&lessonId=...&blockIndex=...
                   (trả thread hiện có hoặc khởi tạo; kèm allowance)
        │
User nhắn tin ───► POST /tutor/messages {clientMessageId, entryPoint,
        │           contextRef{lessonId, blockIndex}, text, threadId?}
        │           Header: accept: text/event-stream, last-event-id (resume)
        ▼
   SSE stream (10.8 KB phiên #1):
        event: delta   {text, id}          — token-by-token
        event: tool    {tutorToolCall...}  — client hiển thị "Pol's working"
        event: confirm {tutorAction...}    — action cần user xác nhận
        event: done    {message, limit, threadId, allowance}
        event: error   {message}
        (interrupt: POST .../messages/{id}/stop; resume: last-event-id header)
        ▼
Sau stream: GET /tutor (refresh thread) — messages có toolCalls[4] thực tế
        │
Quyết định người dùng trên message ──► POST /tutor/actions/{actionId}/{result}
```

**FACT:** Mỗi tin nhắn trong thread mang `contextLabel` (context từ bài học được hiển thị kèm) — 8/8 messages có contextLabel. Request mang `contextRef{lessonId, blockIndex}` — **backend nhận ngữ cảnh bài học qua tham số có cấu trúc**, không phải client tự chèn nội dung bài học vào prompt.

**FACT:** `allowance{limit, remaining}` được trả kèm — rate limit theo lượt tutor, đồng bộ với `limits.tutorAllowance` ở `/me/entitlement`.

## 5. Thuật toán / kỹ thuật AI có bằng chứng

| # | Kỹ thuật | Mức | Bằng chứng runtime | Bằng chứng tĩnh (GĐ1) |
|---|---|---|---|---|
| 1 | **LLM streaming (SSE)** | FACT | 4× POST `text/event-stream` 200 OK | Protocol handler delta/tool/confirm/done |
| 2 | **Agent tool-calling** | FACT | 4 toolCalls `{name, summary, ok}` trong thread history | Enum 6 tool names |
| 3 | **Structured context passing** (grounding vào lesson/block) | FACT | `contextRef{lessonId, blockIndex}` + `contextLabel` trên mọi message | Entry points enum |
| 4 | **Rate-limited tutor** | FACT | `allowance{limit,remaining}` + `limit{resetAt}` | `TUTOR_LIMIT_REACHED` code |
| 5 | **Idempotent writes** | FACT | `clientMessageId`, `clientAttemptId` do client sinh | Idempotency key trong apiRequest |
| 6 | **Prefetch lesson kế tiếp** | FACT | `GET /lessons/{next}?prefetch=1` | — |
| 7 | **Content versioning** | FACT | `contentVersion` trong lesson + attempts | — |
| 8 | **Gamification loop** (XP/streak/hearts/goal) | FACT | rewards object đầy đủ trong attempts response | — |
| 9 | **Progressive lesson unlocking** (`ready`, `state`, `paywalled` per unit node) | FACT | path response | — |
| 10 | **RAG server-side** (retrieval trước khi sinh) | INFERENCE | UI giai đoạn "Bổ sung kiến thức nền còn thiếu"; `source: null` cho khóa topic-based nhưng vẫn sinh được; tool `read_source` tồn tại | citationSchema, sections{anchor,heading,gist} |
| 11 | **Citation vào nguồn** (arxiv /abs/ → /html/) | FACT (mã nguồn) — KHÔNG quan sát runtime (khóa học test không dùng source) | — | citationUrl rewrite |
| 12 | **Vector search / embeddings** | UNKNOWN | Không có tín hiệu nào từ client | Không có trong bundle |
| 13 | **Model LLM cụ thể** | UNKNOWN | Response hoàn toàn do backend render | Không có trong bundle |
| 14 | **Adaptive difficulty** (`harder/easier/more_practical`) | FACT (cơ chế client→backend tồn tại) — hiệu quả điều chỉnh là UNKNOWN | — | enum + quick actions UI |

## 6. Bảng Evidence chi tiết

| # | Nhận định | Nguồn | Mức tin cậy | Giới hạn |
|---|---|---|---|---|
| E1 | Khóa học tạo thành công: `crs_01M66F3X1K2J31Y00QJDTAP9R7`, id format `crs_` + ULID | URL `/new/generating?courseId=...` (lượt 3) | FACT — cao | Chỉ 1 khóa học quan sát |
| E2 | 4 giai đoạn generation hiển thị trên UI | Accessibility tree lượt 5 (text capture đã approved) | FACT — cao | Tên giai đoạn là UI string, không phải trạng thái server nội bộ |
| E3 | Poll generation 2s | Code `useGeneration` (module 1737) + GET không bắt được do attach-limited | FACT (mã) / INFERENCE (runtime timing) | Không thấy số polling thật trong capture |
| E4 | 4 SSE POST tutor messages 200 OK | Network log lượt 10 | FACT — cao | Body SSE không được REA parse (shapes null); không xác minh được thứ tự event thật |
| E5 | Thread có 8 messages, 4 toolCalls, mọi message có contextLabel | GET /tutor response shape (94 properties) | FACT — cao | Giá trị text bị ẩn — không biết tool nào được gọi, nội dung gì |
| E6 | contextRef{lessonId, blockIndex} gửi kèm tin nhắn | POST body shape | FACT — cao | — |
| E7 | Attempts nộp batch results có timing | POST attempts shape + 201 | FACT — cao | 1 lần nộp duy nhất quan sát |
| E8 | Prefetch lesson kế tiếp | URL `?prefetch=1` | FACT — cao | — |
| E9 | Entitlement có tutorAllowance + limits.courses | GET /me/entitlement shape | FACT — cao | tier của tài khoản test là free (subscription: null) |
| E10 | Generation là backend orchestration | Không có request nào từ client ngoài poll trong pha generating | FACT — cao | Lượt 3 chỉ bắt 3 PNG (attach-limited) — 82 API calls đã xảy ra nhưng không đọc được nội dung |
| E11 | RAG / retrieval phía server | UI pipeline step + cấu trúc brief/sections/citations (GĐ1) | INFERENCE — trung bình | Không chứng minh được kỹ thuật retrieval cụ thể |
| E12 | Embeddings / vector DB | — | UNKNOWN | Không có tín hiệu nào ở bất kỳ tầng nào client chạm được |
| E13 | LLM provider | — | UNKNOWN | Không suy đoán từ phong cách phản hồi theo đúng quy tắc nhiệm vụ |

## 7. Những thành phần chưa thể xác định

1. **Model / provider LLM** — toàn bộ ở backend; không có tín hiệu client-side.
2. **Cơ chế retrieval của bước "Bổ sung kiến thức nền còn thiếu"** — web search, embedding search, hay LLM nội tại: UNKNOWN.
3. **Nội dung SSE events thật** (thứ tự delta/tool/confirm trong 4 phiên) — REA không parse `text/event-stream`; chỉ có tổng dung lượng (10.8 KB phiên đầu).
4. **4 toolCalls cụ thể** trong phiên test — tên, summary bị ẩn bởi policy REA.
5. **Chất lượng/độ chính xác của AI** (điểm quiz do AI chấm với short-answer) — không đánh giá được trong phạm vi này.
6. **Source ingest pipeline thật** (arxiv/web/pdf) — khóa học test dùng topic trống; chưa chạy luồng source (cần tải tài liệu — đã tránh theo quy tắc).
7. **Cơ chế `paywalled` units** — khóa test chưa chạm unit trả phí.

## 8. Đề xuất kiểm tra tiếp theo

1. **Tạo khóa học từ một nguồn cụ thể** (arXiv paper công khai, VD link người dùng có quyền truy cập) để quan sát: `POST /sources/upload`, `GET /sources/{id}` trạng thái `extracting → ready`, và citation `{anchor, heading, gist}` thật trong bài học + tool `read_source` trong tutor. *(Cần người dùng tự cung cấp tài liệu — tôi không tự thực hiện.)*
2. **Bắt SSE events đầy đủ** bằng cách dùng `capture-browser-scenario` của REA (nếu phiên bản hỗ trợ giữ event-stream frames) hoặc kiểm tra trong DevTools người dùng với mục tiêu đếm event types — chỉ ghi nhận cấu trúc, không lưu nội dung người dùng.
3. **Thử các quick actions** (`explain_deeper`, `regenerate_unit`...) từng cái một để map toolCalls name → UI action.
4. **Chạm TUTOR_LIMIT** (hết allowance) để xác minh hành vi `TUTOR_LIMIT_REACHED` và `resetAt` — chỉ khi người dùng chấp nhận tiêu hạn mức.
5. **Test adaptive difficulty**: bấm "Đi sâu hơn" / "Rút ngắn lại" và so sánh `contentVersion` / `blocks` của lesson trước-sau.
6. **Kiểm tra `last-event-id` resume**: ngắt mạng giữa stream rồi bật lại (thử trong môi trường người dùng kiểm soát).
7. **So sánh 2 course cùng topic** để đo tính deterministic của generation (chỉ định tính, không đánh giá chất lượng).

---

## Phụ lục: Nhật ký quan sát (để tái lập)

| Lượt | File | Cửa sổ (UTC) | Cấu hình | Kết quả chính |
|---|---|---|---|---|
| 1 | ps-dyn-01-onboarding.json | 13:04:36–13:06:06 | 1 origin, 90s | 0 requests (user idle) |
| 2 | ps-dyn-02-course.json | 13:06:27–13:09:27 | 1 origin, 180s | 0 requests (user idle) |
| 3 | ps-dyn-03-newcourse.json | 13:13:23–13:17:23 | 1 origin, 240s | 3 PNG; **82 API bị lọc**; URL `/new/generating?courseId=crs_01M66F3X1K2J31Y00QJDTAP9R7` |
| 4 | ps-dyn-04-generating.json | 13:18:09–13:18:39 | 1 origin, 30s | 0 (poll ngoài cửa sổ) |
| 5 | ps-dyn-05-gen2.json | 13:20:38–13:20:58 | +accessibility, 20s | Pipeline steps UI + "Khóa học đã sẵn sàng" + tutor UI (Pol, 4 quick actions) |
| 6 | ps-dyn-06-tutor.json | 13:21:40–13:23:10 | 1 origin, 90s | 4 PNG; **11 API bị lọc** (nhắn Pol #1) |
| 7 | ps-dyn-07-tutor2.json | 13:23:52–13:25:22 | 2 origins (cách sai), 90s | 0 (user idle) |
| 8 | ps-dyn-08-tutor3.json | 13:25:55–13:30:55 | 2 origins (cách sai), 300s | 0 (user idle) |
| 9 | ps-dyn-09-final.json | 13:31:51–13:37:51 | 2 origins (cách sai), 360s | 8 PNG; **37 API bị lọc** |
| 10 | ps-dyn-10-fixed.json | 13:31:51–13:37:51* | **2 origins (đúng cú pháp)**, 360s | **40 API requests đầy đủ shape** — xem §2.2 |

\* Lượt 10 ghi đè lượt 9 cùng khoảng thời gian hoạt động — dữ liệu lượt 10 là bản đầy đủ của cùng phiên tương tác.

*Báo cáo này không chứa token, cookie, giá trị storage hay nội dung tin nhắn người dùng. Tất cả shapes là cấu trúc không giá trị theo chính sách REA mặc định.*
