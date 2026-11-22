# 02 — User Journeys & Stories

**Trạng thái (`2026-11-22`):** Journeys A–B **IMPLEMENTED · REPORTED TESTED (mock)**; Journeys C–E **IMPLEMENTED nhưng mặc định tắt cờ (`DEFAULT-OFF`)**. Các mở rộng đối chiếu tham chiếu (Proposal revision, Glossary, AI short grading) vẫn là `PROPOSAL`.

## 1. Journey A — Tạo khóa học từ chủ đề (Core — IMPLEMENTED)

**Điều kiện:** đã đăng nhập (khách chưa đăng nhập thấy `LandingPage` tại `/`); cookie/CSRF hợp lệ.

1. User vào `/new`, nhập topic 1–200 ký tự, nhấn tạo. Client gửi `clientCourseId` để retry không sinh course trùng.
2. Server tạo course `interview`, sinh 5 câu hỏi; user trả lời lần lượt tại `/new/interview` (free-text), có thể tiếp tục sau reload.
3. Đủ 5 câu, server trích xuất `LearnerProfile` (deterministic rule-based) và sinh proposal versioned kèm curriculum DAG (`skills`, `prerequisites`, `units`, `outcomes`). User xem tại `/new/proposal` trước khi approve.
4. User approve; API trả `202` với job `queued`; frontend chuyển sang `/new/generating` và poll `GET /v1/courses/{id}/generation` mỗi **2 giây**, ngừng poll khi `ready`/`failed`.
5. Job sẵn sàng: vào `/course/[courseId]` xem units/lessons/tiến độ (và mastery/sources/learning-path khi cờ bật); chọn `/lesson/[lessonId]`.
6. Sau quiz, server trả score/solution/XP, course progress cập nhật; reload không mất attempts.

**Ngoại lệ đã xử lý:** topic rỗng; submit câu số 5 hai lần; approve đôi đồng thời; network timeout sau request commit; Celery/Redis unavailable (beat reconciler thu hồi); worker crash/stale dispatch (`RELIABILITY-CELERY-01/02`); failed job retry không làm mất bài cũ.

## 2. Journey B — Học bài dạng bước và làm quiz (Core — IMPLEMENTED)

- Lesson player (`/lesson/[lessonId]`) chạy ở **focus mode** (ẩn side nav/tab bar, cột đọc 720px căn giữa), hiển thị **từng block một** kèm progress bar và `OutlineSheet` điều hướng giữa các block (`teach`, `mc`, `blank`, `order`, `match`, `short`).
- `GET /v1/lessons/{id}` trả **public blocks**, tuyệt đối không chứa answer key (`order`/`match` shuffle bằng HMAC `LESSON_SHUFFLE_SECRET`).
- UI giữ draft answers trên client và nộp **1 lần ở cuối bài** (`POST /v1/lessons/{id}/attempts`) với `clientAttemptId` ổn định và `contentVersion`.
- Nếu `contentVersion` thay đổi trước submit: trả `409`, UI hướng dẫn tải bài mới.
- Đạt `≥80%` (`INCUMBENT / PRODUCT APPROVAL PENDING`) ⇒ lesson tính completed; XP cộng theo trần `(user, lesson, contentVersion)` (`10/câu đúng + 20 bonus`), không farm được bằng submit trùng. Khi `P50_ENABLED=true`, hệ thống tạo `ReviewCard` và trả `reviewCardCreated=true`.

## 3. Journey C — Hỏi AI Tutor theo bài (P3 — IMPLEMENTED, `TUTOR_ENABLED=false`)

1. User mở `TutorPanel` tại block đang học: trên desktop (`≥1024px`) panel **dock cạnh bài học** rộng 400px (phi modal); trên `<1024px` mở dạng **overlay modal** có focus trap + `inert`.
2. Client `POST /v1/courses/{id}/tutor/messages` với `clientMessageId`, `threadId?`, `contextRef: {lessonId, blockIndex}` (nếu `TUTOR_ENABLED=false`, API trả `503 TUTOR_DISABLED`).
3. Backend xác minh owner/course/lesson/blockIndex từ DB, chạy tối đa `TUTOR_TOOL_MAX_CALLS` read-only tools nếu `TUTOR_TOOLS_ENABLED=true`, stream SSE (`delta`, `tool`, `done`, `error`, `cancelled`, `heartbeat`).
4. User bấm Dừng (`POST .../stop`): best-effort server cancellation, giữ phần nội dung đã nhận (`providerStopGuaranteed=false`).
5. User reload: đọc lại lịch sử từ `GET .../threads/{threadId}` (`replaySupported=false`, không hỗ trợ `Last-Event-ID`).

**Ngoại lệ đã xử lý:** `blockIndex` ngoài biên (422), lesson khác course/owner (404), smuggle field lạ (422), quota hết (429 + `quota`), double-click cùng `clientMessageId` (replay/409), disconnect/stale stream.

## 4. Journey D — Học từ PDF / Web / arXiv có citation (P4 — IMPLEMENTED, đa số `DEFAULT-OFF`)

1. User vào `/sources`, đăng ký nguồn (`POST /v1/sources`) và gắn vào course (`POST /v1/courses/{id}/sources`).
2. User upload PDF (`POST /v1/sources/{id}/document`, `SOURCE_INGEST_ENABLED=true`) hoặc nhập URL/arXiv kèm `userConfirmedRights=true` (`POST /v1/sources/{id}/web-document`, khi `WEB_INGEST_ENABLED=true` và host nằm trong allowlist).
3. Worker extract text theo trang (có nhánh OCR opt-in `rapidocr`/`vietocr` nếu `OCR_ENABLED=true`; nếu tắt, PDF scan trả `no_text`), chunk với provenance và sinh embedding (`hashing` mặc định hoặc `openai_compatible`).
4. Khi `RAG_ENABLED=true`, người học tìm kiếm (`POST /v1/courses/{id}/sources/search`) hoặc hỏi Tutor: retrieval lọc owner trong SQL trước khi RRF, server validate mọi `chk_*` citation theo allowlist của request. Không đủ bằng chứng ⇒ abstention rõ ràng (`insufficientEvidence=true`), không bịa citation.

## 5. Journey E — Mastery, lộ trình & ôn tập FSRS (P5 — IMPLEMENTED, `P50_ENABLED=false`)

1. Khi `P50_ENABLED=true`, trang `/course/[courseId]` gọi `GET /v1/courses/{id}/mastery` và `GET /v1/courses/{id}/learning-path` để hiển thị mức nắm vững từng skill (rule-based, gắn nhãn minh bạch) và bài tiếp theo theo prerequisite DAG kèm lý do.
2. Nếu `P52_EXPOSURE_ENABLED=true`, learning-path kèm `recommendationToken` (HMAC) để client gửi lại `POST /v1/courses/{id}/recommendation-events` thu thập dữ liệu exposure.
3. Trang `/review` tải hàng đợi đến hạn (`GET /v1/reviews/due`) và chấm 4 mức FSRS (`POST /v1/reviews/{cardId}/grade`, idempotent theo `clientReviewId`). Khi `P50_ENABLED=false`, UI hiển thị trạng thái tính năng đang tắt (503).

## 6. Cross-cutting acceptance

- Mọi tài nguyên của user khác trả 404 (chống existence leak).
- Reload và đổi tài khoản (A logout → B login) xóa toàn bộ query cache theo `user.id + sessionEpoch`.
- Trạng thái loading, empty, error, retry, cancelled, feature-disabled (503) hiển thị trung thực; không mock dữ liệu khi API chưa có.
