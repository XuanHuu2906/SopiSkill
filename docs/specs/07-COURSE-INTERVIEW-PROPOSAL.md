# 07 — Course, Interview & Proposal Specification

**Trạng thái:** Core flow REPORTED IMPLEMENTED; learner profile, DAG, proposal editing là PROPOSAL.

## 1. Requirements

| ID | Behavior | Verification |
|---|---|---|
| COURSE-001 | Topic bắt buộc, 1–200 ký tự và đã trim | Empty/too-long → validation error |
| COURSE-002 | Create idempotent theo clientCourseId/user | Retry cùng key không trùng course |
| COURSE-003 | Mỗi course có đúng 5 interview questions, không rỗng/trùng | Schema + semantic test |
| COURSE-004 | Câu trả lời gắn position; không được ghi ngoài 1..5 hoặc sai owner | Negative tests |
| COURSE-005 | Chỉ khi đủ 5 câu mới sinh/hiển thị proposal hợp lệ | State tests |
| COURSE-006 | Proposal versioned, units/lessons/outcomes và mục tiêu học rõ | Schema+lint |
| COURSE-007 | Approve pins current proposal version, không tạo 2 active jobs | Concurrent approve tests |
| COURSE-008 | Reject invalid state transitions; server authoritative | 409/422 matrix |
| COURSE-009 | Profile snapshot từ 5 câu + DAG prerequisites acyclic | P2.1 tests |
| COURSE-010 | Cho phép revise proposal (nếu được duyệt) bằng version conflict control | P2.x future gate |

## 2. Interview schema

**Inputs về mặt nghiệp vụ:** chủ đề, mức kiến thức hiện tại, mục tiêu, thời lượng dự kiến, phong cách học/ràng buộc. Hệ thống có thể điều chỉnh câu chữ theo topic, nhưng luôn **5 câu**.

**Minimum normalized answer model (P2.1 proposed):**

```json
{
  "currentLevel":"beginner",
  "goal":"Viết các chương trình Python đơn giản",
  "availableMinutesPerDay":20,
  "preferredLanguage":"vi",
  "preferredStyle":"examples-first",
  "uncertainties":["thời gian tự khai chưa được kiểm chứng"]
}
```

Đây là profile rút trích theo dữ liệu người học tự nhập, **không** suy đoán khả năng thực tế, đặc điểm nhạy cảm hay bệnh lý. Nếu thiếu thông tin, giữ unknown và không tự bịa. `preferredLanguage` là proposal mới cần chốt UX.

## 3. Proposal schema & constraints

Theo tài liệu hiện hữu: proposal gồm name/title, objective, difficulty, `units[]`, learning outcomes; mỗi unit có title, blurb/objectives và danh sách lesson titles. Tài liệu DB gợi ý **2–6 units, tổng 2–40 lessons**; validator hiện tại cần audit trước khi siết giới hạn mới.

**Proposed P2.1 enhancements:**

```json
{
  "schemaVersion":2,
  "title":"Python cho người mới",
  "objective":"Viết và kiểm thử chương trình cơ bản",
  "difficulty":"beginner",
  "learningOutcomes":[{"id":"lo-1","verb":"explain","text":"Giải thích biến và kiểu dữ liệu"}],
  "units":[{"id":"unit-1","title":"Nhập môn","lessonTitles":["Biến và kiểu dữ liệu","Điều kiện"]}],
  "curriculumGraph":{"nodes":[{"skillId":"python-basics","label":"Cú pháp cơ bản"}],"edges":[]}
}
```

- Validate stable IDs unique, no empty title/outcome, no duplicate unit/lesson names, no cycle in graph.
- Mỗi lesson ánh xạ ít nhất một outcome; prerequisites phải thuộc graph.
- LLM JSON chỉ là **candidate**; Pydantic + semantic lint quyết định accept/reject.
- Client không được tự gửi approved status hoặc sửa `schemaVersion` trực tiếp vào DB.

## 4. State machine

```text
interview --(answer #5 + valid proposal)--> proposed
proposed --(approve current version, txn)--> approved
approved --(job claimed)--> generating
generating --(success)--> ready
generating --(fatal/exhausted)--> failed
failed --(explicit retry)--> approved/queued new job --> generating
```

Không tái dùng `ready` để biểu thị đã học xong; ready = nội dung đã sẵn sàng. State transition cụ thể cần audit code để giữ backward compatibility.

## 5. Approval consistency

- Approve trong transaction check current proposal version, owner, state, active job; set `approved_at` và create job.
- Duplicate concurrent approve trả active job hoặc conflict có cấu trúc; không tạo 2 jobs cùng active window.
- Nếu có future edit: sửa tạo **new proposal version**; version đã approve giữ immutable snapshot; chỉ re-approve explicit mới generate nội dung từ version mới.

## 6. UI acceptance

- Trang interview sau reload đánh dấu những câu đã trả lời và tiếp tục câu chưa trả lời; **không hiện lại text cũ** theo policy hiện tại.
- Proposal hiện loading/error/approved rõ; approve disabled sau click/đã approve.
- Nếu chỉnh sửa chưa triển khai, UI không hiển thị nút sửa giả.
- Proposal được xem trước mọi job sinh lessons. User B không đọc được proposal A.

## 7. Không làm trong phase P2.1

Không xoá interviews đã lưu, không tự thực hiện regenerate hàng loạt, không thêm billing, không train LLM, không bảo đảm mọi mục tiêu sư phạm đúng nếu chưa eval.
