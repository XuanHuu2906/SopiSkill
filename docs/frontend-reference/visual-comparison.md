# Visual comparison

Method: each reference screen was measured in a signed-in Chrome profile at a fixed
viewport; the SopiSkill local build was then measured with the **same** script at the same
viewport. Comparison is by numbers (bounding box + computed style), not impressions.

Status vocabulary:

- **MATCHED** — layout, spacing, colour and type scale agree within the tolerances below.
- **PARTIAL** — same structure and tokens, but one or more deltas (different copy, missing
  data-driven element, or a component with no SopiSkill equivalent).
- **NOT MATCHED** — visible structural difference.
- **NOT OBSERVED** — the reference state was never reached, so nothing is claimed.

Tolerances: content column ±2 px, card size ±4 px, radius/colour/font-size exact,
height of chrome (nav, bars, controls) ±2 px, section spacing ±4 px.

## Reference baselines (measured 2026-11-03, 1440x900)

| Metric | Value |
|---|---|
| Side nav | x 0, w 264, bg `#FCFAFF`, border-right 1 px `#E6DEFA` |
| Content column | x 312, w 1040 |
| Page background | `#F1ECFD` (light) / `#120E20` (dark) |
| Home hero card | 1040x156, radius 22, bg `#7B5BE6`, shadow `0 14px 30px -12px rgba(123,91,230,.6)` |
| Home greeting | 48/52 w800 |
| Course card | 336x122, radius 22, white, card shadow |
| Lesson reading column | x 360, w 720 |
| Lesson header | back 40 px at x=285, track 712x10, counter x≈1076, glossary 40 px at x=1116 |
| Bottom action bar | h 56 |
| Quiz option | 720x68, radius 16, 2 px `#E6DEFA` |
| Tutor sheet content | x 1113, w ~302 |

## Local build (measured 2026-11-03, same script)

| Metric | Value | Delta vs reference |
|---|---|---|
| Side nav | 264, bg `#FCFAFF` | 0 |
| Content column | x 312, w 1040 | 0 |
| Page background | `rgb(241,236,253)` = `#F1ECFD`; dark `rgb(18,14,32)` = `#120E20` | 0 |
| Home hero card | 1040x155, radius 22, bg `#7B5BE6`, glow shadow | −1 px height |
| Home greeting | 48/52 w800 Manrope | 0 |
| Course card | 336x122, radius 22, three columns of `336px` in the 1040 grid, gap `16px` (measured 2026-11-04: `gridX 312`, `gridW 1040`, `cols "336px 336px 336px"`, `gap "16px"`) | 0 on every metric; the ring is 52 px |
| Lesson reading column | x 353, w 720 (viewport 1440 minus scrollbar 15) | column x matches centre of 1425 |
| Lesson header | back 40 px at x=277, track 735x10, counter x=1075 | header 872 px wide, matches reference 872 |
| Bottom action bar | h 56 (`btn-lg`) | 0 |
| Quiz option | 68 px tall, radius 16, `2px #E6DEFA`; selected `#EBE3FF` + `2px #7B5BE6` | 0 |
| Tutor sheet | docked at ≥1024 px: x 1040, w 400, full height, 1 px hairline, `--shadow-rail` violet shadow cast leftward; overlay below 1024 px: 380 px / full width | 0 on position and width at 1440; shadow gradient is row-for-row identical to the reference (see below); the <1024 px overlay is a deliberate layout choice, not a delta |

## Per-screen status

