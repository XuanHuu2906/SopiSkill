# Screen inventory — reference vs SopiSkill

Every row was captured on 2026-11-03 with the viewports listed. Evidence files live in
`docs/frontend-reference/evidence/` (DOM + computed style JSON) and
`docs/frontend-reference/screenshots/` (PNG).

Legend for confidence: **FACT** measured, **INFERENCE** derived, **UNKNOWN** not observed,
**PROPOSAL** SopiSkill decision.

## Capture log

| Screen | Route | Viewports | Evidence files | Confidence |
|---|---|---|---|---|
| Sign-in | `/sign-in` | 1440x900, 768x1024, 390x844 | `dom-signin-*.json`, `screenshots/signin-*.png` | FACT |
| Home / dashboard | `/home` | 1440x900, 390x844, dark 1440x900 | `dom-home-1440x900.json`, `dom-home-390x844.json`, `dom-home-dark-1440x900.json`, `screenshots/home-*.png` | FACT |
| Course overview | `/course/{id}` | 1440x900, 768x1024, 390x844 | `dom-course-*.json`, `screenshots/course-*.png` | FACT |
| Lesson — teach block 1 | `/lesson/{id}` | 1440x900, 390x844 | `dom-lesson-1440x900.json`, `dom-lesson-390x844.json`, `screenshots/lesson-*.png` | FACT |
| Lesson — teach block 3 | same | 1440x900 | `dom-lesson-teach3.json`, `screenshots/lesson-teach3-1440x900.png` | FACT |
| Lesson — summary ("Trước bài kiểm tra") | same | 1440x900 | `dom-lesson-summary.json`, `screenshots/lesson-summary-1440x900.png` | FACT |
| Quiz — multiple choice | same | 1440x900 | `dom-quiz-1.json`, `dom-quiz-selected.json`, `screenshots/quiz-1-1440x900.png`, `quiz-selected-1440x900.png` | FACT |
| Quiz — correct feedback | same | 1440x900 | `dom-quiz-result.json`, `screenshots/quiz-result-1440x900.png` | FACT |
| Quiz — fill in the blank | same | 1440x900 | `dom-quiz-done.json`, `screenshots/quiz-done-1440x900.png` | FACT |
| Tutor panel | same (open over lesson) | 1440x900 | `dom-tutor-open.json`, `screenshots/tutor-open-1440x900.png` | FACT |
| New course (limit state) | `/new` | 1440x900 | `dom-new-1440x900.json`, `screenshots/new-1440x900.png` | FACT |
| Profile | `/profile` | 1440x900 | `dom-profile-1440x900.json`, `screenshots/profile-1440x900.png` | FACT |
| Interview + plan | `/new/interview?courseId=…` | 1440x900 | `dom-interview-done-1440x900.json`, `screenshots/interview-done-1440x900.png` | FACT (already-completed state) |
| Generating | `/new/generating?courseId=…` | 1440x900 | `dom-generating-1440x900.json`, `screenshots/generating-1440x900.png` | FACT (terminal state) |

## Screens not observed (honest gaps)

| Screen | Why not observed | Consequence for SopiSkill |
|---|---|---|
| Sign-up flow | Reference uses OAuth only (`Continue with Apple/Google`); no email/password form exists | SopiSkill keeps its own email/password form; layout is **PROPOSAL**, not a copy |
| Interview questions 1–4 in-progress | The only accessible course was already fully answered; creating a new course would consume quota | Conversation layout is inferred from the completed transcript (**INFERENCE**) |
| Proposal editing | No edit affordance was visible in the completed plan; account is on a limited tier | SopiSkill proposal page keeps its own review controls (**PROPOSAL**) |
| Generating in progress | Course had already finished generating; only the terminal screen was reachable without spending quota | Stage list is FACT (4 stage labels + "Mở lộ trình"); running spinner/progress states are **PROPOSAL** |
| Order / match / short-answer quiz blocks | The reached lesson only exposed `teach`, `mc` summary and `blank` before the session ended | Those block layouts are **PROPOSAL**, built to match the measured card/option/typography system |
| Wrong-answer feedback | Answering wrong would have mutated the learning record | SopiSkill keeps its own wrong-state styling; palette values reused (moss/clay/danger) |
| Onboarding, league, settings sheet | Owner did not authorize spending quota or mutating the profile | Not implemented; out of scope |
| Mobile tab labels for tutor | The `Pol` tab label was observed only in the bottom bar at 390 px | Tab labels reused as FACT |

