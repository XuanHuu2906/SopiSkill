# SopiSkill — Báo cáo tổng hợp Phase 4 → Phase 8

> **Ngày cập nhật:** 2026-11-25  
> **Nhánh hiện tại:** `feat/polyglot-phase9` (dựng từ commit chốt Phase 8 `2ac257c`)  
> **Kiến trúc:** Polyglot 2 dịch vụ — `core-api` (Spring Boot 3.4.5 / Java 21 Virtual Threads) + `ai-engine` (Python 3.12 / FastAPI + Redis Streams workers) + `frontend` (Next.js 15 / TanStack Query v5) trên PostgreSQL 16 (`pgvector`), Redis 7 và MinIO.  
> **Quy ước trạng thái:** **IMPLEMENTED** (đã có mã nguồn) · **TESTED** (đã thực thi test thật và PASS) · **NOT TESTED** (chưa chạy trên hạ tầng/provider trả phí bên ngoài).

---

## 1. Bảng tổng quan Phase 4 → Phase 8

| Phase | Tên giai đoạn | Commit | Flyway `core.*` | Trạng thái | Điểm kiểm chứng nổi bật |
|---|---|---|---|---|---|
| **Phase 4** | Nội dung bài học giàu tương tác (KaTeX, 4 loại Figure / 7 SVG, Multi-Blank, 5 Practice Formats) | `386f76c` | `V3` | **TESTED (PASS)** | `33/33` pytest, `6/6` JUnit, `7/7` E2E + `0` axe; `0` byte answer key lộ trên wire |
| **Phase 5** | Agentic AI Tutor "Sopi" Đa Pod (6 Tools, 3 Thread Kinds, `PlanChat`, `ChangeCard`, Redis SSE) | `6b1ac68` | `V4` | **TESTED (PASS)** | `38/38` pytest, `7/7` JUnit (**2 pod `core-api` song song**), `8/8` E2E + `0` axe |
| **Phase 6** | Gamification, Hearts (Timed + FSRS Refill), Milestones, `/complete` & Leagues | `264b7a4` | `V5` | **TESTED (PASS)** | `10/10` JUnit (20 luồng đồng thời = `100 XP`, 31 user tách 2 cohort `30+1`), `9/9` E2E + `0` axe |
| **Phase 7** | OAuth2 (Google/Apple), Rotating Refresh Sessions, Onboarding 4 bước, i18n (`vi`/`en`) & Web Push | `72c7340` | `V6` | **TESTED (PASS)** | `13/13` JUnit (RS256 anti-takeover, Refresh reuse detection, quiet hours `22:00–08:00`), `10/10` E2E + `0` axe |
| **Phase 8** | Offline-First IndexedDB Cache (6 Stores), Raw-Answer Outbox & Smart Prefetch | `2ac257c` | *(không đổi)* | **TESTED (PASS)** | `11/11` E2E (`setOffline(true)` → học & nộp → `setOffline(false)` → tự sync XP + cô lập `outbox.owner` A → B) |

---

## 2. Chi tiết từng Phase

### Phase 4 — Nội dung bài học giàu tương tác (`386f76c`)

#### Mục tiêu
Nâng cấp bài học từ dạng câu hỏi cơ bản lên hệ thống khối học tập đa phương thức (toán học, hình vẽ SVG, bảng so sánh, điền nhiều chỗ trống, tình huống, vòng tốc độ, trả lời ngắn có phúc khảo) nhưng giữ nguyên tuyệt đối nguyên tắc **0 answer key trên trình duyệt**.

#### Những gì đã thực hiện (**IMPLEMENTED**)
- **Cơ sở dữ liệu (`core-api` Flyway `V3`):**
  - `core-api/src/main/resources/db/migration/V3__short_answer_grades.sql`: tạo bảng `core.short_answer_grades` (`sag_`) lưu kết quả chấm câu trả lời ngắn 3 mức (`got_it | almost | not_yet`), `key_points JSONB`, `feedback`, và trạng thái phúc khảo (`disputed`, `dispute_reason`).
