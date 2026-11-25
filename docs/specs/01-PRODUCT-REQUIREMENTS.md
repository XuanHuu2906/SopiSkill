# 01 — Product Requirements Document (PRD)

**Sản phẩm:** SopiSkill — AI Learning Platform, nền tảng học tập cá nhân hóa độc lập.  
**Trạng thái:** Cập nhật `2026-11-22`; baseline thực tế và backlog phân biệt rõ theo `00-STATUS-AND-SOURCES.md`.

## 1. Vấn đề và giá trị

Người tự học có mục tiêu không đồng đều, tài liệu rời rạc, khó chọn thứ tự kiến thức và thiếu phản hồi đúng lúc. Sản phẩm tổ chức trọn chuỗi **xác định nhu cầu → duyệt lộ trình → học bài → tự kiểm tra → hỏi AI trong ngữ cảnh → theo dõi tiến độ & ôn tập cách quãng**, gắn với tài liệu có nguồn đối chiếu.

**Không** hứa cải thiện điểm số theo một tỷ lệ cụ thể. Nghiên cứu sư phạm chỉ là bối cảnh thiết kế, không chứng minh hiệu quả của ứng dụng này.

## 2. Người dùng và kịch bản

- **Learner:** tự học, sinh viên, người ôn phỏng vấn hoặc bổ sung kỹ năng; sử dụng web trên desktop/mobile browser.
- **Admin/operator (nội bộ, tương lai):** quan sát job, lỗi model, quota; không được xem nội dung cá nhân nếu chưa có chính sách/quyền tương ứng.
- **System worker:** xử lý generation/ingestion/reconciliation, không phải actor đăng nhập.

Mặc định giao diện tiếng Việt. Truyền `language` xuyên suốt course/proposal/lesson/tutor (`P1-LANG`) và tách `appLanguage` / `lessonLanguage` là hạng mục ưu tiên tiếp theo, chưa triển khai.

## 3. Yêu cầu chức năng

| ID | Mô tả kiểm chứng được | Độ ưu tiên | Trạng thái (2026-11-22) |
|---|---|---|---|
| PRD-001 | Người dùng đăng ký/đăng nhập, dữ liệu course tách biệt theo owner | Must | **IMPLEMENTED · REPORTED TESTED** |
| PRD-002 | Tạo course từ topic hợp lệ và trả lời **đúng 5** câu interview | Must | **IMPLEMENTED · REPORTED TESTED** (`P1-PEDAGOGY` đã sửa ở working tree) |
| PRD-003 | Xem đề cương versioned trước approve; không generate lessons nếu chưa approve | Must | **IMPLEMENTED · REPORTED TESTED** (chưa có chỉnh sửa proposal trước approve) |
| PRD-004 | Sinh lessons bất đồng bộ, theo dõi state/progress, lỗi và retry an toàn | Must | **IMPLEMENTED · REPORTED TESTED** (`RELIABILITY-CELERY-01/02` deployed) |
| PRD-005 | Đọc lesson blocks và submit quiz; server grade; progress bền vững | Must | **IMPLEMENTED · REPORTED TESTED** (`P1-QUIZ-BLANK` + HMAC shuffle) |
| PRD-006 | LLM thật tạo nội dung có schema, DAG và đánh giá sư phạm/cost có bằng chứng | Must cho AI MVP | **PARTIAL** — hạ tầng P2.1–P2.2 xong; eval thật `3.17/4` còn `P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT` |
| PRD-007 | Tutor stream trả lời từ context lesson, history owner-scoped, quota & stop | Should | **IMPLEMENTED · DEFAULT-OFF** (`TUTOR_ENABLED=false`; pass mock E2E `TUTOR-MOCK-01`; real streaming NOT TESTED) |
| PRD-008 | Upload PDF/Web/arXiv thuộc quyền người dùng, RAG & citation đúng page/chunk | Should | **IMPLEMENTED · ĐA SỐ DEFAULT-OFF** (`SOURCE_INGEST_ENABLED=true`; `RAG`/`WEB`/`OCR` tắt; hashing embedding baseline) |
| PRD-009 | Đề xuất bài tiếp theo/ôn tập FSRS từ lịch sử học và skill graph | Could | **IMPLEMENTED · DEFAULT-OFF** (`P50_ENABLED=false`; BKT/DKT deploy BLOCKED) |
| PRD-010 | Hệ thống vận hành có CI, backup-restore, chính sách dữ liệu và quota | Must trước public launch | **PARTIAL** — P6.1 CI PASS; distributed rate-limit, staging TLS/CSP, backup drill, retention policy chưa làm |

