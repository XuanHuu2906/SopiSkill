# Implementation checklist

Each item is only ticked after it is implemented **and** verified. Commands are listed
next to the phase so the verification is reproducible.

## Phase UI-0 — Evidence (done)

- [x] Repo audit: branch `feat/p6.0-ci-pipeline`, HEAD before work, clean tree
- [x] REA CLI verified (`rea --version` → 6.7.0), CDP at `127.0.0.1:9222`
- [x] Design tokens extracted from the live page + bundle constant tables
- [x] 14 screen states captured with DOM + computed style at 1440/768/390
- [x] Screen inventory, interaction map, component mapping documented
- [x] API gaps listed rather than invented

## Phase UI-1 — Design foundation

- [x] `globals.css` replaced with token layer (colour light/dark, type scale, space,
      radius, shadow, motion) + primitives
- [x] `next/font` loads Manrope 700/800 and Inter 400/500/600
- [x] `data-theme` switching with `sopiskill.theme` persistence
- [x] Button / Card / Field / Badge / ProgressBar / Skeleton components
- [x] Focus-visible ring, `sr-only`, reduced-motion preserved
- [x] Verify: `npm run typecheck`, `npm run lint`, `npm run build`

## Phase UI-2 — Shell, auth, dashboard

- [x] `AppFrame` (side nav 264 / bottom bar 50 / content 1040)
- [x] Login page restyled; auth logic, CSRF, redirect untouched
- [x] Dashboard: greeting, resume hero, course cards, empty/loading/error
- [x] Theme toggle
- [x] Verify: typecheck, lint, build, local capture at 1440/768/390

## Phase UI-3 — Course creation

- [x] `/new` topic screen
- [x] `/new/interview` transcript + 5-question flow + reload resume preserved
- [x] `/new/proposal` plan card, stats, units, approve
- [x] `/new/generating` 4-stage list, polling guard and retry preserved
- [x] Verify: typecheck, lint, build

## Phase UI-4 — Learning experience

- [x] `/course/[courseId]` hero progress, unit sections, lesson rows, sources,
      mastery and learning-path blocks
- [x] `/lesson/[lessonId]` reading column, header, teach blocks, citation line
- [x] Quiz: MC / blank / order / match / short with keyboard support
- [x] Feedback band, result summary
- [x] `clientAttemptId` stability and server grading untouched
- [x] Verify: typecheck, lint, build

## Phase UI-6 — `/review` and `/sources` restyled

- [x] `/review`: page header (eyebrow + `page-title`), `Card`, `Badge`, `Button` rating
      controls, `Skeleton` loading, `role="alert"` errors. Review logic untouched.
- [x] `/sources`: header, `Card` sections, `TextInput` with bound labels, `Badge` status,
      `Button`, `Skeleton`; `.source-item` / `.web-ingest` styles added. All mutations,
      polling and session-scope invalidation untouched.
- [x] Fixed: source inputs rendered with browser default styling (`input` had no `type`,
      so `input[type="text"]` never matched) and stretched to 260 px tall by a `flex` style
      applied inside the flex-column `.field`. Now 53 px tall, radius 16, border `#E6DEFA`.
- [x] Verify: `npx tsc --noEmit`, `npm run lint`, `npm run build` all exit 0;
      screenshots at 1440 and 768.

## Phase UI-5 — Tutor

- [x] Right-side sheet with backdrop and Escape-to-close
- [x] Message bubbles, tool badges, citations block
- [x] Composer with send + stop; streaming caret
- [x] Quota and thread history preserved
- [x] Verify: typecheck, lint, build

## Phase UI-7 — Accessibility and audit closure (2026-11-03)

- [x] Contrast: `--ink-3` retuned to `#645c81` (light) / `#9f94c5` (dark) — previously
      3.12–3.61:1 and 4.09–4.46:1; now ≥4.78:1 and ≥4.98:1 across all surface tokens
