# PHASE REPORT — OVERLAY MODAL CONTRACT (TUTOR + OUTLINE SHEETS)

Format follows §11 of `docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`.

## Metadata

- **Date:** 2026-11-04
- **Repository / branch / HEAD:** SopiSkill · `feat/p6.0-ci-pipeline` · `d747e78`
- **Working tree at start:** modified (15 tracked files) + untracked (`docs/`, `frontend/src/components/`, `frontend/public/`, `frontend/src/app/fonts.css`)
- **Working tree at end:** same set, plus `frontend/src/components/ui/useModalPanel.ts`
- **Commits created:** none (explicit instruction from the user)
- **Supersedes:** `2026-11-04-lesson-player-and-build.md` §"NOT TESTED" item 3 and
  `docs/frontend-reference/accessibility-review.md` §"Known gaps" item 1

## Objective

The previous phase left one concrete gap open: the tutor sheet handled `Escape` and nothing
else. Static reading at the start of this pass found the outline sheet had the *same* defect,
because both were written as a bare `keydown` listener:

```tsx
useEffect(() => {
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}, [onClose]);
```

Three things follow from that shape, and all three are user-facing:

1. `Tab` walks out of the sheet into the page behind it. A keyboard user loses their place and
   has no signal that the sheet is a modal surface.
2. There is no `role="dialog"` / `aria-modal`, so a screen reader reads the sheet as an `aside`
   inside the normal content flow — the background is not suppressed.
3. Focus is never returned to the control that opened the sheet, so closing drops the caret to
   `<body>` and the next `Tab` starts from the top of the page.

The objective was to close this for both sheets with one implementation, and to **measure**
the result rather than assert it.

## Files changed

| File | Change |
|---|---|
| `frontend/src/components/ui/useModalPanel.ts` | **New.** Shared modal hook: Escape close, Tab/Shift+Tab wrap, initial-focus selector, ancestor-chain `inert` sweep, focus restoration |
| `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx` | Dropped the Escape-only effect; `<aside>` now `role="dialog" aria-modal="true" aria-labelledby="tutor-heading"`; initial focus `#tutor-input`; backdrop `tabIndex={-1}` |
| `frontend/src/app/lesson/[lessonId]/page.tsx` | Same change for `OutlineSheet`; initial focus `.outline-item.is-active` |
| `docs/frontend-reference/accessibility-review.md` | Table row PARTIAL → PASS; new "Overlay sheet modal contract" section with measured output; Known gaps renumbered |
| `docs/frontend-reference/component-mapping.md` | `useModalPanel.ts` added to the foundation inventory; "twelve files" corrected to "the files listed below" |
| `docs/development-progress.md` | New FR-4b entry at the top; FR-4's NOT TESTED line annotated |

`frontend/src/lib/api.ts` was **not** touched. No backend file was touched. No CSS changed.

## IMPLEMENTED

- **One hook, two call sites.** `useModalPanel({ open, onClose, panelRef, initialFocusSelector })`
  owns the whole contract. Both sheets pass a ref and a selector; neither carries modal logic
  of its own.
- **`role="dialog"` + `aria-modal="true"` + `aria-labelledby`** on each `<aside>`, pointing at
  the sheet's existing heading (`tutor-heading`, `outline-heading`).
- **Initial focus chosen per sheet.** The tutor lands on the composer because that is what the
  user opened the sheet to use; landing on the close button would make the first `Tab` skip the
  input. The outline lands on `.outline-item.is-active` so a keyboard user resumes from the step
  they are on rather than from step 1.
- **Tab and Shift+Tab wrap** within the panel's focusable set, filtered to elements that are
  actually rendered (`offsetParent !== null`).
- **`inert` on the background.** `aria-modal` is only a hint to assistive tech; the DOM still
  exposes the background to programmatic focus. The hook walks the panel's ancestor chain and
  marks every sibling `inert`, which removes them from the tab order *and* from the
  accessibility tree. `.tutor-backdrop` is deliberately skipped: it is a full-viewport
  `<button>` and it is the click-to-close target.
