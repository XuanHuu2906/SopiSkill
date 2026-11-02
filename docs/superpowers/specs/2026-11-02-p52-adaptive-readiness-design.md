# P5.2 — Advanced Adaptive AI: readiness evidence + exposure logging — Design

**Ngày:** 2026-11-02 · **Phase:** P5.2 · **Trạng thái:** DRAFT chờ duyệt
**Branch dự kiến:** `feat/p5.2-adaptive-readiness` (tách từ `feat/p5.1-bkt-research`)
**Quyết định người dùng:**
1. Phạm vi: **readiness assessment + logging schema** (không huấn luyện DKT/LSTM/bandit).
2. **Có** thêm logging runtime sau feature flag.
3. Reward: **suy offline** bằng JOIN, không cột reward trên bảng exposure.
4. Propensity: **deterministic = 1.0**, ghi rõ chưa thể OPE.
5. Điểm ghi: **endpoint POST riêng**, không ghi trong GET.

---

## 1. Ý định và lý do

Plan mục 18 khai P5.2 là **chỉ nghiên cứu** và cấm "huấn luyện mô hình đắt đỏ vì trào lưu".
Nhưng có một rào cản kỹ thuật cụ thể hơn cả thiếu dữ liệu: **hiện không tồn tại bất kỳ
bản ghi nào cho biết hệ thống đã gợi ý gì cho ai, lúc nào**. Không có exposure, không có
propensity, không có policy version ⇒ mọi so sánh off-policy trong tương lai đều
không thể thực hiện hợp lệ, dù sau này có bao nhiêu `lesson_attempts`.

Vì vậy P5.2 làm hai việc tách bạch:

- **(A) Readiness assessment** — đo định lượng khoảng cách tới ngưỡng của DKT/LSTM và của
  contextual bandit, in verdict `BLOCKED`/`NOT STARTED` kèm điều kiện mở lại. Không
  model, không dependency mới.
- **(B) Exposure logging** — thêm bảng append-only ghi *gợi ý đã hiển thị*, có feature flag
  mặc định TẮT, để **bắt đầu tích luỹ dữ liệu** cần cho bandit sau này.

Không có phần nào thay đổi thứ tự bài người học thấy. Mastery vẫn `rule_based`.

> **Ghi chú phạm vi (bắt buộc):** plan mục 18 ghi P5.2 "chỉ nghiên cứu" và "chưa đủ dữ
> liệu ⇒ `NOT STARTED`, không cố triển khai". Việc (B) thêm migration + endpoint là
> **vượt wording đó**, nên phase này phải kèm:
> - sửa plan §18 để tách rõ **P5.2a (research/readiness)** và **P5.2b (exposure logging,
>   flag TẮT)**;
> - một dòng trong §26 Decision log ghi đây là **quyết định người dùng duyệt** ngày
>   2026-11-02, kèm lý do (không có exposure thì OPE vĩnh viễn không hợp lệ);
> - giữ nguyên câu "chưa huấn luyện DKT/LSTM/bandit" trong mọi báo cáo.
> Nếu không có ba điều trên thì chỉ được làm (A).

## 2. Goals / Non-goals / Anti-goals

**Goals**
- Trả lời được, bằng số: thiếu bao nhiêu chuỗi/user/course để DKT khả thi; thiếu những
  bảng/cột nào để OPE khả thi.
- Ghi nhận exposure recommendation một cách append-only, idempotent, scoped owner, có
  policy version + propensity + context hash.
- Cho phép tính reward **offline** bằng JOIN với `lesson_attempts` / `review_events`.
- Giữ nguyên hành vi khi flag TẮT (mặc định): không bảng ghi mới, không endpoint mới trả
  thành công.

**Non-goals**
- Không huấn luyện DKT/LSTM. Không thêm `torch`/`sklearn`/`numpy` vào requirements.
- Không triển khai contextual bandit, không đổi `nextLesson`.
- Không epsilon-greedy, không đổi trải nghiệm học.
- Không dựng pipeline reward online / cron.
- Không migration phá huỷ, không sửa migration `0001`–`0015`.

