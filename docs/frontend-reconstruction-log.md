# Frontend reconstruction — work log (2026-11-03)

This file records what was actually done, in order, with the commands that were executed
and the evidence produced. It is written in Vietnamese because the task asked for
Vietnamese phase reports, and it complements `docs/development-progress.md` (which keeps
the product ledger).

**Branch:** `feat/p6.0-ci-pipeline` · **HEAD at start:** `d747e78` · **Working tree at start:** clean.

> Không có commit nào được tạo trong phiên này. Mọi thay đổi nằm trong working tree.

---

## 0. Tóm tắt một đoạn

Đã khảo sát trực tiếp PolySkill bằng REA 6.7.0 (CLI, Chrome CDP 9222) để lấy bằng chứng
thật về bố cục/màu/chữ/khoảng cách, ghi thành bộ hồ sơ `docs/frontend-reference/`, rồi
triển khai lại giao diện SopiSkill trên Next.js 15 hiện có với design system riêng, giữ
nguyên toàn bộ backend contract, auth cookie/CSRF, session-scoped cache, polling và chấm
điểm phía server. Đã chạy `tsc`, `lint --max-warnings=0`, `npm run build` (đều pass) và
dựng một backend + Celery + Postgres throwaway để chụp màn hình so sánh thật.

---

## 1. Audit repository (FACT)

Lệnh đã chạy:

```bash
git status --short            # rỗng
git branch --show-current     # feat/p6.0-ci-pipeline
git rev-parse HEAD            # d747e78ee8392a354db79805fe73b1477bc0c531
git log --oneline -10
```

Đọc: `AGENTS.md`, `docs/architecture.md`, `docs/development-progress.md` (1908 dòng),
`docs/specs/13-FRONTEND-UX.md`, `docs/specs/05-API-CONTRACTS.md` (qua code),
`polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md`,
`research/polyskill-blackbox/**` (README, test-matrix, 2 file evidence redacted, reports).

Kiểm chứng stack thật từ `frontend/package.json`:

| Claim | Kết quả |
|---|---|
| Next.js 15 | `next@15.5.28` ✔ |
| React 19 | `react@^19.0.0` ✔ |
| TanStack Query | `@tanstack/react-query@^5.62.0` ✔ |
| TypeScript | `typescript@^5` ✔ |
| Lint gate | `eslint . --max-warnings=0` ✔ |
| Scripts | `dev`, `build`, `start`, `lint`, `typecheck` ✔ |
| Không có Playwright | xác nhận: không có dependency/script e2e |

Frontend hiện tại (trước khi sửa): 11 file trong `src/app`, 1 file `lib/api.ts` (839 dòng),
1 `globals.css` (425 dòng), toàn bộ style bằng class thủ công `.card/.badge/.quiz-option`.

---

## 2. REA — công cụ và giới hạn (FACT)

```bash
rea --version                 # 6.7.0
rea doctor                    # healthy:false CHỈ vì thiếu engine native (hopper/ghidra/ida/jadx)
```

- Không có MCP server `rea` đăng ký trong `opencode.json`/`opencode.jsonc` ⇒ dùng REA
  dạng CLI. Đây là lựa chọn có chủ đích, không phải lỗi.
- `rea doctor` báo `healthy:false` vì thiếu Hopper/Ghidra/IDA/JADX. Không liên quan tới
  browser observation. Không cài thêm engine nào trong phiên này.
- `kill`/`doctor` không được dùng để "sửa" gì; chỉ đọc.

Chrome mở với profile cách ly đã đăng nhập sẵn (owner đăng nhập từ phiên trước):

```bash
chrome.exe --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 \
  --user-data-dir="C:\Users\huung\AppData\Local\REA-PolySkill-Profile" ... 
```

Lệnh REA thực sự dùng:

```bash
rea list-browser-targets http://127.0.0.1:9222 \
  --allowed-origins https://web.polyskill.app --format json
rea inspect-web-page http://127.0.0.1:9222 <targetId> \
  --allowed-origins https://web.polyskill.app --observation-ms 2500 \
  --include-accessibility-text --format json
rea capture-web-screenshot http://127.0.0.1:9222 <targetId> \
  --allowed-origins https://web.polyskill.app --format json
```

