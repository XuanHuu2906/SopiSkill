# SOPISKILL — MASTER PLAN TÁI THIẾT KẾ FRONTEND DỰA TRÊN REA / POLYSKILL

**Phiên bản:** 1.0  
**Ngày soạn:** 2026-11-03  
**Sản phẩm cần triển khai:** SopiSkill / AI Learning Platform  
**Repository được tài liệu dự án nêu:** https://github.com/XuanHuu2906/SopiSkill  
**Sản phẩm tham khảo hành vi và trải nghiệm:** https://web.polyskill.app  
**Đối tượng thực thi:** OpenCode trên Windows, dùng REA + Chrome CDP (nếu đã cấu hình và được phép).  
**Loại tài liệu:** **PLAN / PROPOSAL — chưa phải bằng chứng đã triển khai hoặc chạy test.**

> **MỤC TIÊU ĐÚNG:** Tái thiết kế **frontend SopiSkill** theo các luồng, cách tổ chức nội dung và chất lượng trải nghiệm đã quan sát ở PolySkill, giữ nguyên **backend FastAPI của SopiSkill**.  Đây là kế hoạch theo phase, không phải một prompt giao việc đơn lẻ.


---

## 0. Mục tiêu, không mục tiêu và tiêu chuẩn đầu ra

### 0.1 Mục tiêu sản phẩm

- Người học có trải nghiệm thống nhất từ **đăng nhập → dashboard → nhập chủ đề → phỏng vấn 5 câu → duyệt đề cương → theo dõi sinh khóa học → course overview → lesson player → quiz → lưu tiến độ**.
- Giao diện phản ánh tốt mô hình **lesson theo block**: `teach`, `mc`, `blank`, `order`, `match`, `short`.
- Xây **design system độc lập** có thể phát triển lâu dài, ưu tiên cấu trúc và mức hoàn thiện UX quan sát được từ PolySkill.
- Tạo quy trình đối chiếu có bằng chứng: **reference screenshot → SopiSkill screenshot → issue → sửa → kiểm chứng lại**.
- Chỉ dùng **backend/API hiện hữu của SopiSkill**.

### 0.2 Không làm trong dự án frontend này

- Không chuyển Next.js sang Expo/React Native Web chỉ vì PolySkill dùng Expo.
- Không viết lại FastAPI, Redis/Celery, PostgreSQL, auth, job orchestration, LLM provider.
- Không tích hợp backend PolySkill; không giả mạo Tutor, citation, source ingest hoặc subscription chưa được backend SopiSkill hỗ trợ.
- Không mở rộng API/backend, database migrations, production deploy, billing hoặc LLM trả phí nếu chưa duyệt task riêng.

### 0.3 Deliverables bắt buộc

1. **Bộ nghiên cứu UI/UX** đặt trong `docs/frontend-reference/`: screen inventory, evidence registry, interaction map, design tokens, component map, gap analysis.
2. **Frontend code thực** tương thích với repo, không phải mockup tĩnh.
3. **Screenshot comparison** cùng viewport desktop/tablet/mobile đối với các màn hình có reference được phép lưu.
4. **Tests/build logs** trên môi trường chạy thực tế, phân biệt IMPLEMENTED / TESTED / NOT TESTED / BLOCKED.
5. **Phase report** cập nhật nối tiếp trong `docs/development-progress.md` và danh sách khác biệt còn tồn tại.

### 0.4 Định nghĩa mức tương đồng

- **Functional fidelity**: các thao tác SopiSkill hoạt động với API thật của dự án, kết quả sau reload đúng.
- **Interaction fidelity**: hướng đi, feedback, loading/error và tiến độ gần với mô hình trải nghiệm đã quan sát.
- **Visual fidelity**: layout grid, tỷ lệ, spacing, typography, component geometry, density và hierarchy tương đồng ở các viewport xác định.
- **Brand independence**: giao diện không gây nhầm tưởng là website PolySkill chính thức; toàn bộ brand/asset riêng.
- Không tự gắn nhãn “pixel-perfect”, “giống 95%”, “TESTED” khi chưa có bằng chứng so sánh đo được.

---

## 1. Nguồn sự thật và mức độ tin cậy

### 1.1 Tài liệu phải đọc

| Nguồn | Vai trò | Mức độ tin cậy |
|---|---|---|
| **Repository SopiSkill ở HEAD hiện tại** | Nguồn sự thật cho code/API thực tế | Chỉ xác nhận sau khi OpenCode audit |
| `AGENTS.md`, `opencode.json`, `.opencode/skills/` (nếu có) | Quy tắc agent, công cụ và quyền | Phải xem code/config thực |
| `docs/development-progress.md` | Nhật ký triển khai/kiểm thử trước đây | Reported evidence, không thay thế lần test hiện tại |
| `docs/architecture.md`, `docs/implementation-plan.md` | Kiến trúc/phạm vi | Design; có thể lạc hậu |
| `docs/MASTER_IMPLEMENTATION_PLAN.md` | Roadmap tổng sản phẩm | Dùng để tránh xung đột phase khác |
| `02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md` | Vision và ưu tiên dự án | Bối cảnh, một số trạng thái cũ có thể lỗi thời |
| `polyskill-analysis-report.md` | Phân tích REA tĩnh | FACT giới hạn theo frontend bundle |
| `polyskill-dynamic-analysis.md` | Quan sát runtime REA + Chrome CDP | FACT giới hạn theo capture/origin filter |
| `Pasted text(1).txt` do người dùng cung cấp | Prompt yêu cầu frontend đã phác thảo | Yêu cầu đầu vào; chưa phải plan nghiệm thu |

