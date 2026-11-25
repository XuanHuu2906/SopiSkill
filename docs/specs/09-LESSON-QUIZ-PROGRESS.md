# 09 — Lesson Engine, Quiz, Progress & XP

**Trạng thái (`2026-11-22`):** **P1.1**, **P6.1 HMAC shuffle**, **`P1-QUIZ-BLANK`** (`BLANK_SLOT_COUNT=1`), **P5.0 `reviewCardCreated`** và **FR-4/FR-5 step-by-step lesson player** đã **IMPLEMENTED · REPORTED TESTED**. Policy hoàn thành `≥80%` và thang XP vẫn giữ nhãn `INCUMBENT / PRODUCT APPROVAL PENDING`.

## 1. Block contract hiện hữu (`schemas.py`, `lesson_content.py`, `validation.py`)

| Block | Public payload (`GET /v1/lessons/{id}`) | Private grading key (`Lesson.content`) | Grading hiện tại |
|---|---|---|---|
| `teach` | `title`, `paragraphs[]` (1..30) | Không có | Không chấm |
| `mc` | `question`, `options[2..6]` | `answerIndex` | So index hợp lệ (từ chối `bool`) |
| `blank` | `sentence` (bắt buộc đúng **1** chỗ trống `____`) | `answer` | Trim + casefold exact-match |
| `order` | `prompt`, `items[]` đã shuffle bằng **HMAC key** + stable public IDs | thứ tự gốc | So full ordered ID sequence |
| `match` | `prompt`, hai cột đã shuffle bằng **HMAC key** + stable public IDs | `pairs[]` | So pair mapping |
| `short` | `question` | `acceptedAnswers[1..10]` | Exact-match normalized; **chưa có** LLM rubric grading |

## 2. Requirements

| ID | Yêu cầu | Trạng thái |
|---|---|---|
| LESSON-001 | Public `GET /v1/lessons/{id}` không lộ bất cứ answer key trước submit | **IMPLEMENTED · TESTED** |
| LESSON-002 | Server chấm toàn bộ; client không gửi `correct`/`score` (`extra=forbid`, reject `bool`) | **IMPLEMENTED · TESTED** |
| LESSON-003 | `order`/`match` shuffle bằng HMAC `LESSON_SHUFFLE_SECRET` (fallback `JWT_SECRET`), không suy ngược được từ dữ liệu công khai | **IMPLEMENTED · TESTED** (P6.1) |
| LESSON-004 | Attempts lưu `clientAttemptId`, `contentVersion`, `answers/results/score`, `userId` từ session | **IMPLEMENTED · TESTED** |
| LESSON-005 | Same `clientAttemptId` retry → same result/reward, kể cả concurrent Postgres | **IMPLEMENTED · TESTED** |
| LESSON-006 | Stale `contentVersion` → `409`, không làm mất attempt cũ | **IMPLEMENTED · TESTED** |
| LESSON-007 | Progress tính từ attempts đạt `≥80%` ở `contentVersion` hiện hành | **IMPLEMENTED · TESTED** |
| LESSON-008 | XP cap theo `(user, lesson, contentVersion)`; transaction + row lock chống farm | **IMPLEMENTED · TESTED** |
| LESSON-009 | Sau submit mới trả `results[].solution`, `score`, `rewards` | **IMPLEMENTED · TESTED** |
| LESSON-010 | Mỗi lesson có ≥1 `teach` + ≥1 quiz; `blank` đúng 1 chỗ trống; worker gọi `validate_lesson` | **IMPLEMENTED · TESTED** (`P1-QUIZ-BLANK`) |

## 3. Public/private separation (ưu thế bảo mật của SopiSkill)

- Khác với PolySkill (chấm `mc`/`blank`/`order`/`match` ở client bằng đáp án nằm trong payload bài học), **SopiSkill giữ nguyên tắc server-authoritative 100%**.
- `Lesson.content` chỉ lưu phía server; `GET /v1/lessons/{id}` luôn chiếu qua `public_block()`.
- `order`/`match` dùng HMAC key bí mật (`LESSON_SHUFFLE_SECRET`, bắt buộc tồn tại ở production — cả `backend` và `worker` dùng chung khoá để không lệch hoán vị).
- `GET /v1/lessons/{id}` còn trả `grounding` (`source_grounded` | `general_ai_knowledge`), `citations[]` và `evidenceNotice`.

## 4. Progress & XP policy (`lesson_service.py`)

**INCUMBENT (đang chạy trong code, chờ product approval chính thức):**

```text
XP_PER_CORRECT = 10
XP_LESSON_COMPLETED_BONUS = 20
lesson_completed = (correct / total >= 0.80) at current lesson.content_version
course_progress_percent = 100 * completed_current_lessons / total_ready_lessons
```
- `xp_awarded` chỉ cộng phần chênh lệch so với mức XP cao nhất user đã từng đạt cho cùng `(user, lesson, contentVersion)`; retry/replay không farm được XP.
- Khi `P50_ENABLED=true`, nộp attempt kích hoạt cập nhật `skill_mastery` và khởi tạo `review_cards` (`AttemptOut.reviewCardCreated = true`).

## 5. Attempt lifecycle

1. Player dạng bước (FR-4) hiển thị 1 block/màn, giữ draft answers trên client, mint 1 `clientAttemptId` cho mỗi lần nộp.
2. Client `POST /v1/lessons/{id}/attempts` với `{clientAttemptId, contentVersion, durationMs?, answers: [{index, answer}]}`.
3. Backend xác minh owner, `contentVersion`, schema, lock XP của user, chấm theo private `Lesson.content`, ghi/replay `lesson_attempts` và `xp_events`, trả `AttemptOut` kèm `results[].solution`.
4. Frontend invalidate session-scoped queries (`course`, `courses`, `me`, `mastery`, `learning-path`).

## 6. Mở rộng đề xuất từ đối chiếu PolySkill (`PROPOSAL — NOT IMPLEMENTED`)

Xem chi tiết trong `docs/frontend-reference/api-gap-register.md`:
- **Per-block grading & AI Short-Answer Rubric Grader (`GAP-11`):** thêm `POST /v1/lessons/{id}/blocks/{index}/grade` để cho phản hồi tức thì từng câu **nhưng vẫn giữ đáp án ở server**, riêng `short` hỗ trợ chấm rubric (`got_it | almost | not_yet`, `keyPoints[]`, `feedback`) + `dispute`.
- **Glossary & Recap (`GAP-06`, `GAP-14`):** thêm `terms[]`, inline `termKey`, `takeaway`, và `GET /v1/courses/{id}/glossary`.
- **Figures, Tables, MathJax & Practice Formats (`GAP-16`, `GAP-17`, `GAP-18`):** `teach.figure` (`formula`/`table`/`visual`/`diagram`), MathJax `$...$`, `estimatedMinutes`, practice formats (`scenario`, `spot`, `speed`, `explain`), và Reel engine (đánh giá ROI riêng trước khi đầu tư).