Bổ sung (đọc-only) một CDP driver nhỏ để lấy computed style + bounding box, vì REA không
xuất computed style. Script nằm ở `%TEMP%\opencode\ps-recon\` (ngoài repo): `drive.mjs`,
`snap.mjs`, `shot.mjs`, `cdp.mjs`. Chỉ gọi `Runtime.evaluate`, `Page.captureScreenshot`,
`Emulation.setDeviceMetricsOverride`, `Input.dispatchMouseEvent` cho các thao tác UI mà
người dùng đã cho phép.

**Bài học từ phiên trước vẫn đúng:** `--allowed-origins` phải lặp theo từng origin.
Phiên này chỉ quan sát `web.polyskill.app` nên không lặp lại lỗi lọc `api.polyskill.app`.

---

## 3. Bằng chứng đã thu (FACT)

Lưu tại `docs/frontend-reference/evidence/` và `docs/frontend-reference/screenshots/`.

### 3.1 Bundle tĩnh

```bash
curl -s https://web.polyskill.app/_expo/static/js/web/entry-*.js -o entry.js
sha256sum entry.js
# e7f84aaffae7a3be5d943437e1ccd084a69c12aad1675f3bcc841703bde5d4ce  (5 849 374 bytes)
```

Từ bundle trích ra (đều là FACT, không suy đoán):

- Bảng màu light/dark đầy đủ (`#241C3B`, `#7B5BE6`, `#F1ECFD`, …).
- Thang chữ 20 biến thể (`displayXl 48/52 w800` → `caption 12/16 w500`).
- `space` 2→64, `radius` 6/10/16/22/28/999.
- `contentWidth` page 1040, reading 720, form 680, narrow 560.
- `screenPadding` desktop 48/48/72, mobile 20/8/24.
- `shadows` card/raised/overlay/sheet/glow/knob/rail (light + dark).
- `motion.duration` press 120, feedback 200, sheet/rise 280, pop 320, bar 420, …
- `DESKTOP_MIN_WIDTH = 1024`, `SIDE_NAV_WIDTH = 264`, `TAB_BAR_HEIGHT = 50`.
- 15 route Expo Router; chuỗi i18n tiếng Việt đầy đủ (`mods/m1018.js`).

### 3.2 DOM + computed style (viewports thật)

| File | Nội dung |
|---|---|
| `dom-signin-1440x900.json` / `-768x1024` / `-390x844` | Login: khối canh giữa, nút 420x56, radius 999 |
| `dom-home-1440x900.json`, `dom-home-390x844.json`, `dom-home-dark-1440x900.json` | Dashboard, side nav 264, content 1040, hero 1040x156 |
| `dom-course-1440x900.json`, `-768x1024`, `-390x844` | Course overview, unit/lesson rows |
| `dom-lesson-1440x900.json`, `-390x844`, `dom-lesson-teach3.json`, `dom-lesson-summary.json` | Lesson player, summary |
| `dom-quiz-1.json`, `dom-quiz-selected.json`, `dom-quiz-result.json`, `dom-quiz-done.json` | MCQ, selected state, feedback, fill-in |
| `dom-tutor-open.json` | Tutor sheet, bubbles, composer |
| `dom-new-1440x900.json` | New-course quota state |
| `dom-interview-done-1440x900.json` | Interview transcript + plan |
| `dom-generating-1440x900.json` | 4-stage generation (terminal) |
| `dom-profile-1440x900.json` | Profile, milestones |

Ảnh: `screenshots/*-1440x900.png`, `-768x1024.png`, `-390x844.png`, dark mode.

### 3.3 Thao tác UI đã tự thực hiện (chỉ điều hướng, không ghi dữ liệu)

1. `/home` → mở khóa học có sẵn → `/course/{id}`.
2. Mở bài 1 → `/lesson/{id}`; bấm `Tiếp tục` qua 3 khái niệm; `Tóm tắt nhanh`.
3. `Làm bài kiểm tra` → chọn đáp án B → `Kiểm tra` → xem band đúng → `Tiếp tục` → block điền chỗ trống.
4. `Đóng bài học` → về course; mở lại bài → `Hỏi Pol` → chụp panel tutor đã có lịch sử.
5. Điều hướng trực tiếp `/new`, `/profile`, `/new/interview`, `/new/generating`.
6. **Không** tạo khóa học mới, không nộp quiz sai, không đổi thông tin tài khoản (tránh
   thay đổi bản ghi học tập của owner).

### 3.4 Giới hạn evidence (ghi trung thực)

