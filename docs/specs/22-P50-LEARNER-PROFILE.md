# P5.0 — Learner Profile, Mastery Baseline & FSRS (Design)

**Ngày:** 2026-11-02 · **Phase:** P5.0 · **Trạng thái:** APPROVED (chờ implement)
**Quyết định người dùng:** B — snapshot bền vững + thư viện `fsrs`; phạm vi full gồm UI review.

---

## 1. Ý định và lý do

Lộ trình học hiện chỉ dựa vào 5 câu interview và `completed/total` theo attempt ≥80%.
Không có "người học đã nắm kỹ năng này chưa", không có ôn tập cách quãng, không có lý do
kiểm tra được cho gợi ý bài tiếp theo.

P5.0 biến dữ liệu attempt đã có thành: **(a)** mastery theo từng skill (rule-based, không
giả danh ML), **(b)** lịch ôn tập FSRS từ review event thật, **(c)** gợi ý bài tiếp theo tôn
trọng prerequisite DAG kèm lý do hiển thị cho người học.

## 2. Goals / Non-goals / Anti-goals

**Goals**
- Gắn skill ổn định (`CurriculumSkill` đã sinh ở P2.1) vào lesson bằng migration mới,
  backfill từ chính `course_proposals.payload` — không bịa skill.
- Mastery baseline deterministic từ `lesson_attempts`; công bố rõ là heuristic,
  **không** phải xác suất đã hiệu chuẩn.
- FSRS thật (thư viện `fsrs` 6.3.x) từ review event có rating/thời điểm.
- Gợi ý "học tiếp" chỉ khi prerequisite đã đạt; giải thích được vì sao.
- UI ôn tập: hàng đợi card đến hạn, reveal, 4 mức đánh giá.

**Non-goals**
- BKT (P5.1), DKT/LSTM, contextual bandit (P5.2).
- Không dự đoán năng lực bằng mô hình học máy; không gọi heuristic là ML.
- Không thay `completed/total` hay XP của P1.1; mastery là lớp bổ sung.

**Anti-goals**
- Gợi ý bài khi prerequisite chưa đạt mà không nói lý do.
- Mastery tăng vô hạn khi nộp lại cùng attempt/version (farm).
- Review card/event bị tạo trùng khi retry mạng hoặc double-click.
- Hiển thị "đã nắm vững" cho user chưa học bài nào.

## 3. Constraint từ repo hiện tại (FACT, đã kiểm tra)

- `CurriculumSkill{id,title,lesson,bloomLevel,outcome}` + `prerequisites[(parent,child)]`
  chỉ nằm trong `course_proposals.payload` (JSON); **không** có bảng DB.
- `pedagogy.normalize_curriculum()` đảm bảo mỗi lesson có đúng 1 skill (kể cả proposal cũ)
  và từ chối DAG có chu trình (`pedagogy.py:252-331`).
- `worker/generation.py` tạo `Unit`/`Lesson` theo `proposal.units[].lessonTitles`;
  **`lesson.title` bị ghi đè bằng `content.title` của provider** (`generation.py:294,309`)
  ⇒ map skill↔lesson **bắt buộc theo `(unit.order_index, lesson.order_index)`**, không theo title.
- `lesson_attempts` UNIQUE `(lesson_id,user_id,client_attempt_id)`, có `score_correct`,
  `score_total`, `content_version`, `duration_ms`, `results`.
- `submit_attempt` đã serialize theo user bằng `SELECT User.xp ... FOR UPDATE`
  (`lesson_service.py:103-114`).
- Progress tính từ attempts trên `contentVersion` hiện hành (`course_service.py:314-339`).
- Stack: Python 3.13, SQLAlchemy async, Alembic head = `0014_p43_ocr`, test SQLite in-memory
  (StaticPool, một connection) + PostgreSQL production. Message/UI tiếng Việt.