- **Backend (`core-api`):**
  - `PublicBlockProjector.java`:
    - Đàm phán năng lực client qua header `X-Client-Blocks` (`teach,mc,blank,multi_blank,order,match,short,speed,recap,figure`).
    - Mở rộng `teach` hỗ trợ `kicker`, `takeaway`, `terms[]`, `cite`, và **loại trừ tương hỗ** `figure` **HOẶC** `image`.
    - Nâng cấp `blank` sang **Multi-Blank Word Bank** (`parts`, `answers[1..4]` chỉ nằm ở server, `bank[2..10]` trộn HMAC tất định; vẫn tương thích ngược 100% với 1-blank).
    - Lọc sạch `answerIndex`, `mc.outcomes[]`, `answers`, `acceptedAnswers`, `keyPoints`, `solution` khỏi `GET /v1/lessons/{id}`.
    - Bổ sung `speed` (`SpeedRound` 60s chấm trên server), `recap` (không chấm điểm), `computeCorrectIndices` (khóa các vị trí đã điền đúng khi làm lại mà không lộ đáp án còn lại), `selectedOutcomeFor` (chỉ mở hệ quả của lựa chọn người học vừa bấm), và `evaluateShortThreeLevel` (`got_it | almost | not_yet`).
  - `LessonController.java`: mở rộng `POST /v1/lessons/{id}/blocks/{idx}/grade` (ẩn `solution` trên multi-blank/speed sai) và thêm `POST /v1/lessons/{id}/grades/{gradeId}/dispute` gọi sang `ai-api /internal/lessons/grade-short`.
- **AI Engine (`ai-engine`):**
  - `ai-engine/app/agents/figure_validator.py`: bộ kiểm định tất định cho **4 loại Figure** (`formula`, `table` với tone `moss|clay|neutral`, `visual`, `diagram` đủ **7 layout SVG**: `flow | timeline | branch | cycle | stack | split | hub`), chặn node mồ côi, cạnh trỏ sai node, số lẻ ở `split`, nhãn >48 ký tự ở `cycle`, và xung đột `figure + image`.
  - Cập nhật `validation.py`, `providers.py`, `config.py` (`LESSON_IMAGES_ENABLED=false` mặc định, 0đ chi phí).
- **Frontend (`frontend/`):**
  - Tự host 20 font KaTeX `.woff2` tại `frontend/public/fonts/katex/` + `frontend/src/app/katex-selfhosted.css` (không gọi CDN bên ngoài).
  - Tạo 7 component mới trong `frontend/src/components/lesson/`: `MathText.tsx` (KaTeX + thuật ngữ inline `{termKey}` mở `VocabSheet` lọc sẵn), `FigureRenderer.tsx` (4 loại Figure & 7 layout SVG), `CitationChip.tsx`, `MultiBlankWordBank.tsx`, `ScenarioAndSteps.tsx`, `SpeedRound.tsx` (hỗ trợ kéo/nút + bàn phím `←`/`→` chuẩn WCAG 2.1 AA), `RecapView.tsx`.
  - Nâng tương phản màu chủ đạo `--ember` (`#6746d9`, `6.03:1`) trong `globals.css`.

#### Kiểm chứng (**TESTED** / **NOT TESTED**)
- **TESTED:** `ai-engine` `33/33` pytest + `bandit` 0 findings; `core-api` `6/6` JUnit (gồm `Phase4IntegrationTest`); `frontend` `7/7` Playwright E2E + `axe-core` 0 violations (xác minh 0 byte đáp án lộ trên wire).
- **NOT TESTED:** Sinh ảnh qua provider trả phí (`LESSON_IMAGES_ENABLED=false`); chấm dispute qua LLM trả phí (đã kiểm đầy đủ hợp đồng trên `MockProvider`).

---

### Phase 5 — Agentic AI Tutor "Sopi" Đa Pod (`6b1ac68`)

#### Mục tiêu
Chuyển đổi Trợ giảng AI "Sopi" sang kiến trúc đa pod thực thụ (stateless sau Redis), hỗ trợ nối lại stream SSE không rớt chữ, hủy stream tức thì xuyên pod, mở rộng đủ 6 công cụ tự chủ và luồng chỉnh sửa đề cương / viết lại chương có xác nhận của người học.