- Không quan sát được sign-up (PolySkill chỉ có OAuth) ⇒ form email/password của SopiSkill
  là PROPOSAL, không phải bản sao.
- Không quan sát được interview đang diễn ra (khóa duy nhất đã trả lời xong) ⇒ bố cục
  đang-làm dựa vào transcript hoàn chỉnh + token đo được (INFERENCE).
- Không quan sát được generation đang chạy (đã xong) ⇒ chỉ có nhãn 4 giai đoạn là FACT.
- Không quan sát order/match/short của PolySkill (bài mở chỉ tới blank) ⇒ thiết kế các
  block đó là PROPOSAL, dùng đúng hệ card/option/chữ đã đo.
- Không quan sát dark mode bằng UI (nút "Chế độ tối" nằm trong side nav chỉ hiển thị ở
  desktop và phiên này không bấm), nên đã ép `prefers-color-scheme: dark` qua CDP để lấy
  token dark. Đó là FACT cho token, không phải FACT cho ảnh chụp UI dark.

---

## 4. Hồ sơ thiết kế đã tạo

```
docs/frontend-reference/
  reference-audit.md        # phương pháp, giới hạn, nhãn FACT/INFERENCE/UNKNOWN/PROPOSAL
  screen-inventory.md       # 14 trạng thái màn hình + 8 màn hình chưa quan sát được
  interaction-map.md        # G/A/D/C/O/L/Q/T — cái gì đã chạy, cái gì suy luận
  design-tokens.md          # màu light+dark, thang chữ, space, radius, layout, shadow, motion
  component-mapping.md      # reference → component SopiSkill (kèm "not mapped")
  visual-comparison.md      # baseline đo được + bảng trạng thái + dung sai so sánh
  implementation-checklist.md
  evidence/                 # ~25 file JSON DOM/computed-style + REA evidence
  screenshots/              # ảnh reference + ảnh local
```

---

## 5. Những gì đã triển khai

### 5.1 Nền tảng (UI-1)

| File | Nội dung |
|---|---|
| `frontend/src/app/globals.css` (viết lại) | Token layer light+dark + `prefers-color-scheme`, thang chữ, card/button/badge/field/progress, shell, lesson, quiz, tutor, responsive |
| `frontend/src/app/layout.tsx` | `next/font` Manrope 700/800, Inter 400/500/600, JetBrains Mono; bọc `Providers` + `AppFrame` |
| `frontend/src/app/providers.tsx` | Bọc thêm `ThemeProvider`; giữ nguyên toàn bộ logic session/cache/logout/guard |
| `frontend/src/components/layout/ThemeProvider.tsx` | `light | dark | system`, lưu `sopiskill.theme`, set `data-theme` |
| `components/ui/Button.tsx` | `Button`, `ButtonLink`, `IconButton`; variant primary/dark/secondary/ghost/light/success/danger/text; size lg/md/sm |
| `components/ui/Card.tsx` | default/tint/accent/hero/dashed/correct/wrong |
| `components/ui/Field.tsx` | `Field`, `TextInput`, `TextArea` có label/hint/error bound qua `htmlFor`/`aria-invalid` |
| `components/ui/Badge.tsx` | accent/muted/success/danger/lock |
| `components/ui/Progress.tsx` | `ProgressBar` (role=progressbar, aria-valuenow) + `ProgressRing` SVG |
| `components/ui/Skeleton.tsx` | shimmer giữ layout khi tải |
| `components/ui/Icon.tsx` | bộ icon stroke nội bộ (không copy asset của reference) |

### 5.2 Shell, auth, dashboard (UI-2)

| File | Nội dung |
|---|---|
| `components/layout/AppFrame.tsx` | Side nav 264 px (brand, 4 nav, khóa học + ring, XP, theme, đăng xuất), content 1040, tab bar mobile; `/login` dùng `auth-shell` |
| `components/layout/TabBar.tsx` | 4 tab (Trang chủ / Mới / Tài liệu / Ôn tập), 50 px + safe area |
| `components/layout/ThemeToggle.tsx` | segmented Sáng / Hệ thống / Tối + biến thể compact |
| `app/login/page.tsx` | Panel canh giữa, typography hero, field có label; giữ `?next=`, chống open redirect, `useSessionRefresh` |
| `app/page.tsx` | Lời chào theo giờ + resume hero (ember, glow) + course grid + empty/loading/error/retry |

### 5.3 Tạo khóa học (UI-3)