> Nếu file tham khảo chưa có trên máy OpenCode: ghi **MISSING REFERENCE** và dùng các tài liệu có thực; không tự viết nội dung rồi khẳng định đã đọc nguồn. Không ghi đè các tài liệu nghiên cứu gốc.

### 1.2 Các FACT đã được báo cáo, cần kiểm lại nếu thay đổi

**PolySkill (bằng chứng từ hai báo cáo REA 2026-10-30):**
- Client được phân tích: Expo SDK 57 / React Native Web / React 19.2.3 / Metro / Expo Router; đây **không phải** stack đề xuất cho SopiSkill.
- Luồng topic → interview 5 câu → proposal → approve → generation → lessons.
- Client polling generation khoảng **2 giây**; các request generation đầu phiên runtime có phần bị lọc bởi origin filter, không coi mọi bước là runtime verified.
- Lesson blocks `teach`, `mc`, `blank`, `order`, `match`, `short`; có ngữ cảnh Tutor theo `lessonId`, `blockIndex`.
- Tutor client có SSE, contextRef, toolCalls; hình dạng nội dung SSE events và logic backend không được xác minh đầy đủ.
- Có client-side schema/luồng source arXiv/web/PDF; không suy ra server đã dùng thuật toán RAG cụ thể.

**SopiSkill (được báo cáo trong `development-progress.md`, chưa audit HEAD ở lượt lập kế hoạch):**
- Frontend Next.js 15 + TypeScript + TanStack Query; backend FastAPI.
- Đã có `frontend/src/app` với các màn: `/`, `/login`, `/new`, `/new/interview`, `/new/proposal`, `/new/generating`, `/course/[courseId]`, `/lesson/[lessonId]`.
- Có auth bằng HttpOnly cookie + CSRF, session-scoped query keys, dashboard, course generation, quiz, progress.
- P1.3 ghi `npm run build`, typecheck và E2E đã được chạy ở thời điểm báo cáo; P2.0 ghi backend tests/real-provider smoke; **không suy ra môi trường hiện tại vẫn pass**.
- Tutor SSE / RAG chưa được xác minh đã triển khai; phải audit HEAD.

### 1.3 Quy tắc phân loại chứng cứ

- `FACT`: quan sát trực tiếp trên một phiên runtime/asset được phép hoặc kiểm chứng từ source hiện tại; ghi nguồn + thời điểm + giới hạn.
- `INFERENCE`: suy luận từ dấu hiệu, không trình bày như đã xác minh.
- `UNKNOWN`: chưa quan sát/không có bằng chứng hoặc REA không có quyền nhìn thấy.
- `PROPOSAL`: quyết định thiết kế của SopiSkill.
- `IMPLEMENTED`: có code thật tại HEAD/working tree.
- `TESTED`: có lệnh thực sự chạy, output và exit code trong phiên thực hiện.
- `BLOCKED`: thiếu quyền, công cụ, dữ liệu, contract hoặc quyết định cần thiết.

---

## 2. Phạm vi màn hình — screen inventory và ưu tiên

| ID | Reference cần khảo sát (theo hành vi) | Route SopiSkill cần audit | Ưu tiên | Trạng thái ban đầu |
|---|---|---|---|---|
| S01 | Login / register | `/login` | P0 | NEED AUDIT |
| S02 | Dashboard / My Courses / Empty state | `/` | P0 | NEED AUDIT |
| S03 | Topic creation | `/new` | P0 | NEED AUDIT |
| S04 | 5-question interview | `/new/interview` | P0 | NEED AUDIT |
| S05 | Proposal / review / approve | `/new/proposal` | P0 | NEED AUDIT |
| S06 | Generation: queued, running, ready, failed | `/new/generating` | P0 | NEED AUDIT |
| S07 | Course overview / units / lessons / progress | `/course/[courseId]` | P0 | NEED AUDIT |
| S08 | Lesson content player / teach block | `/lesson/[lessonId]` | P0 | NEED AUDIT |
| S09 | `mc` quiz | Lesson player | P0 | NEED AUDIT |
| S10 | `blank` quiz | Lesson player | P0 | NEED AUDIT |
| S11 | `order` quiz | Lesson player | P0 | NEED AUDIT |
| S12 | `match` quiz | Lesson player | P0 | NEED AUDIT |
| S13 | `short` quiz | Lesson player | P0 | NEED AUDIT |
| S14 | Quiz result, score, completion | Lesson player/course overview | P0 | NEED AUDIT |
| S15 | Tutor launcher/chat/panel/context | Component/gap — TBD | P1 | CONTRACT GAP until verified |
| S16 | Proposal editing/AI revision | Contract/gap — TBD | P2 | DO NOT FAKE |
| S17 | Source ingest (PDF/web/arXiv) | Contract/gap — TBD | P2 | DO NOT FAKE |
| S18 | Gamification, billing, advanced settings | Future backlog | P3 | OUT OF MVP |

**Quan trọng:** Route PolySkill cụ thể không được giả định trùng với SopiSkill. Reference dùng theo **tên màn hình/trạng thái**, không phải sao chép URL/API.

### 2.1 States bắt buộc cho mỗi màn

- Default, hover/pressed/focus (khi có), loading, skeleton/placeholder, empty, validation error, network error, unauthorized/expired session, success, retry.
- Khi màn có state machine: test trực tiếp các trạng thái phù hợp, tránh trình bày animation progress giả như tiến độ server thật.
- Khi PolySkill chưa quan sát được một state: đánh dấu `NOT OBSERVED` và đề xuất UX riêng, không mô tả như FACT.

---

