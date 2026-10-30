# Development Progress

> Ghi nhận trạng thái thực tế. Quy ước: **IMPLEMENTED** (có code) / **TESTED** (đã chạy và pass) / **NOT TESTED** (chưa chạy).

## 2026-10-30 — P2.0 LLM Provider Infrastructure (Provider-Neutral)
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **Fail-fast thay vì fallback**: provider lạ/thiếu key/model/base URL ⇒ `ProviderConfigError` ⇒ API 503 `PROVIDER_NOT_CONFIGURED`. Mock chỉ khi `LLM_PROVIDER=mock`.
  - Provider thật đã được người dùng duyệt cho smoke test: **Deploy.com** (`https://api-cdn.deploy.com/api/v1`) + model `deepseek-ai/deepseek-v4.1-flash-1017`. Key **chỉ** trong `.env` (gitignored), không commit, không log.
  - `LLM_PROVIDER` đã được đưa về `mock` sau smoke test để `docker compose up` không tự phát sinh chi phí.
  - Semantic lint **repair** case đáp án blank bị lộ trong câu (thay bằng `____`) thay vì fail — tránh đốt thêm request mà nội dung vẫn dùng được.
- IMPLEMENTED:
  - `backend/app/providers/base.py`: error taxonomy đầy đủ (`ProviderConfigError`, `ProviderAuthError`, `ProviderTimeoutError`, `ProviderRateLimitError`, `ProviderTransientError`, `ProviderBudgetError`, `SchemaInvalidError`) với `code` + `retryable`.
  - `backend/app/providers/validation.py` (mới): semantic rules interview (đúng 5, không trùng), proposal (unit/bài không trùng, có outcome), lesson (≥1 teach + ≥1 quiz, `answerIndex` bounds, option trùng, blank mask, order/match trùng khóa).
  - `backend/app/providers/openai_compatible_provider.py` (mới): adapter `/chat/completions`, timeout, retry backoff+jitter (tôn trọng `retry-after`), bounded retries, budget token, cắt input theo `LLM_MAX_INPUT_CHARS`, log metadata redacted (`provider/model/prompt_version/tokens` — không key/prompt).
  - `backend/app/providers/__init__.py`: registry `mock | openai | openai_compatible`, `provider_name()`, fail-fast.
  - `backend/app/core/config.py`: `llm_api_key/llm_base_url/llm_model/llm_timeout_seconds/llm_max_retries/llm_max_output_tokens/llm_max_input_chars` + `llm_api_key_resolved`.
  - `backend/app/api/v1/routes.py`: `_provider()` → 503 cấu hình; `course_service._generate_proposal` map `ProviderError` → 503 (không lộ chi tiết).
  - `backend/app/services/job_service.py`: `classify_error` dùng taxonomy provider (`retryable`) thay vì đoán theo kiểu exception.
  - `backend/app/worker/generation.py`: `asyncio.TimeoutError` → `ProviderTimeoutError` để retry đúng.
  - `docker-compose.yml`: truyền `LLM_API_KEY/BASE_URL/MODEL` cho backend/worker/beat.
  - `.env.example`: block cấu hình provider mới. `docs/llm-provider.md` (mới): bật/tắt, taxonomy, validation, riêng tư, rollback.
- TESTED:
  - `python -m pytest -q` → **119 passed, 6 skipped** (13.72s). Mới: `tests/test_llm_provider.py` (28 test mocked HTTP) + `tests/test_provider_config_api.py` (4 test fail-fast API) + 3 test taxonomy trong `test_job_reliability.py`.
  - Mocked HTTP coverage: valid output, JSON hỏng, non-object JSON, sai số câu hỏi, câu trùng, proposal trùng bài, `answerIndex` OOB, thiếu teach, blank lộ đáp án (repair), blank không marker, 429+retry-after (retry rồi thành công + hết retry), 5xx bounded, timeout, connection error, 401 không retry, 400 không lộ body, budget vượt trần token, content rỗng, fail-fast key/model/base URL, provider lạ không phải mock, log không chứa key/prompt, input truncation.
  - `npm run build` không đổi (backend-only phase).
  - `E2E_BASE=… python backend/e2e_acceptance.py` → **35/35 PASS** (mock vẫn là mặc định).
  - **REAL PROVIDER SMOKE TEST (được duyệt, 3 request):** Deploy.com + `deepseek-ai/deepseek-v4.1-flash-1017`
    - interview: 5 câu, schema OK, 4.79s, 150 prompt / 196 completion tokens
    - proposal: 3 unit / 12 bài / 7 outcome, 13.89s, 422 / 1879 tokens
    - lesson: 5 block (`teach`, `mc`, `blank`, `short`), 12.05s, 384 / 1319 tokens
    - Tất cả HTTP 200; log chỉ chứa metadata. Phát hiện + sửa 1 lỗi thật: LLM trả block `blank` có đáp án nằm sẵn trong câu → server mask thành `____` (có unit test).
- NOT TESTED: streaming responses; provider thứ hai (Anthropic) — không triển khai; cost estimate chính xác (provider không trả giá); P2.1 hierarchical generation bằng LLM thật.
- BLOCKED: **P2.0.3 real E2E tự động trong CI** — cần biến môi trường/ngân sách riêng; không đưa key vào CI. P2.1 real e2e cần duyệt thêm budget cho 10 topic eval.
- Database: không đổi schema (revision vẫn `0004_p12_job_reliability`).
- Security: key server-only (`.env`, gitignored, `LLM_PROVIDER=mock` mặc định); API 503 không lộ env; log redacted; input bị cắt; output vượt budget → `ProviderBudgetError`; không có nhánh fallback ngầm.
- Regressions: 0. pytest 84 → 119; E2E 35/35; build OK.
- Known limitations:
  - `LLM_MAX_OUTPUT_TOKENS` cao (1879 token cho proposal) → cần hạ xuống hoặc thêm `max_completion_tokens` theo provider nếu muốn tiết kiệm.
  - `response_format=json_object` là phần mở rộng; provider không hỗ trợ sẽ trả 400 → `SchemaInvalidError`.
  - Chưa lưu `cost_estimate` vào DB job (chỉ log token); P2.2 sẽ làm metrics/cost.
