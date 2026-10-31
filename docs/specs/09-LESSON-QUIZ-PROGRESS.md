# 09 — Lesson Engine, Quiz, Progress & XP

**Trạng thái:** P1.1 đã được báo cáo IMPLEMENTED + TESTED; kiểm tra code hiện tại trước khi thay đổi. Policy 80% cần product owner chốt lâu dài.

## 1. Block contract

| Block | Public payload | Private grading key | Grading |
|---|---|---|---|
| `teach` | Nội dung giảng, ví dụ | Không có | Không chấm |
| `mc` | Câu hỏi + options | `answerIndex` | So index/ID hợp lệ |
| `blank` | Câu điền với `____` | normalized accepted answer(s) | Trim + casefold theo policy |
| `order` | Các items được shuffle, stable public IDs | thứ tự đúng/private IDs | So full ordered ID sequence |
| `match` | Hai nhóm được shuffle, stable public IDs | đúng map cặp ghép | So pair mapping |
| `short` | Câu hỏi tự luận ngắn | `acceptedAnswers[]` hoặc rubric | Giai đoạn hiện tại exact-match normalized, **không** LLM grading |

Kiểu `short` nếu mở rộng semantic grading bằng LLM là phase khác, phải tách `pending`/rubric và evaluation; không tự dùng LLM để chấm chính xác như quiz đóng.

## 2. Requirements

| ID | Yêu cầu |
|---|---|
| LESSON-001 | Public `GET lesson` không lộ bất cứ answer key trước submit |
| LESSON-002 | Server chấm, client không được gửi `correct`, `score` hay giải pháp |
| LESSON-003 | `order` và `match` không tiết lộ đáp án qua thứ tự public arrays |
| LESSON-004 | Attempts lưu `clientAttemptId`, `contentVersion`, answer/results/score, userId từ session |
| LESSON-005 | Same clientAttemptId retry → same result/reward, kể cả concurrency |
| LESSON-006 | Stale contentVersion → 409, không làm mất attempt cũ |
| LESSON-007 | Progress từ attempts đạt yêu cầu ở version hiện hành, không phải lesson ready |
| LESSON-008 | XP award không thể farm bằng repeated attempts; transaction/unique enforced |
| LESSON-009 | Sau submit có feedback/solution theo policy nhưng không leak trước submit |
| LESSON-010 | Lessons ít nhất một teach + một quiz; typed blocks validate đủ |

## 3. Public/private separation

- Bản ghi `Lesson.content` private có answer keys; API read dùng `public_blocks` projection server-side.
- `order`/`match` dùng stable IDs theo lessonId/contentVersion/blockId, shuffle ổn định; không gửi private canonical order.
- Response `POST attempts` mới trả `results[].solution`, score, reward (`xpEarned` từ `attempt.xp_awarded` đã ghi, không tính lại sau).
- Test E2E **không** dựa vào đáp án đọc từ GET public; dùng private test fixture/database dành cho test.

## 4. Progress and XP policy

**INCUMBENT (đang áp dụng theo progress, product approval pending):**

```text
lesson_completed = exists(attempt where user matches,
   attempt.content_version == lesson.content_version,
   correct/total >= 0.80)
course_progress_percent = 100 * completed_current_lessons / total_ready_lessons
```

- Nếu `total_ready_lessons=0`: percent = 0 (tránh chia 0).
- Lịch sử attempts phiên bản cũ được giữ, nhưng không tính đạt bản mới nếu nội dung thay đổi; version bump chỉ khi title/content thực thay đổi.
- XP upper-bound theo `(user, lesson, contentVersion)`; reattempt chỉ cộng chênh lệch tối đa. Lock/unique ở DB bảo vệ concurrent submissions.
- Policy mức thưởng/threshold 80% và behavior khi remake content cần quyết định product chính thức nếu ra production.

## 5. Attempt lifecycle

1. Client lưu draft answers tại UI, tạo một `clientAttemptId` cho **một lần nộp**.
2. POST `results[]` và contentVersion; backend auth & owner, validate indices/IDs, reject duplicates/extra fields, lock XP data.
3. Chấm private answer key, insert attempt hoặc replay existing, allocate XP an toàn, commit transaction.
4. Trả result/solution/reward; frontend invalidate course/progress/XP queries.
5. Nếu timeout phía client: retry **cùng** clientAttemptId, không tạo id mới.

## 6. Negative and concurrency tests

- Missing/foreign lesson → 404; malformed answer/boolean injected → 422.
- GET all 5 quiz types không chứa answer keys; `order`/`match` shuffle không leak solution.
- `correct=true`, score client giả, invalid index/duplicate blocks → bị reject/ignore an toàn.
- 20 POST cùng id dưới PostgreSQL → một attempt, một XP award; 20 POST id khác nhau → XP vẫn không quá cap.
- Regen changed content → version tăng, past attempts còn; stale submit → 409; unchanged content → không tăng version giả.
- Reload / switching users giữ progress đúng và không leak A sang B.