#### Những gì đã thực hiện (**IMPLEMENTED**)
- **Cơ sở dữ liệu (`core-api` Flyway `V4`):**
  - `core-api/src/main/resources/db/migration/V4__tutor_threads_actions_and_entrypoints.sql`: mở rộng `core.tutor_threads` (`kind` `'course'|'anchor'|'task'`, `anchor_key`, `sealed`, `lesson_id` nullable cho `PlanChat`), `core.tutor_messages` (`entry_point`, `context_label`), và tạo bảng `core.tutor_actions` (`act_`, trạng thái `pending | confirmed | declined | preparing | ready | failed | unavailable`).
- **Backend (`core-api`):**
  - `TutorRedisStreamService.java`: ghi tuần tự toàn bộ SSE frame vào Redis Stream `tutor:stream:{messageId}` (TTL 10 phút) cho phép nối lại qua `Last-Event-ID` từ **bất kỳ pod nào**; phát & nhận lệnh dừng stream tức thì xuyên pod qua Redis Pub/Sub `tutor:cancel:{messageId}` + cờ ngắn hạn `tutor:cancelled:{messageId}`.
  - `GlobalTutorSessionsController.java` & `TutorController.java`:
    - `GET /v1/tutor/sessions`: danh sách phiên liên khóa học gom nhóm `thisWeek` / `earlier`.
    - `POST /v1/courses/{id}/tutor/sessions`, `GET /v1/courses/{id}/tutor` (lọc `entryPoint`, `anchor`, cursor `before`).
    - `GET /v1/courses/{id}/tutor/messages/{msgId}/stream`: nối lại stream bằng `Last-Event-ID` (hoặc phát sự kiện `restarted` khi quá hạn).
    - `POST /v1/courses/{id}/tutor/actions/{actionId}/{confirm|decline}`: khi `confirm`, khóa unit, tăng `content_version + 1` và đẩy job `regenerate_unit` lên Redis Stream `queue:ai:llm`.
    - Xử lý server-side cho `tool_effect`: `flag_question` → `core.content_flags`; `revise_proposal` → tạo `core.course_proposals` phiên bản `v+1`; `regenerate_unit` → tạo `core.tutor_actions` ở trạng thái `pending`.
  - `InternalCallbackController.java`: cập nhật `core.tutor_actions` sang `ready`/`failed` khi worker hoàn tất viết lại chương.
- **AI Engine (`ai-engine`):**
  - `ai-engine/app/agents/tutor_agent.py`: kích hoạt đủ **6/6 tools**: `read_lesson`, `explain_deeper`, `read_source` (tra `sourceBrief.sections` theo `section_anchor` + Hybrid RAG), `flag_question`, `revise_proposal`, và `regenerate_unit` (chỉ tạo bản xem trước chờ xác nhận, tuyệt đối không tự ý sửa bài).
- **Frontend (`frontend/`):**
  - `PlanChat.tsx` trên `/new/proposal` (trượt `ProposalCard` sang `v+1` và thu gọn bản cũ vào `"Bản nháp trước"`).
  - `ChangeCard.tsx`: hiển thị preview viết lại chương, nút xác nhận/từ chối và tự poll `5s` từ `preparing` cho tới `ready` (`"Đã cập nhật"`).
  - `TutorPanel.tsx` & `GlobalSopiSheet.tsx`: 6 bộ prompt chips theo `entryPoint`, badge tên tool tiếng Việt cho 6/6 tools, phiên liên khóa `Tuần này` / `Trước đó`, và tự động resume bằng `Last-Event-ID`.

#### Kiểm chứng (**TESTED** / **NOT TESTED**)
- **TESTED:** `ai-engine` `38/38` pytest + `bandit` 0 findings; `core-api` `7/7` JUnit — gồm `Phase5MultiPodTutorTest` chạy **2 instance `core-api` độc lập song song** sau Redis (mở SSE ở Pod 1 → ngắt TCP → resume `Last-Event-ID` vào Pod 2 đủ chữ; mở SSE ở Pod 1 → gọi `/stop` vào Pod 2 dừng tức thì); `frontend` `8/8` Playwright E2E + `axe-core` 0 violations.
- **NOT TESTED:** Chạy Sopi trên LLM provider trả phí (`MockProvider` mặc định 0đ); chaos xóa Pod thật trên cụm Kubernetes `kind` (lên lịch ở Phase 10).

---

### Phase 6 — Gamification, Hearts (Timed + FSRS Refill), Milestones, `/complete` & Leagues (`264b7a4`)