- PHASE GATE: **PARTIAL** — infrastructure + mocked tests + 1 real smoke test đạt; **BLOCKED** phần tự động hoá real-provider trong CI và P2.1 real eval.
- NEXT: P2.1 AI Course Generator + Pedagogy DAG (cần duyệt budget cho 10-topic eval trước khi chạy real).

## 2026-10-30 — P1.3 Frontend UX, Navigation & Session Isolation
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **Session isolation** không chỉ ở server: client gắn `user.id` + `sessionEpoch` vào mọi query key (`useSessionQueryKey`) và `removeQueries()` khi login/logout. Không có `localStorage` user id nào còn sót.
  - Route guard là **UX** (`useRequireAuth` → `/login?next=…`); ownership vẫn do backend enforce (404).
  - Endpoint mới `GET /v1/courses` — không nhận `userId` từ client, luôn scope theo identity đã xác thực.
  - Interview reload: server không trả nội dung câu trả lời cũ (tránh lộ trên máy khác); UI hiển thị "✓ đã trả lời" cho các câu đã xong và tự nhảy tới câu kế tiếp; đủ 5 câu → chuyển thẳng proposal.
- IMPLEMENTED:
  - `backend/app/services/course_service.py::list_courses`: phân trang `limit/offset`, order theo `updated_at desc`, progress từ attempts (dùng lại `_completed_lesson_ids`), `resumeLessonId/resumeLessonTitle/lastCompletedLessonTitle`.
  - `backend/app/api/v1/routes.py`: `GET /v1/courses` (`limit` 1..50, `offset` ≥0), `CourseListOut`/`CourseListItemOut`.
  - `frontend/src/app/providers.tsx` (viết lại): `SessionProvider` (epoch), `useSessionQueryKey`, `useRequireAuth`, `useSessionRefresh`, `useRedirectAfterLogin` (chặn open redirect), `useLogout` clear cache; retry policy không retry 4xx.
  - `frontend/src/app/page.tsx`: dashboard "Khóa học của tôi" (5 gần nhất, tiến độ %, link "Học tiếp", empty/loading/error+retry).
  - `frontend/src/app/login/page.tsx`: guard-safe (`Suspense` cho `useSearchParams`), hỗ trợ `?next=`, label `htmlFor`, `role="alert"`, nút toggle `type="button"`.
  - `frontend/src/app/new/**`: route guard, session-scoped keys, interview reload logic, proposal hiển thị trạng thái `approved` và disable nút, generating phân biệt trạng thái/lỗi retryable.
  - `frontend/src/app/course/[courseId]`, `lesson/[lessonId]`: route guard, session-scoped key, invalidate `["session"]` sau khi nộp quiz.
  - `frontend/src/app/globals.css`: `.sr-only`, `.course-list`, `:focus-visible`, `prefers-reduced-motion`.
  - `frontend/src/lib/api.ts`: `fetchCourses`, type `CourseList/CourseListItem`.
  - `backend/e2e_acceptance.py`: +5 check (10, 10b, 10c, B3, B4) → **35/35**.
- TESTED:
  - `python -m pytest -q` → **84 passed, 6 skipped** (9.03s). Thêm `tests/test_courses_list.py` (6 test: scoped, pagination, param range 422, resume chuyển bài, 401, không có tham số userId).
  - `npm run build` → OK (9 routes). `npx tsc --noEmit` → không lỗi. Frontend container rebuild; `/`, `/login`, `/new`, `/course/crs_x`, `/lesson/lsn_x`, `/new/interview?courseId=crs_x` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **35/35 PASS** (10 dashboard scoped; 10b progress+resume; 10c pagination; B3 B không thấy course A; B4 B bị 404 ở generation/proposal/interview).
- NOT TESTED: browser automation thật (Playwright) cho cache isolation/login-switch; screen reader; kiểm thử mạng chập chờn trên UI; `next lint` (chưa có ESLint config, không tự tạo).
- BLOCKED: none.
- Database: không đổi schema (chỉ thêm endpoint & query), revision vẫn `0004_p12_job_reliability`.
- Security: `GET /v1/courses` bỏ qua mọi tham số `userId` (test chứng minh); guard chỉ là UX, dữ liệu vẫn 404 ở server; open-redirect chặn `//` và URL ngoài; 401 không bị retry vô hạn; không log token/cookie.
- Regressions: 0. pytest 78 → 84; E2E 30 → 35; build OK.
- Known limitations:
  - Cache isolation dựa trên TanStack Query key + `removeQueries`; nếu service worker/cache CDN được thêm sau này cần rà lại.
  - `sessionEpoch` reset khi full reload (by design — cache cũng mất theo).
  - Interview chưa cho phép sửa câu trả lời đã gửi (server không giữ bản nháp); nằm ngoài contract hiện tại.
  - Dashboard mới hiển thị 5 khóa gần nhất ở trang chủ; chưa có trang danh sách đầy đủ.
- PHASE GATE: **PASS** (A→logout→B không lộ cache; list chỉ của B; reload giữ tiến độ; build pass; E2E 35/35).
- NEXT: P2.0 LLM Provider Infrastructure (provider-neutral, mock vẫn mặc định). **ĐÃ HOÀN THÀNH** — xem entry phía trên.