| File | Nội dung |
|---|---|
| `app/new/page.tsx` | Cột 680, tiêu đề 48/52, input có label, chip gợi ý, card ghi chú |
| `app/new/interview/page.tsx` | Transcript bubble (question surface / answer ember), progress 6 px, đếm `Câu n/5`, resume sau reload, `Ctrl+Enter`, trạng thái đã-xong chuyển thẳng proposal |
| `app/new/proposal/page.tsx` | Plan card, stat strip 3 ô, hồ sơ học viên, outcomes, lộ trình kỹ năng, unit cards, nút duyệt |
| `app/new/generating/page.tsx` | Danh sách 4 giai đoạn có dot done/active/pending, phần trăm bài, retry, dòng chi phí, giữ `refetchInterval` 2 s và dừng ở terminal |

### 5.4 Học (UI-4)

| File | Nội dung |
|---|---|
| `app/course/[courseId]/page.tsx` | Hero tiến độ, `ProgressBar` 10 px, học tiếp, unit sections, lesson rows (index/title/meta/badge), mastery, sources, learning-path; giữ 2 s polling và 503 graceful |
| `app/lesson/[lessonId]/page.tsx` | Lesson player **focus mode**: không side nav/tab bar, cột 720 căn giữa, header rộng 872 với back/progress/đếm/version, block eyebrow + title 34/40 (28/34 cho quiz), prose 19/31, citation line, word/term pills, bottom action bar sticky |
| Quiz | `quiz-option` 68 px radius 16 viền 2 px, selected `--wash` + viền `--ember`, letter trắng; blank/order/match/short có label sr-only + điều khiển bàn phím; feedback dòng `✓/✗`; `ResultSummary` (correct band khi hoàn hảo) |
| Bảo mật | Không đổi `buildAnswers`, `clientAttemptId` fingerprint, `contentVersion`, invalidate `session`/`me`; không render đáp án trước khi nộp |

### 5.5 Tutor (UI-5)

| File | Nội dung |
|---|---|
| `app/lesson/[lessonId]/TutorPanel.tsx` | Đổi sang sheet phải (backdrop + `aside` 380 px), header `Trợ giảng` + context + allowance, bubble user (ember) / assistant (surface + shadow), tool badge, citation block, composer 50 px + nút gửi 48 px, `Escape` để đóng |
| Giữ nguyên | SSE parse, `delta/done/citations/tool/cancelled/error`, `stopTutorMessage`, thread history, quota, `aria-live="polite"` |

### 5.6 Sửa lỗi phát hiện khi chạy thật

| Lỗi | Sửa |
|---|---|
| `ProgressRing` vẽ chữ `0 %` đè lên cả ring 22 px trong side nav | Thêm prop `showLabel` mặc định chỉ bật khi `size >= 40` |
| Interview khi đã trả lời đủ 5 câu vẫn render textarea `✓ đã trả lời` | Tính `completedCount` trước khi render, hiện trạng thái "Đang mở kế hoạch học" thay vì cho nộp lại |
| `/new/generating` điều hướng ngay khi course đã `ready` khiến không chụp được màn hình | Ghi nhận: đây là hành vi đúng (terminal → course), không phải lỗi; evidence generating chỉ có trạng thái terminal từ reference |
| XP hiển thị "đã được cộng XP tối đa" ngay cả khi 0 câu đúng | Đổi copy theo `score.correct > 0` |
| Lesson page chiếm cả shell khiến cột 720 bị đẩy sang phải (x=485) | Thêm focus mode: ẩn side nav + tab bar, `padding: 16px 20px 96px`, cột 720 căn giữa → đo lại x=353 (tâm viewport), header 872 |
| Dev server trả 500 `Cannot find module './77.js'` / `vendor-chunks/@tanstack.js` sau khi chạy `next build` trong lúc dev đang chạy | Đã từng gặp: `.next` bị ghi đè bởi build production trong khi dev server đang phục vụ. Sửa: dừng dev, `rm -rf .next`, chạy lại `npm run dev`. Đây là thao tác vận hành, không phải lỗi code — sau khi dọn, tất cả route trả 200 và dark mode đo đúng |

---

## 6. Kiểm chứng đã chạy (TESTED)

### 6.1 Frontend gates

```bash
cd frontend
npx tsc --noEmit          # exit 0, no output
npm run lint              # eslint . --max-warnings=0 → exit 0
npm run build             # next build → ✓ Compiled successfully, 11 routes
```