- [x] Removed `opacity` dimming from `.hero-card .hero-kicker` / `.hero-step` / `.eyebrow`
      (axe measured 4.23:1 and 3.36:1 white-on-ember)
- [x] `/login` wrapped in `<main>` (axe: `landmark-one-main`, `region`)
- [x] Heading order fixed on `/new`, `/new/proposal`, `/new/interview`; missing-`courseId`
      states on interview and proposal now render an `H1` + recovery button
- [x] `.profile-box h3` → `.profile-box h2` to match the promoted heading
- [x] Verify: `npx tsc --noEmit` exit 0, `npm run lint` exit 0, axe 0 violations

## Cross-cutting gates

- [x] No answer key, token, or private data in DOM before submit (scanned)
- [x] Logout → login as a different user does not surface the previous user's cache
      (`local-home-user2-1440x900.json`: `leakedUser1=false`, `leakedCourse1=false`)
- [x] Responsive with no horizontal overflow on **9 routes × 3 viewports = 27 combinations**
      (1440×900, 768×1024, 390×844), measured with `scrollWidth == clientWidth`.
      200 % zoom (720×450 CSS viewport) also clean on `/`, `/course`, `/lesson`, `/new`,
      `/review`, `/sources`.
- [x] Keyboard: all 9 routes audited — 0 unnamed controls, 100 % tab-reachable,
      0 negative `tabindex`, 0 `input` without `type`, 0 `img` without `alt`
- [x] Heading hierarchy on all 9 routes starts at `H1` with no skipped levels
- [x] axe-core `axe.run(document)` — **0 violations** on all 9 routes, light **and** dark
- [x] `docs/development-progress.md` updated without deleting history

## Privacy

- [x] Owner display name redacted from JSON/Markdown evidence and from the PNGs
      (`docs/frontend-reference/evidence-register.md#privacy-redaction`)
- [x] No cookie, token, email or private page body stored

## Phase UI-8 — Overlay modal contract (2026-11-04)

- [x] `useModalPanel` hook extracted; owns Escape, Tab/Shift+Tab wrap, initial focus,
      `inert` background sweep, and focus restoration
- [x] Tutor sheet: `role="dialog"`, `aria-modal="true"`, `aria-labelledby="tutor-heading"`,
      initial focus `#tutor-input`
- [x] Outline sheet: same semantics, initial focus `.outline-item.is-active`
- [x] `onClose` held in a ref so an inline-arrow prop does not re-run the trap each render
- [x] Verify: Tab cycle stays inside both sheets (7 stops for outline, measured with native
      CDP key events); 14/15 background elements inert while open; programmatic background
      focus blocked; `[inert]` count 0 after close; focus restored to the exact trigger
- [x] Verify: axe-core 0 violations on the lesson page with each sheet open
- [x] Verify: `npx tsc --noEmit`, `npm run lint`, `npm run build` all exit 0

## Not done (honest)

- [ ] Playwright E2E suite (no Playwright in the project; not added)
- [ ] Backend `pytest` rerun (backend untouched this session)
- [ ] Screen-reader (NVDA/VoiceOver) smoke test

Done since this list was first written: self-hosted fonts (21 faces, 644 KB, no build-time
network), the tutor/outline sheet focus trap + `aria-modal` verification (above), and the
final screenshot gaps — dark `/login`, dark + 390 for `/new/interview` and `/new/proposal`,
and a real in-progress `/new/generating` at dark 1440 and 390 light (2026-11-04).

Corrected 2026-11-03 — these were previously listed as outstanding but are already true:

- `/review` and `/sources` both import `Button`, `Badge`, `Card`, `Skeleton`, `TextInput`
  and render on the new design system.
- Colour contrast is measured (axe-core, 0 failures, both themes); 200 % zoom is measured;
  all 9 routes have keyboard/naming/heading results.
- 768×1024 and 390×844 captures now exist for every route. `/new/generating` is only
  capturable in its non-terminal `Đang sinh` state: the route redirects to `/course/{id}`
  the moment generation reports `ready`.