## 2026-10-30 — P1.2 Reliable Generation Jobs & Safe Retries
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - State machine: `queued → running → ready`, và `running → queued` (transient, bounded) hoặc `→ failed` (fatal/hết lượt). Approve/retry giữ `queued` rồi dispatch.
  - **Outbox**: `dispatched_at IS NULL` = "DB đã commit nhưng broker chưa nhận". Reconciler (Celery beat, 30s) gửi lại; không bao giờ bỏ job kẹt `queued`.
  - **Không phải exactly-once**: claim nguyên tử đảm bảo *một worker chạy một lần tại một thời điểm*; redelivery là no-op.
  - `attempts_count` = số lần worker claim (bắt đầu 0, chặn bởi `max_attempts`=3). Không dùng để đếm retry của người dùng.
  - Inline fallback chỉ cho dev/test; compose đặt `GENERATION_ALLOW_INLINE_FALLBACK=false` cho backend/worker/beat.
- IMPLEMENTED:
  - `backend/app/services/job_service.py` (mới): `claim_job` (`UPDATE ... WHERE queued OR lease hết hạn RETURNING`), `renew_lease`, `is_superseded`, `finish_ready`, `fail_or_requeue`, `classify_error`, `retry_countdown` (backoff 2/4/8… chặn 60s), `dispatch_job` (broker + outbox ack + `dispatch_attempts`), `recover_stuck_jobs`, `_fail_exhausted`.
  - `backend/app/worker/generation.py` (viết lại): claim trước khi làm gì, heartbeat mỗi lesson, `asyncio.wait_for(provider.generate_lesson, timeout)`, chặn `SUPERSEDED`/`LEASE_LOST`, giữ `course_id` scalar sau rollback (fix MissingGreenlet), retry có backoff qua `fail_or_requeue`.
  - `backend/app/worker/reconcile.py` (mới) + `celery_app.beat_schedule`: reconciler định kỳ.
  - `backend/app/worker/celery_app.py`: `acks_late`, `prefetch=1`, time limits, `visibility_timeout`.
  - `backend/app/services/course_service.py`: `_lock_course_row` (`SELECT … FOR UPDATE` + `populate_existing`) trước khi kiểm tra state; `_active_job` chặn tạo 2 job; pin `proposal_version`; 409 `JOB_ALREADY_ACTIVE`.
  - `backend/app/api/v1/routes.py`: dispatch qua `job_service` (không raise khi broker lỗi); `GenerationOut` thêm `attempts`, `dispatched`, `lastErrorCode`.
  - `backend/alembic/versions/0004_p12_job_reliability.py` (mới, expand-only): 7 cột + index `(status, created_at)`.
  - `docker-compose.yml`: thêm service `beat`; `GENERATION_ALLOW_INLINE_FALLBACK=false` cho backend/worker/beat.
  - Frontend `new/generating`: `useMutation` retry (chống spam), label trạng thái tiếng Việt, hiển thị "đang chờ worker" khi `dispatched=false`, phân biệt lỗi retryable, dừng poll ở terminal state.
  - `.env.example`: 6 biến reliability. `e2e_acceptance.py`: +3 check (5b, 5c, 5d) → **30/30**.
- TESTED:
  - `python -m pytest -q` → **78 passed, 6 skipped** (10.04s). 6 skip = 2 file race PostgreSQL khi thiếu `POSTGRES_TEST_URL`.
  - `POSTGRES_TEST_URL=… pytest tests/test_p11_postgres_concurrency.py tests/test_p12_postgres_concurrency.py -q` → **6 passed** (3.21s): 10 worker claim đồng thời ⇒ đúng 1 thắng; 10 approve đồng thời ⇒ đúng 1 job; lease hết hạn ⇒ 1 worker claim lại; reconciler idempotent.
  - `npm run build` → OK. Frontend rebuild + `/`, `/login`, `/new/generating` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **30/30 PASS** (5b `dispatched=true attempts=1`; 5c retry tạo job mới; 5d retry không phá bài đã học).
  - **Failure injection trên Docker stack thật:**
    - *Redis down:* `docker compose stop redis` → approve vẫn **202**, job `queued` với `dispatched=false`, `attempts=0` (không báo thành công giả). `docker compose start redis` → beat phát reconciler sau ≤30s, log `reconciler recovered jobs count=1`, job → **ready** (`dispatch_attempts=2`).
    - *Worker chết:* force `lease_expires_at = now()-10min` trên job đang `running` → reconciler requeue, worker mới claim (`attempts_count=2`), sinh đủ **4 lessons**, không trùng.
    - *Duplicate delivery:* chạy task 2 lần cùng job → 4 lessons (không nhân đôi), job ready.
    - *Provider timeout / schema invalid:* unit test với provider giả → `PROVIDER_TIMEOUT` ⇒ requeue; `PROVIDER_SCHEMA_INVALID` ⇒ failed ngay; bài cũ giữ nguyên.
  - Alembic DB tạm: `0003 → 0004` (7 cột + index đúng), `downgrade -1` về `0003` (còn 10 cột), `upgrade head` lại OK, autogenerate ⇒ `pass`.
  - DB chính `ailp`: `0004_p12_job_reliability (head)`; 37 users / 28 courses / 64 lessons / 17 attempts / 18 jobs / 32 units (đã tăng do các lần chạy E2E/failure-injection — dữ liệu seed cũ 24 users vẫn còn).