## 3. Bộ hồ sơ khảo sát REA + Chrome (PHASE R0–R2)

### 3.1 Quy trình quan sát có phép

1. Xác minh phiên bản và tool REA đã cài (trước đây báo cáo dùng REA 6.7.0); xem chính xác hướng dẫn CLI/MCP hiện có.
2. Chỉ attach Chrome tab được chủ tài khoản cho phép; không bật remote debugging/profile chứa dữ liệu nhạy cảm không cần thiết.
3. Khảo sát **UI hiển thị** của PolySkill qua tương tác thông thường. Với network observations, chỉ đọc metadata/schemas cần thiết và chỉ trên phiên hợp lệ được phép.
4. Không bypass đăng nhập/captcha/paywall/rate limit; không gọi thử API trực tiếp ngoài UI; không thu thập hoặc xuất cookie/token/headers nhạy cảm, body riêng tư.
5. Lưu chứng cứ không chứa dữ liệu cá nhân và có quyền lưu. Nếu screenshot có thông tin riêng: thay bằng fixture/synthetic data hoặc redact trước khi lưu.
6. Ghi rõ filter/origins được phép; kiểm tra `disallowed_origin` trong REA như bài học từ báo cáo động.
7. Không tin rằng REA tái dựng “source React đầy đủ” hay DOM/CSS/animation chính xác từ JS minified; luôn xác minh bằng quan sát màn hình.

### 3.2 Form ghi nhận mỗi screen (`screen-inventory.md`)

```yaml
screen_id: S04
reference_name: Personalized Interview
reference_url_or_navigation: "Observed navigation, do not invent route"
observed_at: "YYYY-MM-DD HH:mm +07:00"
viewport: {width: 1440, height: 900, device_scale_factor: 1}
source: "CDP screenshot / REA notes / manual observation"
visibility: "OBSERVED | PARTIAL | NOT OBSERVED"
auth_scope: "own account only"
layout: "Description with measured/estimated values clearly labeled"
visual_tokens: "Color / type / spacing / border / shadow"
interaction: "What was actually exercised"
states: ["default", "answered", "loading"]
unknowns: []
reference_artifact: "path if saved lawfully, else NOT STORED"
sopiskill_route: "/new/interview"
confidence: "FACT | INFERENCE | UNKNOWN"
```

### 3.3 Evidence register

| Evidence ID | Màn | Loại evidence | Viewport | Nguồn/thời gian | Điều chứng minh | Điều **không** chứng minh |
|---|---|---|---|---|---|---|
| EV-001 | S03 | screenshot | 1440x900 | Điền khi capture | Bố cục màn topic | Logic backend sinh course |
| EV-002 | S04 | UI recording/notes | 390x844 | Điền khi capture | Điều hướng phỏng vấn | Prompt dùng trên server |
| EV-003 | S06 | REA network metadata | desktop | Điền khi capture | Client poll trạng thái | Internal job architecture |

Không tạo evidence ID “đã thu thập” khi artifact chưa tồn tại.

### 3.4 Bộ viewport tối thiểu

- Desktop: **1440 × 900**.
- Tablet: **768 × 1024**.
- Mobile: **390 × 844**.
- Nếu không truy cập được màn reference ở một viewport, đánh dấu `NOT OBSERVED`, không dựng dữ liệu đo giả.
- Cố định browser zoom = 100%, font loading hoàn tất, viewport/DPR và trạng thái nội dung để so sánh công bằng.

### 3.5 Đầu ra nghiên cứu

```text
docs/frontend-reference/
  README.md
  screen-inventory.md
  evidence-register.md
  interaction-map.md
  design-tokens.md
  component-mapping.md
  api-gap-register.md
  visual-comparison.md
  accessibility-review.md
  decisions.md
  phase-reports/
  screenshots/     # chỉ khi được phép và đã redact
```

---

## 4. Design system SopiSkill (PHASE F1)

### 4.1 Nguyên tắc

- Đo đạc/reference trước, sau đó định nghĩa **token của SopiSkill**. Không copy nguyên CSS/stylesheet/bundle hoặc asset bên thứ ba.
- Hệ tokens dùng được trên toàn bộ màn để ngăn style drift. Ưu tiên CSS variables / design tokens phù hợp stack hiện có.
- Giữ accessibility: độ tương phản đọc được, focus ring, reduced motion, semantic landmarks; không đánh đổi chức năng để chạy theo screenshot.

### 4.2 Token cần xây

```text
Brand:          primary / accent / success / warning / danger
Surface:        canvas / surface / elevated / muted
Text:           primary / secondary / tertiary / inverse
Border:         subtle / strong / interactive
Typography:     family / xs-sm-base-lg-xl-2xl / weight / leading
Spacing:        4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 ...
Radius:         sm / md / lg / xl / pill
Elevation:      card / popup / modal
Layout:         content max-width / sidebar width / header height
Motion:         duration / easing / reduce-motion override
```

Giá trị thực chỉ điền sau audit; không hard-code “màu của PolySkill” từ suy đoán.

### 4.3 Components nền

- `AppShell`, `Header`, `PrimaryNav`, `MobileNav`, `PageContainer`, `Breadcrumb` (chỉ nếu UX cần).
- `Button`, `IconButton`, `TextField`, `Textarea`, `FormField`, `Radio/OptionCard`, `Progress`, `Badge`, `Card`, `Dialog`, `Toast`, `Skeleton`, `EmptyState`, `ErrorState`.
- `Stepper`, `CourseCard`, `UnitAccordion`, `LessonRow`, `LessonBlock`, `QuizControls`, `QuizFeedback`.
- Dùng component hiện có trước; không thêm UI library nặng hoặc thay router/state manager nếu không có lý do đo được.