`npm run build` output (rút gọn, chạy lại sau FR-3):

```
Route (app)                    Size  First Load JS
┌ ○ /                       3.47 kB         124 kB
├ ○ /_not-found               995 B         104 kB
├ ƒ /course/[courseId]      4.81 kB         125 kB
├ ƒ /lesson/[lessonId]      9.93 kB         130 kB
├ ○ /login                  2.15 kB         122 kB
├ ○ /new                      2.3 kB         122 kB
├ ○ /new/generating         3.51 kB         124 kB
├ ○ /new/interview          3.83 kB         124 kB
├ ○ /new/proposal           4.06 kB         124 kB
├ ○ /review                 3.71 kB         124 kB
└ ○ /sources                7.04 kB         127 kB
```

### 6.2 Backend + worker throwaway (không đụng DB chính)

- DB chính `reverseengineer-db-1` (volume `reverseengineer_pgdata`) **không bị migrate**.
- Tạo database mới `ailp_ui_check` trong cùng instance Postgres local:

```bash
docker exec reverseengineer-db-1 psql -U ailp -d ailp -c "CREATE DATABASE ailp_ui_check;"
cd backend
DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@localhost:5433/ailp_ui_check" \
  python -m alembic upgrade head       # → 0016_p52_exposure (head)
```

- Uvicorn `127.0.0.1:8000` chạy với `.env` throwaway (`LLM_PROVIDER=mock`,
  `JWT_SECRET=ui-check-secret-not-for-production`).
- Celery worker chạy local (`--pool=solo`).
- Seed bằng script HTTP thật (register → tạo course → trả lời 5 câu → approve):

```
registered ui-check-…@example.com
course crs_f3b911fd-…  status interview
questions 5
proposal "Quy trình LUMORA-731 và ngưỡng ORBIT: lộ trình cơ bản" units 2
generation status ready  lessonsDone 4/4
lesson lsn_d750df29-…  blocks teach,mc,blank,order,match,short
```

- Toàn bộ 3 tài khoản/khóa học test nằm trong DB throwaway; xóa bằng drop database khi
  cần, không ảnh hưởng dữ liệu người dùng.

### 6.3 Đo lại giao diện local (số thật)

| Màn hình | Đo được | So với reference |
|---|---|---|
| Login 1440 | panel 420, h1 40/44 Manrope 800, nút 420x56 radius 999, bg `#F1ECFD` | khớp token; cấu trúc form khác theo thiết kế SopiSkill |
| Login 390 | 350 px full-bleed, nút 56, cùng thang chữ | khớp thang đo mobile |
| Home 1440 | nav 264 `#FCFAFF`, content x=312 w=1040, greeting 48/52, hero 1040x155 `#7B5BE6` + glow | MATCHED về khung/token |
| Home 390 | 1 cột, tab bar 4 ô cao 67 (50 + safe area), không overflow ngang | MATCHED về cấu trúc |
| Course 1440 | eyebrow 13/18, h1 34/40, progress 10 px, lesson row 74 px | MATCHED về token |
| Lesson 1440 | cột 720 tại x=353 (focus mode), header 872 tại x=277, eyebrow 13/18, title 34/40, prose 19/31 | khớp số đo reference (720/872) |
| Quiz 1440 | option 68 px radius 16 viền `#E6DEFA`, selected `#EBE3FF` + viền `#7B5BE6`, CTA disabled `#CDC1EF` | MATCHED về token và kích thước |
| Tutor 1440 | sheet 380 (reference ~360–380), bubble user ember / assistant surface+shadow, composer 50 px, gửi 48 px | PARTIAL: reference 302 content + 24 gutter, SopiSkill 380 |
| New 1440 | cột 680, h1 48/52, chip 36 px | MATCHED khung; không có trạng thái quota (API GAP) |
| Proposal 1440 | plan card, stat strip 3 ô, outcome rows, unit list, CTA 640x56 | PARTIAL: reference có "học xong bạn sẽ có thể" dạng câu nối; SopiSkill dùng danh sách đánh số |
| Interview 1440 (đang làm) | bubble question 604, progress 6 px, `Câu 3/5` | PARTIAL: reference dùng chip trả lời nhanh do backend sinh; SopiSkill dùng textarea (contract khác) |
| Mobile lesson 390 | không overflow (`scrollWidth = 390`), tab bar ẩn ở focus mode | MATCHED |
| Home dark 1440 | `paper = #120E20`, `body = rgb(18,14,32)`, shadow dark trùng reference | MATCHED (token) |