- NOT TESTED: Celery broker failover nhiều node; real LLM provider cost/latency; load test nhiều job song song; `next lint` (Next 15 yêu cầu khởi tạo ESLint interactively — chưa cấu hình, không tự ý tạo config).
- BLOCKED: none.
- Database: revision `0004_p12_job_reliability`. Backup trước migration: `backup_pre_p12_20261030_234631.sql` (10 COPY, 130 KB, đã gitignore). Không xoá volume, không drop bảng.
- Security: ownership giữ nguyên (404 cross-user); lỗi provider được rút gọn ≤200 ký tự, không log prompt/key; không có endpoint nào cho client tự set `status` job; `JOB_ALREADY_ACTIVE` chặn double-approve cả ở DB lock.
- Regressions: 0. E2E 27 → 30 check, pytest 57 → 78.
- Known limitations:
  - Exactly-once vẫn không tuyệt đối (worker crash *sau* khi ghi lesson nhưng *trước* commit cuối → lần claim sau upsert lại theo `order_index`, nên không nhân bản; nhưng `lessons_done` có thể nhảy).
  - `_fail_exhausted` dùng chung `CourseStatus.failed` — chưa tách mã lỗi cấp course.
  - Reconciler là single beat instance; nhiều instance sẽ dispatch trùng (vô hại vì claim nguyên tử, nhưng tốn broker message).
  - Chưa có metric Prometheus/OTel (để P6).
- PHASE GATE: **PASS** (claim race + outbox recovery + bounded retry + no-false-success đều có bằng chứng chạy thật trên Docker; không mất dữ liệu).
- NEXT: P1.3 Frontend UX, Navigation & Session Isolation. **ĐÃ HOÀN THÀNH** — xem entry phía trên.

## 2026-10-30 — P1.1 Quiz Integrity, Progress, XP & Content Versioning
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions:
  - **PROPOSAL (policy mới)**: lesson `completed` khi có attempt đạt **≥80%** trên `contentVersion` hiện hành (`lesson_content.COMPLETION_THRESHOLD_PERCENT = 80`). Không đồng nhất `LessonStatus.ready` với "đã học".
  - **PROPOSAL (XP)**: XP tính theo `(user, lesson, contentVersion)` với mức thưởng tối đa; nộp lại/retry chỉ nhận phần chênh lệch, tổng không vượt mức tối đa ⇒ không farm XP. Sinh lại nội dung (version mới) cho phép nhận XP cho version mới.
  - **PROPOSAL (post-submit)**: `GET lesson` không bao giờ trả đáp án; response nộp bài có `results[i].solution` (đáp án) để UI hiển thị sau khi nộp.
- IMPLEMENTED:
  - `backend/app/services/lesson_content.py` (mới): public projection (loại `answerIndex`/`answer`/`acceptedAnswers`/`pairs`), shuffle ổn định theo `sha256(lessonId:contentVersion:blockId)` cho order/match + id public, grading deterministic dùng id public, `solution_for`, `is_completed`.
  - `backend/app/services/grading_service.py`: **xoá** — thay bằng `lesson_content` (một nguồn chấm duy nhất, không còn hai logic lệch nhau).
  - `backend/app/services/lesson_service.py`: ownership bằng JOIN `courses.user_id`; validate duplicate index + index ngoài bounds (422); `SELECT users.xp ... FOR UPDATE` để tuần tự hoá XP; idempotency theo `(lesson,user,clientAttemptId)` + bắt `IntegrityError` khi race; ghi `attempt.xp_awarded`; XP không vượt mức tối đa cho version.
  - `backend/app/api/v1/routes.py`: GET lesson trả `public_blocks`; attempt trả `xpEarned = attempt.xp_awarded` (không tính lại từ score); course detail nhận `user_id`.
  - `backend/app/services/course_service.py`: `_completed_lesson_ids()` tính progress từ attempts của version hiện hành; `get_course_detail` trả `progress` + `lessons[].completed`; `approve_course` set `proposal.approved_at`.
  - `backend/app/models/models.py`: `LessonAttempt.xp_awarded`, `XpEvent.content_version`, index `ix_xp_events_lesson_version`.
  - `backend/alembic/versions/0003_p11_quiz_integrity.py` (mới, expand-only): 2 cột + 1 index, idempotent theo inspector; downgrade drop đúng phần thêm.
  - `backend/app/schemas/schemas.py`: `LessonSummaryOut.completed`, `AttemptResultOut.solution`, `AttemptAnswer` `extra=forbid` + từ chối `answer` kiểu bool (chặn coerce `true`→`1`).
  - `backend/app/worker/generation.py`: chỉ tăng `content_version` khi title/nội dung **thực sự** đổi (so sánh qua chữ ký JSON để tuple/list không gây bump giả); `except Exception`.
  - Frontend `frontend/src/app/lesson/[lessonId]/page.tsx`: viết lại cho public blocks (order/match dùng id), `clientAttemptId` ổn định theo fingerprint nội dung (retry mạng không tạo attempt mới), `useMutation` + invalidate `["course"]`/`["me"]`, loading/error/retry, aria-label cho nút điều hướng.
  - Frontend `frontend/src/app/course/[courseId]/page.tsx`: hiển thị tiến độ %, badge "✓ đã học", loading/error/retry.
  - `backend/e2e_acceptance.py`: dựng đáp án từ **private content trong DB** (`E2E_PG_DSN`, không đọc public payload) + 6 check mới (7b, 8c, 8d, 9b, 9c, 9d) → **27/27**.