**Anti-goals**
- Gọi logging là "adaptive AI đã chạy".
- Báo "sẵn sàng bandit" chỉ vì đã có bảng log.
- Ghi exposure của user khác, hoặc nhận `userId`/`courseId` từ client mà không kiểm.
- Ghi mỗi lần GET khiến refetch TanStack Query thổi phồng impression.
- Log nội dung bài học, prompt, hay bất kỳ PII nào ngoài id.

## 3. Constraint từ repo (FACT, đã kiểm)

- `learning_path_service.build_learning_path` là **GET** trả `nextLesson` /
  `reviewLessonId` / `blockedBy` / `prerequisitesDag`; hiện **không log** gì.
- Không có bảng `recommendation_*`/`impression`/`exposure` trong `models.py`.
- Reward tín hiệu đã có sẵn: `lesson_attempts(score_correct, score_total, content_version,
  created_at, lesson_id, user_id)` và `review_events(rating, reviewed_at)`.
- Migration head: `0015_p50_learner_profile`; pattern test migration contract tồn tại
  (`tests/test_p50_migration_contract.py`) và convention expand-only + downgrade đối xứng.
- Feature-flag convention: cờ tắt ⇒ route trả **503 `*_NOT_ENABLED`** (xem
  `learner.py::_require_enabled`, tutor).
- CSRF: `verify_csrf(request)` cho mọi POST; rate limit `rate_limit(request, key, limit,
  window_seconds)`.
- Ownership: `course_service.get_owned_course(db, course_id, user.id)` ⇒ 404 cross-user.
- Test stack: SQLite in-memory + `create_all()` từ `Base.metadata`, nên thêm bảng vào
  `models.py` là đủ cho test; migration chỉ cần cho PostgreSQL.
- Policy hiện deterministic ⇒ **propensity luôn 1.0**; điều này phải được ghi trong spec
  như một giới hạn, không phải chi tiết kỹ thuật.

## 4. Phương án đã cân nhắc

| Phương án | Đổi lấy | Kết luận |
|---|---|---|
| A. Chỉ readiness report, không logging | Ít rủi ro nhất; nhưng 6 tháng nữa vẫn không có dữ liệu ⇒ lặp lại đúng vấn đề P5.1 | Loại (người dùng chọn có logging) |
| **B. Readiness + bảng exposure append-only, flag mặc định TẮT, endpoint POST** | Bắt đầu tích luỹ dữ liệu thật mà không đổi trải nghiệm; có migration + route mới nhưng cô lập sau flag | **CHỌN** |
| C. Như B + epsilon-greedy để OPE hợp lệ ngay | OPE hợp lệ; nhưng đổi trải nghiệm học thật và giảm chất lượng gợi ý | Loại (người dùng từ chối) |
| D. Cột `reward_*` trên exposure, cập nhật khi có attempt | Không cần JOIN; nhưng phá tính append-only, rủi ro lost update | Loại (người dùng chọn suy offline) |

## 5. Thiết kế (A) — Readiness assessment

### 5.1 `backend/evals/p52_readiness.py` (read-only, không ghi DB)

Đo trên DB thật qua `DATABASE_URL` (dùng lại `mastery_dataset.detect_tables` +
`redact_dsn`); không `create_all`.

Chỉ số đo:

| Chỉ số | Cách đo | Dùng cho |
|---|---|---|
| `attempts` | `COUNT(lesson_attempts)` | chung |
| `usersWithAttempts` | `COUNT(DISTINCT user_id)` | chung |
| `usersGe5` / `usersGe10` / `usersGe20` | đếm user theo số attempt | DKT |
| `maxAttemptsPerUser` | `MAX(count)` | DKT |
| `sequencesGe5` (user,skill) | tái dùng extractor P5.1 | DKT |
| `coursesWithGe2Users` | đếm course có ≥2 user có attempt | DKT / bandit |
| `exposureTable` | bảng `recommendation_events` có tồn tại? | bandit |
| `exposureRows` | `COUNT(recommendation_events)` | bandit |
| `distinctPolicies` | `COUNT(DISTINCT policy_version)` | bandit |
| `distinctArms` | `COUNT(DISTINCT arm_kind, arm_id)` | bandit |
| `propensitySpread` | `MIN/MAX(propensity)` | bandit |

