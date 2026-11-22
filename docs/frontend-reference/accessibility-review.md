# Accessibility review

Scope: the SopiSkill build in this working tree. Method is static inspection of the shipped
code plus live DOM probes and an **axe-core run** over nine routes. Anything not measured is
labelled **NOT MEASURED** rather than assumed.

Re-verified 2026-11-03 against the running dev server at `localhost:3000`, Chrome CDP
`127.0.0.1:9222`, axe-core injected from `frontend/node_modules/axe-core/axe.min.js`.

## Checks performed

| Area | Check | Result | Evidence |
|---|---|---|---|
| Automated audit | axe-core `axe.run(document)` over 9 routes, light **and** dark | **PASS (0 violations)** | see "Automated audit" below |
| Colour contrast | every text node on every audited route, computed by axe | **PASS (0 failures)** | same run; token-level check also clean |
| Focus visibility | `:focus-visible` ring declared | **PASS** | `globals.css`; live probe reported `outline: 3px` |
| Landmark structure | `<nav aria-label="Điều hướng chính">` + `<main>` on every route incl. `/login` | **PASS** | `components/layout/AppFrame.tsx` |
| Current-page state | `aria-current="page"` on active nav row | **PASS** | `AppFrame.tsx:85` |
| Screen-reader-only text | `.sr-only` utility present and used | **PASS** | `globals.css`, interview label |
| Reduced motion | `prefers-reduced-motion` block | **PASS** | `globals.css` |
| Form labels | `label[htmlFor]` bound to input `id`; `aria-invalid` on error | **PASS** | `components/ui/Field.tsx:26,48,68` |
| Progress semantics | `role="progressbar"` on bar and ring | **PASS** | `components/ui/Progress.tsx:16,48` |
| Live streaming region | `role="log" aria-live="polite" aria-relevant="additions text"` | **PASS** | `lesson/[lessonId]/TutorPanel.tsx:414` |
| Named controls | 9 routes: 0 unnamed, 100 % tab-reachable, 0 negative tabindex | **PASS** | live probe, table below |
| Heading hierarchy | every route starts at `H1`, no skipped levels | **PASS** | live probe, table below |
| Keyboard for drag-like quiz (order/match) | move controls provided; no pointer-only path | **PASS by inspection** | `lesson/[lessonId]/page.tsx` order/match renderers |
| Horizontal overflow | 9 routes × 3 viewports = 27 combos, `scrollWidth == clientWidth` | **PASS** | measured, see below |
| Zoom / 200 % | 720×450 CSS viewport (1440×900 @ 200 %) on 6 routes | **PASS** | no horizontal overflow, no offenders |
| Modal/sheet keyboard model | two paths: overlay (< 1024 px + outline sheet) has `aria-modal`, Tab wrap, `inert`; docked tutor (≥ 1024 px) is non-modal and lets Tab leave the rail | **PASS** | live probe, see "Sheet keyboard model" below |
| Sheet ARIA host | both sheets are `<div role="dialog">`; `<aside>` would be an invalid override | **PASS (fixed 2026-11-04)** | axe re-run, 5 surfaces, see below |
| Screen-reader pass | no NVDA/VoiceOver run | **NOT MEASURED** | — |

## Automated audit

`axe.run(document)` on nine routes, once in light and once with `data-theme="dark"`:

```text
/            0 violations   /new        0 violations
/login       0 violations   /interview  0 violations
/course      0 violations   /proposal   0 violations
/lesson      0 violations   /review     0 violations
                            /sources    0 violations

light: 0 · dark: 0
```

Two real defects were found by this run and fixed before it went green:

1. **`color-contrast` on `/` — `.hero-kicker` (4.23:1) and `.hero-step` (3.36:1).**
   Both sat on `.hero-card` (`--ember: #7b5be6`) and were dimmed with `opacity`
   (0.92 / 0.75). Compositing white onto ember produced `#f4f2fd` and `#ded6f9`, both below
   the 4.5:1 floor. Fixed by removing the opacity from `.hero-card .eyebrow`,
   `.hero-card .hero-kicker`, and `.hero-card .hero-step`; they now render pure
   `var(--on-accent)`.
