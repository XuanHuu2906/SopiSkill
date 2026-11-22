# 13 — Frontend UX, States, Navigation & Accessibility

**Trạng thái (`2026-11-22`):** Tất cả **10 route pages** và đợt tái thiết kế giao diện **FR-1 → FR-5** (design tokens light/dark, 21 font tự host, step-by-step lesson player, `OutlineSheet`, docked `TutorPanel`, modal focus trap + `inert`) đã **IMPLEMENTED (working tree chưa commit)** và **REPORTED VERIFIED** bằng `tsc`/`lint`/`build` + đo DOM/pixel/axe-core thủ công qua Chrome CDP (`docs/frontend-reference/`). **NOT TESTED:** Playwright E2E tự động và screen reader thật (NVDA/VoiceOver).

## 1. Navigation & Routes hiện hữu (`frontend/src/app/`)

| Route | Trạng thái | Chức năng chính |
|---|---|---|
| `/` | **IMPLEMENTED** | Khách chưa đăng nhập thấy `LandingPage` (không side nav/tab bar); user đã đăng nhập thấy Dashboard (lời chào theo giờ, resume hero, course grid, 5 khóa gần nhất ở SideNav) |
| `/login` | **IMPLEMENTED** | Đăng nhập / đăng ký email+password, giữ `?next=` đã chặn open redirect |
| `/new` | **IMPLEMENTED** | Nhập topic (1–200 ký tự) + topic suggestion chips |
| `/new/interview` | **IMPLEMENTED** | 5 câu hỏi dạng transcript bubble + progress, resume sau reload |
| `/new/proposal` | **IMPLEMENTED** | Plan card, units/lessons, outcomes, stat strip, approve (không có nút sửa giả) |
| `/new/generating` | **IMPLEMENTED** | Poll `2s` dừng ở terminal state, hiển thị 4 giai đoạn & lỗi/retry |
| `/course/[courseId]` | **IMPLEMENTED** | Hero tiến độ, unit sections, lesson rows, mastery, linked sources, learning-path (xử lý sạch 503 khi P5.0 tắt) |
| `/lesson/[lessonId]` | **IMPLEMENTED** | Focus mode (ẩn nav, cột 720px, header 872px), **player dạng từng bước** (1 block/màn cho cả 6 loại `teach/mc/blank/order/match/short`), `OutlineSheet`, `TutorPanel` (docked 400px ở `≥1024px` / modal overlay `<1024px`), 1 lần submit cuối bài + `ResultSummary` |
| `/sources` | **IMPLEMENTED** | Đăng ký/upload PDF/Web/arXiv (theo `ingest-config`), xem trạng thái ingest & OCR, liên kết/tìm kiếm RAG |
| `/review` | **IMPLEMENTED** | Hàng đợi ôn tập FSRS 4 mức đánh giá (hiển thị trạng thái 503 khi `P50_ENABLED=false`) |

**App shell (`components/layout/AppFrame.tsx`):** Desktop `≥1024px` có SideNav `264px` + content `1040px` + `ThemeToggle` (Sáng/Hệ thống/Tối, key `sopiskill.theme`); Mobile có `TabBar` (`Trang chủ`, `Khóa học mới`, `Tài liệu`, `Ôn tập`).

**Dữ liệu & bảo mật client (`lib/api.ts`, `providers.tsx`):** `credentials: "include"`, CSRF header cho mutating requests, query keys scoped theo `user.id + sessionEpoch`, xóa sạch cache khi logout/đổi tài khoản. `NEXT_PUBLIC_API_URL` được inline lúc `npm run build`.

## 2. Design System & Fonts (FR-1..FR-5)

- **Self-hosted fonts (`frontend/public/fonts/*.woff2`, `src/app/fonts.css`):** 21 file (644 KB) gồm Manrope 700/800, Inter 400/500/600, JetBrains Mono 400/500 chia subset `latin / latin-ext / vietnamese` (thay `next/font/google` để sửa lỗi build offline/webpack).
- **UI Primitives (`components/ui/`):** `Button`, `Card`, `Field` (`TextInput`/`TextArea`), `Badge`, `Progress` (`ProgressBar`/`ProgressRing`), `Skeleton`, `Icon`, `useModalPanel`, `useMediaQuery`.

## 3. Requirements

| ID | UX behavior | Trạng thái (2026-11-22) |
|---|---|---|
| UX-001 | Protected routes redirect có `?next=` an toàn khi chưa login | **IMPLEMENTED · VERIFIED** |
| UX-002 | Đổi tài khoản A→B không rò cache course/XP/lesson | **IMPLEMENTED · VERIFIED** |
| UX-003 | Form validation, loading/empty/error/retry/503 states rõ ràng | **IMPLEMENTED · VERIFIED** |
| UX-004 | Generation poll 2s, dừng ở terminal state | **IMPLEMENTED · VERIFIED** |
| UX-005 | Interview reload tiếp tục đúng câu chưa trả lời | **IMPLEMENTED · VERIFIED** |
| UX-006 | Quiz submission giữ ổn định `clientAttemptId` & `contentVersion` | **IMPLEMENTED · VERIFIED** |
| UX-007 | Keyboard, focus trap/modal contract, contrast WCAG AA, reduced-motion | **IMPLEMENTED · axe-core 0 violations (CDP); screen-reader NOT TESTED** |
| UX-008 | Tutor panel streaming/stop/history, docked ≥1024px / overlay <1024px | **IMPLEMENTED (UI verified; browser SSE E2E NOT TESTED)** |
| UX-009 | `/sources` upload/status/web-ingest/RAG theo `ingest-config` | **IMPLEMENTED** |
| UX-010 | Phân biệt rõ trạng thái mock / feature-disabled (503) / không đủ căn cứ | **IMPLEMENTED** |

## 4. Accessibility contract (FR-4b, FR-5 — REPORTED VERIFIED via CDP)

- `useModalPanel` dùng chung cho `OutlineSheet` và `TutorPanel`:
  - **Modal (`modal=true`: OutlineSheet và TutorPanel `<1024px`):** `<div role="dialog" aria-modal="true" aria-labelledby=...>`, bẫy `Tab`/`Shift+Tab`, gắn `inert` lên các nhánh nền, `Escape` đóng và trả focus về nút kích hoạt.
  - **Docked (`modal=false`: TutorPanel `≥1024px`):** `<div role="dialog">` không `aria-modal`, không `inert`, `Tab` rời sang bài học tự do, `Escape` vẫn đóng và trả focus.
- Đã sửa lỗi `aria-allowed-role` (`<aside role="dialog">` → `<div role="dialog">`), chạy lại `axe-core` trên 5 bề mặt (dock light/dark, overlay 768/390, outline) đạt **0 violations**.
- **Giới hạn:** chưa kiểm thử bằng NVDA/VoiceOver thật; chưa có Playwright E2E tự động (`frontend/package.json` chưa cài test runner).

## 5. Design boundaries & API gaps (`docs/frontend-reference/api-gap-register.md`)

- Tuyệt đối không sao chép logo/mascot/asset/copy của PolySkill và không giả lập dữ liệu cho endpoint chưa tồn tại.
- Toàn bộ 23 khoảng trống UX phụ thuộc backend (`GAP-01`..`GAP-23`: thời lượng bài, glossary `terms[]`, figures/MathJax, per-block feedback, proposal editing, Reel player, practice formats, offline outbox, profile stats/milestones, billing/notifications) được theo dõi có hệ thống tại `docs/frontend-reference/api-gap-register.md`.