#### Mục tiêu
Hoàn thiện toàn bộ vòng lặp động lực học tập (XP, Streak theo múi giờ, Streak Freeze, Tim gắn kết FSRS, Huy hiệu cột mốc, Màn hoàn thành bài học và Bảng xếp hạng tuần) chạy nguyên tử trong **1 giao dịch ACID duy nhất** trên `core-api`.

#### Những gì đã thực hiện (**IMPLEMENTED**)
- **Cơ sở dữ liệu (`core-api` Flyway `V5`):**
  - `core-api/src/main/resources/db/migration/V5__gamification_hearts_milestones_leagues.sql`:
    - Mở rộng `core.users`: `timezone`, `goal_lessons` (`1|2|3`), `best_streak_days`, `last_active_day`, `streak_freezes` (`0..2`), `hearts` (`0..5`), `hearts_refill_at`.
    - Tạo 4 bảng: `core.user_daily_activity`, `core.user_milestones`, `core.league_cohorts` (`lgc_`, 5 hạng `bronze | silver | gold | sapphire | ruby`), `core.league_memberships` (`lgm_`).
- **Backend (`core-api`):**
  - `GamificationService.java`, `LeagueService.java`, `GamificationController.java`, `SopiProperties.java`:
    - Chuẩn hóa thưởng cấu hình được: `XP_LESSON_BASE = 80`, `XP_PERFECT_BONUS = 20` (tối đa `100 XP` / phiên bản bài học), thực thi trong `@Transactional` có khóa dòng `SELECT ... FOR UPDATE` trên `core.users`.
    - Tính Streak theo đúng `ZoneId` múi giờ người học; tự tặng `+1` `streak_freeze` mỗi bội số 7 ngày (tối đa `2`); tự tiêu `1` freeze khi lỡ đúng 1 ngày (`today - 2`).
    - **Hearts gắn kết FSRS:** `HEARTS_MAX = 5`, hồi theo thời gian (`30` phút/tim), tùy chọn chặn `409 OUT_OF_HEARTS` (`HEARTS_ENFORCEMENT_ENABLED`), và **cộng ngay `+1` tim** khi hoàn thành thẻ ôn tập đến hạn tại `POST /v1/reviews/{cardId}/grade` (`LearnerController.java`).
    - Tự mở khóa **7 nhóm Milestones + 9 Ladder Milestones (`16` huy hiệu)** trong cùng giao dịch nộp bài; trả thêm `unitBreakdown` & `newlyEarnedMilestones` tại `POST /v1/lessons/{lessonId}/attempts`.
    - Thêm `GET /v1/home`, `GET /v1/me/profile`, `PATCH /v1/me/preferences`, và `GET /v1/league` + `GET /v1/league/last` (giới hạn **30 học viên/cohort**, chốt hạng tuần top 20% thăng hạng / bottom 20% xuống hạng trừ `bronze`, sau cờ `LEAGUES_ENABLED=false` mặc định).
- **Frontend (`frontend/`):**
  - Trang mới `/lesson/[lessonId]/complete`: Confetti tôn trọng `prefers-reduced-motion`, điểm/độ chính xác/`+XP`/chuỗi/tim, `UnitBreakdown`, huy hiệu vừa mở khóa, gợi ý qua `/review` hồi tim FSRS; tự chuyển hướng từ `LessonPage` sau khi nộp bài.
  - `WeekChart.tsx` & `WeekRecapCard.tsx`: tích hợp vào trang chủ `/` và trang hồ sơ `/profile` (kèm lưới 16 huy hiệu đã đạt/chưa đạt và độ chính xác).
  - Trang mới `/league` và thông báo hồi `+1 tim` trên `/review`.

#### Kiểm chứng (**TESTED** / **NOT TESTED**)
- **TESTED:** `core-api` `10/10` JUnit — gồm `CoreApiIntegrationTest` (20 luồng đồng thời nhận đúng `100 XP`, 0 double-XP) và `Phase6GamificationTest` (ranh giới ngày `UTC` vs `Asia/Ho_Chi_Minh`, freeze ngày 7 & tự tiêu freeze, chặn `409 OUT_OF_HEARTS` → chấm FSRS hồi `+1` tim → nhận `100 XP` + milestones, **31 học viên tách đúng 2 cohort `30 + 1`** + chốt tuần thăng 6 người lên `silver`); `ai-engine` `38/38` pytest; `frontend` `9/9` Playwright E2E + `axe-core` 0 violations.
- **NOT TESTED:** Cron chốt hạng tuần tự động qua mốc Chủ nhật → Thứ Hai UTC (đã test trực tiếp `LeagueService.settleWeek` trong JUnit); giao diện `/league` khi bật `LEAGUES_ENABLED=true` trên trình duyệt (đã test API với `LEAGUES_ENABLED=true` trong JUnit và UI mặc định `false` trong E2E).