- `fsrs` 6.3.2: pure Python, `Requires-Dist: typing-extensions`, `Requires-Python >=3.10`.
  `Scheduler.review_card(card, rating, review_datetime, review_duration)`, `Rating` 1..4,
  `State` 1..3. **`enable_fuzzing` mặc định True** ⇒ phải truyền `False` để deterministic.
  **`Card.card_id` là `int`**, truyền `None` sẽ `sleep(1ms)` ⇒ luôn truyền int dẫn xuất.
  **`ReviewLog` không có `elapsed_days`/`scheduled_days`** ⇒ tự tính.

## 4. Phương án đã cân nhắc

| Phương án | Đánh đổi | Kết luận |
|---|---|---|
| A. Derive mastery on-the-fly, chỉ 2 bảng review | Ít migration; nhưng mỗi GET phải JOIN attempt→skill, không audit được, khó giải thích "vì sao" | Loại |
| **B. Snapshot mastery + 5 bảng + thư viện `fsrs`** | Nhiều bảng/migration hơn; truy vấn nhanh, audit được, giải thích được; thêm 1 dependency thuần Python | **CHỌN** |
| C. Như B nhưng tự viết FSRS | Không thêm dependency; nhưng tự bảo trì thuật toán + vector test, rủi ro lệch spec | Loại (người dùng chọn B) |

## 5. Thiết kế dữ liệu — migration `0015_p50_learner_profile` (expand-only)

```
skills(id UUID PK, course_id FK→courses CASCADE, key text, title text, bloom_level text,
       outcome text, order_index int, created_at, updated_at)
  UNIQUE(course_id, key)

lesson_skills(lesson_id FK→lessons CASCADE, skill_id FK→skills CASCADE, created_at)
  PK(lesson_id, skill_id)
  INDEX(skill_id)

skill_mastery(user_id FK→users CASCADE, skill_id FK→skills CASCADE,
              attempts int, correct int, total int, mastery_score float,
              last_attempt_at timestamptz, updated_at)
  PK(user_id, skill_id)
  INDEX(skill_id)          -- để tính coursePercent / gate prereq theo skill

review_cards(id UUID PK, user_id FK→users CASCADE, lesson_id FK→lessons CASCADE,
             skill_id FK→skills SET NULL nullable,
             state smallint, step smallint nullable,
             stability float nullable, difficulty float nullable,
             due_at timestamptz, last_review_at timestamptz nullable,
             scheduler_version text, created_from_attempt_id FK→lesson_attempts SET NULL,
             created_at, updated_at)
  UNIQUE(user_id, lesson_id)
  INDEX(user_id, due_at)

review_events(id UUID PK, card_id FK→review_cards CASCADE, user_id FK→users CASCADE,
              rating smallint, reviewed_at timestamptz,
              elapsed_days int, scheduled_days int,
              duration_ms int nullable,
              state_before smallint, state_after smallint,
              scheduler_version text, client_review_id text,
              created_at)
  UNIQUE(card_id, client_review_id)
  INDEX(card_id, reviewed_at), INDEX(user_id, reviewed_at)
```

- `skills.key` = `CurriculumSkill.id` từ proposal (ổn định **trong 1 course**).
- Không backfill dữ liệu giả: `skill_mastery` chỉ có row khi có attempt thật.
- `skills` **luôn upsert theo `(course_id, key)`**, không delete+insert — vì
  `skill_mastery.skill_id` là CASCADE, xoá skill sẽ xoá mất mastery.
- Downgrade đối xứng (drop 5 bảng mới); không sửa migration cũ.

## 6. Backfill skill

`backfill_course_skills(db, course)` — idempotent, đọc **proposal mới nhất** (hoặc proposal
version mà job đã dùng nếu có) rồi `normalize_curriculum` để lấp skill thiếu:

1. Upsert `skills` theo `(course_id, key)`; nếu trùng `key`/slug do `_slug()` cắt 24 ký tự
   thì thêm hậu tố `-2`, `-3` **deterministic theo thứ tự** và log cảnh báo.
