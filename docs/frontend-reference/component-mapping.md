# Component mapping — reference element → SopiSkill component

Corrected 2026-11-04 against the actual tree. An earlier revision of this file listed a
fine-grained component split (`components/course/*`, `components/quiz/*`, `components/tutor/*`,
`components/lesson/*`) that was **planned but never built**. Only the files listed below
exist; the learning screens are implemented inline in their route files. This document now
records reality, not the plan.

Inventory rule: anything listed here must exist on disk. Anything that does not is either
marked *(planned, not built)* or removed.

## Foundation (UI-1)

| SopiSkill file | Replaces | Purpose |
|---|---|---|
| `frontend/src/app/globals.css` | the old 425-line stylesheet | Token layer + page/block styles. ~3 700 lines. Keeps `.sr-only`, `:focus-visible` ring, `prefers-reduced-motion` |
| `frontend/src/app/fonts.css` | `next/font/google` | 21 self-hosted `@font-face` rules (Manrope 700/800, Inter 400/500/600, JetBrains Mono 400/500) with Google's `unicode-range` split preserved; declares the `--font-*` custom properties |
| `frontend/public/fonts/*.woff2` | — | 21 files, 644 KB total |
| `frontend/src/components/ui/Button.tsx` | inline `<button>` usages | Variants primary/dark/secondary/ghost/success/wrong/text/danger; sizes lg/md/sm; loading + block |
| `frontend/src/components/ui/Card.tsx` | `.card` | Variants default/raised/tint/accent/hero/dark/dashed/correct/wrong |
| `frontend/src/components/ui/Field.tsx` | `.auth-form` inputs | Labelled input/textarea with error + hint slots |
| `frontend/src/components/ui/Badge.tsx` | `.badge` | Neutral/accent/success/warn/lock tones |
| `frontend/src/components/ui/Progress.tsx` | inline tracks | Exports **both** `ProgressBar` (10 px track, pill radius, ember fill) and `ProgressRing` (52/22 px SVG ring) |
| `frontend/src/components/ui/Skeleton.tsx` | ad-hoc "Đang tải…" | Layout-stable loading blocks |
| `frontend/src/components/ui/Icon.tsx` | inline SVG | Typed `IconName` union, single sprite |
| `frontend/src/components/ui/useModalPanel.ts` | ad-hoc Escape handlers in tutor + outline sheets | Modal contract for an overlay panel: `Escape` close, Tab/Shift+Tab wrap, initial-focus target, background `inert` sweep, focus restoration to the opener. Holds `onClose` in a ref so an inline-arrow prop does not re-run the trap each render |

## Shell (UI-2)

| SopiSkill file | Purpose |
|---|---|
| `frontend/src/components/layout/AppFrame.tsx` | The whole shell in one file: desktop side nav (264 px), mobile bottom bar, content column (max 1040, pad 48/48/72), `<main>` landmark. Skipped for focus mode (`/lesson/*`) and auth |
| `frontend/src/components/layout/TabBar.tsx` | Bottom tab bar, 50 px, active ember tint. Four cells — SopiSkill has no tutor tab |
| `frontend/src/components/layout/ThemeToggle.tsx` | Sáng / Hệ thống / Tối segmented switch |
| `frontend/src/components/layout/ThemeProvider.tsx` | Applies `data-theme` on `document.documentElement`; `STORAGE_KEY = "sopiskill.theme"` |

*(planned, not built: `SideNav.tsx`, `PageHeader.tsx`, `AppShell.tsx` — their roles live
inside `AppFrame.tsx`.)*

## Dashboard + auth (UI-2)

| SopiSkill file | Purpose |
|---|---|
| `frontend/src/app/page.tsx` | Landing when anonymous; greeting + resume hero + course cards when signed in. 212 lines |
| `frontend/src/components/landing/LandingPage.tsx` | Anonymous landing surface |
| `frontend/src/app/login/page.tsx` | Email/password form in a centred auth panel. Same API calls as before |

*(planned, not built: `ResumeHero.tsx`, `CourseCard.tsx` — rendered inside `page.tsx`.)*

## Creation flow (UI-3)

| SopiSkill file | Purpose |
|---|---|
| `frontend/src/app/new/page.tsx` | Topic form, centred column, chips |
| `frontend/src/app/new/interview/page.tsx` | Transcript + progress; textarea answers (GAP-04), 5-question flow, reload resume |
| `frontend/src/app/new/proposal/page.tsx` | Plan card, stat strip, outcomes, unit list, approve CTA |
| `frontend/src/app/new/generating/page.tsx` | 4-stage list with live status, retry, cost line |

*(planned, not built: `InterviewBubble.tsx`, `PlanStats.tsx`, `StageList.tsx`.)*

## Learning (UI-4)

| SopiSkill file | Purpose |
|---|---|
| `frontend/src/app/course/[courseId]/page.tsx` | Hero progress header, unit sections, lesson rows, sources, mastery/path blocks. 423 lines |
| `frontend/src/app/lesson/[lessonId]/page.tsx` | **Step-based player**, 810 lines. Holds the header, all six block renderers (`teach`, `mc`, `blank`, `order`, `match`, `short`), the outline sheet, the result state, and the bottom action bar |
| `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx` | Right-side sheet; keeps streaming, stop, citations, quota, thread history. 554 lines |

*(planned, not built: `LessonHeader.tsx`, `BlockFrame.tsx`, `TeachBlock.tsx`, `BottomBar.tsx`,
`OptionRow.tsx`, `BlankBlock.tsx`, `OrderBlock.tsx`, `MatchBlock.tsx`, `ShortBlock.tsx`,
`FeedbackBand.tsx`, `ResultSummary.tsx`.)*

**Correction to the old plan:** `FeedbackBand.tsx` was planned for per-question feedback, but
the backend grades a whole lesson in one batch (`grade_attempt`), so per-question bands are
contractually impossible — see GAP-11. The result state lives at the end of the lesson
instead.

## Tutor (UI-5)

The tutor UI is all inside `TutorPanel.tsx`; the planned `TutorSheet.tsx`,
`MessageBubble.tsx` and `Composer.tsx` were **not** built as separate files.

## Not mapped (deliberately)

| Reference element | Reason |
|---|---|
| League, milestones, weekly chart on `/profile` | No backend contract (GAP-03) |
| OAuth providers | SopiSkill auth is email/password |
| Paywall, billing | Out of scope for this task |
| Mascot / logo assets | Brand assets must not be copied (D-01) |
| Per-lesson duration, unit tone, paywall flags, lock state | API GAP; requires additive backend fields (GAP-01, GAP-02, GAP-12) |
| Offline save, vocabulary list, lesson summary sheet | API GAP (GAP-13, GAP-14) |