Ngưỡng (PROPOSAL, ghi vào spec và `--help`):

| Hạng mục | Điều kiện tối thiểu |
|---|---|
| DKT/LSTM | ≥ 500 user có ≥ 10 attempt; `sequencesGe5` ≥ 200; ≥ 50 course có ≥ 2 user |
| Contextual bandit (off-policy) | ≥ 5 000 exposure; ≥ 2 `policy_version`; ≥ 3 arm; propensity có spread (max − min ≥ 0.1) |

Verdict mỗi hạng mục: `READY` / `BLOCKED` kèm danh sách lý do định lượng (giống
`summarize` ở P5.1). Mặc định hôm nay dự kiến: **cả hai `BLOCKED`**.

CLI: `python -m evals.p52_readiness [--database-url …] [--json] [--save]`. Exit 0 luôn
(không phải test fail); report `status` nói rõ.

## 6. Thiết kế (B) — Exposure logging

### 6.1 Bảng `recommendation_events` (migration `0016_p52_exposure`)

Append-only, expand-only, downgrade chỉ drop đúng bảng mới.

```
recommendation_events
  id                 UUID PK
  user_id            FK users(id) ON DELETE CASCADE, NOT NULL
  course_id          FK courses(id) ON DELETE CASCADE, NOT NULL
  context_hash       char(64) NOT NULL    -- sha256 hex của context canonical
  policy_version     text NOT NULL        -- vd "p5.0-rule-v1"
  arm_kind           text NOT NULL        -- "next_lesson" | "review_lesson"
  arm_id             UUID NOT NULL        -- lesson_id được gợi ý
  lesson_content_version integer NOT NULL -- snapshot version tại lúc gợi ý
  propensity         float NOT NULL       -- 1.0 hôm nay (deterministic)
  reason_code        text NOT NULL        -- NEXT_IN_SEQUENCE | PREREQUISITES_MET |
                                          --   PREREQUISITE_NOT_MET | FALLBACK_REVIEW_WEAKEST
  exposed_at         timestamptz NOT NULL
  created_at         timestamptz server_default now()

  CONSTRAINT uq_recommendation_event_context
    UNIQUE(user_id, course_id, context_hash, arm_kind, arm_id)   -- idempotent
  INDEX ix_recommendation_events_course (course_id, exposed_at)
  INDEX ix_recommendation_events_user   (user_id, exposed_at)
```

Ghi chú thiết kế:
- **`arm_id NOT NULL` có chủ đích.** Arm luôn là một lesson cụ thể; bỏ nhánh "arm NULL"
  để UNIQUE không phụ thuộc NULL-semantics của PostgreSQL (NULL ≠ NULL ⇒ insert trùng
  vẫn lọt). `COALESCE` ở tầng service **không** chặn được race giữa hai request đồng thời,
  nên phương án đúng là ràng buộc DB.
- **`lesson_content_version`** là snapshot bắt buộc: sau khi lesson regenerate,
  `lessons.content_version` đổi và JOIN reward theo version hiện tại sẽ sai. Ghi version
  **tại thời điểm gợi ý**.
- **`arm_id` + `lesson_content_version`** đủ để JOIN reward mà không cần thêm `lesson_id`.
- **Không** có `reward_*`: reward suy offline qua JOIN.
- **Không** có `client_received_at`/`dwell`: chưa có nhu cầu, YAGNI.
- UNIQUE là **"một exposure cho mỗi (context, arm)"**, **không phải** đếm impression.
  Đây là quyết định phạm vi: bandit sau này cần impression count thì phải thêm bảng riêng
  — ghi rõ trong docstring và spec, không được im lặng mở rộng nghĩa của bảng.
