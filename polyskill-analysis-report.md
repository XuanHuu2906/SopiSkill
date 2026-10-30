# Báo cáo kỹ thuật: Phân tích web.polyskill.app bằng REA

> **Phạm vi:** Phân tích tĩnh bundle frontend (sau đăng nhập) + quan sát CDP. Không có tương tác backend nào được thực hiện ngoài việc tải trang.
> **Công cụ:** REA 6.7.0 (`list-browser-targets`, `analyze-web-bundle`, `inspect-web-page`) + Chrome 156 CDP remote debugging.
> **Bằng chứng chính:** Bundle `https://web.polyskill.app/_expo/static/js/web/entry-a3803cab42a2ab75ae9ef2e391ee92d0.js` — 5.849.374 bytes, SHA-256 `e7f84aaffae7a3be5d943437e1ccd084a69c12aad1675f3bcc841703bde5d4ce` (đã xác minh khớp khi export từ capture).

---

## 1. Framework & công nghệ — ĐÃ XÁC NHẬN

| Thành phần | Bằng chứng (nguồn từ bundle) |
|---|---|
| **Expo SDK 57** | Manifest nhúng: `{"name":"PolySkill","slug":"polyskill-app","version":"1.0.0","sdkVersion":"57.0.0","owner":"qnguyen3",...,"bundler":"metro"}` |
| **React 19.2.3** | `e.version="19.2.3"` trong module React |
| **React Native Web** | Route `_expo/static/js/web/`, style props kiểu react-native-web |
| **Metro bundler** | `__METRO_GLOBAL_PREFIX__`, định dạng module `__d(function(g,r,i,a,m,e,d)...)` |
| **expo-router** | `"/expo-router/build/views/Navigator"`, routes `""`, `_sitemap`, `+not-found`, `"experiments":{"typedRoutes":true}` |
| **TanStack Query** | `useQuery`/`useQueryClient` (62 lần gọi) |
| **Reanimated + Worklets** | Chuỗi lỗi `[Reanimated]...`, link `docs.swmansion.com/react-native-worklets` |
| **expo-sqlite** | `openDatabaseAsync`, `PRAGMA journal_mode = WAL`, `PRAGMA user_version` |
| **MathJax** | `mjx-keep-attrs`, `data-semantic-speech`, các attr `scriptlevel/displaystyle` |
| **zod** | Toàn bộ API schema dùng `t.z.enum/object/...` |
| **Mixpanel** | Token nhúng: `mixpanelToken:"3310e38f5580f8d1e31d8074566800f3"` |
| **EAS** | `extra.eas.projectId: "9df59dfd-4ff8-45b0-96d7-fb57001aa6c3"` |

Storage client (quan sát trực tiếp qua CDP, giá trị đã redact):
- `localStorage`: `polyskill.installId`, `polyskill.refreshToken`
- IndexedDB / sessionStorage: rỗng tại thời điểm quan sát.

## 2. Cấu trúc JavaScript — ĐÃ XÁC NHẬN

- **1 bundle duy nhất** (không thấy code-splitting), ~5.85 MB, minified, 2.200+ module Metro; REA parse 1.181.207 AST nodes (`completeness: complete`).
- Kiến trúc: API client trung tâm (`apiRequest`) → zod schemas → TanStack Query hooks → màn hình expo-router.
- i18n đầy đủ (~12+ ngôn ngữ nhúng: EN, DE, IT, ES, FR, ID, JA, KO, PT, SV, VI…).

## 3. API endpoints — ĐÃ XÁC NHẬN (từ call-sites trong bundle)

**Base:** `https://api.polyskill.app` + prefix `/v1`
(nguồn: `Object.freeze({apiBaseUrl:..., apiPrefix:'/v1', appVersion:..., mixpanelToken:..., leagues:!1, adaptyKey:''})`)

### Auth & user
- `POST /v1/auth/exchange`, `POST /v1/auth/refresh`, `POST /v1/auth/signout`, `POST /v1/auth/link/confirm`
- OAuth callbacks: `/auth/google-callback.html`, `/auth/apple-callback`
- `GET /v1/me`, `/v1/me/profile`, `/v1/me/stats`, `/v1/me/onboarding`, `/v1/me/entitlement`, `/v1/me/notifications`, `/v1/me/identities`

### Billing (SePay — cổng thanh toán VN)
- `/v1/billing/plans`, `/billing/checkout`, `/billing/portal`, `/billing/sync`, `/billing/sepay/plans`, `/billing/sepay/orders`