- **Focus restoration** to the element that was focused when the sheet opened.
- **Cleanup is total.** Removing the listener, stripping every `inert` the hook added, then
  restoring focus — in that order, so the restored element is not still inert.

## TESTED

Production build (`next start`, port 3001), Chrome CDP, 1440×900, authenticated against the
real lesson `lsn_21f2cf0f-56ea-4632-a5da-bee35502dc3d`.

**Type / lint / build**

- `cd frontend && npx tsc --noEmit` → no errors
- `cd frontend && npm run lint` → no issues
- `NEXT_PUBLIC_API_URL=http://localhost:8001 npm run build` → exit 0, lesson route 11.5 kB

**Tutor sheet**

- `role=dialog`, `aria-modal=true`, `aria-labelledby=tutor-heading`
- initial focus `TEXTAREA#tutor-input`
- `Tab` cycles between the composer and the close button, `insideSheet: true` at every stop
- `Escape` closes and restores focus to `BUTTON|Hỏi trợ giảng`

**Outline sheet**

```text
open:   role=dialog  aria-modal=true  initialFocusInside=true  initialFocusIsActiveStep=step
        outsideCount=15  inertOutside=14  inertElements=11
bg focus while open:  blocked (activeElement stays on .outline-item.is-active)
after Escape:         sheetPresent=false  inertLeft=0
                      restoredTo="Mục lục bài học"  isOutlineTrigger=true
bg focus after close: focusable
```

Native Tab movement (CDP `Input.dispatchKeyEvent`, not a synthetic `keydown`) produced a
seven-element cycle: step 1 → 2 → 3 → 4 → 5 → 6 → close → wrap to step 1, with
`insideSheet: true` at every stop. The 15th element outside the sheet by selector but not inert
is the sheet's own close button, which is inside the panel by containment.

**axe-core**, `runOnly` wcag2a / wcag2aa / wcag21a / wcag21aa, three states:

```text
base lesson page   0 violations
tutor sheet open   0 violations
outline sheet open 0 violations
```

## Root causes found and fixed this pass

1. **Escape-only handler with no trap.** Both sheets registered a `window` `keydown` listener
   that handled only `Escape`. `Tab` therefore fell through to the document, and the browser
   moved focus into the nav behind the sheet.
2. **No dialog semantics at all.** Neither sheet had `role`, `aria-modal`, or an
   `aria-labelledby` link to its own heading. To a screen reader the sheet was an `aside` in
   the content flow.
3. **`aria-modal` alone would not have been enough.** It instructs AT to ignore the background
   but leaves the DOM reachable: a scripted `.focus()` on a background button still succeeds.
   This was the reason for adding a real `inert` sweep rather than stopping at the attribute.
4. **`onClose` in the effect deps.** Every call site passes an inline arrow
   (`onClose={() => setTutorOpen(false)}`). Putting that in the dependency array re-runs the
   effect on every parent render — and for a focus trap, re-running means the initial-focus
   line pulls focus back into the panel mid-typing. The hook holds `onClose` in a ref and keeps
   the deps at `[open, panelRef, initialFocusSelector]`.

## NOT TESTED

- **Real screen reader (NVDA / VoiceOver)** — **NOT MEASURED**. The contract is measured at the
  DOM level (`role`, `aria-modal`, `inert`, `document.activeElement`). No announcement-order
  test has been run.
- **Playwright / E2E.** Every check above was driven by hand over CDP. There is still no
  automated regression test for the modal contract.
- **Nested sheets.** No flow currently opens both sheets at once, so stacking was not
  exercised. The hook does not attempt to coordinate two panels.
- **Older browsers.** `inert` support is Chrome 102+, Safari 15.5+, Firefox 112+. On older
  engines the Tab trap still holds but the background may remain in the accessibility tree.

## BLOCKED / API GAP

None added. The register stays at **15** entries (`docs/frontend-reference/api-gap-register.md`).
This change is purely client-side and touches no endpoint.

## API contract / security review

- `frontend/src/lib/api.ts` unchanged.
- No request shape, query key, or cache-key change. `clientAttemptId` and `contentVersion` are
  untouched.
- Auth remains HttpOnly cookie + CSRF header, `credentials: "include"`.
- The network log during verification contained only the same read-path calls as the previous
  phase (lesson fetch, tutor status). No new call was introduced.