---

## 5. Kiến trúc frontend và hợp đồng backend

### 5.1 Cấu trúc đề xuất (điều chỉnh theo repository)

```text
frontend/
  src/
    app/
      (existing Next.js App Router routes — giữ nguyên)
      globals.css
      providers.tsx
    components/
      ui/
      layout/
      courses/
      interview/
      proposal/
      generation/
      lessons/
      quiz/
      tutor/          # chỉ UI sau khi contract được xác nhận
    lib/
      api.ts
      query-keys.ts   # chỉ nếu refactor an toàn
    hooks/
    styles/           # token/utility nếu repo cần
  tests/              # theo convention repo
```

**Lưu ý:** Đây là proposal. OpenCode phải liệt kê file thực tế trước và chỉ tạo thư mục thiếu.

### 5.2 Contract không được phá

- **Session/auth**: HttpOnly cookie, `credentials: 'include'`, CSRF cho request thay đổi dữ liệu, không đưa token vào localStorage.
- **Session isolation**: TanStack Query keys chứa định danh session phù hợp; login/logout account switching clear dữ liệu cũ.
- **Courses**: giữ endpoint và shape SopiSkill đã có; UI hiển thị trạng thái thật (`interview`, `proposed`, `approved`, `generating`, `ready`, `failed`).
- **Interview**: đủ 5 câu; reload/đã trả lời; không tự tiết lộ dữ liệu câu trả lời riêng khi server không trả.
- **Proposal**: review/approve theo contract; tính năng sửa proposal chưa có API phải ghi `API GAP`, không mock chức năng như thật.
- **Generation**: poll theo contract hiện có (~2s trong thiết kế), tự dừng tại terminal, không đếm tiến độ giả; retry không spam.
- **Lesson**: GET chỉ nhận public blocks; không đưa `answerIndex`/`acceptedAnswers`/private keys vào bundle/public API.
- **Quiz**: attempt gửi lên backend; `clientAttemptId` ổn định khi retry; score và feedback nhận từ server; stale `contentVersion` xử lý đúng.
- **Progress/XP**: render dữ liệu API, invalidate đúng cache sau submit; reload vẫn đúng.
- **User ownership**: backend kiểm tra, frontend guard chỉ là hỗ trợ UX; không tin courseId/lessonId client tự cung cấp.
- **LLM provider**: UI không gọi provider trực tiếp; không đổi `LLM_PROVIDER` để test visual; mock được hiển thị rõ khi cần.

### 5.3 API GAP / feature gate

| Tính năng mong muốn | Trạng thái plan | Cách làm an toàn |
|---|---|---|
| Proposal editing / AI revision | API cần xác minh | Chỉ hiển thị khi API SopiSkill hỗ trợ; không fake |
| Tutor SSE | Theo tài liệu dự án còn roadmap | UI shell / design spec trước, không giả chat hoạt động |
| Tutor tool calls, stop/cancel, allowance | Roadmap P3 | Đợi backend contract; không dùng API PolySkill |
| Source upload/RAG/citation | Roadmap P4 | Để backlog; không tạo citation giả |
| Hearts/streak/subscription | Ngoài MVP | Không thêm vào luồng chính nếu dữ liệu chưa có |

---

## 6. Dependency graph & thứ tự thực hiện

```text
R0  Repository / REA readiness audit
 |
 v
R1  Reference screen capture + interaction evidence
 |
 v
R2  Existing SopiSkill UI audit + API mapping + gap register
 |
 v
F1  Design tokens + reusable primitives + AppShell
 |
 +----> F2  Login + Dashboard + Course Cards
 |
 +----> F3  Topic + Interview + Proposal + Generation
 |              |
 |              v
 +----------> F4  Course overview + Lesson player + Quiz
 |              |
 |              v
 +----------> F5  Error / Empty / Loading / Responsive / A11y
 |                             |
 |                             v
 +--------------------------> F6  Visual regression + Browser E2E
                               |
                               v
                             F7  Final review / handoff / docs

OPTIONAL, separate approval:
T1 Tutor UI integration (chỉ sau khi backend Tutor contract verified)
S1 Source ingest/RAG frontend (chỉ sau khi API hoạt động)
```

**Gating:** Phải đóng gate mỗi phase trước khi sang phase phụ thuộc. Một phase có thể chia thành nhiều commit/PR nhỏ. Không tích hợp tính năng chưa có backend chỉ vì nhìn thấy ở PolySkill.

---

## 7. Chi tiết từng phase: task, file, DoD, kiểm thử, không làm

### PHASE R0 — Repo & REA readiness audit (P0 / bắt buộc)

**Mục tiêu:** Xác định trạng thái thực của repo và bộ công cụ, tránh agent ghi đè công việc trước.

**Bối cảnh:** `development-progress.md` là nhật ký ngày 2026-10-30; đã có báo cáo P1.3/P2.0 nhưng chưa xác minh HEAD hiện tại.

**File/module:** `AGENTS.md`, `opencode.json`, `frontend/package.json`, `frontend/src/app/**`, `frontend/src/lib/api.ts`, docs.

**Thứ tự:**
1. `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git diff --stat`.
2. Kiểm tra các trang, providers, query hooks, contracts, CSS, thư viện UI và lệnh tests.
3. Kiểm tra REA tool/skills thực sự cài và quyền Chrome/CDP; không tự đoán CLI flag hoặc tự chỉnh global config.
4. Chụp baseline screenshots **SopiSkill** nếu môi trường chạy và có dữ liệu test hợp lệ; lưu đường dẫn/log.
5. Xuất `repo-audit.md` + `baseline-issues.md` và trạng thái environment.