2. Map `skill.lesson` (title **trong proposal**) → `(unit.order_index, lesson.order_index)`
   bằng vị trí trong `proposal.units`; tra `Lesson` theo **vị trí**, không theo title.
3. Upsert `lesson_skills` (idempotent).

Chạy: (a) inline ngay sau khi generation ghi lesson khi `P50_ENABLED=true`;
(b) task reconciler `backfill_all_skills` chỉ khi `P50_BACKFILL_ENABLED=true` (mặc định TẮT).

## 7. Mastery baseline (rule-based, deterministic)

Với mỗi skill, chỉ tính attempt có `content_version == lesson.content_version` hiện hành:

- `block_accuracy_i = score_correct_i / score_total_i` (an toàn khi `score_total == 0` ⇒ bỏ qua).
- `age_days_i = max(0, now - created_at_i)`; `weight_i = 0.5 ** (age_days_i / 30)`.
- `mastery_score = Σ(weight_i * block_accuracy_i) / Σ(weight_i)`, clamp [0,1].
- Lưu thêm `attempts`, `correct`, `total`, `last_attempt_at` để truy vết.

API trả `masteryScore` + `method: "rule_based"`, **không** gọi `probability`.
Ngưỡng đạt: `MASTERY_PASS_THRESHOLD=0.7` (env, PROPOSAL — cần hiệu chỉnh khi có dữ liệu thật).
Recency half-life 30 ngày là hằng số có tên `MASTERY_RECENCY_HALF_LIFE_DAYS`.

Mastery cập nhật trong **cùng transaction** với `submit_attempt` (sau khi grade, trước
`db.commit()`), upsert bằng `INSERT ... ON CONFLICT DO UPDATE` trên PostgreSQL
(`skill_mastery` PK). Trên SQLite (test) dùng nhánh `SELECT` + `INSERT/UPDATE` trong cùng
transaction — `submit_attempt` đã giữ lock `User` row nên tuần tự an toàn.
Nếu lesson **chưa có** `lesson_skills` (legacy chưa backfill) ⇒ bỏ qua mastery, ghi log, và
**không** làm attempt thất bại.

`contentVersion` đổi: **không reset** mastery. Vì mastery chỉ tính attempt đúng version hiện
hành, mastery của skill sẽ tự rơi về 0 khi version đổi cho tới khi có attempt mới (dữ liệu cũ
vẫn còn trong `lesson_attempts`). Ghi rõ trong docs.

## 8. FSRS (thư viện `fsrs`, pin version)

- `FSRS_SCHEDULER_VERSION = "py-fsrs-6.3.2"`; tham số mặc định của thư viện;
  `desired_retention=0.9`; `enable_fuzzing=False` (deterministic cho test và tái lập lịch).
- `learning_steps=()` và `relearning_steps=()` để card vào thẳng `State.Review`.
  Lý do: test deterministic + UX "ôn theo ngày", không có bước học 1/10 phút.
  Hệ quả đã đo: Again→1 ngày, Hard→1 ngày, Good→2 ngày, Easy→8 ngày.
- **Policy tạo card (đã chốt):** tạo khi có **attempt đầu tiên** của lesson (kể cả <80%),
  1 card / `(user, lesson)`. Rating khởi tạo suy ra từ `block_accuracy` của attempt:
  `<0.6 → Again(1)`, `<0.8 → Hard(2)`, `<1.0 → Good(3)`, `==1.0 → Easy(4)`.
  Nhờ vậy ôn bài yếu là luồng thật, không phải code chết.
- Người dùng chủ động ôn: 4 nút `Again/Hard/Good/Easy` gửi rating thật.
- Mọi thời điểm UTC aware. **SQLite trả datetime naive** ⇒ adapter luôn
  `_as_utc(dt)` (`dt.replace(tzinfo=UTC)` nếu `tzinfo is None`) trước khi gọi scheduler.