---

### Phase 7 — OAuth2 (Google/Apple), Rotating Refresh Sessions, Onboarding 4 bước, i18n & Web Push (`72c7340`)

#### Mục tiêu
Hoàn thiện xác thực đa phương thức chống chiếm đoạt tài khoản, cơ chế xoay vòng Refresh Token phát hiện đánh cắp phiên, luồng cá nhân hóa đầu vào 4 bước, đa ngôn ngữ tách biệt giao diện với bài học, và hệ thống nhắc học tôn trọng giờ yên lặng.

#### Những gì đã thực hiện (**IMPLEMENTED**)
- **Cơ sở dữ liệu (`core-api` Flyway `V6`):**
  - `core-api/src/main/resources/db/migration/V6__oauth_sessions_onboarding_and_push.sql`:
    - Mở rộng `core.users`: `avatar` (`happy|graduate|curious|wink|excited`), `locale`, `app_language`, `lesson_language`, `onboarded_at`, `onboarding_profile JSONB`.
    - Tạo 5 bảng: `core.user_sessions` (`ses_`), `core.auth_identities` (`aid_`), `core.notification_preferences`, `core.push_subscriptions` (`psh_`), `core.in_app_notifications` (`ntf_`).
- **Backend (`core-api`):**
  - `OAuthIdentityService.java` & `OAuthAndSessionController.java`:
    - Xác thực chữ ký mật mã RS256/ES256 cho OIDC ID Token **Google & Apple** (`POST /v1/auth/exchange`, kiểm tra `iss`, `aud`, `exp`, `sub`, `email`, chặn `alg=none` và tấn công hạ cấp `HS*`).
    - **Chống chiếm tài khoản:** nếu trùng email tài khoản hiện hữu, tuyệt đối không tự liên kết mà trả **`409 ACCOUNT_LINK_REQUIRED`** kèm `linkTicket` ký HMAC-SHA256 TTL 5 phút; buộc chứng minh quyền sở hữu (mật khẩu Argon2id hoặc phiên chủ tài khoản) tại `POST /v1/auth/link/confirm`; thêm `GET/POST /v1/me/identities`.
  - `SessionService.java` & `AuthAndMeController.java`:
    - Cấp song song HttpOnly `access_token` và **Rotating HttpOnly `refresh_token`** (`Path=/v1/auth`, chỉ lưu SHA-256 hash trong DB).
    - `POST /v1/auth/refresh`: xoay vòng trong cùng `family_id`; phát hiện phát lại token đã xoay/đã thu hồi sẽ **hủy tức thì toàn bộ `family_id`** (`401 REFRESH_TOKEN_REUSE_DETECTED`).
    - `POST /v1/auth/logout?all=true`: thu hồi phiên trên toàn bộ thiết bị.
  - `NotificationService.java`, `OnboardingAndNotificationsController.java`, `CourseController.java`:
    - `PUT /v1/me/onboarding`: lưu 4 nhóm (`roles, topics, learningStyles, goals`) và đính kèm `onboardingProfile` vào payload sinh khóa học gửi sang `ai-engine`.
    - `GET/PATCH /v1/me/notifications`: bắt buộc bước `15` phút (`0..1425`), khung giờ yên lặng qua đêm `22:00–08:00` theo múi giờ người dùng.
    - `POST/DELETE /v1/push/register` (kiểm tra endpoint HTTPS), In-App Inbox (`/v1/me/notifications/inbox`), và bộ quét đủ **7 loại thông báo** (`course.ready`, `course.failed`, `league.settled`, `daily.reminder`, `streak.guard`, `weekly.recap`, `comeback.nudge` ngày `2, 4, 8, 15`).