### 6.4 Đổi tài khoản (session isolation) — chạy thật

Hai tài khoản trong DB throwaway:

1. user1 (`ui-check-…`) đăng nhập, thấy khóa học `Quy trình LUMORA-731…`.
2. `Đăng xuất` → `/login`.
3. user2 (`ui-check-user2@example.com`) đăng nhập.
4. Đo DOM: `leakedUser1 = false`, `leakedCourse1 = false`, `ownCourse = true`.

```json
{"p":"/","leakedUser1":false,"leakedCourse1":false,"ownCourse":true}
```

5. user2 mở URL lesson của user1 → server trả
   `Lesson không tồn tại hoặc không thuộc quyền của bạn.`; UI hiển thị error box +
   `Thử lại`, không lộ nội dung.

### 6.5 Accessibility — chạy thật (FR-3, 2026-11-03)

Trước FR-3, mục này chỉ đo một màn lesson bằng probe tự viết. Probe đó **không** mô hình
hoá `opacity` khi composite màu chữ, nên đã báo xanh trong khi vẫn còn lỗi WCAG thật. FR-3
thay bằng axe-core chạy thật trên 9 route × 2 theme.

```text
/            0 violations   /new        0 violations
/login       0 violations   /interview  0 violations
/course      0 violations   /proposal   0 violations
/lesson      0 violations   /review     0 violations
                            /sources    0 violations
light: 0 · dark: 0   (18 lượt chạy)
```

Chi tiết đầy đủ (bảng control/heading, overflow 27 phép đo, zoom 200 %) nằm trong
`docs/frontend-reference/accessibility-review.md`.

Hai lỗi thật do axe phát hiện, đã sửa:

1. `.hero-kicker` 4.23:1 và `.hero-step` 3.36:1 — `opacity` 0.92/0.75 composite trắng lên
   `--ember #7b5be6`. Bỏ `opacity` ở cả ba rule `.hero-card .eyebrow` / `.hero-kicker` /
   `.hero-step`.
2. `/login` nằm ngoài `<main>` (`landmark-one-main`, `region`). Bọc `children` trong
   `<main>` ở nhánh `/login` của `AppFrame.tsx`.

Cũng trong FR-3: `--ink-3` light `#8a82a6 → #645c81`, dark `#8479a8 → #9f94c5`; sửa thứ tự
heading trên `/new` (H1→H3 skip), `/new/proposal` (thiếu H1) và `/new/interview` (không có
heading ở cả ba trạng thái).

### 6.6 Kiểm tra không rò dữ liệu

```js
document.documentElement.outerHTML  // 27 276 ký tự
['solution','answerKey','correctOption','answer_key'].filter(k => html.includes(k))
// → [] (rỗng)
```

Không có answer key/solution trong DOM trước khi nộp; `correct` chỉ xuất hiện sau khi
server trả `results`.

---

## 7. NOT TESTED

- Playwright/E2E: dự án không có Playwright, không thêm dependency mới. Các luồng
  login → dashboard → course → lesson → quiz → đổi tài khoản đã được lái thật qua CDP
  nhưng **không** phải test tự động có assertion.
- Backend regression suite (`pytest`) chưa chạy lại trong phiên này vì không sửa backend.
  Frontend không đổi contract; `tsc/lint/build` pass.
- Docker image build cho frontend/backend chưa chạy.
- Screen-reader thật (NVDA/VoiceOver) — **NOT MEASURED**. FR-3 chỉ có axe-core; axe là
  kiểm tra tự động, không thay được một lượt đọc bằng trình đọc màn hình.
- Focus trap / `aria-modal` của Tutor sheet — chỉ xác nhận `Escape` đóng được; chưa đo
  việc `Tab` có bị giữ trong sheet hay không.
- Dark mode: đã chụp 8 route ở 1440 (thiếu `/login`, `/new/interview`, `/new/proposal`,
  `/new/generating`). Không kiểm chứng bằng UI thật của PolySkill (chỉ ép media query);
  so sánh là token-vs-token, không phải ảnh UI thật.
- 390×844 chưa có cho `/new/interview` và `/new/proposal`.
- Không đo được `contentVersion`/prefetch của PolySkill (ngoài phạm vi).
- Không có screenshot so sánh pixel-diff tự động; mọi so sánh ở mức số đo DOM.