- The `inert` sweep operates on `parent.children` of ancestor nodes only — it cannot reach
  outside the document and writes nothing but the `inert` attribute, which cleanup removes.

## Visual comparison

**No change.** No CSS was added or removed; `role`, `aria-modal`, `tabIndex`, and `inert` are
behavioural attributes with no layout effect. The geometry recorded in the previous phase
(header 872 px at x=285 on 1440; 720 px at x=24 on 768; 366 px at x=12 on 390; bottom bar
97 / 97 / 81 px) still holds, and the outline sheet still opens at x=1060, w=380.

## Known limitations

- The focusable selector is a static list. Interactive `contenteditable`, `details`/`summary`,
  or media elements added to a sheet later would need it extended.
- `inert` is applied along the ancestor chain only. A panel rendered into a portal outside the
  page's normal tree (none today) would need portal-aware sibling handling.
- The hook assumes a single open panel. If two sheets are ever open at once, the second
  effect's cleanup will strip the first one's `inert` marks.
- Focus restoration targets whatever was `document.activeElement` at open time. If that
  element is unmounted while the sheet is open, restoration silently no-ops.

## Privacy

No new captures. The verification session used the existing test account
`rea.verify@test.dev` and did not touch the owner account. No personal data appears in any
recorded probe output; the probes read only `aria-label`, `className`, and element tag names.

## Rollback

Pure Git. Deleting `frontend/src/components/ui/useModalPanel.ts` and restoring the prior
Escape-only effects in `TutorPanel.tsx` and `lesson/[lessonId]/page.tsx` returns the tree to
the pre-phase state. There is no migration, no data mutation, and no config change.

## PHASE GATE

**PASS** for this phase's objective. The modal contract is implemented for both sheets and
measured: dialog semantics, initial focus, a genuine seven-stop Tab cycle that does not escape,
14/15 background elements inert while open, blocked programmatic focus on the background, focus
restored to the exact trigger, `[inert]` fully removed on close, and 0 axe violations in all
three states.

Overall project status stays **PARTIAL**: automated E2E and a real screen-reader pass are still
absent, and those are the two gaps this phase explicitly did not attempt.

## Screenshot grid closed

Items 2 and 3 of the original NEXT list were completed in the same session, after this
report's main body was written:

| Capture | File |
|---|---|
| `/login` dark 1440 | `local-login-dark-1440x900.png` |
| `/new/interview` dark 1440 | `local-interview-dark-1440x900.png` |
| `/new/interview` light 390 | `local-interview-390x844.png` |
| `/new/proposal` dark 1440 | `local-proposal-dark-1440x900.png` |
| `/new/proposal` light 390 | `local-proposal-390x844.png` |
| `/new/proposal` dark 390 | `local-proposal-390x844-dark.png` |
| `/new/generating` dark 1440, real in-progress | `local-generating-dark-1440x900.png` |
| `/new/generating` light 390, real in-progress | `local-generating-390x844.png` |

Each PNG was opened and visually confirmed to show the intended screen, not a redirect
target. Getting the two `/new/generating` shots required minting a fresh course and
capturing within a ~700 ms nav wait — the route redirects to `/course/{id}` the moment
generation reports `ready`, so the terminal state is not capturable by design.

Two deterministic probes are worth keeping, because both are easy to repeat wrongly:

- `/new/interview` redirects to `/new/proposal` once all five answers are stored, and
  `/new/generating` redirects on completion. Always read back `location.href` and the `h1`
  in the same eval as the shot; a capture that "looks plausible" can be the wrong route.
- A `fetch` POST from the page needs `X-CSRF-Token` copied from the `csrf_token` cookie;
  without it the API returns `403 {"detail":{"code":"CSRF_INVALID"}}`.

## NEXT

1. Playwright E2E covering creation → proposal → generating → lesson → quiz, with assertions —
   including a regression test that asserts the Tab cycle stays inside both sheets.
2. Screen-reader smoke test (NVDA on Windows) over the lesson + quiz flow, to turn the
   DOM-level modal evidence into an announcement-order observation.