- `fsrs.Card.card_id` (int): dẫn xuất `int(uuid.int % (2**63 - 1))`; UUID vẫn là DB PK.
- `review_events` append-only (audit bất biến); `review_cards` là snapshot hiện tại.
  `elapsed_days`/`scheduled_days` do server tự tính (thư viện không trả).
- Idempotency: `clientReviewId` unique theo card; retry cùng id ⇒ trả **card hiện tại** +
  `duplicate=true`, không tạo event, không đổi lịch.

## 9. Next-lesson policy (đã chốt: chặn + fallback)

- `prerequisites` đọc từ proposal đã lưu (DAG đã validate P2.1).
- Bài kế tiếp hợp lệ khi `status=ready`, chưa completed, **và** mọi skill prerequisite có
  `mastery_score >= MASTERY_PASS_THRESHOLD`.
- Nếu bài kế tiếp bị chặn bởi prerequisite chưa đạt ⇒ **không** trả nó làm `nextLesson`;
  trả `nextLesson=null` + `blockedBy: [{lessonId,title,prerequisites:[...]}]` và fallback
  `reviewLessonId` = bài yếu nhất đã học (mastery thấp nhất) để UI đề xuất ôn.
- Mã lý do ổn định: `NEXT_IN_SEQUENCE`, `PREREQUISITES_MET`,
  `PREREQUISITE_NOT_MET` (chỉ giải thích), `FALLBACK_REVIEW_WEAKEST`.
- Mọi truy vấn scope `Course.user_id == user.id`; cross-user ⇒ 404.

## 10. API (mới, `/v1`)

```
GET  /v1/courses/{courseId}/mastery
     → {items:[{skillId, title, bloomLevel, masteryScore, method:"rule_based",
                attempts, correct, total, lastAttemptAt, passThreshold}],
        coursePercent, reviewDueCount}

GET  /v1/courses/{courseId}/learning-path
     → {nextLesson:{lessonId,title,reason:{code,message}}|null,
        reviewLessonId, reviewDueCount,
        blockedBy:[...], prerequisitesDag:{nodes,edges}}

GET  /v1/reviews/due?courseId=&limit=20
     → {items:[{cardId, lessonId, lessonTitle, skillTitle, dueAt, state,
                overdueDays}], total}

POST /v1/reviews/{cardId}/grade        (CSRF + rate limit + ownership)
     body {rating:1..4, clientReviewId, durationMs?}
     → {card:{cardId,dueAt,state}, eventId, duplicate}
```

- `stability`/`difficulty` **không** trả ra API người học (chỉ dùng nội bộ/debug log).
- Rating ngoài 1..4 ⇒ 422; card không thuộc user ⇒ 404; thiếu `clientReviewId` ⇒ 422.
- `AttemptOut` thêm field additive `reviewCardCreated: bool` để UI hiện thông báo
  "Đã thêm vào lịch ôn tập" (không phá contract cũ).
- Cờ `P50_ENABLED` (mặc định **false**): route vẫn đăng ký nhưng trả **503
  `P50_NOT_ENABLED`** (theo convention `tutor.py:95-104`), không tạo card, flow cũ nguyên.

## 11. Frontend

- `course/[courseId]`: khối **"Học tiếp"** (kèm lý do ngắn + `blockedBy` nếu có),
  khối **"Ôn tập (N)"**, và thanh mastery theo skill (không hiện chữ "xác suất").
- `review/page.tsx` (mới): hàng đợi card đến hạn; hiện tiêu đề bài + skill, nút
  "Hiện đáp án" (reveal tên bài/skill — **không** lộ answer key quiz), 4 nút rating có
  `aria-label`, "Còn N thẻ", empty state trung thực khi hết/hết hạn.