### Tạo khóa học bằng AI
- `POST /v1/courses` — body `{topic: string(1..200), sourceId?}`, idempotency key, timeout 60s
- `POST /v1/courses/{id}/interview/answer` — body `{position: 0..4, answers: string[](1..6)}`, timeout 60s
- `POST /v1/courses/{id}/approve`
- `GET /v1/courses/{id}/generation` (client poll mỗi 2s), `POST /v1/courses/{id}/retry`
- `GET /v1/courses/{id}/plan`, `GET /v1/courses/{id}/path`, `GET /v1/courses/{id}/glossary`, `DELETE /v1/courses/{id}`

### Sources (nguyên liệu học)
- `POST /v1/sources/upload` (PDF), `POST /v1/sources/{id}/ingest`, `GET /v1/sources/{id}`, `DELETE /v1/sources/{id}`
- Loại nguồn: `enum(['arxiv','web','pdf'])`
- Trạng thái pipeline: `awaiting_upload → pending → extracting → ready | failed`
- Lý do từ chối: `unsupported, unreachable, paywalled, no_text, too_short, too_long, unsafe, not_teachable, internal`

### AI Tutor (streaming)
- `POST /v1/courses/{id}/tutor/messages` — header `accept: text/event-stream`, `last-event-id` (resume SSE), Bearer token + auto-refresh khi 401
- `POST /v1/courses/{id}/tutor/sessions`, `GET /v1/tutor/sessions`
- `POST /v1/courses/{id}/tutor/messages/{messageId}/stop`
- `POST /v1/courses/{id}/tutor/actions/{actionId}/{result}`

### Bài học
- `GET /v1/lessons/{id}`, `POST /v1/lessons/{id}/retry`, `POST /v1/lessons/{id}/attempts`,
  `POST /v1/lessons/{id}/blocks/{index}/grade`, `POST /v1/lessons/{id}/grades/{gradeId}/dispute`,
  `POST /v1/lesson/{id}/complete`

## 4. Luồng xử lý dữ liệu của tính năng AI — ĐÃ XÁC NHẬN (từ phía client)

```
[Chủ đề hoặc Source]                     [Source pipeline]
POST /courses {topic, sourceId?}   <───  arxiv/web/pdf → upload → ingest
        │                                 trạng thái: extracting → ready
        ▼                                      │  (brief: what/claims/
Interview 5 câu (position 0..4)                │   notation/assumes/sections)
POST /courses/{id}/interview/answer            ▼
        ▼                               Tạo khóa học (server-side;
Proposal: {name, objective,              client poll GET /generation
  shape{units 2-6, lessons 4-40,         mỗi 2s})
  checkpoints 0-6, project}, outcomes)          │
        ▼                                      ▼
POST /courses/{id}/approve ─────────► Lessons: blocks 'teach' | 'mc' | 'blank'
        ▲                               | 'order' | 'match' | 'short'
        │                               figures: 'formula' | 'visual' | 'diagram'
  AI Tutor: POST /tutor/messages (SSE) ─ delta* → tool → confirm → done
```

**Chi tiết tutor (agent loop có tool-calling):**
- SSE events client xử lý: `delta` (text token), `tool`, `confirm`, `done` (kèm `message`, `limit`, `threadId`, `allowance`), `error`, `restarted`.
- Tên tool (enum xác nhận): `regenerate_unit`, `flag_question`, `explain_deeper`, `read_lesson`, `revise_proposal`, `read_source`.
- Message schema: `toolCalls[]` = `{name, summary(1..160), ok:boolean}`, `contextLabel` nullable.
- Entry points tutor: `tab, wrong_answer, teach_block, term, path_harder, proposal`.
- Điều chỉnh độ khó: `harder, easier, more_practical`.
- Rate limit: lỗi `TUTOR_LIMIT_REACHED` kèm `{remaining, limit, resetAt}`.
- AI tutor có tên hiển thị: **"Pol"** (chuỗi i18n: "Pol's working", "Help Pol", "Il ragionamento di Pol"…).

## 5. Bằng chứng về thuật toán AI (RAG / embeddings / Transformer)

**Đã xác nhận ở phía client:**