**Acceptance:** Có báo cáo HEAD, git status, route/component inventory, API owner, lệnh build/test hiện có, tool readiness. **Không sửa UI trong R0**.

**Tests:** `npm run build` hoặc `npx tsc --noEmit` nếu dependencies sẵn; lỗi/thiếu môi trường ghi NOT TESTED/BLOCKED.

**Không làm:** Clone repo lần hai, clean/reset dữ liệu người dùng, cài package quy mô lớn, chạy migration.

### PHASE R1 — REA reference capture & UX evidence (P0)

**Mục tiêu:** Tạo bản mô tả PolySkill có thể truy vết và màn hình thực để đối chiếu; không chỉ đọc bundle.

**File:** `docs/frontend-reference/screen-inventory.md`, `evidence-register.md`, `interaction-map.md`, `screenshots/` khi hợp lệ.

**Thứ tự:**
1. Khảo sát màn S01–S14 trên tài khoản được phép (không cần cố xem mọi paywalled screen).
2. Từng màn: desktop/tablet/mobile, state, navigation, button/keyboard, spacing/layout.
3. Ghi đo đạc và phân biệt số đo thật với ước lượng; ghi viewport, zoom, DPR.
4. Tách `FACT` về frontend với `UNKNOWN` về backend.
5. Đối chiếu sơ bộ với route SopiSkill, không sửa code.

**Acceptance:** 100% màn **có thể truy cập hợp lệ** trong scope được ghi; màn còn thiếu gắn NOT OBSERVED. Có ít nhất một evidence entry/màn được quan sát. Không có secrets/private content.

**Không làm:** Bypass, call endpoint nội bộ, sao chép bundle/CSS/asset.

### PHASE R2 — Gap analysis + buildable plan (P0)

**Mục tiêu:** Chuyển reference thành backlog UI theo file và API contract.

**File:** `component-mapping.md`, `api-gap-register.md`, `design-tokens.md`, `decisions.md`.

**Thứ tự:**
1. Với mỗi route SopiSkill, ghi component hiện có, reference visual pattern, thiếu gì và risk.
2. Lập API mapping SopiSkill-only, trạng thái success/error/retry.
3. Phân loại **visual-only / interaction-only / needs API / out-of-scope**.
4. Ước lượng mức độ ảnh hưởng/số file và acceptance test cho từng story.
5. Chốt F1–F7, không đổi thứ tự nếu phụ thuộc chưa giải quyết.

**Acceptance:** Mỗi story có route, file/modules liên quan, contract, acceptance, test, rollback. `API GAP` được dán nhãn rõ.

### PHASE F1 — Design foundation & AppShell (P0)

**Mục tiêu:** Tạo nền giao diện có thể tái sử dụng, không ảnh hưởng nghiệp vụ.

**File dự kiến:** `frontend/src/app/globals.css`, components UI/layout; chỉ tạo file mới cần thiết.

**Thứ tự:**
1. Tạo tokens SopiSkill từ R1/R2.
2. Chuẩn hóa font, container widths, responsive grid, colors, spacing, radii, buttons, form fields.
3. Xây `AppShell` và navigation; không đổi route semantics.
4. Thêm loading, focus, keyboard states và reduced motion.
5. So sánh desktop/mobile, sửa overflow/hydration issues.

**Acceptance:** Component primitives dùng chung ở tối thiểu 2 màn; build/typecheck; 1440/768/390 không tràn; không làm mất auth guard, route guard hoặc session provider.

**Tests:** typecheck, build, screenshot smoke, keyboard focus checks.

**Không làm:** Backend changes, lớn tiếng tự nhận “đã clone PolySkill”, global rewrite không liên quan.

### PHASE F2 — Authentication + Dashboard (P0)

**Mục tiêu:** Người dùng đăng nhập và nhận biết khóa học/trạng thái/tiến độ dễ dàng.

**Files:** `frontend/src/app/login/page.tsx`, `frontend/src/app/page.tsx`, `providers.tsx`, `api.ts` chỉ nếu cần; components account/course card.

**Thứ tự:**
1. Tách UI khỏi auth/session logic hiện hữu để không làm hỏng security contract.
2. Login/register/error/loading/focus; redirect `next` an toàn.
3. Dashboard course cards, empty state, loading/error/retry, continue learning.
4. Responsive navigation và active state.
5. Test account switch A → logout → B, cache clearing, reload.

**Acceptance:** Login/logout/register và protected redirect hoạt động; course list đúng owner; không hiển thị data A khi B đăng nhập; visual evidence đủ màn S01/S02.

**Tests:** browser flow, `npm run build`, backend auth integration nếu có thể.

**Không làm:** Thay HttpOnly cookie bằng localStorage, gửi userId client để chọn owner, sửa auth backend ngoài phase.

### PHASE F3 — Topic → 5 Interviews → Proposal → Generation (P0)

**Mục tiêu:** Luồng tạo khóa học xuyên suốt, giao diện đẹp nhưng trạng thái chính xác.

**Files:** `frontend/src/app/new/**`, API hooks/components hiện tại.

**Thứ tự:**
1. Topic form, validation, submit disabled/loading.
2. Interview question card, option/input, stepper 1/5–5/5, answered-state, reload.
3. Proposal layout: title, objective, units, lesson list, outcomes, approval state.
4. Generation: queued/running/ready/failed, data-backed progress, bounded retry, stop polling terminal.
5. Responsive/error boundary và navigation bằng keyboard.

**Acceptance:** Tạo course mới, hoàn tất 5 câu, thấy proposal, approve, job ready hoặc failed đúng API, chuyển course page; reload không làm sai state; không gửi duplicate mutation.