- TESTED:
  - `python -m pytest -q` (backend) → **57 passed, 2 skipped** (6.48s). 2 skip = test race PostgreSQL khi thiếu `POSTGRES_TEST_URL`.
  - `POSTGRES_TEST_URL=...p11_race_check python -m pytest tests/test_p11_postgres_concurrency.py -q` → **2 passed** (1.07s): 20 request đồng thời cùng `clientAttemptId` ⇒ 1 attempt, XP = 70 đúng 1 lần; 20 request với id khác nhau ⇒ 20 attempt nhưng XP vẫn 70.
  - `npm run build` → OK, 9 routes. Frontend container rebuild + `GET /lesson/...`, `/course/...`, `/login` → 200.
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` (Docker stack, code mới) → **27/27 PASS**: gồm `7b GET lesson không lộ answer key`, `8c nộp lại không farm XP`, `8d client gửi correct=true → 422`, `9b progress từ attempt 25%`, `9c lesson được đánh dấu`, `9d stale version → 409`.
  - Alembic trên DB tạm `g0_fresh_verify`: `0002 → 0003` (2 cột + index đúng), `downgrade -1` về `0002` (cột biến mất), `upgrade head` lại OK; `alembic revision --autogenerate` ⇒ `pass` (không drift).
- NOT TESTED: LLM thật (không có key); browser automation (Playwright) cho UI; load test.
- BLOCKED: none.
- Database: revision `0003_p11_quiz_integrity` đã áp dụng trên DB chính `ailp`. Backup trước migration: `backup_pre_p11_20261030_231407.sql` (10 COPY, 107 KB). Sau migration: 24 users / 32 lessons / 6 attempts **giữ nguyên**. Downgrade path: drop 1 index + 2 cột (rows cũ `xp_awarded=0`, `content_version=NULL`); không backfill vì không tái dựng được XP lịch sử chính xác.
- Security: answer key không rời server trước khi nộp (test cả 5 loại block); client không thể gửi `correct`/field lạ (422) hay bool; ownership vẫn 404 ở course + lesson; XP dưới row lock; `solution` chỉ có trong response POST attempts.
- Regressions: E2E cũ vẫn pass (21 → 27 check, 0 fail); pytest 40 → 57 (+17); build OK.
- Known limitations:
  - `GET /v1/courses/{id}` giờ chạy thêm 1 query attempts (nhỏ, có index `(lesson_id,user_id)` sẵn có); có thể gộp aggregate sau.
  - Progress threshold 80% là PROPOSAL chưa được người dùng duyệt riêng — đổi qua hằng số `COMPLETION_THRESHOLD_PERCENT`.
  - `xp_events.content_version` NULL cho rows lịch sử (trước 0003) ⇒ các attempt cũ không được tính vào "XP đã cộng theo version" (chỉ ảnh hưởng nếu user nộp lại bài cũ sau khi có version tăng; hành vi an toàn: cộng thêm tối đa 1 lần).
  - Chưa có endpoint danh sách attempts (chỉ dùng nội bộ).
- PHASE GATE: **PASS** (6/6 acceptance criteria có bằng chứng chạy thật; race test trên PostgreSQL pass; không mất dữ liệu).
- NEXT: P1.2 Reliable Generation Jobs & Safe Retries.

## 2026-10-30 — G0 Audit, Quality Gate & Migration Consistency
- Base commit: `464e5e19d978e0afee58960a73f44451c43fbdcf` (branch `main`, HEAD == baseline, không có commit mới)
- New commit/branch: NOT COMMITTED (working tree)
- Scope & decisions: re-audit baseline, chạy lại toàn bộ test/build/E2E, kiểm tra revision Alembic trên **DB tạm**, rà code course/lesson/worker/provider để chốt backlog P1.1/P1.2. Không sửa `0001_initial.py` / `0002_auth_columns.py`.
- IMPLEMENTED:
  - `backend/alembic/env.py`: import `app.models` để `Base.metadata` có bảng thật. **Trước fix:** `alembic revision --autogenerate` trên DB vừa upgrade head sinh migration **drop toàn bộ 9 bảng** vì metadata rỗng (đã kiểm chứng bằng file autogen rồi xoá). **Sau fix:** autogenerate sinh `upgrade(): pass` (no drift). Không đổi revision nào.
- TESTED (môi trường: Windows, Python 3.13.7, Docker Compose stack đang chạy, PostgreSQL 16):
  - `python -m pytest -q` (backend) → **40 passed, 8 warnings, 3.01s** (exit 0). Cảnh báo: httpx per-request cookies deprecated; `HTTP_422_UNPROCESSABLE_ENTITY` deprecated alias.
  - `npm run build` (frontend) → **thành công**, 9 routes (`/`, `/login`, `/new*`, `/course/[courseId]`, `/lesson/[lessonId]`).
  - `E2E_BASE=http://127.0.0.1:8001 python backend/e2e_acceptance.py` → **21/21 PASS** (auth, CSRF 403, unauth 401, cross-user 404, generate 4 lessons, quiz 5/5, reload, token giả 401).
  - Docker: `docker compose ps` → 5/5 service chạy; `/health` → `{"status":"ok","env":"development","provider":"mock"}`.
  - Alembic trên **DB tạm `g0_revision_verify`** (tạo mới trong container `db`, port host 5433; **không đụng `ailp`**):
    - `alembic upgrade head` → `0002_auth_columns (head)`; 9 bảng + `alembic_version`; `users` = 10 cột, `email`/`password_hash` nullable.
    - `alembic downgrade -1` → `0001_initial`; `users` còn 8 cột (mất đúng 2 cột auth) và chỉ còn `users_external_id_key`.
    - `alembic downgrade base` → chỉ còn `alembic_version`, 0 enum type còn lại (downgrade xoá enum sạch).
    - `alembic upgrade head` lần 2 → `0002_auth_columns (head)` (forward recovery OK). DB tạm đã DROP sau kiểm tra.
  - DB chính `ailp` sau audit: `alembic_version = 0002_auth_columns`; 24 users / 20 courses / 32 lessons / 6 attempts — **không thay đổi dữ liệu**.