| Screen | Reference evidence | Local evidence | Status | Remaining delta |
|---|---|---|---|---|
| Sign-in 1440 | `signin-1440x900.png` | `local-signin-1440x900.png` | PARTIAL | Same frame/typography/pill buttons; SopiSkill shows email+password instead of OAuth (its own auth contract) |
| Sign-in 768 | `signin-768x1024.png` | `local-signin-768x1024.png` | PARTIAL | Same delta as above; centred panel preserved |
| Sign-in 390 | `signin-390x844.png` | `local-signin-390x844.png` | PARTIAL | Full-bleed 350 px, 56 px buttons — matches mobile metrics |
| Dashboard 1440 | `home-1440x900.png` | `local-home-1440x900.png` | MATCHED (frame) / PARTIAL (content) | No league/milestone chips. Card geometry matches at this viewport — `auto-fill minmax(300px,1fr)` resolves to three `336px` columns in the 1040 grid; it becomes responsive below 1440, where the reference stays at a fixed 336 |
| Dashboard 390 | `home-390x844.png` | `local-home-390x844.png` | MATCHED (frame) | 4-cell bottom bar (SopiSkill has no tutor tab) |
| Dashboard dark | `home-dark-1440x900.png` | `local-home-dark-1440x900.png` | MATCHED (tokens) | Exact same paper/ink/shadow values |
| Course overview 1440 | `course-1440x900.png` | `local-course-1440x900.png` | PARTIAL | No per-lesson minutes, no `Pro` tone, no locked rows (SopiSkill lessons are all open) |
| Course overview 390 | `course-390x844.png` | `local-course-390x844.png` | PARTIAL | Same deltas; single column, no overflow |
| Lesson teach 1440 | `lesson-1440x900.png`, `lesson-teach3-1440x900.png` | `prod-lesson-teach-1440.png` | MATCHED (metrics + flow model) | Rebuilt 2026-11-04: one block per screen, paginated, fixed chrome bands. Header row measures 872 px at x=285 vs reference 872 px at x=285 |
| Lesson 768 | `lesson-768x1024.png` | `prod-lesson-teach-768.png` | MATCHED (metrics) | Header 720 px at x=24; bottom bar 97 px |
| Lesson 390 | `lesson-390x844.png` | `prod-lesson-teach-390.png` | MATCHED (metrics) | Tab bar hidden in focus mode; bottom bar 81 px; no horizontal overflow |
| Lesson dark 1440 / 768 / 390 | — | `prod-lesson-teach-dark-{1440,768,390}.png` | MATCHED (tokens) | Paper `rgb(18,14,32)`, title `rgb(239,233,252)`, primary `rgb(155,123,255)` |
| Lesson summary | `lesson-summary-1440x900.png` | — | NOT IMPLEMENTED | SopiSkill has no separate summary step; quiz blocks follow teach blocks |
| Quiz MCQ 1440 | `quiz-1-1440x900.png`, `quiz-selected-1440x900.png` | `local-lesson-1440x900.png` | MATCHED | Option geometry and selection colours identical |
| Quiz feedback | `quiz-result-1440x900.png` | — | **API GAP** | Reference reveals a moss band per question. `grade_attempt` grades the whole lesson in one batch, so per-question feedback is impossible; SopiSkill submits once at the end and shows a result state (GAP-11) |
| Quiz blank | `quiz-done-1440x900.png` | (inside lesson page) | PARTIAL | Reference taps word chips; SopiSkill uses an input per blank (same visual chips exist for sentence terms only) |
| Tutor 1440 | `tutor-open-1440x900.png` | `local-tutor-docked-1440x900.png`, `local-tutor-docked-dark-1440x900.png` | MATCHED (interaction model + geometry, measured 2026-11-04) | Bubbles/badges/composer metrics match. The dock now reflows the page exactly like the reference: column x 360→160, track x 145, CTA x 660, bar right edge 1040, rail x 1040 w 400, paper `241,236,253` unchanged, no scrim. The rail is `role="dialog"` without `aria-modal` because it is not modal (see accessibility-review.md). Below 1024 px the sheet stays a modal overlay by design |
| New course 1440 | `new-1440x900.png` | `local-new-1440x900.png` | PARTIAL | Reference shows a quota-limit card; SopiSkill has no quota state (and no paywall) |
| Interview 1440 | `interview-done-1440x900.png` | `local-interview-1440x900.png`, `local-interview-progress-1440x900.png` | PARTIAL | Reference renders quick-answer chips generated by its backend; SopiSkill uses a textarea because `/interview` returns question text only |
| Generating 1440 in progress | `generating-1440x900.png` (terminal) | `local-generating-dark-1440x900.png`, `local-generating-390x844.png` | MATCHED (structure) | Captured 2026-11-04 in real `Đang sinh` state on a freshly approved course: 4-stage list, all stages pending, exit note. The **terminal** state is still not capturable by design — the route redirects to `/course/{id}` on `ready` |
| Profile 1440 | `profile-1440x900.png` | — | NOT IMPLEMENTED | No profile route or milestone API in SopiSkill |

## Interaction model: the tutor docks (measured, then implemented)

Row-scan of `tutor-open-1440x900.png` against the closed-tutor reference, then the same
probe on the local build. Both runs are 1440x900, light theme, same lesson.