**Tests:** browser E2E mock provider (được dán nhãn mock); API error 401/403/409/5xx; polling stop.

**Không làm:** Fake proposal editing, hardcode progress %, tự mở provider trả phí, sao chép endpoint PolySkill.

### PHASE F4 — Course overview + Lesson Player + Quiz (P0 / quan trọng nhất)

**Mục tiêu:** Phần học chính có chất lượng trải nghiệm cao, giữ integrity của quiz.

**Files:** `frontend/src/app/course/[courseId]/page.tsx`, `frontend/src/app/lesson/[lessonId]/page.tsx`, components course/lesson/quiz.

**Thứ tự:**
1. Course outline: unit/lesson hierarchy, progress, completed/current/locked states từ API.
2. Lesson shell: heading, navigation, step control, teach content renderer.
3. Quiz component theo **6 block types** (teach + 5 loại câu hỏi): MC, blank, order, match, short; hiển thị đúng shape public data.
4. Answer entry/validation; không render private answer keys trước submit.
5. Submission state, idempotent attempt, server score/feedback, completion UI.
6. Regenerate/stale contentVersion/409, retry network, reload, progress revalidation.
7. Responsive lesson UI, tab order, keyboard interaction (đặc biệt order/match).

**Acceptance:** Tất cả block có fixture và render đúng; cả 5 dạng quiz gửi attempt đúng; không tự chấm client; không lộ key; progress/XP đồng bộ sau reload; user B không xem course/lesson A.

**Tests:** unit render/answer serialization, browser flows, backend E2E nếu chạy được, screenshot states, keyboard checks.

**Không làm:** Thay scoring threshold, trả lời mở bằng LLM khi API không hỗ trợ, fake XP, reset progress.

### PHASE F5 — UX hardening: loading/error/empty/responsive/a11y (P0)

**Mục tiêu:** Đạt tiêu chuẩn sản phẩm thực chứ không chỉ screenshot ở trạng thái đẹp.

**Files:** routes/components liên quan, `globals.css`, tests.

**Thứ tự:**
1. Audit tất cả loading/empty/error/unauthorized/expired session/server down.
2. Responsive tại 1440/768/390; keyboard navigation, focus visible, label and aria.
3. `prefers-reduced-motion`; animation không làm giả tiến độ.
4. Cải thiện state persistence và chống double click.
5. Kiểm tra các màn dài, nội dung dài/tiếng Việt, overflow và scroll restoration.

**Acceptance:** Không có blocker accessibility cơ bản; không có dead-end UI khi API lỗi; không tràn ở 3 viewport; không hiện stale user data.

### PHASE F6 — Visual regression + E2E & quality gate (P0)

**Mục tiêu:** Đối chiếu có hệ thống thay vì đánh giá chủ quan “giống rồi”.

**Files:** `visual-comparison.md`, tests/frontend e2e, screenshots được phép.

**Thứ tự:**
1. Tạo data fixture ổn định trong SopiSkill test env; reference state đã được chứng minh bằng screenshot hoặc notes.
2. Chụp SopiSkill cùng viewport; align viewport, zoom, font load, content state.
3. Tạo comparison matrix: layout, typography, spacing, density, component hierarchy, state transitions.
4. Nếu dùng pixel diff, ghi tool/version/threshold và **không so ảnh khác nội dung rồi suy ra UX tương đồng thấp**.
5. Chạy manual/browser E2E 10–15 luồng chủ lực và security regressions.
6. Lập danh sách `MATCHED / PARTIAL / NOT MATCHED / NOT OBSERVED`, ưu tiên sửa lỗi nghiêm trọng.

**Acceptance:** Có screenshot/gap matrix cho mọi màn đã quan sát, ít nhất 3 viewport cho các màn core khi reference tương ứng tồn tại; build + flows và test regressions có log; lỗi tồn được ghi rõ.

### PHASE F7 — Release review & handoff (P0)

**Mục tiêu:** Có đầu ra merge được mà không làm hỏng hệ thống.

**Thứ tự:**
1. Audit diff/PR, dependency changes, responsive/performance, no leaked secrets.
2. Chốt docs, map routes/screens/components, known limitations.
3. Đối chiếu backend coverage và có ý kiến không triển khai Tutor/RAG UI giả.
4. Ghi mốc HEAD/branch, test commands, outputs, screenshots, gate.
5. Đề xuất 1–3 task kế tiếp, chỉ xin phép commit/push/deploy khi cần.

**Acceptance:** Không còn blocker P0; mọi đánh giá PASS có evidence; không tự push `main`/deploy.

---

## 8. Optional phase chỉ sau gate

### T1 — AI Tutor UI integration (P1, backend-first)

**Điều kiện:** Backend SopiSkill thực sự có SSE contract ổn định, auth/ownership, `contextRef`, thread persistence, stop/cancel/quota nếu UI hiển thị.

**Nội dung:** Tutor launcher, side panel, message list, contextual label, stream `delta/done/error`, cancellation button nếu API hỗ trợ, history/reload, error/retry, tool activity chỉ cho tool thực.

**Tests:** cross-user 404, invalid block index, streaming disconnect, idempotency, reload history, quota. Không gọi API PolySkill; không giả LLM.

### S1 — Sources / citations UI (P2, backend-first)

**Điều kiện:** SopiSkill có source ingest/RAG và citation validator thật.

**Nội dung:** upload UI, status, source list, citation navigation tới nguồn hợp lệ. Citation không có source page/chunk xác minh được thì không hiển thị như citation thật.

---