1. **Streaming LLM qua SSE** — `text/event-stream`, event `delta` từng token, resume bằng `last-event-id`.
2. **Tool-calling agent** — event `tool` + enum 6 tool names ở trên; hành vi agent-loop với action confirm.
3. **Hệ trích dẫn (citation) có cấu trúc** — `citationSchema`; mỗi citation có `{anchor(1..24 ký tự), heading(1..160), gist(1..200)}`; URL arXiv được rewrite `/abs/` → `/html/`. Đây là cơ chế neo nội dung AI về đoạn văn trong nguồn — đặc trưng cho kiến trúc retrieval-augmented.
4. **Pipeline ingest tài liệu** — extract → brief có cấu trúc: `what`, `claims[]` (1–10), `notation[]` (≤20), `assumes[]` (≤10), `sections[]` (anchor/heading/gist). Cấu trúc theo *đoạn có anchor* phục vụ truy xuất về sau.
5. **Personalization** — learner profile (roles / topics / learningStyles / goals) + phỏng vấn 5 câu → `proposal` do AI sinh (units/lessons/outcomes).
6. **Không có ML chạy trên client** — không tìm thấy ONNX / tensorflow.js / wasm model. Các từ khóa `transformer`, `vector`, `embedding` chỉ xuất hiện dưới dạng false-positive (`drag`, `vectorEffect`, Reanimated inner product error string).

**CHỈ LÀ SUY ĐOÁN (không chứng minh được từ frontend):**

- Tên model LLM cụ thể (GPT / Claude / Gemini / Llama…) — **không có** chuỗi nào trong bundle; toàn bộ xử lý AI nằm ở `api.polyskill.app` (server-side, opaque với client).
- Vector DB, embeddings, chunking strategy, prompt templates — không thấy dấu vết trong client. Việc có citations + tool `read_source` **gợi ý mạnh** RAG server-side nhưng frontend không thể chứng minh thuật toán cụ thể (cosine similarity, hybrid search, reranking…).
- `temperature`, `max_tokens` — không xuất hiện trong client.

## 6. Tổng hợp: Xác nhận vs. Suy đoán

| # | Nhận định | Trạng thái |
|---|---|---|
| 1 | Expo SDK 57 + RN Web + React 19.2.3 + Metro | ✅ Xác nhận (manifest + runtime strings) |
| 2 | Backend `https://api.polyskill.app/v1`, 40+ endpoints | ✅ Xác nhận (call-sites + zod schemas) |
| 3 | Tutor AI: SSE streaming + tool-calling + rate limit | ✅ Xác nhận (protocol handler + enums) |
| 4 | Citation neo theo anchor vào nguồn arxiv/web/pdf | ✅ Xác nhận (citationSchema + URL rewrite) |
| 5 | Pipeline ingest tài liệu với brief có cấu trúc | ✅ Xác nhận (schemas + trạng thái) |
| 6 | Model LLM cụ thể phía server | ❓ Không xác định được từ client |
| 7 | RAG server-side (vector search, embeddings) | ❓ Suy đoán hợp lý, chưa chứng minh |

## 7. Giới hạn của phân tích

- Chỉ phân tích **frontend**; hành vi server (model, RAG, prompt) là black-box đối với client.
- Routes/endpoint dựng bằng chuỗi động hoặc code lazy-load ở vùng sâu sau đăng nhập có thể chưa được đưa vào bundle tại thời điểm capture.
- REA không thực thi captured JS; mọi kết luận dựa trên phân tích tĩnh (1.181.207 AST nodes, `completeness: complete` cho script đã capture).
- Quan sát mạng CDP tại trang onboarding rỗng (request đã xảy ra trước khi attach) — endpoints được suy ra từ code, không phải từ traffic bắt được.
- Phần lớn match "rag" trong bundle là false-positive (`drag`, `fragment`) — đã loại khỏi bằng chứng.

## 8. Kết luận

PolySkill là ứng dụng học cá nhân hóa xây trên **Expo SDK 57 / React Native Web / React 19**, backend AI tại `https://api.polyskill.app/v1`. Tính năng cốt lõi: biến **chủ đề / paper arXiv / trang web / file PDF** thành khóa học có cấu trúc qua phỏng vấn + proposal do AI sinh, kèm **AI tutor "Pol"** dạng agent SSE stream có tool-calling, rate limit và citation neo vào nguồn. Kiến trúc client **tương thích** với RAG server-side (citations + `read_source` tool), nhưng thuật toán cụ thể (model LLM, embeddings, vector search) **không thể xác nhận chỉ từ frontend**.

---

*Phân tích thực hiện ngày 2026-10-30 bằng REA 6.7.0 (CLI) — các trích dẫn chuỗi lấy trực tiếp từ bundle đã capture và xác minh SHA-256.*