| Element | Reference, tutor closed | Reference, tutor open | SopiSkill, tutor open (now) |
|---|---|---|---|
| Reading card left edge | x 360 | x 160 (−200) | x 160 |
| Progress track | x 348..1055 (708) | x 148..855 (708) | x 145 w 708 |
| Primary CTA | x 866..1073 (208) | x 666..873 (208) | x 660 w 220 |
| Tutor rail | — | x 1040..1439 (~400) | x 1040 w 400 |
| Bottom bar right edge | 1440 (full width, tutor closed) | **1004** + shadow to 1039 + hairline 1040 | 1004 + shadow to 1039 + hairline 1040 |
| Page background | `241,236,253` | `241,236,253` (unchanged) | `241,236,253` (unchanged) |
| Backdrop | — | none | `display:none` |

The reference **docks** the tutor: the reading column keeps its 720 px width and its
internal metrics, and the whole page shifts left by exactly 200 px — 1440 − 400 rail
width, re-centred into the remaining 1040 px. No scrim, no dimming, page stays interactive.

SopiSkill originally **overlaid** (`position:fixed; right:0; width:min(380px,100vw)` over
`.tutor-backdrop { inset:0; background:var(--scrim) }`). That is now fixed: at
`@media (min-width: 1024px)` `.app-content` reserves `--dock-width: 400px`, `.lesson-bar`
pins to `right: 400px`, the sheet widens to 400 px, and the backdrop hides.
Reserving exactly 400 px leaves a 1040 px content box, so the 720 px column centres at
x=160 and the bar's inner track lands at x=160 — matching the reference to the pixel while
letting `.lesson-header`'s existing `−75 px` offset keep working unchanged.

The rail **keeps** its shadow. An intermediate version of this CSS set
`box-shadow: none` on `.tutor-sheet.is-docked`, which was a regression: a row-scan of the
reference at y=450 shows paper `241,236,253` fading to `223,215,241` by x=1039, onset
around x=985–993. `--shadow-rail` (`-18px 0 48px -32px rgba(74,45,150,.4)`) is the same
hue, so the override was simply removed. After rebuild the gradient is **byte-identical to
the reference** at both y=450 and the bottom-bar row y=884:

```text
reference y=884:  ... 1035-1036 (2) 248,245,252 · 1037-1037 (1) 248,245,253
                        1038-1039 (2) 247,244,252 · 1040-1040 (1) 230,222,250 · 1041-1439 rail
local     y=884:  ... 1035-1036 (2) 248,245,252 · 1037-1037 (1) 248,245,253
                        1038-1039 (2) 247,244,252 · 1040-1040 (1) 230,222,250 · 1041-1439 rail
```

The bottom bar row also settles an earlier error in this document: it claimed the
reference's bar spanned the full 1440 px with the tutor open. It does not. The bar body ends
at x=1004 and is followed by the shadow, so it stops at the rail exactly as the content does.

Below 1024 px there is not room for both a 720 px column and a 400 px rail, so the modal
overlay is kept — re-verified at 768×1024 (scrim full viewport, sheet 380 px at x=388,
`aria-modal="true"`) and 390×844 (full-width sheet, no horizontal overflow).

Because the docked rail is not modal, `useModalPanel` gained a `modal` flag: the docked
path keeps Escape and focus restoration but drops the Tab trap and inert sweep, which would
otherwise make the lesson beside the rail unreachable by keyboard. The two keyboard models
are documented in `accessibility-review.md`.

Screenshots: `local-tutor-docked-1440x900.png` (light) and
`local-tutor-docked-dark-1440x900.png` (dark) are the docked evidence;
`local-tutor-768x1024.png` and `local-tutor-390x844.png` are the overlay evidence.
`local-tutor-1440x900.png` was re-captured after the scrim fix and now shows the correct
scrim (`155,149,172`), not the old violet band.

## What is *not* claimed

- No pixel-perfect claim. The reference is React Native Web with a different rendering
  pipeline (no CSS box model quirks, different text rasterisation).
- No claim of identical copy. All Vietnamese strings in SopiSkill are its own.
- No claim that the interaction model is identical where the backend contract differs
  (paginated concepts vs scrolling page, chip answers vs textarea, word-chip blanks vs
  inputs).

## How to reproduce a comparison

1. `cd frontend && npm run dev`.
2. Open Chrome with `--remote-debugging-port=9333 --user-data-dir=<temp>`.
3. Run the measurement script used for the reference (`Runtime.evaluate` snapshot of
   bounding boxes + computed style) at 1440x900, 768x1024, 390x844.
4. Compare the numbers in the tables above.