- **Frontend (`frontend/`):**
  - `I18nProvider.tsx` & `dictionaries.ts`: khung 12 ngôn ngữ, hoàn thiện 100% từ điển `vi` + `en`, đồng bộ tách biệt hoàn toàn `appLanguage` và `lessonLanguage`.
  - Trang 4 bước `/onboarding` + banner trên `/`, nút Google/Apple + `LinkAccountSheet.tsx` trên `/login`, `AvatarSheet.tsx` + cài đặt ngôn ngữ/thông báo/Web Push/đăng xuất mọi thiết bị trên `/settings`, Service Worker `frontend/public/sw.js`, và `NotificationCenter.tsx` trên thanh điều hướng.

#### Kiểm chứng (**TESTED** / **NOT TESTED**)
- **TESTED:** `core-api` `13/13` JUnit — gồm `Phase7SecurityAndOnboardingTest` (chặn token giả `401`, chống chiếm tài khoản `409 ACCOUNT_LINK_REQUIRED` + sai mật khẩu/ticket giả `401` + đúng mật khẩu `200`; xoay vòng Refresh `R1 → R2` + phát hiện reuse `R1` vô hiệu hóa cả `R2` + `logout?all=true`; Onboarding 4 bước + tách `appLanguage`/`lessonLanguage` + bước `15` phút + Web Push HTTPS + chặn hoàn toàn trong quiet hours `22:00–08:00` và phát đủ ngoài quiet hours); `frontend` `16/16` routes, `10/10` Playwright E2E + `axe-core` 0 violations.
- **NOT TESTED:** Trang consent thật trên domain Google/Apple và đẩy Web Push tới FCM/APNs thật (cần OIDC Client ID & VAPID keys production).

---

### Phase 8 — Offline-First IndexedDB Cache (6 Stores), Raw-Answer Outbox & Smart Prefetch (`2ac257c`)

#### Mục tiêu
Cho phép người học tiếp tục đọc bài, tra thuật ngữ và nộp câu trả lời mượt mà khi mất mạng/mạng yếu, tự động đồng bộ lấy điểm & XP thật khi có mạng trở lại, đồng thời giữ vững tuyệt đối nguyên tắc **0 answer key trên trình duyệt** và **cô lập dữ liệu giữa các tài khoản**.

#### Những gì đã thực hiện (**IMPLEMENTED**)
- **IndexedDB `sopiskill_offline_v1` (`frontend/src/lib/offline/db.ts`):**
  - Khởi tạo đúng **6 object stores**: `cached_courses`, `cached_lessons`, `cached_glossary`, `outbox_attempts`, `cached_reel_clips`, `local_prefs`.
  - Lớp lọc phòng thủ `stripForbiddenKeys` đảm bảo `cached_lessons` chỉ lưu `public_blocks` (**0 answer key**); `invalidateStaleCachedLesson` tự xóa bài cache ngay khi `contentVersion` trên server tăng.
  - Cô lập chủ sở hữu nghiêm ngặt: `clearOfflineDatabase()` xóa sạch 6 stores khi `logout`, và `ensureOfflineOwner(userId)` tự quét sạch toàn bộ nếu phát hiện chuyển đổi người dùng A → B.
- **FIFO Raw-Answer Outbox (`frontend/src/lib/offline/outbox.ts`):**
  - `enqueueOfflineAttempt` lưu câu trả lời thô gắn chặt `outbox.owner = user.id` khi ngoại tuyến hoặc lỗi mạng (không chấm điểm cục bộ).
  - `flushOutboxAttempts` xả FIFO lên `core-api` `POST /v1/lessons/{id}/attempts`, chỉ xử lý bản ghi thuộc `currentUserId`, áp dụng exponential backoff `min(5s * 2^(attempts-1), 300s)` cho lỗi mạng/5xx, drop sạch lỗi `4xx` không thể phục hồi (trừ `401`), và phát sự kiện `sopiskill:attempt-synced` để nâng cấp trực tiếp màn `/lesson/[id]/complete` lên kết quả & XP thật.
- **Smart Prefetch & Service Worker App Shell (`prefetch.ts`, `frontend/public/sw.js`):**
  - Tải trước `path` + `glossary` + **3 bài `ready` tiếp theo** trên Wi-Fi (**1 bài** khi bật `saveData` hoặc mạng chậm `slow-2g/2g/3g`), bỏ qua các unit/lesson đang `paywalled`.
  - Nâng cấp Service Worker `sw.js` cache App Shell, RSC payload và static chunk (tuyệt đối không cache `/v1/*` hay đáp án) giúp chuyển trang `/course/[id] → /lesson/[id] → /lesson/[id]/complete` hoạt động trơn tru khi ngoại tuyến hoàn toàn.