## Structure per screen (FACT)

### Sign-in (1440x900)

- Centred column, content width 420 px for buttons, centred text above.
- Eyebrow `PolySkill` 13/18 semibold, colour `--c-emberDeep` (#5A38C6).
- H1 40/44 `Manrope_800ExtraBold`, colour `--c-ink` (#241C3B), literally `Learn anything.`
- Lede 17/27 Inter regular, colour `--c-ink2`, max width 360 px.
- Two 56 px pill buttons (radius 999): dark filled (`--c-btn` #241C3B, fg #FCFAFF)
  and white surface with ink text.
- Disclaimer 13/18 `--c-ink3`, then Terms/Privacy links in `--c-emberDeep`.
- At 390x844 the whole stack goes edge to edge with 20 px horizontal padding, buttons 56 px.

### App shell (desktop ≥1024)

- Side nav fixed at **264 px**, background `--c-cream` (#FCFAFF), right border
  1 px `--c-linen` (#E6DEFA).
- Nav padding: top 24, horizontal 16, bottom 16; groups separated by 24 px.
- Brand row: mark 34 px + 22/28 Manrope bold "PolySkill", 8 px gap, 8 px horizontal padding.
- Nav row: min-height 44, padding 12, radius 16, gap 12, icon 22 px; active row
  background `--c-wash` (#EBE3FF) with `--c-emberDeep` label; hover `--c-bone`.
- Course row (secondary nav): min-height 40, radius 16, 22 px progress ring + 15/20 title.
- Daily counters card: white surface, radius 22, padding 16; two pill chips
  (height 36, radius 999, background `--c-bone`) for streak and XP.
- Footer rows: dark-mode toggle and settings, same nav row metrics.
- Content column: horizontal padding 48, top 48, bottom 72, content max width **1040 px**
  (`contentWidth.page`), so the 1440 viewport resolves to x=312 width=1040.

### Home dashboard (1440x900)

- `Thứ Ba` eyebrow 13/18 semibold `--c-ink3` at y=48.
- Greeting 48/52 `Manrope_800ExtraBold` `--c-ink` at y=68 ("Chào buổi chiều, Người học.").
- Resume hero card: 1040x156, radius 22, padding 32, background `--c-ember` (#7B5BE6),
  shadow `0 14px 30px -12px rgba(123,91,230,.6)`; title 15/20 semibold white,
  chapter 13/18 white, lesson title 34/40 `Manrope_800ExtraBold` white;
  right side a 159x56 white pill button with `--c-emberDeep` label.
- Section label `Khóa học của bạn` 22/28 `Manrope_700Bold` 28 px below the hero.
- Course card: 336x122, radius 22, white, `shadows.card`, padding 16, gap 16;
  left a 52 px progress ring, title 17/22 semibold, meta 13/18 `--c-ink3`;
  overflow menu 32x32 at top-right (8 px inset).
- Empty state on `/home` was not reachable (account has a course).

### Course overview (1440x900)

- Header row: eyebrow + huge title (48/52) inside a 553x112 button-like container with
  22 px radius; right side 159x56 `Tiếp tục` pill filled `--c-ember`.
- Progress: 410x10 track `--c-linen` radius 999 at y=181, label `0% · còn 16/16` 15/20.
- Source line: "Tạo từ tệp PDF này" 13/18 + document title 15/20 medium.
- Unit header: `Trang 1 · Quy trình · đã xong 0/5` 13/18 semibold `--c-ink`;
  unit title 22/28 `Manrope_700Bold`; unit blurb 15/22 `--c-ink2`.
- First lesson card: 656x142, radius 22, white, `shadows.card`, padding 16, gap 4;
  kicker `Học tiếp · 9 phút` 13/18; title 19/24 `Manrope_700Bold`;
  right-aligned CTA text `Bắt đầu bài học` 15/20 semibold.
- Locked lesson rows: 656x74 hit area, radius 16, no surface (transparent),
  title 17/22 medium `--c-ink2`, meta 13/18 `--c-ink3` (`Đã khóa · 8 phút`).
- "Pro" badge: 12/16 medium `--c-ink3` next to the unit eyebrow.
- Footer "Quá dễ? Quá khó?" card: full width 720x80, radius 22, background `--c-bone`,
  padding 16, title 17/22 semibold, body 13/18.

### Lesson player (1440x900)

- Centred reading column width **720 px** (x=360 at 1440), top inset 112.
- Header row at y=16..56: circular back button 40 px at x=284, progress track
  712x10 at y=31, `1/7` 15/20 medium `--c-ink3`, glossary button 40 px at x=1116.
- Eyebrow `Khái niệm 1/3` 13/18 semibold `--c-emberDeep` at y=112.
- Title 34/40 `Manrope_800ExtraBold` at y=138.
- Ordered-step card: 688x42 radius 10 background `--c-wash`, step label 15/20 medium.
- Lede 13/18 `--c-ink3`, then body 19/31 Inter regular `--c-ink2` with inline
  term buttons 19/31 semibold `--c-emberDeep`.
- Citation line 12/16 medium `--c-ink3` (`Trang 1 — Quy trình LUMORA-731`).
- Glossary pill row: pills height 38, radius 999, background `--c-wash`, label 15/20 semibold.
- Bottom action bar pinned at y=824: back circle 48 px `--c-bone`, `Hỏi Pol`
  122x56 `--c-wash`, primary 220x56 filled (`--c-ember` mid-lesson, `--c-emberDeep` at
  the last concept step) with white 17/22 semibold label.
- Summary screen: eyebrow `Trước bài kiểm tra` + 28/34 title; three 720x80 rows
  (radius 16, transparent, hover surface) each with index 15/20 semibold, title
  17/22 semibold, body 15/22 regular; glossary pills below; CTA `Làm bài kiểm tra`.

### Quiz (1440x900)

- Same shell as the lesson: progress `4/7`, eyebrow `Chọn đáp án`, question 28/34.
- Option row: 720x68, radius 16, white surface, 2 px border `--c-linen`,
  16 px horizontal inset for the letter, 17/27 regular answer text.
- Selected option: background `--c-wash`, border `2px solid --c-ember`, letter colour
  becomes white (`#FFF` measured on the selected letter).
- Primary CTA: 220x56, disabled fill `--c-sand` (#CDC1EF) with `rgba(16,16,16,...)`
  text; enabled fill `--c-ember`.
- Correct feedback band: eyebrow colour `--c-mossDeep` (#1F7A68) "Quá chuẩn!",
  body 15/22, CTA 200x56 filled `--c-mossDeep` (#1F7A68) with white label.
- Fill-in-the-blank: sentence 17/27 with 64x34 blank buttons; word bank chips
  54–93 x44, radius 10, white surface, 1 px white border; helper text 13/18 `--c-ink3`
  with a `Xóa` action in `--c-emberDeep`.

### Tutor panel (1440x900)

- Right-side sheet, width ~302 px content with 24 px outer gutter, spanning the full
  height over the reading column; the lesson column re-centres to the left
  (x=160, width 720) when the panel is open.
- Header: `Pol` 19/24 `Manrope_700Bold`, allowance 13/18 `--c-ink3`,
  close button 32 px `--c-bone` at the top-right.
- User bubble: radius 22, background `--c-ember`, white 15/22 text, max width 302.
- Assistant bubble: radius 22, white surface, `shadows.card`, 15/22 `--c-ink`;
  a tool badge line 13/18 `--c-ink2` (`đã đọc tài liệu nguồn`).
- Quick-reply chips: 15/20 semibold `--c-emberDeep`, horizontally scrollable row
  above the composer.
- Composer: 303x50, radius 22, 1 px border `--c-linen`, 15/22 placeholder
  `--c-ink`; send button 48x48 pill `--c-ember`.

### New course (1440x900)

- Same shell; centred column 388 wide (x=658) starting at y=210.
- H1 48/52 `Manrope_800ExtraBold`, lede 17/27 `--c-ink2` (max 380 wide).
- Quota card at y=440: title 19/24 `Manrope_700Bold`, body 15/22,
  CTA 108x48 pill `--c-ember` with 15/20 semibold white label.
- The topic input is present in the DOM under the quota overlay (**INFERENCE**: locked
  tier hides it); its measured metrics came from the same bundle token set.

### Interview + plan (1440x900)

- Top bar centred: back circle 40 px at x=20, course title 17/22 semibold,
  status 13/18 `--c-ink3` (`Kế hoạch học đã sẵn sàng`), progress track 680x6.
- Conversation: alternating 604-wide question cards (white, radius 22, padding 12x16)
  and answer bubbles (background `--c-ember`, white text, radius 22, padding 12x16).
- Plan block: eyebrow 13/18 `--c-emberDeep` `Kế hoạch của bạn`, title 22/28
  `Manrope_700Bold`, blurb 15/22.
- Stat strip: 640x66, radius 16, background `--c-washSoft`; three stats with
  19/24 `Manrope_800ExtraBold` value in `--c-emberDeep` and 12/16 caption `--c-ink3`.
- Outcomes list: bullet-less rows with 15/22 `--c-ink2`, key phrase 15/22 semibold `--c-ink`.
- Primary CTA full width 640x56 pill `--c-ember`.

### Generating (1440x900)

- Centred column, eyebrow 13/18 `--c-emberDeep` (`Khóa học đã sẵn sàng`),
  title 34/40 `Manrope_800ExtraBold` at y=298.
- Four stage rows spaced 61 px apart, each 17/22 semibold `--c-ink` with a left
  indicator; stage names FACT: `Đọc câu trả lời của bạn`,
  `Bổ sung kiến thức nền còn thiếu`, `Phác thảo lộ trình`, `Soạn bài học 1`.
- CTA full width 560x56 `--c-ember` with label `Mở lộ trình`.

### Profile (1440x900)

- Name 34/40 display heavy, meta 13/18 `--c-ink3`.
- Four stat tiles in a row, white surface radius 22 padding 16,
  value 28/32 display, caption 13/18.
- Weekly bar chart card, milestone lists with per-milestone progress and tier chips.
  Not implemented in SopiSkill beyond a compact XP/streak summary.

## Gaps that are API-dependent in SopiSkill

| Reference element | SopiSkill backend support | Decision |
|---|---|---|
| Weekly XP bar chart + 46 milestones | No endpoint | Not rendered; show XP + streak only (already in `/v1/auth/me`) |
| League | No endpoint | Not rendered |
| Per-lesson estimated minutes (`· 9 phút`, `· 4 phút`) | Not in `CourseDetailOut` | Not rendered; would need an additive field (**API GAP**) |
| Unit tone / paywall (`Pro`) | Not in SopiSkill model | Not rendered (**API GAP**) |
| Lesson prefetch (`?prefetch=1`) | Not implemented | Optional later phase |
| Glossary pill row from `terms[]` | Not in `LessonOut` | Rendered only when `terms` exists; otherwise omitted |
| Per-question feedback band (explanation after each question) | Grading is a single batch call over the whole lesson | Not rendered; one submit at the end (**API GAP**) |
| Lesson type tag, lock state, unit ordering, offline save, vocabulary list, lesson summary sheet | Not in `LessonOut` | Not rendered (**API GAP**) |
| Seven-step lesson structure (`1/7` … `7/7`) | SopiSkill lessons ship six blocks | Counter reflects the real block count (`1/6` … `6/6`) |

## Implemented lesson player — measured state (2026-11-04)

The player was rebuilt as a **step-based** view: one block visible at a time, with the
counter and progress bar reflecting position in `blocks[]`. Verified live against
`/lesson/lsn_21f2cf0f-56ea-4632-a5da-bee35502dc3d`, which carries all six block types in
order: `teach`, `mc`, `blank`, `order`, `match`, `short`.

**Chrome.** Both chrome bands are fixed, not sticky: cream above (`y=0..63`) and below
(`y=804..899`) with the paper reading band between them (`y=64..802`, `#f1ecfd`). At 390 the
whole frame is cream with a single linen hairline at `y=763`.

**Lesson header at 1440.** The row deliberately overhangs the 720 px text column, matching
the reference:

| Element | x | width |
|---|---|---|
| Row | 285 | 872 |
| Close button | 300 | 40 |
| Progress track | 345 | 708 |
| Counter `1/6` | 1074 | ~20 |
| Outline button | 1130 | 40 |

Implemented as `width: calc(100% + 152px); margin-left: -75px` behind
`@media (min-width: 1024px)`. Residual vs. reference is 1–4 px and is font-metric drift.

**Block renderers.** `mc` → `.quiz-option` rows with `.option-letter` chips; `blank` →
`.blank-label` + a text input; `order` → `.order-item` rows with `.btn-icon` move controls
and `.summary-index`; `match` → `.match-row` with a `<select>` per left item; `short` →
`.blank-label` + input; `teach` → `.block-eyebrow` / `.block-title` / `.block-body` plus a
`.notice-box` provenance line.

**Outline sheet.** Opens from the header book button into a 380 px right-side sheet
(`x=1060`..`1440`), lists all six blocks with their type label and **public prompt only**,
marks the current step with `aria-current="step"`, closes on select, `Escape`, or backdrop
click, and jumps to the chosen step. Because it reads only `block.type` and the public
prompt, it cannot leak an answer key.

**Submit.** Exactly one submit at the end — per the backend contract
(`grade_attempt` grades the whole lesson in one batch), so per-question grading is not
possible. A fully correct run lands on the `.lesson-result` state with a `--moss-wash`
perfect band.

**Known divergence.** The disabled-state primary CTA uses `--sand` with `--ink-2` text,
which differs from the reference's disabled treatment; contrast still passes (see
`accessibility-review.md`).

---

## Complete Route & Sheet Map — Craft Anything `0.6.1` Addendum (2026-11-22, `OBSERVED_STATIC`)

Unpacking Metro module `M9` (Expo Router context) and `M1808` (`./_layout.tsx`) from
`entry-a3803cab42a2ab75ae9ef2e391ee92d0.js` (`ev_3025…`) gives the **complete** screen inventory
of PolySkill (15 production routes + 5 global sheets) compared against SopiSkill's actual
Next.js App Router pages (`frontend/src/app/**/page.tsx`):

| PolySkill Route (`M9`) | Purpose | SopiSkill Equivalent | Status |
|---|---|---|---|
| `./_layout.tsx` (`M1808`) | Root auth guard, sync, push router, `OfflineBar`, 5 global sheets | `layout.tsx` + `providers.tsx` | Partial (no push/offline sync/global sheets) |
| `./index.tsx` (`M1869`) | Redirect to `/onboarding` or `/(tabs)/home` | `page.tsx` (dashboard directly) | Different (no onboarding gate) |
| `./sign-in.tsx` (`M2181`) | Apple + Google OAuth only | `login/page.tsx` (email/password) | Different by design |
| `./onboarding.tsx` (`M2170`) | 5-step onboarding (`Hello → Language → 4 Questions → Reminder → Done`) | — | **Not in SopiSkill** |
| `./(tabs)/_layout.tsx` (`M10`) | Desktop `SideNav` (`264px`) + mobile 5-tab bar (`Home/Learn/New/Pol/You`) | App shell components | Implemented (without `Pol`/`You` mobile tabs) |
| `./(tabs)/home.tsx` (`M1757`) | Greeting, `upNext` hero, active/completed courses, `WeekRecapCard`, streak nudges | `page.tsx` | Partial (no week recap/streak nudges) |
| `./(tabs)/new.tsx` (`M1798`) | Topic input + `AddSourceMenu` (`pdf`/`arxiv`/`url`) + course quota gate | `new/page.tsx` + `sources/page.tsx` | Partial (split across `/new` and `/sources`) |
| `./(tabs)/course/[id].tsx` (`M1651`) | Units (`ember`/`bone`), `CourseSourceRow`, node states, `Pro` lock, `Too easy?` Pol card | `course/[courseId]/page.tsx` | Partial (no unit tone/paywall/`preparing` poll/`path_harder` card) |
| `./(tabs)/profile.tsx` (`M1807`) | Stats, `WeekChart`, 7-category `Milestones`, `LeagueCard`, settings | `profile/page.tsx` + `settings/page.tsx` | Partial (4 real stat tiles from `/v1/me/stats`, courses grid, `ListGroup` shortcuts; no weekly chart/milestones/league) |
| `./league/index.tsx` (`M1870`) | 30-user cohort leaderboard, 5 tiers (`leagues` flag currently `false` on web) | — | **Not in SopiSkill** (disabled on ref web too) |
| `./lesson/[id]/index.tsx` (`M2121`) | `ReelPlayer` intro + 6 block types + 5 formats (`SpeedRound`, `StepsQuestion`, `ShortQuestion` + `SelfMarkFooter`/dispute) + `RecapView` + `VocabSheet` | `lesson/[lessonId]/page.tsx` | Partial (6 blocks implemented; no Reel, `SpeedRound`, `RecapView`, `VocabSheet`, per-block short grading) |
| `./lesson/[id]/complete.tsx` (`M1871`) | Optimistic/settled rewards, streak/freeze/milestones, `UnitBreakdown`, `Confetti` | Inline `.lesson-result` in `lesson/[lessonId]/page.tsx` | Partial (no dedicated route, milestones, or `UnitBreakdown`) |
| `./new/source.tsx` (`M2169`) | Source ingest polling (`1.5s`), `SourceCard`, structured `brief` preview | `sources/page.tsx` | Different flow (separate source management page) |
| `./new/interview.tsx` (`M2162`) | 5-question interview (`single`/`multi` chips) + `PlanChat` (`revise_proposal`) + `ProposalCard` | `new/interview/page.tsx` + `new/proposal/page.tsx` | Partial (split into 2 routes; textarea instead of chips; no `PlanChat` revision) |
| `./new/generating.tsx` (`M2161`) | 4-step generation progress (`2s` poll) + retry | `new/generating/page.tsx` | Implemented |
| *SopiSkill-only:* `review/page.tsx` | FSRS spaced-repetition review queue (P5.0) | `review/page.tsx` | SopiSkill extension (not in PolySkill) |

**5 Global Sheets mounted in PolySkill (`M1808`):** `TutorSheet` (slide-over rail + conversation history + course switcher), `SettingsSheet` (display name, `appLanguage`/`lessonLanguage`, theme, plan, notifications/reminder picker, linked identities, delete account), `AvatarSheet` (5 avatars), `PaywallSheet` (Polar Card + SePay VietQR), `LinkAccountSheet` (`ACCOUNT_LINK_REQUIRED` challenge).