- `lesson/[lessonId]`: sau khi nộp, nếu `reviewCardCreated` hiện "Đã thêm vào lịch ôn tập".
- Một `clientReviewId` cho mỗi lần grade đang bay (giữ trong `useRef`), disable 4 nút khi
  pending. Invalidate TanStack Query sau grade attempt/review.
- Tuân `vercel-react-best-practices` + `web-design-guidelines`.

## 12. Tests bắt buộc

- Migration contract: `0015` metadata (5 bảng, UNIQUE/FK CASCADE/index), `down_revision=0014`.
- Backfill: proposal có skills/prerequisites ⇒ đúng `skills`+`lesson_skills`; proposal cũ
  thiếu curriculum ⇒ `normalize_curriculum` lấp; map theo vị trí **khi title lesson khác
  title proposal** (mô phỏng provider thật); slug trùng ⇒ hậu tố, không UNIQUE abort.
- Mastery: deterministic; nộp lại cùng version không tăng; version mới ⇒ mastery rơi về 0
  cho tới khi học lại; lesson chưa có skill ⇒ không crash; cross-user isolation.
- FSRS: pin `now` cố định; 4 rating cho due khác nhau; card tạo ngay ở attempt đầu;
  idempotent `clientReviewId`; rating ngoài khoảng ⇒ 422; naive datetime SQLite được ép UTC.
- Next-lesson: chặn khi thiếu prereq + trả `blockedBy` + fallback bài yếu; gợi ý đúng khi đủ.
- API: CSRF 403, rate limit 429, ownership 404, cờ tắt ⇒ 503.
- Regression: pytest hiện có (540 pass/25 skip) xanh; `npx tsc --noEmit` + `npm run build`.
- E2E `backend/e2e_acceptance.py`: thêm check mastery/learning-path/review grade khi
  `P50_ENABLED=true`; xác nhận flow cũ không đổi khi cờ tắt.

## 13. An toàn

- Ownership ở SQL; mastery/server tính từ attempt đã lưu, không nhận score từ client.
- Rating client chỉ dùng làm input FSRS, không ảnh hưởng điểm bài/XP.
- Log chỉ id + rating + interval; không log nội dung bài/đáp án.
- Không mở route ghi nào cho user khác; card/event scope theo `user_id`.

## 14. Ngoài phạm vi

- Không BKT/DKT/bandit; không hiệu chuẩn mastery thành xác suất.
- Không notify/push/email nhắc ôn.
- Không đổi `completed/total`/XP của P1.1.
- Không chọn timezone ở server; due lưu UTC, hiển thị theo máy người dùng.

## 15. Thứ tự thực hiện

1. `requirements.txt` + `fsrs`; migration `0015` + model + contract test.
2. `mastery_service` + `backfill_course_skills`; hook vào generation.
3. Hook mastery vào `submit_attempt` (+ `reviewCardCreated`).
4. `spaced_repetition_service` (fsrs adapter, pin version, UTC coercion).
5. `learning_path_service` (next lesson + reasons + fallback).
6. API routes (`api/v1/learner.py` — mastery/learning-path/reviews) + schemas.
7. Frontend: course blocks + `/review` + lesson notice.
8. Tests + docs/progress.

## 16. Quyết định đã chốt

| # | Quyết định |
|---|---|
| 1 | Tạo review card ở **attempt đầu tiên** (kể cả <80%), 1 card/(user,lesson) |
| 2 | 1 card/bài, recall theo **chủ đề bài + skill** (không lộ answer key) |
| 3 | Mastery = accuracy có recency half-life **30 ngày**; ngưỡng đạt **0.7** (PROPOSAL, env) |
| 4 | `contentVersion` đổi: **không reset**, mastery tự rơi về 0 cho tới attempt mới |
| 5 | Prereq chưa đạt: **chặn** bài mới + **fallback ôn bài yếu** kèm lý do |
| 6 | Thêm dependency `fsrs>=6.3,<7` (pure Python, chỉ kéo `typing-extensions`) |