- NOT TESTED: backup/restore drill (P6); real LLM (không có key, ngoài scope G0); browser-based UI test.
- BLOCKED: none.
- Database: không tạo revision mới. Phát hiện lệch **không phá dữ liệu** trên DB fresh: 0001 tạo `users_email_key` (unique trên `email`) và 0002 tạo thêm `uq_users_email` → **2 unique constraint trùng chức năng** trên DB tạo mới hoàn toàn; DB chính chỉ có `uq_users_email` (vì 0001 được stamp, không chạy). Đề xuất forward-only (revision mới drop constraint thừa) khi thực sự cần — chưa làm trong G0 vì không ảnh hưởng correctness.
- Security: audit xác nhận GET lesson hiện trả **raw answer key** (`mc.answerIndex`, `blank.answer`, `short.acceptedAnswers`, thứ tự `order.items`, `match.pairs`) → chuyển thành gate bắt buộc của P1.1. Ownership course/lesson enforce ở server (cross-user 404 đã test).
- Regressions: không có (40/40, build OK, 21/21).
- Known limitations (chuyển P1.1/P1.2):
  - P1.1: progress luôn `0` và có nhánh chết `if lesson.status.value == "ready": pass` (`course_service.get_course_detail`); XP cộng mỗi attempt mới (farm được) và response tính lại `xpEarned` từ score thay vì giá trị đã ghi; idempotency attempt là check-then-insert (race → có thể IntegrityError/XP 2 lần); `CourseProposal.approved_at` không bao giờ được set khi approve; order/match dùng chính thứ tự mảng làm đáp án.
  - P1.2: không có atomic claim (`job.status in (ready,)` only, không khoá `queued`); `dispatch_generation` chạy sau `commit` và không bắt lỗi `send_task` → job kẹt `queued`; `_use_celery` chọn lúc import; `except (SchemaInvalidError, Exception)`; không retry/backoff/heartbeat; `attempts_count` chỉ tăng ở `retry_course`.
- PHASE GATE: **PASS** (baseline tái lập được; schema/revision kiểm chứng trên DB tạm; không tác động dữ liệu chính; nguy cơ migration được ghi nhận là known limitation, không cần rollback).
- NEXT: P1.1 Quiz Integrity + Progress + XP + Content Version.

## 2026-10-30 (buổi 3) — P0.5.1 Auth & Migration Stabilization

### Sửa lỗi + hardening
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Hằng số HTTP sai `HTTP_422_UNAUTHORIZED` → `HTTP_422_UNPROCESSABLE_ENTITY` | IMPLEMENTED + TESTED | user_service.py; test_invalid_email_returns_422_not_401 (422 + không có WWW-Authenticate header) |
| **Bug rate limit dead-code:** `bucket.append(now)` nằm trong nhánh `if` sau `raise` → request hợp lệ không bao giờ được ghi bucket → rate limit không bao giờ block | IMPLEMENTED + TESTED | limits.py fix; test_login_rate_limited: 10× 401 rồi lần 11 → 429; test_register_rate_limited tương tự |
| Rate limit cho /auth/login (10/phút), /auth/register (10/phút), /auth/logout (30/phút) | IMPLEMENTED + TESTED | auth.py; 2 test trên |
| Rate-limit buckets clear giữa tests (fixture) | IMPLEMENTED + TESTED | conftest.py client fixture; test_rate_limit_buckets_reset_between_tests → 401 (không 429) |
| Auth resolution: deleted user + token hợp lệ → 401 USER_NOT_FOUND (không crash) | TESTED | test_valid_token_with_deleted_user_returns_401 |
| User scope trong session: /me trả đúng user đăng nhập, không leak giữa users | TESTED | test_me_after_login_same_user_no_crossuser_leak |

### Kiểm chứng migration/rollback (không đụng dữ liệu chính)
| Kiểm chứng | Kết quả |
|---|---|
| SQLite: upgrade head → downgrade base → upgrade head → current | 0002_auth_columns (head) — pass |
| PostgreSQL **temp DB riêng** `alembic_verify_tmp` (trong container db, KHÔNG phải DB chính): upgrade head → \d users có email+password_hash+uq_users_email → downgrade base → chỉ còn alembic_version | pass; temp DB đã DROP sau verify |
| DB chính `ailp`: 20 users giữ nguyên, không volume bị xóa | XÁC MINH sau verify |

### Regression P0.5.1 (Docker stack, code mới)
1. `pytest -q` → **40/40 passed** (33 cũ + 7 mới).
2. `npm run build` → ✓ Compiled successfully, 9 static pages.
3. `docker compose up -d --build backend worker` → started; `/health` → ok.
4. `e2e_acceptance.py` → **21/21 PASS**.

### Ràng buộc đã tôn trọng
- Migration 0001/0002 đã deploy **không bị sửa hash/content** — chỉ verify.
- Không xóa volume `reverseengineer_pgdata`, không mất dữ liệu (backup vẫn còn từ P0.5).
- Không tích hợp LLM thật / Tutor / RAG.

### Giới hạn còn lại
- Rate limit vẫn in-memory per-process (restart mất bucket) — distributed Redis để sau.
- `HTTP_422_UNPROCESSABLE_ENTITY` là deprecated alias trong Starlette mới (vẫn hoạt động); cân nhắc đổi sang `HTTP_422_UNPROCESSABLE_CONTENT` khi bump dependency.
- WEAK_PASSWORD của service layer hiện không thể trigger qua HTTP (Pydantic schema chặn trước với cùng điều kiện) — được test trực tiếp ở service level.

