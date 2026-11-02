# P5.2 — Adaptive Readiness (research) + Exposure Logging (flag off)

**Ngày:** 2026-11-02 · **Phase:** P5.2 · **Trạng thái:** IMPLEMENTED + TESTED
**Design:** `docs/superpowers/specs/2026-11-02-p52-adaptive-readiness-design.md`
**Plan:** `docs/superpowers/plans/2026-11-02-p52-adaptive-readiness.md`

> **Không huấn luyện mô hình nào.** Không DKT, không LSTM, không contextual bandit,
> không thay đổi thứ tự bài người học thấy. Mastery vẫn `method="rule_based"`.

---

## 1. Vì sao P5.2 tách làm hai phần

`docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` §18 ghi P5.2 "chỉ nghiên cứu" và cấm
"huấn luyện mô hình đắt đỏ vì trào lưu". Nhưng có một rào cản kỹ thuật cụ thể hơn việc
thiếu dữ liệu: **hệ thống không ghi lại nó đã gợi ý gì cho ai, lúc nào**. Không có
exposure, không có propensity, không có policy version ⇒ mọi đánh giá off-policy trong
tương lai đều không thể thực hiện hợp lệ, dù sau này có bao nhiêu attempt.

Vì vậy:

- **P5.2a — Readiness assessment** (thuần nghiên cứu): đo khoảng cách tới ngưỡng,
  không đụng runtime.
- **P5.2b — Exposure logging** (flag TẮT): bắt đầu tích luỹ dữ liệu cần cho bandit.
  Đây là phần **vượt wording cũ** của plan, nên đã được người dùng duyệt riêng ngày
  2026-11-02 và ghi vào §26 Decision log.

## 2. P5.2a — Kết quả đo thật (2026-11-02)

```bash
cd backend
python -m evals.p52_readiness \
  --database-url "postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp"
```

```
P5.2 readiness p5.2-readiness-v1 — postgresql+asyncpg://ailp:***@127.0.0.1:5433/ailp
  attempts=127 users=66 maxPerUser=3 usersGe10=0 sequencesGe5=0 coursesGe2Users=0
  exposures=0 policies=0 arms=0 propensitySpread=None
  DKT: BLOCKED
    - usersGe10=0 < 500
    - sequencesGe5=0 < 200
    - coursesWithGe2Users=0 < 50
  BANDIT: BLOCKED
    - exposureRows=0 < 5000
    - distinctPolicies=0 < 2
    - distinctArms=0 < 3
    - propensitySpread=None < 0.1 (policy deterministic ⇒ chưa thể OPE)
  opeSupported=False
```

Đối chiếu `psql` độc lập: **127** attempt, **66** user, max **3** attempt/user — khớp.

**Ngưỡng (PROPOSAL, cần hiệu chỉnh khi có dữ liệu):**

| Hạng mục | Điều kiện |
|---|---|
| DKT/LSTM | `usersGe10 ≥ 500`, `sequencesGe5 ≥ 200`, `coursesGe2Users ≥ 50` |
| Contextual bandit | `exposureRows ≥ 5000`, `distinctPolicies ≥ 2`, `distinctArms ≥ 3`, `propensityMax − propensityMin ≥ 0.1` |

Verdict chỉ chuyển `READY` khi **tất cả** điều kiện đạt. Đặc biệt bandit **không thể**
đạt khi policy còn deterministic, vì propensity spread = 0.

## 3. P5.2b — Exposure logging

### 3.1 Vì sao cần token

Policy gợi ý hiện **deterministic** (`learning_path_service` không ngẫu nhiên), nên:

- `propensity = 1.0` cho mọi arm ⇒ **không có overlap** ⇒ OPE không hợp lệ về thống kê.
  Ghi rõ trong mọi report: `opeSupported=false`.
- Client **không thể** tự khai arm: nếu tin client, kẻ xấu có thể ghi khống exposure để
  làm sai lệch dữ liệu huấn luyện tương lai.

Do đó GET `learning-path` phát thêm `recommendationToken` — HMAC-SHA256 trên payload
`(user, course, arm_kind, arm_id, context_hash, lesson_content_version, policy_version,
iat)` với khoá `JWT_SECRET`, TTL 900s. Client gửi lại token; server **verify rồi vẫn
tính lại** learning-path và so khớp.

### 3.2 Bảng `recommendation_events` (migration `0016_p52_exposure`)

Append-only, expand-only. Không có cột `reward_*`: reward suy **offline**.

| Cột | Ghi chú |
|---|---|
| `user_id`, `course_id` | FK CASCADE (privacy: xoá user/course ⇒ xoá audit của họ) |
| `context_hash` | sha256 của context **hẹp** (next/review/due/blocked) — bỏ title/message |
| `policy_version` | `p5.0-rule-v1` (đổi khi logic gợi ý đổi) |
| `arm_kind`, `arm_id` | `next_lesson` / `review_lesson` + `lesson_id`; **NOT NULL** |
| `lesson_content_version` | snapshot **tại thời điểm gợi ý** (bắt buộc để reward đúng) |
| `propensity` | `1.0` hôm nay |
| `reason_code` | `NEXT_IN_SEQUENCE`/`PREREQUISITES_MET`/`FALLBACK_REVIEW_WEAKEST` |
| `exposed_at`, `created_at` | thời điểm |

Ràng buộc: `uq_recommendation_event_context (user_id, course_id, context_hash, arm_kind,
arm_id)`, 2 index `(course_id, exposed_at)` và `(user_id, exposed_at)`.