2. **`landmark-one-main` + `region` on `/login`.** The auth shell rendered outside any
   `<main>`, so all page content was unlandmarked. Fixed by wrapping the auth children in
   `<main>` inside `AppFrame.tsx`.

## Named controls and headings (live probe)

Sel: `a[href],button,input,textarea,select,[role=button],[role=link],[role=tab],[role=radio],
[role=switch],[role=checkbox],[tabindex]:not([tabindex="-1"])`.

```text
/               17 controls   unnamed=0   tab=17   h=[ H1, H2, H2 ]
/course/{id}    17 controls   unnamed=0   tab=17   h=[ H1, H2, H2, H2 ]
/lesson/{id}    20 controls   unnamed=0   tab=20   h=[ H1, H2 ×6 ]
/new            18 controls   unnamed=0   tab=18   h=[ H1, H2 ]
/new/interview  12 controls   unnamed=0   tab=12   h=[ H1 ]
/review         12 controls   unnamed=0   tab=12   h=[ H1 ]
/sources        15 controls   unnamed=0   tab=15   h=[ H1, H2, H2 ]
```

All routes also reported `negativeTab: []`, `inputsNoType: []`, `imgsNoAlt: []`, and
`nav[Điều hướng chính]` + `main` landmarks. `/review` and `/sources` additionally expose
`header`.

Heading fixes made this pass:

- `/new` had `H1 → H3` (level skip). The advice card heading is now `H2`.
- `/new/proposal` had **no `h1`** (started at `H2`); the plan name is now the page `H1`,
  and the learner-profile heading moved `H3 → H2`. CSS selector updated to `.profile-box h2`.
- `/new/interview` had no heading at all and could render heading-less in two states.
  `flow-header-title` is now an `H1`, the "interview complete" state is an `H1`, and the
  missing-`courseId` state renders a real `H1` + recovery button.
- `/new/proposal` missing-`courseId` state likewise now renders an `H1` + recovery button.

## Responsive / overflow (measured)

`scrollWidth == clientWidth` for all 9 routes at 1440×900, 768×1024 and 390×844:

```text
ROUTES WITH ISSUES: 0 / 27
```

At 200 % zoom (720×450 CSS viewport, DPR 2) `/`, `/course`, `/lesson`, `/new`, `/review`
and `/sources` all reported `overflowX = 0` with no offending elements.

## Screenshot coverage

Light-mode captures exist for every route at 1440×900. Additional widths:

| Route | 1440 | 768 | 390 |
|---|---|---|---|
| `/` (dashboard) | ✅ | ✅ | ✅ |
| `/login` | ✅ | ✅ | ✅ |
| `/course/{id}` | ✅ | ✅ | ✅ |
| `/lesson/{id}` (incl. quiz blocks) | ✅ | ✅ | ✅ |
| `/new` | ✅ | ✅ | ✅ |
| `/new/interview` | ✅ | ✅ | ✅ |
| `/new/proposal` | ✅ | ✅ | ✅ |
| `/new/generating` | ✅ | ✅ | ✅ |
| `/review` | ✅ | ✅ | ✅ |
| `/sources` | ✅ | ✅ | ✅ |

Dark mode: every route above, including `/login`, `/new/interview`, `/new/proposal` and
`/new/generating` (captured 2026-11-04).

## Lesson player contrast audit (2026-11-04)

Driven live across all six block types (`teach`, `mc`, `blank`, `order`, `match`, `short`).
Foreground was composited over the effective ancestor background (alpha stacked), then
scored against the WCAG 2.1 floor — 4.5:1 for body text, 3:1 for large text
(≥24 px, or ≥18.66 px at weight ≥700).

**Result: 0 failures in light theme.** Lowest measured ratios:

| Element | Ratio | Floor |
|---|---|---|
| `.lesson-bar-primary` (disabled + enabled) | 4.69 – 5.10 | 4.5 |
| `.blank-label`, `.caption`, `.lesson-counter` | 5.36 | 4.5 |
| `.outline-label` | 5.36 | 4.5 |
| `.summary-index` | 7.46 | 4.5 |
| `.quiz-option.selected` | 13.01 | 4.5 |
| `.order-item` | 16.10 | 4.5 |

Dark theme was verified by computed-style read-back rather than full re-audit; the palette
asserts the same floors by construction (`--ink #efe9fc` on `--paper #120e20` ≈ 15:1).

