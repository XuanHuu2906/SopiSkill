# 07 — Course, Interview & Proposal Specification

**Trạng thái (`2026-11-22`):** Core flow + **P2.1** (`LearnerProfile` + curriculum DAG `skills`/`prerequisites`) **IMPLEMENTED · REPORTED TESTED**. Bản sửa **`P1-PEDAGOGY`** (parser tiếng Việt không dấu/word boundary) **IMPLEMENTED · REPORTED TESTED** ở working tree nhưng **chưa deploy vào container**. Các mục `P1-LANG`, `P1-LEVEL-FIT` và `COURSE-010` (chỉnh sửa Proposal) vẫn đang **OPEN / PROPOSAL**.

## 1. Requirements

| ID | Behavior | Trạng thái (2026-11-22) |
|---|---|---|
| COURSE-001 | Topic bắt buộc, 1–200 ký tự và đã trim | **IMPLEMENTED · TESTED** |
| COURSE-002 | Create idempotent theo `(userId, clientCourseId)` | **IMPLEMENTED · TESTED** |
| COURSE-003 | Mỗi course có đúng 5 câu interview, không rỗng/trùng | **IMPLEMENTED · TESTED** |
| COURSE-004 | Câu trả lời gắn `position` (`0..4`); kiểm tra owner & biên | **IMPLEMENTED · TESTED** |
| COURSE-005 | Chỉ đủ 5 câu mới sinh/hiển thị proposal hợp lệ | **IMPLEMENTED · TESTED** |
| COURSE-006 | Proposal versioned (`name`, `objective`, `units[2..6]`, `outcomes[2..8]`) | **IMPLEMENTED · TESTED** |
| COURSE-007 | Approve pins current proposal version, không tạo 2 active jobs | **IMPLEMENTED · TESTED** |
| COURSE-008 | Reject invalid state transitions; server authoritative | **IMPLEMENTED · TESTED** |
| COURSE-009 | `LearnerProfile` deterministic từ 5 câu + DAG `skills`/`prerequisites` acyclic | **IMPLEMENTED · TESTED** (`P1-PEDAGOGY` chưa deploy container) |
| COURSE-010 | Cho phép revise proposal trước approve (versioned `PATCH` hoặc `PlanChat` + `revise_proposal`) | **PROPOSAL / NOT IMPLEMENTED** (`GAP-08`) |

## 2. Interview & LearnerProfile thực tế (`backend/app/schemas/schemas.py`, `services/pedagogy.py`)

- **Interview hiện tại:** 5 câu hỏi text thuần (`InterviewOut {questions[5], completedCount}`), người học nhập tự do (`answer: 1..2000`). *(Khác với PolySkill có `kind: single|multi` + `choices[2..6]` — ghi nhận tại `GAP-04`.)*
- **`LearnerProfile` thực tế do server trích xuất rule-based:**
```json
{
  "goal": "Viết các chương trình Python đơn giản",
  "currentLevel": "beginner",
  "weeklyMinutes": 180,
  "preferredStyles": ["hands_on", "visual"],
  "depth": "deep",
  "warnings": []
}
```
- **`P1-PEDAGOGY` (`2026-11-05`, uncommitted):** bổ sung `_fold()` bỏ dấu tiếng Việt (`đ→d`, NFD), word-boundary lookaround chống false positive (`4th`, `trong`, `sau`), nhận dạng `phut/gio/tieng/min/hr`, `"hiểu sâu"`, `"đồ thị"`, `"ví dụ thực tế"`, và phát `warnings[]` khi có xung đột `deep` vs `broad` (`tests/test_p1_pedagogy.py`: 54 tests reported pass).
- **Khoảng trống còn mở:**
  - **`P1-LEVEL-FIT`:** kiểm soát prompt/profile để model không tự đẩy độ khó lên `advanced` trái với mức học viên yêu cầu (8/11 topic lệch level trong real eval `2026-11-04`).
  - **`P1-LANG`:** chưa có tham số `language` xuyên suốt course → proposal → lesson → tutor (6/6 topic tiếng Anh trong real eval bị trả tiếng Việt).

## 3. Proposal schema thực tế (`ProposalPayload`)

```json
{
  "name": "Python cho người mới",
  "objective": "Viết và kiểm thử chương trình cơ bản",
  "units": [
    {"title": "Nhập môn", "blurb": "...", "lessonTitles": ["Biến và kiểu dữ liệu", "Điều kiện"]}
  ],
  "outcomes": ["Giải thích biến và kiểu dữ liệu", "Viết rẽ nhánh cơ bản"],
  "learnerProfile": { "...": "..." },
  "skills": [
    {"id": "sk-1", "title": "Biến và kiểu dữ liệu", "lesson": "Biến và kiểu dữ liệu", "bloomLevel": "understand", "outcome": "..."}
  ],
  "prerequisites": [["sk-1", "sk-2"]]
}
```
- `units`: 2–6 units, mỗi unit 1–12 `lessonTitles`; `outcomes`: 2–8; `skills`: tối đa 48; `prerequisites`: tối đa 96 cạnh `[prereqId, skillId]`.
- Validator kiểm tra DAG acyclic, endpoint tồn tại, mapping lesson hợp lệ; legacy proposal chưa có `learnerProfile`/`skills` vẫn đọc được bình thường.

## 4. State machine & Approval consistency

```text
interview --(answer #5 + valid proposal)--> proposed
proposed  --(approve current version, txn)--> approved
approved  --(job claimed)--> generating
generating --(success)--> ready
generating --(fatal/exhausted)--> failed
failed    --(explicit retry)--> approved/queued new job --> generating
```
- Approve kiểm tra owner, state, current version và không có active job trong transaction; pin `proposal_version` trên `generation_jobs`.
- Nếu mở rộng `COURSE-010` (Proposal revision) ở phase sau: giữ immutable snapshot cho version đã approve; mỗi lần sửa tăng `version` và yêu cầu re-approve tường minh trước khi generate.

## 5. UI acceptance (FR-1..FR-5)

- `/new/interview` tiếp tục đúng câu chưa trả lời sau reload.
- `/new/proposal` hiển thị plan card, units/lessons, outcomes, stat strip; không hiển thị nút "Chỉnh sửa" giả khi `COURSE-010` chưa có backend contract.
- Cross-owner truy cập interview/proposal trả `404`.