**Quyết định phạm vi:** UNIQUE = "một exposure cho mỗi (context, arm)", **không phải**
đếm impression. Bandit cần impression count sau này thì phải thêm bảng riêng — không
được ngầm đổi nghĩa ràng buộc.

`arm_id NOT NULL` có chủ đích: PostgreSQL coi `NULL != NULL`, nên nếu cho phép arm NULL
thì UNIQUE không chặn được insert trùng, và `COALESCE` ở tầng service không chặn được
race giữa hai request đồng thời.

### 3.3 API

`POST /v1/courses/{courseId}/recommendation-events`

- Body: `{"recommendationToken": "..."}` — `extra="forbid"`.
- Thứ tự kiểm: cờ `P52_EXPOSURE_ENABLED` (503 `P52_NOT_ENABLED`, **trước** khi chạm
  bảng) → `P50_ENABLED` (503 `P50_NOT_ENABLED`) → CSRF → rate limit 60/60s →
  ownership (404) → verify token → tính lại learning-path → so `context_hash` +
  `arm_kind` + `arm_id` + `lesson_content_version` → ghi (idempotent, SAVEPOINT).
- Token sai/hết hạn/lệch context ⇒ HTTP 200 với `recorded=false` + `reason`
  (`TOKEN_INVALID` | `TOKEN_EXPIRED` | `CONTEXT_STALE`), **không** ghi row.
- Response: `{recorded, duplicate, exposureId, reason}`; `exposureId` dạng `rce_<uuid>`.

### 3.4 Reward offline

`recommendation_log_service.reward_for_events(db, events, window_days=14)` — chỉ SELECT:

1. Attempt **sau** `exposed_at` trong cửa sổ, khớp `lesson_id = arm_id` **và**
   `content_version = lesson_content_version` ⇒ `reward = score_correct/score_total`.
2. Nếu không có, review **sau** `exposed_at`, đi qua `review_cards` (vì
   `review_events` không có `lesson_id`) ⇒ `reward = (rating-1)/3`.
3. Không có tín hiệu ⇒ `reward = None` (**không** gán 0 giả).

Event trước `exposed_at` bị loại — có test riêng.

### 3.5 Frontend

Trang `/course/[courseId]` gọi `recordRecommendation` một lần cho mỗi token mới
(`useRef` chống StrictMode double-render), fire-and-forget, bỏ qua lỗi; không đổi UI,
không invalidate cache. Khi cờ TẮT, `recommendationToken` là `null` ⇒ không gọi gì.

## 4. Đã kiểm chứng

- `pytest -q` → **673 passed, 29 skipped** (baseline trước phase: 635/28).
- Migration trên PostgreSQL throwaway `p52_migration_check`: `upgrade head` → `0016`
  với đúng UNIQUE + 2 index + 3 FK CASCADE; `downgrade -1` → `0015`, quan hệ biến mất,
  `users` còn nguyên; `upgrade head` lại OK. DB đã drop.
- Concurrency trên `p52_race_check`: 6 `record_exposure` đồng thời cùng context ⇒
  **đúng 1 row**, không task nào ném exception. DB đã drop.
- `npx tsc --noEmit` → 0 lỗi; `npm run build` → OK; `docker compose config` → exit 0.
- Readiness eval trên DB thật → cả DKT và bandit `BLOCKED`, `opeSupported=false`.

## 5. Giới hạn đã biết

1. **Không có OPE** cho tới khi có exploration. Propensity 1.0 là giới hạn thống kê,
   không phải chi tiết kỹ thuật.
2. **Không đếm impression.** Một exposure mỗi (context, arm); hiển thị lặp chỉ tăng
   `duplicate=true`, không tăng bộ đếm.
3. **Rate limit in-memory theo process** — nhiều replica thì không phải bảo vệ thật
   (thuộc P6.4).
4. **`review` reward dùng rating 1..4** làm proxy cho "học tốt"; đây là proxy thô, chưa
   hiệu chuẩn với quiz score.
5. **Chưa có job tổng hợp reward** — `reward_for_events` là hàm eval, gọi thủ công.
6. `P52` phụ thuộc `P50`: bật P52 mà tắt P50 thì POST trả 503 (không ngầm bật P50).

## 6. Điều kiện mở lại (khi nào mới cân nhắc bandit)

1. `exposureRows ≥ 5000`, `distinctPolicies ≥ 2`, `distinctArms ≥ 3`.
2. **Propensity có spread** — tức phải có quyết định sản phẩm về exploration (ví dụ
   epsilon-greedy 10%), đánh đổi chất lượng gợi ý hiện tại.
3. Có offline evaluation trên held-out với logging policy đúng.
4. Privacy review cho dữ liệu hành vi.
5. Nếu đạt: shadow mode + rollback + fallback rule-based.

## 7. File

| File | Vai trò |
|---|---|
| `backend/app/models/models.py` | `RecommendationEvent` |
| `backend/alembic/versions/0016_p52_exposure.py` | migration expand-only |
| `backend/app/services/recommendation_token_service.py` | mint/verify HMAC + context hash |
| `backend/app/services/recommendation_log_service.py` | ghi exposure + reward offline |
| `backend/app/api/v1/learner.py` | GET token + POST endpoint |
| `backend/app/schemas/schemas.py` | `recommendationToken`, request/response |
| `backend/evals/p52_readiness.py` | readiness assessment |
| `backend/tests/test_p52_*.py` | contract, token, service, API, readiness, PG race |
| `frontend/src/lib/api.ts`, `frontend/src/app/course/[courseId]/page.tsx` | gọi record 1 lần |
