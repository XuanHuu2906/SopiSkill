# Decisions

Design and engineering decisions taken during the reconstruction, each with its reason
and the alternative that was rejected. Tagged **PROPOSAL** where they are SopiSkill's own
choice rather than something observed in the reference.

## D-01 — Re-implement the layout system, not the product

**PROPOSAL.** Copy the observable layout properties (palette values, type scale, spacing,
radius, elevation, breakpoints) and rebuild our own components. Do not copy logos,
mascots, illustrations, copy strings, or font files.

*Rejected:* shipping a near-verbatim clone. It would carry someone else's brand and
assets into SopiSkill, which §0.4 of the plan forbids (brand independence).

## D-02 — Keep the Next.js 15 App Router stack

**PROPOSAL.** The reference is Expo/React Native Web. Switching SopiSkill to Expo to match
the reference was explicitly out of scope, and would discard a working backend integration
for no user-facing gain.

## D-03 — Tokens as CSS custom properties, not a UI library

**PROPOSAL.** Express the system as CSS variables + hand-built primitives
(`Button`, `Card`, `Field`, `Badge`, `Progress`, `Skeleton`, `Icon`) rather than adding a
component library. Keeps bundle size and dependency surface unchanged, and the tokens map
one-to-one to what was measured.

## D-04 — Light/dark from measured tokens; toggle is ours

Dark values were measured from the reference's token table (FACT). The control shape is a
three-way **Sáng / Hệ thống / Tối** segmented switch rather than the reference's single
toggle (PROPOSAL), stored under `sopiskill.theme`.

*Limit:* dark was forced via `Emulation.setEmulatedMedia`, so this is a token FACT, not a
recorded user-driven dark session.

## D-05 — Preserve the backend contract exactly

No change to `lib/api.ts`, query keys, cookie/CSRF handling, polling intervals,
`clientAttemptId` stability, or server-side grading. All UI work sits above those seams.
This is what lets the work be rolled back by reverting the frontend diff alone.

## D-06 — Omit rather than fake reference features

Where the reference shows data SopiSkill lacks (lesson minutes, paywall, milestones,
quick-answer chips, named tutor tools), the element is omitted and logged in
`api-gap-register.md`. No plausible placeholder data is rendered.

## D-07 — Focus mode for the lesson player

**PROPOSAL.** Hide the side nav and tab bar while inside `/lesson/*`, and centre a 720 px
reading column inside an 872 px header. The reference behaves this way and it measurably
fixed a layout bug where the column was pushed to x=485 instead of centre.

## D-08 — Tutor docks beside the lesson at ≥1024 px, overlays below it

**IMPLEMENTED, TESTED 2026-11-04.** The original entry here said the sheet was "roughly
360–380 px" and accepted that as a small divergence. Measuring the reference corrected
that on three counts:

- **The rail is 400 px, not ~362.** Pixel scan of `tutor-open-1440x900.png` shows the
  reading page's paper background through x=1039, a 1 px `#E6DEFA` hairline at x=1040, and
  the rail surface from x=1041 to x=1439 — a 399 px body, i.e. 400 px including the hairline.
- **It docks; it does not overlay.** Opening the tutor shifts the reading card x 360→160,
  the progress track 348→148 and the *fixed* bottom CTA 866→666 — all exactly −200 px —
  while the page background stays `rgb(241,236,253)` at every sampled row. A scrim-and-overlay
  would have dimmed the page and left the column in place.
- **The page re-centres into the leftover 1040 px.** That is, the same 720 px column centred
  in `1440 − 400`. This is what makes a 400 px reservation on `.app-content` land the column
  at x=160 exactly, and lets `.lesson-header`'s existing `margin-left:-75px` keep working
  unchanged.

SopiSkill now reserves `--dock-width: 400px` on `.app-content`'s right edge at
`@media (min-width: 1024px)`, pins `.lesson-bar` to `right: var(--dock-width)`, and hides the
backdrop. Below 1024 px there is not room for both a 720 px column and a 400 px rail, so the
modal overlay is kept — it is the honest layout at that width, not a shortcut.

Measured after implementation (1440×900, light and dark):

| | Closed | Docked | Target |
|---|---|---|---|
| Reading column | x 360 | x 160 | x 160 |
| Progress track | x 345 w 708 | x 145 w 708 | x 145 |
| Bottom bar | 0..1440 | 0..1040 | right edge 1040 |
| CTA | x 860 | x 660 | x 660 |
| Tutor sheet | — | x 1040 w 400 | x 1040 w 400 |
| Sheet shadow | — | `--shadow-rail`, identical gradient | same |
| Backdrop | — | `display:none` | hidden |
| `aria-modal` | — | absent | non-modal |
| `role="dialog"` host | — | `div` | `div` (`aside` is an invalid host) |
| Page background | `241,236,253` | `241,236,253` | unchanged |