- **Tích hợp UI (`OfflineProvider.tsx`, `OfflineBar.tsx`, `providers.tsx`, `CoursePage`, `LessonPage`, `CompletePage`, `VocabSheet`):**
  - Bật `networkMode: "always"` trên các query có fallback IndexedDB (`useAuth`, `CoursePage`, `LessonPage`, `VocabSheet`), hiển thị `OfflineBar` rõ ràng và thẻ `Chờ đồng bộ ngoại tuyến` trên `/complete`.

#### Kiểm chứng (**TESTED** / **NOT TESTED**)
- **TESTED:** `frontend` lint/typecheck/build (`0` warnings, `16/16` routes); `11/11` Playwright E2E + `axe-core` 0 violations — kịch bản #11 kiểm chứng trực tiếp:
  - IndexedDB `sopiskill_offline_v1` có đủ 6 stores và **0 answer key** trong `cached_lessons`.
  - `context.setOffline(true)` → hiện `OfflineBar` → mở Bài 1 từ cache → tra `VocabSheet` ngoại tuyến → hoàn thành & nộp bài → `/complete` hiện `Chờ đồng bộ ngoại tuyến` (`outbox_attempts = 1`).
  - `context.setOffline(false)` → tự xả FIFO `outbox_attempts` (`0`), `/complete` tự nâng cấp sang `UnitBreakdown` & XP thật, trang chủ ghi nhận XP thật từ server.
  - Cô lập `outbox.owner` khi chuyển tài khoản A → B (kể cả khi cấy bản ghi ngoại lai của A): `ensureOfflineOwner` xóa sạch toàn bộ, User B có `0` outbox và `0 XP`.
- **NOT TESTED:** Kiểm thử trên thiết bị di động vật lý ở chế độ `saveData=true` / mạng `2g` thật (hàm `computePrefetchBudget()` đã được triển khai chuẩn theo `navigator.connection`).

---

## 3. Các nguyên tắc bất biến được bảo toàn xuyên suốt Phase 4 → Phase 8

1. **0 Answer Key trên Frontend & AI Tutor:** Cả mạng (`GET /v1/lessons/{id}`), AI Tutor (`publicBlocks`), lẫn IndexedDB (`cached_lessons` + `stripForbiddenKeys`) đều không chứa bất kỳ khóa đáp án nào; 100% chấm điểm diễn ra trên `core-api`.
2. **Toàn vẹn giao dịch & chống race condition:** Mọi ghi nhận Attempt, XP, Streak, Freeze, Hearts, Mastery, FSRS, Milestones và League XP chạy gọn trong 1 `@Transactional` với `SELECT ... FOR UPDATE`.
3. **Bảo mật xác thực & quyền sở hữu:** Mọi tài nguyên đều kiểm tra `owner = authenticated userId` ở server; OAuth2 RS256 chống chiếm tài khoản (`409 ACCOUNT_LINK_REQUIRED`); Refresh Token xoay vòng phát hiện reuse; IndexedDB & TanStack Query cô lập hoàn toàn khi chuyển tài khoản A → B.
4. **Chuẩn tiếp cận & chi phí 0đ mặc định:** `axe-core` WCAG 2.1 AA đạt **0 violations** trên tất cả 11 kịch bản E2E; 100% bộ kiểm thử mặc định chạy offline/local với `MockProvider` và cờ tính năng trả phí mặc định tắt.

---

## 4. Phần còn lại của lộ trình Master Parity

- **Phase 9 (`feat/polyglot-phase9` — đã tạo nhánh, chưa bắt đầu code):** Entitlements (`Free`/`Pro`), Paywall, `MockBillingGateway`, `SePayVietQrGateway` (VietQR), `PolarGateway` (quốc tế) và Flyway `V7`.
- **Phase 10:** 2-Phase Narrated Reel Engine (`TTSProvider` + Safe AST Plot, Flyway `V8`) và đóng gói Kubernetes (`Helm` + `HPA` + `KEDA` + `kind` Multi-Pod Chaos E2E).