## 4. MVP milestones (cập nhật tiến độ)

- **Core demo (P0.5–P1.3):** **IMPLEMENTED · REPORTED TESTED (mock)** — đăng nhập, topic → 5 answers → proposal → approve → 4 lessons mock → quiz → progress/reload, UI reconstruction FR-1..FR-5 (chưa commit).
- **AI course MVP (P2.1–P2.2):** **PARTIAL** — adapter, DAG, usage/cost budget đã triển khai; cần đóng `P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT` và đo lại với real provider được duyệt ngân sách.
- **Tutor MVP (P3.0–P3.1):** **IMPLEMENTED · DEFAULT-OFF** — cần quyết định ngân sách/bật cờ và kiểm chứng streaming với provider thật.
- **Document-grounded MVP (P4.0–P4.3):** **IMPLEMENTED · ĐA SỐ DEFAULT-OFF** — cần benchmark & bật semantic embedding thật trước khi mở `RAG_ENABLED=true`.
- **Adaptive MVP (P5.0–P5.2):** **IMPLEMENTED · DEFAULT-OFF** — FSRS/mastery sẵn sàng thử nghiệm khi bật `P50_ENABLED=true`; BKT/DKT giữ research-only.
- **Production release (P6):** **PARTIAL** — đã xong P6.1 CI gates; còn P6.2+ security/operations gate và owner approval.

## 5. In-scope / out-of-scope & Product Backlog sau MVP

**Trong phạm vi hiện tại:** web app Next.js, course generator, lesson 6 block types, server-authoritative quiz, progress, AI Tutor SSE, Source/RAG/OCR, Mastery/FSRS, quality eval & CI.  
**Product backlog ưu tiên cao từ đối chiếu thị trường (`docs/frontend-reference/api-gap-register.md`, `PROPOSAL` — cần chốt trước khi làm):**
- Glossary + inline `termKey` (`GAP-06`, `GAP-14`), Figures/Table/MathJax trong `teach` (`GAP-18`).
- Chỉnh sửa/revise Proposal trước approve (`GAP-08`), `source.brief` có cấu trúc.
- Chấm từng câu / AI Rubric Grader cho câu tự luận `short` trong khi giữ server-authoritative (`GAP-11`).
- User settings (`PATCH /v1/me`), tách `appLanguage`/`lessonLanguage` (`GAP-21`), dashboard stats (`/v1/me/stats`, `GAP-03`).

**Chưa đưa vào phạm vi hiện tại (chỉ mở khi có PRD/ngân sách riêng):** sao chép UI/API/assets PolySkill, Narrated Audiovisual Reel Engine (`GAP-16`), 5 practice formats mở rộng như `SpeedRound` (`GAP-17`), Offline SQLite/Service Worker outbox (`GAP-13`), native mobile, social/Leagues (`GAP-23`), Entitlements/Billing Polar+SePay (`GAP-22`), fine-tuning/training model từ đầu, full RL.

## 6. Chỉ số thành công

- **Funnel:** course created → interview completed → proposal approved → generation ready → first lesson started → first quiz submitted.
- **Correctness:** API không rò answer key, cross-owner 404, quiz score server-side, attempts/retries idempotent.
- **Quality:** pass schema/semantic validation + rubric pedagogy trên eval set (mục tiêu sau sửa P1: `language_quality` & `level_fit` ≥ `3.0/4`, `0` lỗi truncation trên real eval).
- **Reliability/cost:** generation failure rate, p95 job duration, tokens & provider cost per generated course, tutor time to first token, citation validity.
- **Learning:** tỷ lệ hoàn thành lesson và review retention FSRS; không đồng nhất engagement với kết quả học tập.

## 7. Điều kiện nghiệm thu tổng quát

Một increment chỉ hoàn tất nếu có: contract, migration expand-only (nếu cần), kiểm tra owner/CSRF, unit/integration/E2E phù hợp, chứng cứ lệnh chạy, cập nhật docs và báo cáo rõ `IMPLEMENTED / TESTED / NOT TESTED / BLOCKED`. Feature dùng AI trả phí phải có phê duyệt scope/budget/dữ liệu gửi ra ngoài.