## 9. Ma trận acceptance regression xuyên suốt

| Kịch bản | F2 | F3 | F4 | F5 | F6 |
|---|:---:|:---:|:---:|:---:|:---:|
| Login/register/logout + HttpOnly cookie/CSRF | ✓ | ✓ | ✓ | ✓ | ✓ |
| A logout → B login: query cache không lộ data A | ✓ | ✓ | ✓ | ✓ | ✓ |
| Topic → 5 questions → proposal → approve → generation | — | ✓ | ✓ | ✓ | ✓ |
| Reload route đang làm và progress persistence | ✓ | ✓ | ✓ | ✓ | ✓ |
| Poll dừng terminal `ready/failed` | — | ✓ | — | ✓ | ✓ |
| `GET lesson` không lộ answer keys | — | — | ✓ | ✓ | ✓ |
| Quiz MC/blank/order/match/short và stale version | — | — | ✓ | ✓ | ✓ |
| Retry same clientAttemptId không double reward | — | — | ✓ | ✓ | ✓ |
| Course/lesson A không cho B truy cập | ✓ | ✓ | ✓ | ✓ | ✓ |
| Keyboard focus / aria labels / reduced motion | ✓ | ✓ | ✓ | ✓ | ✓ |
| Desktop 1440 / tablet 768 / mobile 390 | ✓ | ✓ | ✓ | ✓ | ✓ |
| Build/typecheck + browser smoke/E2E | ✓ | ✓ | ✓ | ✓ | ✓ |

`✓` nghĩa là **test cần thực hiện**, không phải bằng chứng đã PASS.

### 9.1 Lệnh baseline trên Windows PowerShell (chỉ chạy khi đã kiểm tra repo)

```powershell
# Tại thư mục gốc SopiSkill
Get-Location
git status --short
git branch --show-current
git rev-parse HEAD

# Frontend
Set-Location frontend
npm run build
npx tsc --noEmit
Set-Location ..

# Backend regression — nếu venv/dependencies và test environment phù hợp
Set-Location backend
python -m pytest -q
Set-Location ..

# E2E local — chỉ sau khi đã kiểm tra Compose, migrations, DB và env
$env:E2E_BASE = 'http://127.0.0.1:8001'
python .\backend\e2e_acceptance.py
```

- Không tự chạy `docker compose up --build` trên volume đang chứa dữ liệu quan trọng khi chưa kiểm tra migration và backup.
- `npm run lint` chỉ chạy nếu script/config thực sự tồn tại; không tự tạo lint config trong một phase UI không liên quan.
- Browser screenshot/test có thể dùng Playwright nếu cài đặt/cho phép. Chạy test sử dụng fixture, không dùng tài khoản PolySkill để automation tải nặng.
- Nếu thiếu Node/Python/Docker/Playwright, báo `NOT TESTED` hoặc `BLOCKED` và hướng dẫn lệnh tái lập; không “pass theo suy đoán”.

### 9.2 Kiểm tra hiệu năng & chất lượng

- Không gọi API thừa do query keys/refetch; generation polling auto-stop.
- Tránh hydration mismatch trong Next.js, focus trap lỗi modal, layout shift do font/skeleton.
- Tối ưu hình ảnh của **SopiSkill** và lazy loading hợp lý; không tải asset PolySkill làm dependency chạy runtime.
- Theo dõi performance bằng measurements nếu có (không đặt LCP/CLS “PASS” khi không đo).

---

## 10. An toàn, bảo mật, quyền sở hữu và khả năng rollback

**Authorization:** frontend không thể thay backend ownership checks; mọi view/mutation phải theo user hiện tại.  
**Auth:** giữ cookie + CSRF, `credentials: 'include'`, không tự đưa secret vào `NEXT_PUBLIC_*`.  
**Quiz:** giữ private answer key server-side; đặc biệt với order/match không dựa vào thứ tự public làm đáp án.  
**AI:** không gọi LLM provider trực tiếp từ frontend, không giả kết quả real provider khi đang mock.  
**REA:** chỉ các thao tác được phép trên account sở hữu/quyền sử dụng; không cố reverse code/asset/prompt độc quyền hoặc bypass.  
**Visual:** thiết kế độ tương đồng cao trong khuôn khổ nhận diện SopiSkill; nếu có xung đột branding/asset, ưu tiên tự thiết kế lại.  
**Data:** không log token, cookie, toàn bộ prompt, raw user data hoặc screenshots chưa redact.  
**Rollback:** mỗi phase là diff/commit/PR nhỏ; rollback bằng Git, không phụ thuộc migration database; nếu task phát sinh API/migration thì tách phase và xin duyệt.

**Dừng bắt buộc trước:** xoá/sửa dữ liệu DB thật, destructive migration, chỉnh cấu hình secrets, gọi LLM có phí, production deploy, tự động push main, thay đổi quyền tài khoản/Chrome profile nhạy cảm.

---

## 11. Phase report template bắt buộc

Cuối mỗi phase, cập nhật **nối tiếp** `docs/development-progress.md`:

```markdown
## YYYY-MM-DD — FRONTEND <PHASE_ID> — <TÊN>
- Repository / branch / HEAD / git status:
- Reference observed: [screen IDs, viewport, evidence paths]
- NOT OBSERVED: [screen IDs + nguyên nhân]
- Mục tiêu và phạm vi:
- Files changed:
- IMPLEMENTED: [component / route / state]
- TESTED: [lệnh thực thi, exit code, logs, screenshot path]
- NOT TESTED: [lý do]
- BLOCKED: [quyền, tools, contract thiếu]
- API contract / security review:
- Visual comparison: [MATCHED / PARTIAL / NOT MATCHED / NOT OBSERVED]
- Regression results:
- Known limitations:
- Rollback:
- PHASE GATE: PASS / PARTIAL / BLOCKED
- NEXT: [1–3 task cụ thể]
```