**Divergence worth naming.** The disabled primary CTA pairs `--sand` (#cdc1ef) with
`--ink-2` (#4f476b). That is not the reference's disabled treatment, but it clears 4.5:1 and
is kept because a lower-contrast disabled state would fail.

**Fixed this pass.** Two global-rule leaks made the learner-facing overlays unusable:

1. `.tutor-backdrop` is a full-viewport `<button>`, so the global `button` rule
   (`border-radius: var(--radius-pill)`, `min-height: 48px`, ember background) turned the
   scrim into a violet ellipse. Now explicitly reset to `border-radius: 0`, `min-height: 0`,
   `background: var(--scrim)`. Measured after fix: `border-radius: 0px`,
   `background: rgba(36,28,59,0.42)`.
2. `.outline-item` inherited `justify-content: center` from the same rule, so the index pills
   formed a ragged column. Now `justify-content: flex-start`; all rows measure at `x=1077`.

**Font stack change.** Manrope/Inter/JetBrains Mono are now self-hosted with Google's
`unicode-range` split preserved, so Vietnamese diacritics resolve as before. Production
verification: 21 faces referenced from the built CSS, `document.fonts` reports the active
faces `loaded`, and a 24 px Inter run containing `ặệỡử` measures differently from `monospace`,
confirming the Vietnamese subset is really applied rather than falling back.

## Sheet keyboard model — two paths (2026-11-04)

The lesson player has **two** sheet layouts, and they carry different keyboard contracts
because they are different interaction models.

- **Overlay path (< 1024 px, and always for the outline sheet).** The sheet covers the page
  behind a scrim, so the page is unavailable while it is open.
- **Docked path (tutor only, ≥ 1024 px).** The sheet is a 400 px rail beside a still-live
  page. Nothing is dimmed and the reading column re-centres into the space left of it; see
  `decisions.md` D-08 for the measured geometry. This is what the reference does.

Both paths use `frontend/src/components/ui/useModalPanel.ts`; the docked path passes
`modal: false`. Splitting the flag rather than forking the hook is what keeps Escape and
focus restoration identical on both.

### What both paths do

1. `role="dialog"` + `aria-labelledby` pointing at the sheet heading.
2. Initial focus into the panel — the tutor sheet lands on `#tutor-input` (the user opened
   it to type), the outline sheet on `.outline-item.is-active` (continue from the current step).
3. `Escape` closes and focus returns to the element that opened the sheet.

### Overlay path only

4. `aria-modal="true"` on the panel.
5. Tab and Shift+Tab wrap within the panel's focusable set, filtered to rendered elements.
6. An `inert` sweep along the panel's ancestor chain, so assistive tech and programmatic
   focus cannot reach the background. The `.tutor-backdrop` is deliberately excluded — it is
   the click-to-close target.

The docked rail deliberately does **none** of 4–6. `aria-modal="true"` on a non-modal rail
would be a false claim to screen readers, and the Tab trap plus inert sweep would make the
lesson beside the rail unreachable — exactly the content the dock exists to keep visible.
Escape-to-close is still available, but focus is not confined; a keyboard user can Tab from
the rail straight back into the lesson.

Measured on the production build (`next start`, 1440×900, 2026-11-04):

```text
docked:   docked=true  sheetDocked=true  role=dialog  aria-modal=<absent>
          backdrop display=none  pageBg=rgb(241,236,253)  initialFocus=TEXTAREA#tutor-input
overlay (768x1024): docked=false  aria-modal=true  backdrop=rgba(36,28,59,0.42) full viewport
overlay (390x844):  docked=false  aria-modal=true  sheet x=0 w=390  scrollWidth=innerWidth=390
```

Before this pass each sheet had an Escape-only key handler: no focus trap, no `aria-modal`,
no focus restoration, and the background stayed fully reachable by keyboard and screen reader.

`onClose` is held in a ref rather than the effect deps. Every call site passes an inline
arrow, so a direct dep would re-run the trap on each parent render and pull focus back
mid-typing.

Measured on the production build (`next start`, 1440×900), outline sheet — this sheet is
always modal, so the contract below applies unchanged to it:

```text
open:   role=dialog  aria-modal=true  initialFocusInside=true  initialFocusIsActiveStep=step
        outsideCount=15  inertOutside=14  inertElements=11
bg focus while open:  blocked (focus stays on .outline-item.is-active)
after Escape:         sheetPresent=false  inertLeft=0  restoredTo="Mục lục bài học"  isOutlineTrigger=true
bg focus after close: focusable
```

The single non-inert element outside the sheet is the sheet's own close button, which is
inside the panel by containment but outside by the selector used in the probe. Real Tab
movement (CDP `Input.dispatchKeyEvent`, not a synthetic event — a synthetic `keydown` does
not move focus) produced a 7-element cycle through the outline sheet: step 1 → 2 → 3 → 4 →
5 → 6 → close → wrap to step 1, with `insideSheet: true` at every stop.

The tutor overlay still holds that contract at 768×1024 — re-measured 2026-11-04 with real
CDP key events after the `aside`→`div` change. Eight consecutive Tabs from
`TEXTAREA#tutor-input` alternate `#tutor-input ↔ .btn.btn-icon` (the close button) with
`inSheet: true` at **every** stop; the page behind never receives focus.

The docked rail at 1440×900 does the opposite, by design. Same probe, same key events:
starting at `#tutor-input`, Tab goes `BODY → .btn.btn-icon → .btn.btn-icon →
.lesson-bar-secondary`, with `inSheet: false` at all four stops. That is the intended
non-modal contract — a docked side panel that trapped Tab would make the lesson beside it
unreachable by keyboard.

### The earlier "0 violations" claim was wrong

An earlier revision of this document said an "axe-core re-run with each sheet open returned
**0 violations** in both states". Re-running axe-core on 2026-11-04 against all four sheet
surfaces contradicted that, and the contradiction was a real defect, not a probe artifact:

```json
{"id":"aria-allowed-role","impact":"minor","help":"ARIA role should be appropriate for the element",
 "nodes":[{"target":["aside"],
  "html":"<aside class=\"tutor-sheet is-docked\" role=\"dialog\" aria-labelledby=\"tutor-heading\" tabindex=\"-1\">",
  "msgs":["ARIA role dialog is not allowed for given element"]}]}
```

`<aside>` carries an implicit `complementary` role and ARIA forbids overriding it with
`dialog`. The violation was present on **all four** surfaces — the docked rail, the 768 and
390 overlays, and the outline sheet — so the original claim cannot have been produced by the
probe it describes. The likely cause is that the injected script never loaded and
`axe.run` was never actually awaited (an empty result was read as "0 violations"); that is an
inference, not something the old run recorded.

**Fixed:** both sheets are now `<div>` hosts (constant element type across the dock
breakpoint, so resizing never remounts the panel). Re-measured 2026-11-04 on a production
build:

| Surface | `role` | `aria-modal` | axe `violations` |
|---|---|---|---|
| Docked rail, 1440×900 light | `dialog` | absent | `[]` |
| Docked rail, 1440×900 dark | `dialog` | absent | `[]` |
| Overlay, 768×1024 | `dialog` | `true` | `[]` |
| Overlay, 390×844 | `dialog` | `true` | `[]` |
| Outline sheet, 1440×900 | `dialog` | `true` | `[]` |

Result: **0 violations across all five surfaces**, this time with the run's element identity
(`tag: DIV`) captured in the same probe so the sheet is provably the node that was scanned.

Note for future probes: `inert` does not remove elements from `querySelectorAll`, so counting
selector matches cannot detect it. Check `el.closest('[inert]')`, or attempt `.focus()` and
read `document.activeElement`.

## Known gaps and next actions

1. Screen-reader smoke test on the lesson + quiz flow — **NOT MEASURED**. The modal contract
   above is measured at the DOM level; no NVDA/VoiceOver run has confirmed the actual
   announcement order.
2. Automated E2E — not present. Every check in this document was driven by hand over CDP.
   A regression assertion that the Tab cycle stays inside the overlay at < 1024 px is
   planned; the docked path needs the opposite assertion (Tab *does* leave the rail).
3. ~~axe-core re-run against the docked rail~~ — **DONE 2026-11-04.** All five sheet surfaces
   return `[]` after the `aside`→`div` fix (table above). The synthetic-`keydown` caveat still
   applies to any future *keyboard* probe: use CDP `Input.dispatchKeyEvent`.
