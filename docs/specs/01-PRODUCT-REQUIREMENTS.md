# 01 — Product Requirements Document (PRD)

**Sản phẩm:** SopiSkill — AI Learning Platform, nền tảng học tập cá nhân hóa độc lập.  
**Trạng thái:** DRAFT; baseline và backlog phân biệt theo `00-STATUS-AND-SOURCES.md`.

## 1. Vấn đề và giá trị

Người tự học có mục tiêu không đồng đều, tài liệu rời rạc, khó chọn thứ tự kiến thức và thiếu phản hồi đúng lúc. Sản phẩm tổ chức trọn chuỗi **xác định nhu cầu → duyệt lộ trình → học bài → tự kiểm tra → hỏi AI trong ngữ cảnh → theo dõi tiến độ**; dài hạn gắn với tài liệu có nguồn đối chiếu.

**Không** hứa cải thiện điểm số theo một tỷ lệ cụ thể. Nghiên cứu sư phạm trong báo cáo đính kèm là bối cảnh, không chứng minh hiệu quả của ứng dụng này.

## 2. Người dùng và kịch bản

- **Learner:** tự học, sinh viên, người ôn phỏng vấn hoặc bổ sung kỹ năng; sử dụng web trên desktop/mobile browser.
- **Admin/operator (nội bộ, tương lai):** quan sát job, lỗi model, quota; không được xem nội dung cá nhân nếu chưa có chính sách/quyền tương ứng.
- **System worker:** xử lý generation/ingestion, không phải actor đăng nhập.

Mặc định giao diện tiếng Việt; ngôn ngữ đầu ra khóa học phải có lựa chọn rõ ở phase nâng cao. Không suy đoán người dùng là trẻ em hay cần chế độ học đặc thù nếu chưa có yêu cầu.

## 3. Yêu cầu chức năng

| ID | Mô tả kiểm chứng được | Độ ưu tiên | Giai đoạn |
|---|---|---|---|
| PRD-001 | Người dùng đăng ký/đăng nhập, dữ liệu course tách biệt theo owner | Must | Core (reported) |
| PRD-002 | Tạo course từ topic hợp lệ và trả lời **đúng 5** câu interview | Must | Core (reported) |
| PRD-003 | Xem đề cương versioned trước approve; không generate lessons nếu chưa approve | Must | Core (reported) |
| PRD-004 | Sinh lessons bất đồng bộ, theo dõi state/progress, lỗi và retry an toàn | Must | Core (reported) |
| PRD-005 | Đọc lesson blocks và submit quiz; server grade; progress bền vững | Must | Core (reported) |
| PRD-006 | LLM thật tạo nội dung có schema và đánh giá sư phạm/cost có bằng chứng | Must cho AI MVP | P2.1–P2.2 |
| PRD-007 | Tutor stream trả lời từ context lesson, history owner-scoped | Should | P3.0–P3.1 |
| PRD-008 | Upload PDF thuộc quyền người dùng và trả lời có citation đúng page/chunk | Should | P4.0–P4.1 |
| PRD-009 | Có đề xuất bài tiếp theo/ôn tập từ lịch sử học và skill graph | Could | P5 |
| PRD-010 | Hệ thống vận hành có CI, backup-restore, chính sách dữ liệu và quota | Must trước public launch | P6 |

## 4. MVP milestones, không gộp một lần triển khai

- **Core demo (báo cáo đã có):** đăng nhập, tạo course topic → 5 answers → proposal → approve → 4 lessons mock → quiz → progress/reload.
- **AI course MVP (P2.1–P2.2):** real provider được phê duyệt, structured/curriculum DAG, evaluation/cost report; mock vẫn hoạt động offline.
- **Tutor MVP (P3.0–P3.1):** stream grounded lesson, persistent thread, quota, cancellation semantics minh bạch.
- **Document-grounded MVP (P4.0–P4.1):** text PDF -> source chunks -> hybrid retrieval -> validated citations.
- **Production release (P6):** chỉ sau security/operations gate và owner approval.

## 5. In-scope / out-of-scope

**Trong phạm vi theo phase:** web app, course generator, lesson, quiz, progress, tutor, RAG PDF, quản lý nguồn, quality & observability.  
**Ngoài phạm vi trước MVP:** copy UI/API PolySkill, native mobile, social sharing, billing, streak/hearts/leaderboard nâng cao, fine-tuning/training model từ đầu, full RL, scraper không được phép, OCR mọi file.

## 6. Chỉ số thành công (đề xuất; chưa có baseline)

- **Funnel:** course created → interview completed → proposal approved → generation ready → first lesson started → first quiz submitted.
- **Correctness:** API không rò answer key, cross-owner 404, quiz score server-side, attempts/retries idempotent.
- **Quality:** pass schema/semantic validation, rubric pedagogy, lesson/quiz alignment, human review sample.
- **Reliability/cost:** generation failure rate, p95 job duration, tokens & provider cost per generated course, tutor time to first token, citation validity.
- **Learning:** tỷ lệ hoàn thành lesson và review retention; không đồng nhất engagement với kết quả học tập.

Ngưỡng sản phẩm cụ thể cần lấy baseline trước khi áp dụng hard gate; xem `14` và `19`.

## 7. Điều kiện nghiệm thu tổng quát

Một increment chỉ xong nếu có: contract, migration (nếu cần), kiểm tra owner/CSRF, unit/integration/E2E phù hợp, chứng cứ lệnh chạy, thay đổi docs và báo cáo `IMPLEMENTED / TESTED / NOT TESTED / BLOCKED`. Feature dùng AI trả phí phải có phê duyệt scope/budget/dữ liệu gửi ra ngoài.