---

## 8. BLOCKED / API GAP (không tự bịa endpoint)

| Mong muốn từ reference | Trạng thái SopiSkill | Quyết định |
|---|---|---|
| Thời lượng từng bài (`· 9 phút`) | Không có trong `CourseDetailOut` | Không render; cần field additive |
| Unit tone / `Pro` paywall | Không có trong model | Không render |
| Lịch sử 46 milestone, league, weekly chart | Không có endpoint | Không render |
| Quick-answer chips trong interview | Backend trả câu hỏi dạng text, không có options | Dùng textarea; chips chỉ cho chủ đề ở `/new` |
| `prefetch=1` bài kế | Không có | Bỏ qua (không bắt buộc) |
| Glossary `terms[]` trong lesson | `LessonOut` không có | Chỉ render khi có; hiện ẩn |
| `read_source`/`explain_deeper` tool chips | Tutor chỉ phát `tool` event chung | Render badge từ event, không gán tên tool |

Không endpoint nào bị thêm/sửa. Không gọi API PolySkill.

---

## 9. Rủi ro còn lại

1. **Font tải từ Google** (`next/font/google`) — lần build đầu cần mạng; CI không có mạng
   sẽ fail. Nếu cần offline, phải self-host font (chưa làm).
2. **Tutor sheet 380 px** rộng hơn reference (~360) — chấp nhận được nhưng có thể chỉnh.
3. **Proposal/interview** khác cấu trúc reference do contract khác — đã ghi PARTIAL, không
   tuyên bố pixel-perfect.
4. **Không chạy `npm run build` khi `npm run dev` đang phục vụ** trong cùng thư mục: hai
   tiến trình ghi đè `.next/` của nhau và dev server trả 500
   (`Cannot find module './77.js'`, `vendor-chunks/@tanstack.js`). Cách xử lý đã kiểm chứng:
   dừng dev → `rm -rf .next` → `npm run dev`. Đây là giới hạn vận hành, không phải lỗi app.
5. **Tick "Chế độ tối"** trong side nav dùng segmented control thay vì một nút toggle như
   reference; hành vi tương đương, hình thức khác (PROPOSAL).
6. **`--ink-3` đậm hơn reference** (light `#645c81` thay vì `#8a82a6`) — đánh đổi có chủ đích
   để đạt 4.5:1. Đã đo: trước khi đổi là 3.12–3.61:1, sau khi đổi ≥4.78:1 trên mọi surface.
7. **Script audit CDP nằm ngoài repo** (`%TEMP%/opencode/ps-recon/*.mjs`). axe-core có trong
   `node_modules` nhưng driver thì không — muốn tái lập phải viết lại. Đây là khoảng trống
   tái lập thật, không phải điều đã che.

---

## 10. Việc nên làm tiếp

1. Thêm Playwright E2E cho luồng tạo 5 câu → proposal → generating → lesson → quiz, có
   assertion (đây là khoảng trống lớn nhất còn lại).
2. Focus trap + `aria-modal` cho Tutor sheet, đo bằng `activeElement` sau mỗi `Tab`.
3. Dark capture cho `/login` + `/new/*`; 390×844 cho `/new/interview` và `/new/proposal`.
4. Chạy `pytest` backend một lần để xác nhận môi trường (backend không bị chạm).
5. Nếu muốn sát reference hơn: self-host font, thu hẹp tutor sheet, và xin approval để
   thêm field `estimatedMinutes`/`terms` vào backend (additive, có migration).
6. Dọn Chrome profile/DB throwaway sau khi review xong.

---

## 11. Lệnh tái lập nhanh

```bash
# frontend gates
cd frontend && npx tsc --noEmit && npm run lint && npm run build

# backend throwaway (KHÔNG dùng DB chính)
docker compose up -d db redis
docker exec reverseengineer-db-1 psql -U ailp -d ailp -c "CREATE DATABASE ailp_ui_check;"
cd backend && DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@localhost:5433/ailp_ui_check" python -m alembic upgrade head
LLM_PROVIDER=mock JWT_SECRET=dev-only DATABASE_URL="postgresql+asyncpg://ailp:ailp_password@localhost:5433/ailp_ui_check" \
  REDIS_URL=redis://localhost:6379/0 python -m uvicorn app.main:app --port 8000

# frontend dev
cd frontend && npm run dev
```
