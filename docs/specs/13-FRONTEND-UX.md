# 13 — Frontend UX, States, Navigation & Accessibility

**Trạng thái:** Các route core báo cáo đã triển khai; trang Tutor/Source là PROPOSAL.

## 1. Existing navigation (reported)

| Route | Mục tiêu |
|---|---|
| `/` | Dashboard “Khóa học của tôi”, 5 course gần nhất, resume lesson |
| `/login` | Login/register, hỗ trợ `?next=` đã chặn open redirect |
| `/new` | Nhập topic |
| `/new/interview?courseId=...` | Năm câu hỏi; reload tiếp tục câu chưa trả lời |
| `/new/proposal?courseId=...` | Xem proposal và trạng thái approved |
| `/new/generating?courseId=...` | Poll job 2s, hiển thị stage/dispatched/errors |
| `/course/[courseId]` | Units/lessons, completion/progress |
| `/lesson/[lessonId]` | Lesson + quiz public blocks |

**Dữ liệu:** `fetch` gửi cookie `credentials: include`, CSRF cho POST; query key theo authenticated `user.id` + `sessionEpoch`; logout xoá query cache. Guard client chỉ là UX, backend là security boundary.

## 2. Requirements

| ID | UX behavior |
|---|---|
| UX-001 | Tất cả protected routes redirect có return path an toàn khi chưa login |
| UX-002 | A logout → B login không hiển thị course, XP, lesson cache của A |
| UX-003 | Form validation có error rõ; loading/empty/error/retry states |
| UX-004 | Generation poll 2s, stop ở terminal state, không spam retry |
| UX-005 | Interview reload hiển thị số câu đã hoàn thành và next unanswered |
| UX-006 | Quiz submission idempotency key giữ nguyên khi retry network |
| UX-007 | Bàn phím, focus visible, labels, ARIA, reduced-motion |
| UX-008 | Tutor panel streaming/cancel/history context (P3) |
| UX-009 | PDF upload/status, citation mở đúng trang (P4) |
| UX-010 | Giao diện phân biệt mock/real provider khi mode có ý nghĩa cho user |

## 3. State matrix

| Screen | Loading | Empty | Error | Success/terminal |
|---|---|---|---|---|
| Dashboard | Skeleton/loading | Chưa có course → CTA | Retry fetch | Course list + resume |
| Interview | Loading questions | N/A | Ghi answer lỗi, không tăng step giả | 5/5 → proposal |
| Proposal | Validating/sinh | N/A | Schema/provider error | Reviewed/approved badge |
| Generating | Queued/dispatched/running | N/A | Failed + retryable? | Ready → course |
| Lesson | Loading blocks | No ready content → message | Error/stale version | Grade + feedback/progress |
| Tutor (P3) | Connecting/streaming | No messages | Quota/timeout/disconnect | Done/cancelled/history |
| Sources (P4) | Uploading/extracting | No files | Corrupt/oversize/no text | Ready + citation navigation |

## 4. Accessibility

- Semantic form labels/`htmlFor`, role alert cho lỗi, keyboard order, visible focus, no keyboard traps.
- SSE output dùng live region có throttling để screen reader không đọc từng token; nút stop có trạng thái rõ, stream completion announced.
- Quiz `order/match` cần phương án thao tác bằng keyboard, không chỉ drag-and-drop.
- Reduced-motion; contrast/zoom responsive; loading spinner có accessible status.
- Màn nhỏ hỗ trợ lesson ↔ tutor mà không che nội dung học/chấm.

## 5. Data correctness

- Frontend không nhận key/private content; không tự tính score/XP authority.
- Error 401 → login flow; 403 CSRF có hướng dẫn retry/session; 404 không tiết lộ owner; 409 stale version → reload; 429 → quota UI.
- Interview đã trả lời ở server có thể hiển thị “✓ đã trả lời” mà không bắt buộc tải lại text câu trả lời cũ.
- Sau attempt invalidates session-scoped `course`, `me`, `courses` queries; account switch clear cached data.

## 6. Design boundaries

- Thiết kế giao diện SopiSkill độc lập, không copy UI/brand/assets PolySkill.
- Không đưa tool toolbar, billing, leaderboard, native mobile hay proposal-editor chưa có contract vào phase P2.1.
- UI copy tiếng Việt nhất quán; i18n đa ngôn ngữ là quyết định cần chốt, không mặc định đã triển khai.