### Gate rules

- `PASS`: tất cả acceptance bắt buộc của phase được kiểm chứng trong môi trường thực tế.
- `PARTIAL`: đã code nhưng còn screenshot/visual test/browser flow hoặc regression chưa chạy.
- `BLOCKED`: thiếu reference, Chrome/REA permission, API contract hoặc tooling cần thiết. Phải chỉ ra cách gỡ.
- `NOT TESTED`: chưa chạy; không được thay bằng “có vẻ hoạt động”.

---

## 12. Backlog stories giao cho OpenCode (có thể mở issue/PR)

| Story | Phase | Công việc | Acceptance có thể kiểm chứng |
|---|---|---|---|
| FE-001 | R0 | Audit HEAD/stack/tools | Repo inventory + command output |
| FE-002 | R1 | Capture dashboard/login/topic | Evidence registry + viewport records |
| FE-003 | R1 | Capture interview/proposal/generation | Evidence + state transitions |
| FE-004 | R1 | Capture course/lesson/quiz | Evidence + block taxonomy |
| FE-005 | R2 | Gap map + contracts | Route-to-component map, gap register |
| FE-006 | F1 | Tokens & AppShell | No layout overflow + build |
| FE-007 | F1 | Form/button/card/stepper primitives | Reuse ≥2 screens + focus states |
| FE-008 | F2 | Auth screen polish | Login/register/logout + redirect E2E |
| FE-009 | F2 | Dashboard + course cards | Owner scoped list + reload |
| FE-010 | F3 | Topic/interview | 5 answers + reload + error states |
| FE-011 | F3 | Proposal/generation | Approve, poll stop, retry/error |
| FE-012 | F4 | Course overview | Course outline + progress from API |
| FE-013 | F4 | Lesson block renderer | `teach/mc/blank/order/match/short` fixture coverage |
| FE-014 | F4 | Submit/result/progress | No key leak, server grading, idempotency |
| FE-015 | F5 | Responsive/accessibility | 3 viewports + keyboard tests |
| FE-016 | F6 | Screenshots comparison | Matrix + reproducible captures |
| FE-017 | F6 | Browser E2E regression | Critical paths + report output |
| FE-018 | F7 | Review/docs/handoff | No blocker P0, final phase report |
| FE-019 | T1 | Tutor UI (conditional) | Backend SSE contract verified |
| FE-020 | S1 | Source UI (conditional) | Ingest/citation contract verified |

### Priority / thực hiện tuần tự

- **P0:** FE-001 → FE-018 theo dependency ở §6.
- **P1:** FE-019 chỉ sau khi backend Tutor SopiSkill đã có thật.
- **P2:** FE-020 chỉ sau khi backend source ingest/RAG SopiSkill đã có thật.
- **Không gộp cả 20 stories thành một thay đổi khổng lồ.**

---

## 13. Prompt khởi động duy nhất (để agent đọc plan và điều hành theo phase)

> Prompt sau **chỉ là lệnh khởi động**, không thay thế bản kế hoạch này.

```text
Bạn đang làm việc trong repository SopiSkill trên Windows.
Đọc AGENTS.md, docs/development-progress.md, docs/MASTER_IMPLEMENTATION_PLAN.md
(và các file có thật); sau đó đọc toàn bộ
`docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`.

NHIỆM VỤ: triển khai FRONTEND SopiSkill dựa trên bằng chứng quan sát PolySkill
bằng REA, giữ nguyên backend SopiSkill. 

Kiểm tra git status/branch/HEAD, frontend routes, API contracts, REA/Chrome CDP
permissions trước khi sửa. Bắt đầu PHASE R0; R0 hoàn tất mới R1, R2, F1...
Tạo evidence registry và comparison matrix trước khi tuyên bố visual match.

Không sao chép bundle/CSS/assets/logo/prompt thương mại; không sử dụng API
PolySkill cho SopiSkill; không viết lại stack, sửa database, bí mật, dùng LLM
trả phí, deploy hoặc push main khi chưa được duyệt.

Thực thi từng phase nhỏ: audit → plan → implement → test → screenshot
comparison → review → update progress. Báo IMPLEMENTED / TESTED /
NOT TESTED / BLOCKED, lệnh chạy và bằng chứng; không báo PASS giả.
Bắt đầu ở R0 và xuất audit report + task list cụ thể trước khi code UI.
```

---

## 14. Checklist cuối để người dùng review

- [ ] REA đã khảo sát các screen có quyền truy cập; nguồn và trạng thái FACT/UNKNOWN rõ.
- [ ] `docs/frontend-reference/` đủ inventory, tokens, mapping, evidence, gap register.
- [ ] Không có asset/code nhãn PolySkill trong sản phẩm SopiSkill.
- [ ] F1–F4 hoàn thành theo route, contract và fixture thực.
- [ ] Auth/CSRF/session query cache không regression.
- [ ] Course generation state/polling/retry đúng backend.
- [ ] 5 kiểu quiz + teach block render và hoạt động.
- [ ] Không lộ đáp án, không farm XP, không fake progress.
- [ ] Desktop/tablet/mobile được kiểm tra.
- [ ] Screenshot comparison có kết quả trung thực, không phần trăm bịa.
- [ ] Browser E2E/build/typecheck đã chạy hoặc nêu giới hạn rõ.
- [ ] Phase report cuối cùng, next backlog và rollback rõ.

---