---

## 2026-10-30 (buổi 2) — P0.5 Authentication + Alembic Migration

### Backend — Auth (JWT HttpOnly cookie + Argon2id + CSRF)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| POST /v1/auth/register, /login, /logout, GET /me | IMPLEMENTED + TESTED | E2E steps 0, 0b, 0d pass; pytest test_auth.py 13/13 |
| Argon2id password hashing (không plaintext) | IMPLEMENTED + TESTED | test_register_login_me_flow assert `$argon2id$` prefix |
| JWT HS256 + iss/aud/exp validation, secret server-side only | IMPLEMENTED + TESTED | test_expired_token_rejected, test_wrong_issuer_or_audience_rejected, test_tampered_token_rejected |
| get_current_user dependency (user ID từ token, không từ client header) | IMPLEMENTED + TESTED | test_fake_x_user_id_header_does_not_authenticate → 401 |
| X-User-Id demo header chỉ khi ALLOW_DEMO_HEADER=true + ENV=development | IMPLEMENTED + TESTED | compose default false; pytest chạy với false |
| CSRF double-submit cho mutating requests | IMPLEMENTED + TESTED | test_csrf_missing_on_mutation_403; E2E step 0d → 403 |
| Cross-user access → 404 | IMPLEMENTED + TESTED | test_cross_user_access_denied; E2E B/B2 → 404 |
| Ownership + luồng học sau login/reload | IMPLEMENTED + TESTED | test_login_reload_and_continue; E2E step 9 pass |

### Backend — Alembic
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Alembic setup (env.py sync driver, alembic.ini) | IMPLEMENTED + TESTED | `alembic upgrade head` SQLite: 9 bảng tạo thành công |
| Migration 0001_initial (full schema, viết tay khớp models) | IMPLEMENTED + TESTED | upgrade head + downgrade base sạch (SQLite) |
| Migration 0002_auth_columns (idempotent, batch mode cho SQLite) | IMPLEMENTED + TESTED | cycle upgrade→downgrade→upgrade pass; chạy thật trên PostgreSQL DB cũ |
| Backend container chạy `alembic upgrade head` trước start | IMPLEMENTED + TESTED | Dockerfile CMD; logs không lỗi DuplicateTable sau rebuild |
| create_all chỉ còn cho SQLite (dev/test) | IMPLEMENTED + TESTED | pytest 33/33 vẫn pass |
| Migration DB cũ không mất dữ liệu | IMPLEMENTED + TESTED | backup `backup_pre_migration_20261030_221411.sql`; stamp 0001 + upgrade → 16 users + 16 courses giữ nguyên; runbook `docs/migration-runbook.md` |

### Frontend
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| /login page (đăng nhập + đăng ký, toggle mode) | IMPLEMENTED + TESTED | `npm run build` pass; HTTP 200 trên Docker |
| Session bằng HttpOnly cookie (KHÔNG lưu token localStorage) | IMPLEMENTED + TESTED | api.ts `credentials: "include"`; không còn getUserId() |
| CSRF header tự gửi từ csrf_token cookie | IMPLEMENTED + TESTED | api.ts getCsrfToken(); E2E 21/21 pass |
| useAuth + AuthBar (hiển thị user + XP + logout) | IMPLEMENTED | providers.tsx |
| Trang chủ yêu cầu đăng nhập trước khi tạo course | IMPLEMENTED | page.tsx render /login link khi chưa auth |

### Kiểm chứng chạy thật (2026-10-30, Docker Compose full stack)
1. `pytest -q` → **33/33 passed** (20 cũ viết lại cho auth + 13 auth mới).
2. `npm run build` → **thành công** (9 routes, có /login).
3. `docker compose up --build -d` → 5/5 containers Up (db healthy, redis healthy).
4. `python e2e_acceptance.py` → **21/21 PASS** (đã cập nhật: đăng ký/đăng nhập, CSRF, unauth 401, token giả 401, cross-user 404, generation + quiz + reload).
5. Worker: `Task ... succeeded in 0.54s`, 0 Traceback.
6. DB xác minh: users có `password_hash` (argon2id), attempts + xp_events được ghi; dữ liệu cũ 16 users/16 courses giữ nguyên sau migration.

### Các lỗi đã gặp và sửa trong P0.5
1. Alembic CLI autogenerate không chạy được với URL async + greenlet → viết migration tay từ `Base.metadata` (render qua autogenerate API).
2. Migration 0002 duplicate column trên DB mới → chuyển sang idempotent check bằng SQLAlchemy inspector.
3. SQLite không hỗ trợ ALTER ADD/DROP CONSTRAINT → `batch_alter_table` (copy-and-move) khi dialect là sqlite.
4. httpx cookie per-request deprecated warnings — không ảnh hưởng kết quả.
5. Image cũ không chứa 0002 (build trước khi tạo file) → rebuild backend rồi upgrade.

### Chưa làm / giới hạn (cập nhật)
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Refresh token / token rotation | NOT IMPLEMENTED — access token TTL 7 ngày, đủ cho slice hiện tại |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process, identity theo user id |
| HTTPS/deploy production | NOT IMPLEMENTED — local only (COOKIE_SECURE cần bật khi có HTTPS) |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic.
- Token hết hạn sẽ bị từ chối (TESTED); chưa có refresh flow — user đăng nhập lại khi hết hạn.
- Chưa kiểm chứng security ở mức pen-test — chỉ các test case tự viết.

---

## 2026-10-30 — Slice 0 + Slice 1 hoàn thành