- FK CASCADE: xoá user/course sẽ xoá audit tương ứng (phục vụ quyền xoá dữ liệu ở P6).
  Đây là ngoại lệ có chủ đích của "append-only" — chỉ append, không UPDATE; xoá theo
  quyền người dùng là yêu cầu privacy, không phải sửa lịch sử.

### 6.2 `backend/app/services/recommendation_log_service.py`

```python
POLICY_VERSION = "p5.0-rule-v1"

def context_hash(learning_path_payload: dict) -> str      # thuần, deterministic
async def record_exposure(db, *, user_id, course_id, payload, now=None) -> dict
async def reward_for_events(db, events, window_days=14) -> list[dict]   # đọc, cho eval
```

- `context_hash`: sha256 của JSON canonical (`sort_keys`, tách ra từ
  `nextLesson.lessonId`, `reviewLessonId`, `reviewDueCount`, `blockedBy[].lessonId`).
  **Không** hash toàn payload (tránh phụ thuộc thứ tự dict và field mới về sau).
- `record_exposure`: derive arm từ payload **do server vừa tính**, không nhận arm từ
  client. Insert idempotent theo UNIQUE; `IntegrityError` ⇒ trả `duplicate=True`
  (dùng SAVEPOINT `db.begin_nested()` để không phá transaction ngoài).
- `reward_for_events`: cho eval offline. Hai đường JOIN tách biệt:
  - **attempt reward**: `lesson_attempts` với `lesson_id = arm_id`,
    `content_version = lesson_content_version`, `created_at > exposed_at`,
    `created_at <= exposed_at + window`; reward = `score_correct / score_total`.
  - **review reward**: `review_events` **không có** `lesson_id`, nên phải đi qua
    `review_cards`: `review_events.card_id → review_cards.id`,
    `review_cards.lesson_id = arm_id`, `review_events.reviewed_at > exposed_at`.
  - Trả `None` khi chưa có tín hiệu (không gán 0 giả).

- `reason_code` cho arm **review**: `reviewLessonId` hiện không kèm reason. Hai lựa chọn
  đã cân nhắc: (i) thêm reason vào response (đổi contract GET), (ii) gán cố định
  `FALLBACK_REVIEW_WEAKEST` vì đó là **đường duy nhất** sinh `reviewLessonId`
  (`learning_path_service.py:198-209`). **Chọn (ii)** — đúng sự thật, không đổi contract.

### 6.3 Endpoint `POST /v1/courses/{courseId}/recommendation-events`

- **Server phát token, client gửi lại token.** `LearningPathOut` thêm field additive
  `recommendationToken: str | null` (null khi flag TẮT). Token là chuỗi có ký server-side
  chứa `context_hash` + `arm_kind` + `arm_id` + `course_id` + `user_id` + `policy_version`
  + `exposed_at` (HMAC-SHA256 bằng `jwt_secret`). Nhờ vậy:
  - client **không thể bịa** arm/hash (không có khoá);
  - client **luôn có** giá trị để gửi (field nằm trong response GET);
  - server verify token rồi **vẫn tính lại** learning-path tại thời điểm POST để chắc
    arm còn hợp lệ và ownership còn đúng.
- Body: `{ "recommendationToken": str }` (`extra="forbid"`).
- Token hết hạn (mặc định **15 phút**) hoặc chữ ký sai ⇒ `recorded=false`,
  `reason="TOKEN_INVALID"`, HTTP 200; không ghi row.
- **Không** dùng `contextHash` do client tự tính (không kiểm chứng được).
- Auth: `get_current_user`; ownership `get_owned_course` ⇒ 404 cross-user.
- CSRF + rate limit (`recommendation_event`, 60/60s).
- Flag `P52_EXPOSURE_ENABLED` (mặc định **false**) ⇒ 503 `P52_NOT_ENABLED`, kiểm **trước**
  mọi truy vấn bảng. Route cũng cần `P50_ENABLED` (vì gọi `build_learning_path`) ⇒ nếu
  P50 tắt nhưng P52 bật, trả 503 `P50_NOT_ENABLED`; hai cờ độc lập, P52 **không** ngầm
  bật P50.