The rail keeps `--shadow-rail`. An intermediate revision suppressed it with
`box-shadow: none`; a row-scan showed that was wrong — the reference fades
`241,236,253 → 223,215,241` by x=1039, and with the token restored the local gradient is
byte-identical to the reference at both mid-page and the y=884 bottom-bar row.

Dark theme repeats the geometry exactly (paper `18,14,32` → hairline `48,39,72` → rail
`25,20,48`). The 768×1024 and 390×844 paths were re-verified to still take the modal
overlay path (`aria-modal="true"`, full-viewport scrim, sheet 380 px at x=388 / 390 px at
x=0, no horizontal overflow at 390).

Because the docked rail is not modal, `useModalPanel` gained a `modal` flag: the docked
path keeps Escape-to-close and focus restoration but drops the Tab trap and the inert
sweep, which would otherwise make the page beside the rail unreachable by keyboard. See
`accessibility-review.md` for the two keyboard models. Measured with real CDP key events:
Tab from `#tutor-input` leaves to `BODY`, then two icon buttons, then the bottom-bar
secondary action.

Both sheets were `<aside role="dialog">`, which axe flags as `aria-allowed-role`
(`aside` implies `complementary` and ARIA forbids overriding it with `dialog`). Both are
now `<div role="dialog">`; the element type stays constant across the breakpoint so
resizing never remounts the panel. Re-scan of all five sheet surfaces returns 0
violations.

## D-09 — Interview uses a textarea, not quick-answer chips

The reference offers suggested answers per question; SopiSkill's backend returns question
text only (GAP-04). A textarea is the honest UI for that contract. Chips remain for topic
suggestions on `/new`, where they are client-side.

## D-10 — `/review` and `/sources` restyled onto the new primitives (closed 2026-11-03)

Originally this decision kept `.container`, `.card`, `.topbar`, `.badge`, `.link` and
`.error-box` alive so `/review` and `/sources` would not break when `globals.css` was
rewritten. Both pages have since been moved onto `Button`/`Card`/`Badge`/`Skeleton`/
`TextInput`, with `.source-item`, `.web-ingest` and `.source-create-btn` added for their own
layout. Mutation, polling and session-scope invalidation logic was left line-for-line intact.

Fixed while restyling: the `/sources` inputs had no `type`, so `input[type="text"]` never
matched and they rendered with browser-default chrome; and a `flex` style applied directly to
the input inside the flex-column `.field` stretched it to 260 px tall. Both are now 53 px,
radius 16, border `#E6DEFA`.

## D-11 — No new test framework

No Playwright was added; flows were driven manually via CDP. That means the sign-in →
dashboard → course → lesson → quiz → account-switch path is **exercised**, not
**asserted in an automated suite**. Adding E2E remains an explicit follow-up.

## D-12 — Fonts self-hosted, not `next/font/google` (superseded 2026-11-04)

**PROPOSAL with a measured reason.** Originally Manrope 700/800, Inter 400/500/600 and
JetBrains Mono 400/500 were loaded through `next/font/google`, which fetches Google Fonts
at build time. `npm run build` then failed outright:

```text
src\app\layout.tsx
An error occurred in `next/font`.
TypeError: Cannot read properties of null (reading '1')
    at next/dist/compiled/@next/font/dist/google/loader.js:122:78
```

Line 122 is `const ext = /\.(woff|woff2|eot|ttf|otf)$/.exec(googleFontFileUrl)[1];`. Bisection
established that the network path was healthy — the compiled loader run standalone against
the same families returned `[ 'ok', 'ok', 'ok' ]`, `findFontFilesInCss` extracted seven
`.woff2` files, and the exact Google URL answered 200 with the expected CSS. The failure
was confined to the webpack path, where `googleFontFileUrl` arrived without a recognisable
font extension and the `.exec()` result was `null`.

*Fix:* the three families are now **self-hosted** (`frontend/public/fonts/`, 21 `.woff2`
files, 644 KB) with a generated `src/app/fonts.css` that keeps Google's own
`unicode-range` split, so Vietnamese diacritics resolve to the same glyphs as before.
`layout.tsx` no longer imports `next/font/google`. The build no longer touches the network.

*Rejected:* `NEXT_FONT_GOOGLE_MOCKED_RESPONSES` (a supported escape hatch that maps each
CSS URL to a captured response). It would have left the build dependent on a committed
snapshot of Google's CSS and still fetched the `.woff2` files at build time.

*Note:* the fonts are Manrope / Inter / JetBrains Mono — a generic, openly licensed stack
(OFL), **not** PolySkill's font files. D-01's "no copied assets" rule is unaffected.
