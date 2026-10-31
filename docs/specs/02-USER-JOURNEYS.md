# 02 — User Journeys & Stories

**Trạng thái:** Core journeys được ghi nhận trong docs; những journey sau P3/P4 là PROPOSAL.

## 1. Journey A — Tạo khóa học từ chủ đề (core)

**Điều kiện:** đã đăng nhập; cookie/CSRF hợp lệ.

1. User vào `/new`, nhập topic 1–200 ký tự, nhấn tạo. Client gửi `clientCourseId` để retry không sinh course trùng.
2. Server tạo course `interview`, sinh/cung cấp 5 câu hỏi; user trả lời lần lượt, có thể tiếp tục sau reload.
3. Đủ 5 câu, hệ thống sinh proposal versioned: title/objective/units/lesson titles/outcomes. User xem trước khi approve.
4. User approve; API phản hồi job `queued`; frontend đến `/new/generating` và poll trạng thái **2 giây**; ngừng poll khi `ready/failed`.
5. Job sẵn sàng: vào `/course/[courseId]`, thấy cấu trúc bài học; chọn `/lesson/[lessonId]`.
6. Sau quiz, server trả score/feedback, course progress cập nhật; reload không mất attempts.

**Ngoại lệ phải xử lý:** topic rỗng; submit câu số 5 hai lần; approve đôi; network timeout sau request commit; Celery/Redis unavailable; worker crash; failed job retry không làm mất bài cũ.

## 2. Journey B — Học và làm quiz (core)

- Lesson có nội dung `teach` và một hoặc nhiều block quiz (`mc`, `blank`, `order`, `match`, `short`).
- `GET lesson` trả **public blocks**, không chứa answer key. Trạng thái UI local giữ draft answers, submit theo `contentVersion`.
- `POST attempts` với `clientAttemptId` ổn định; server grade deterministic cho dạng đóng; kết quả mới có solution/reward.
- Nếu `contentVersion` thay đổi trước submit: trả 409, UI hướng dẫn tải bài mới, không tự nộp phiên bản cũ.
- Khi đạt threshold 80% theo **policy hiện hành chưa duyệt dài hạn**, lesson tính completed; XP không được farm bằng submit trùng.

## 3. Journey C — Hỏi AI Tutor theo bài (P3; proposed)

1. User mở panel tutor tại block của một lesson thuộc course của mình.
2. Client POST message với `clientMessageId`, `threadId?` và `contextRef { lessonId, blockIndex }`.
3. Backend xác minh user/course/lesson/block, dùng ngữ cảnh từ DB, stream `delta` và `done` hoặc `error`.
4. User reload: thread đã lưu với message final; user B không thấy thread của A.
5. Stop được hiểu là **yêu cầu hủy best-effort**, không hứa reverse phí provider. Reconnect trong lúc stream **không** mặc định replay token khi chưa có event log.

**Ngoại lệ:** blockIndex sai, lesson thuộc người khác, quota hết, stream lỗi, double-click, prompt injection.

## 4. Journey D — Học từ PDF có citation (P4; proposed)

1. User có quyền dùng tài liệu, upload PDF qua UI; server kiểm tra MIME, size, ownership.
2. Worker extract text theo page, chunk có provenance; file không có text trả trạng thái phù hợp (OCR là nhánh tùy chọn).
3. User đặt câu hỏi; retrieval chỉ lấy nguồn có quyền; server validate mọi citation theo `sourceId/chunkId/page` có trong DB.
4. UI hiển thị link mở trang tài liệu phù hợp. Nếu không có evidence, tutor nói không đủ thông tin thay vì tạo citation.

**Ngoại lệ:** file quá lớn, corrupt, scan, chứa chỉ dẫn tấn công prompt, PDF không thuộc user, upload trùng.

## 5. Journey E — Gợi ý học tiếp (P5; proposed)

- User xem dashboard bài sẵn có/đã hoàn thành; hệ thống xếp bài theo prerequisites và skill mastery rule-based.
- Có lý do gợi ý minh bạch; FSRS review chỉ khi đã có history phù hợp.
- Khi thiếu dữ liệu, không hiển thị dự đoán năng lực không có cơ sở.

## 6. Cross-cutting acceptance

- Một user không thể truy cập course/lesson/proposal/job/tutor/source của user khác (server 404 hoặc policy tương đương để không leak existence).
- Reload và account-switch không hiển thị dữ liệu cache người trước.
- Trạng thái loading, empty, error, retry, cancelled rõ ràng; request lỗi không bị trình bày như thành công.
- Mọi thao tác chịu phí phải có giới hạn và trạng thái nguồn dữ liệu xác thực.