- Response: `{ "recorded": bool, "duplicate": bool, "exposureId": str|None }`.
- **Không** trả về arm nào; không cho client đọc log của user khác.

#### Ai gọi endpoint?

Nếu không ai gọi thì bảng luôn rỗng và (B) vô nghĩa. Vì vậy **có** sửa frontend tối thiểu:

- `frontend/src/lib/api.ts`: thêm type `recommendationToken` vào `LearningPath`, thêm
  `recordRecommendation(courseId, token)` (POST kèm CSRF như các mutation khác).
- `frontend/src/app/course/[courseId]/page.tsx`: sau khi `learningPath` query thành công và
  có token, gọi **một lần** trong `useEffect` (fire-and-forget, bỏ qua lỗi, không
  invalidate cache, không đổi UI). Guard bằng `useRef` theo token để StrictMode double-render
  không gọi 2 lần; server vẫn idempotent nên đây chỉ là giảm nhiễu.
- Không thêm trạng thái loading/error cho hành vi ẩn này.

## 7. Thiết kế (C) — Reward offline trong eval

`backend/evals/p52_bandit_eval.py`:
- Nếu `P52_EXPOSURE_ENABLED` tắt hoặc không có exposure ⇒ `INSUFFICIENT_DATA`.
- Nếu có: tính **chỉ số mô tả** (không phải OPE): số arm, phân bố arm, tỷ lệ có reward
  trong cửa sổ, độ trễ trung vị tới reward. **Không** ước lượng policy value, và in rõ
  `opeSupported=false` vì propensity = 1.
- `--json`, `--save`, `--window-days`.

## 8. File chạm

| File | Loại |
|---|---|
| `backend/app/models/models.py` | thêm `RecommendationEvent` |
| `backend/app/models/__init__.py` | export |
| `backend/alembic/versions/0016_p52_exposure.py` | mới |
| `backend/app/services/recommendation_log_service.py` | mới |
| `backend/app/api/v1/learner.py` | thêm route POST + gắn `recommendationToken` vào response GET |
| `backend/app/schemas/schemas.py` | `RecommendationEventRequest/Out`, thêm field additive `recommendationToken` vào `LearningPathOut` |
| `backend/app/core/config.py` | `p52_exposure_enabled`, `p52_token_ttl_seconds` |
| `backend/evals/p52_readiness.py` | mới |
| `backend/evals/p52_bandit_eval.py` | mới |
| `backend/app/services/token_service.py` | mới — HMAC token cho `recommendationToken` |
| `backend/tests/test_p52_*.py` | mới (≥5 file) |
| `.env.example`, `docker-compose.yml` (3 service) | cờ mới |
| `frontend/src/lib/api.ts` | thêm type + `recordRecommendation` |
| `frontend/src/app/course/[courseId]/page.tsx` | gọi record 1 lần khi có token |
| `docs/specs/24-P52-ADAPTIVE-READINESS.md` | mới |
| `docs/development-progress.md`, plan §3+§18 | cập nhật |

**Không chạm:** `learning_path_service.py` (không đổi **logic** gợi ý); route GET chỉ
thêm field `recommendationToken` (additive, `null` khi cờ TẮT), `learner_profile_service.py`,
`requirements.txt`. Frontend **có** chạm tối thiểu để gọi endpoint (xem §6.3).

## 9. Bảo mật

- Client **không** gửi được `userId`, `courseId`, `arm`, `propensity`: đều derive server-side
  (schema `extra="forbid"`).