### Backend (FastAPI + SQLAlchemy async + Celery)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| API: courses/interview/proposal/approve/generation/retry | IMPLEMENTED + TESTED | E2E 16/16 pass qua HTTP thật |
| API: lessons/attempts (grading server-side) | IMPLEMENTED + TESTED | Quiz 5/5 đúng; duplicate attempt idempotent |
| MockProvider (interview questions, proposal, lessons) | IMPLEMENTED + TESTED | Deterministic; schema validate Pydantic |
| Grading deterministic (mc/blank/order/match/short) | IMPLEMENTED + TESTED | Unit tests 9 case |
| Celery worker generation task | IMPLEMENTED + TESTED | Worker log: `Task ... succeeded in 0.11s`; 0 Traceback |
| Idempotency: course + attempt | IMPLEMENTED + TESTED | `test_duplicate_course_creation_idempotent`, `8b. Attempt idempotent` |
| Ownership check (course/lesson) | IMPLEMENTED + TESTED | User khác truy cập → 404 |
| Rate limit in-memory per-process | IMPLEMENTED + TESTED | 429 khi vượt ngưỡng (unit) |
| XP cơ bản | IMPLEMENTED + TESTED | xpEarned=70 cho 5/5 đúng (50 + 20 bonus) |
| Generation retry (upsert không trùng lesson) | IMPLEMENTED + TESTED | retry → 4 lessons unique |

### Frontend (Next.js 15 + TanStack Query)
| Thành phần | Trạng thái | Bằng chứng |
|---|---|---|
| Pages: /, /new, /new/interview, /new/proposal, /new/generating, /course/[id], /lesson/[id] | IMPLEMENTED | `npm run build` thành công, 8 routes |
| Poll generation 2s tự dừng khi ready/failed | IMPLEMENTED | refetchInterval logic |
| Quiz player 5 loại block | IMPLEMENTED | render + nộp + hiển thị kết quả/đáp án |
| Lưu userId localStorage (persistent identity) | IMPLEMENTED | reload giữ user |

### Kiểm chứng chạy thật (2026-10-30)
1. **Unit + integration tests:** `pytest tests` → **20/20 passed** (backend, SQLite in-memory).
2. **E2E local uvicorn:** `e2e_acceptance.py` → **16/16 PASS** (SQLite + inline fallback).
3. **E2E Docker Compose full stack:** `e2e_acceptance.py` → **16/16 PASS** (PostgreSQL + Redis + Celery worker thật; xác minh qua `docker compose logs worker` và query trực tiếp trong `db` container — courses/lessons/attempts/users/xp đều tồn tại trong PostgreSQL).
4. **Frontend build:** `npm run build` → thành công, serve tại :3000 (HTTP 200).
5. **Retry flow:** approve → ready → retry → job mới chạy → lessons upsert không trùng (4 unique).
6. **Cross-ownership:** user B truy cập course/lesson của user A → 404 (course + lesson).

### Các lỗi đã gặp và sửa trong quá trình
1. UUID parse lỗi vì id có prefix `crs_`/`lsn_` → thêm `parse_prefixed_uuid`.
2. SQLite in-memory mất bảng giữa các connection → `StaticPool`.
3. `asyncio.run()` trong running loop (FastAPI request) → `asyncio.create_task` fallback.
4. Pydantic union blocks không phân biệt theo `type` → `Annotated[..., Field(discriminator="type")]`.
5. SQLAlchemy relationships thiếu (`Course.units`, `Unit.lessons`) cho `selectinload`.
6. **asyncpg cross-loop:** Celery task dùng engine module-level → `RuntimeError: ... attached to a different loop` / `InterfaceError: another operation is in progress` → worker tạo engine riêng mỗi task, dispose sau. (Lỗi này đã xác minh: trước fix worker fail, sau fix `succeeded`.)
7. Celery CLI không nhận `:get_celery_app` function → tạo module `app.worker.celery_app.py`.
8. Windows host: `localhost:8001` trỏ IPv6 `[::1]` timeout 8s/conn → dùng `127.0.0.1`. (Môi trường, không phải bug app.)

### Chưa làm / giới hạn
| Thành phần | Trạng thái |
|---|---|
| AI Tutor (SSE, tool registry, allowance) | NOT IMPLEMENTED — thiết kế trong architecture.md |
| RAG Engine (pgvector, citations) | NOT IMPLEMENTED — schema预留 trong database-design.md |
| Gamification nâng cao (streak/hearts/goal/levels) | NOT IMPLEMENTED — chỉ XP cơ bản |
| Auth JWT/OAuth | NOT IMPLEMENTED — demo user qua header `X-User-Id` |
| Adapter LLM thật (OpenAI/Anthropic/...) | NOT IMPLEMENTED — interface sẵn sàng, key qua env |
| Alembic migration | NOT IMPLEMENTED — dùng `create_all` (đủ cho slice này; migration cần khi schema ổn định) |
| Content versioning nâng cao (regenerate giữ attempts) | NOT IMPLEMENTED — contentVersion đã có trong schema |
| Rate limit distributed (Redis) | NOT IMPLEMENTED — in-memory per-process |
| HTTPS/deploy production | NOT IMPLEMENTED — local only |

### Khẳng định đúng mức
- Mock provider **KHÔNG phải AI thật** — nội dung sinh theo template deterministic. Nhãn "AI" chỉ đúng khi bật adapter thật.
- Không kiểm chứng giả thuyết RAG hay thuật toán backend của hệ thống được phân tích — chỉ tham khảo hình thái nghiệp vụ (interview 5 câu, proposal, poll generation, batch attempts) từ 2 báo cáo REA.