- Cross-user ⇒ 404 qua `get_owned_course`, không rò sự tồn tại.
- Idempotency bằng UNIQUE ở DB + SAVEPOINT; retry không nhân exposure.
- Rate limit + CSRF; flag tắt ⇒ 503, không ghi bảng (kể cả bảng chưa migrate trên DB cũ —
  route phải kiểm flag **trước** khi chạm bảng).
- Log chỉ id/hash/reason code; **không** log payload mastery hay nội dung bài.
- Append-only: service **không** UPDATE/DELETE. FK CASCADE là ngoại lệ privacy có chủ đích
  (xoá user/course ⇒ xoá audit của chính họ), đã ghi trong §6.1.
- Rate limit hiện là in-memory theo process; nhiều replica thì đây **không** phải bảo vệ
  thật — giới hạn đã biết, thuộc P6.4.

## 10. Acceptance / Gate

1. Flag TẮT: POST trả 503 `P52_NOT_ENABLED`, **không** ghi row (đếm trước/sau bằng nhau);
   `GET learning-path` không đổi.
2. Flag BẬT: POST với hash đúng ⇒ 1 row; gọi lặp 10 lần ⇒ vẫn 1 row, `duplicate=true`.
3. Client gửi `arm`/`propensity`/`userId` ⇒ 422 (`extra=forbid`).
4. Cross-user ⇒ 404; không tạo row cho user khác.
5. Token sai chữ ký / hết hạn / thuộc user khác ⇒ `recorded=false` + lý do, không ghi row.
6. Thiếu CSRF ⇒ 403; vượt rate limit ⇒ 429.
7. Migration: `upgrade head` trên PostgreSQL temp tạo bảng + `uq_recommendation_event_context`
   + 2 index đúng tên; `downgrade -1` về `0015` xoá đúng bảng, `users`/`courses` còn
   nguyên; `upgrade head` lại OK. Migration có guard `_has_table("courses"/"lessons"/"users")`
   như `0015`, và **không** dùng `op.execute` cho DDL (contract test chỉ quét
   `drop_table/drop_column/alter_column` trong text, nên DDL thô sẽ lọt kiểm tra).
8. Readiness: chạy real ⇒ cả DKT và bandit `BLOCKED` với lý do định lượng; report lưu được.
9. `pytest -q` xanh; số test mới đếm thực tế lúc chạy.
10. `git diff` chứng minh `learning_path_service.py` và `requirements.txt` không đổi, và
    frontend chỉ thay đổi đúng 2 file đã liệt kê (type + 1 effect gọi record).
11. Frontend: `npx tsc --noEmit` và `npm run build` pass; trang course không đổi hành vi
    hiển thị khi P52 TẮT (không có token ⇒ không gọi gì).

## 11. Rollback

- Code: revert commit; không ảnh hưởng dữ liệu vì flag mặc định TẮT.
- DB: `downgrade -1` drop `recommendation_events` (mất exposure đã ghi — đây là dữ liệu
  audit mới, không phải dữ liệu học của người dùng; backup trước nếu đã bật flag lâu).

## 12. Việc để builder quyết

- `POLICY_VERSION = "p5.0-rule-v1"` (đổi khi logic gợi ý thay đổi).
- Cửa sổ reward mặc định 14 ngày (bandit), ghi vào `--help`.
- `context_hash` dùng sha256 hex; có thể cắt 16 ký tự đầu nếu muốn ngắn — đề xuất giữ đủ 64.
- Ngưỡng readiness như §5.1 (PROPOSAL).
- `exposureId` dùng prefix `rce_` và **phải** thêm vào `ID_PREFIXES` của
  `course_service.parse_prefixed_uuid` nếu muốn endpoint nào đó nhận id này về sau.
- Metric eval phải chạy được trên **cả SQLite và PostgreSQL**: không dùng
  `COUNT(DISTINCT a, b)` nhiều cột (SQLite không hỗ trợ) — dùng subquery
  `SELECT COUNT(*) FROM (SELECT DISTINCT a, b FROM …)`.
- `coursesWithGe2Users` phải JOIN qua `lessons` (vì `lesson_attempts` không có `course_id`).
