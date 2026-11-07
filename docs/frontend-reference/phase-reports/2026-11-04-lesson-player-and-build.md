# PHASE REPORT — LESSON PLAYER, STEP MODEL, AND BUILD CLOSURE

Format follows §11 of `docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`.

## Metadata

- **Date:** 2026-11-04
- **Repository / branch / HEAD:** SopiSkill · `feat/p6.0-ci-pipeline` · `d747e78`
- **Working tree at start:** modified (15 files) + untracked (docs, `frontend/src/components/`)
- **Working tree at end:** same set, plus `frontend/src/app/fonts.css` and `frontend/public/`
- **Commits created:** none
- **Supersedes:** `2026-11-03-frontend-reconstruction.md` §"Known limitations" item 1
  (`next/font/google` needs network on first build)

## Objective

Two things were open at the end of the previous phase:

1. The lesson player needed to become a **step-based** experience (one block per screen,
   paginated) to match the reference's interaction model, instead of one scrolling page.
2. `npm run build` failed, so the frontend had never been verified as a production artifact.

## Files changed

| File | Change |
|---|---|
| `frontend/src/app/lesson/[lessonId]/page.tsx` | Step-based player: single visible block, counter/progress bound to `blocks[]`, outline sheet, result state |
| `frontend/src/app/globals.css` | Lesson chrome bands, 872 px header row with −75 px overhang, `.tutor-backdrop` reset, `.outline-item` left alignment |
| `frontend/src/app/layout.tsx` | Dropped `next/font/google`; imports `fonts.css` |
| `frontend/src/app/fonts.css` | **New.** 21 self-hosted `@font-face` rules + `--font-*` properties |
| `frontend/public/fonts/*.woff2` | **New.** 21 files, 644 KB |
| `docs/frontend-reference/*` | Screen inventory, API gaps, a11y review, evidence register, visual comparison, component mapping, decisions |

`frontend/src/lib/api.ts` was **not** touched. No backend file was touched.

## IMPLEMENTED

- **Step model.** The player shows exactly one block at a time. The header counter and the
  progress bar both derive from the visible block's index, so `1/6` … `6/6` tracks the real
  `blocks[]` length rather than a hard-coded denominator.
- **All six block renderers exercised live:** `teach` (eyebrow/title/body/notice), `mc`
  (option rows + letter chips + selected state), `blank` (label + input), `order`
  (rows + move controls + index chips), `match` (row + `<select>`), `short` (label + input).
- **Outline sheet.** 380 px right-side sheet, all six blocks listed with type label and
  public prompt, `aria-current="step"` on the active row, closes on select / `Escape` /
  backdrop click, jumps to the chosen step.
- **Single submit at the end.** Matches the backend contract: `grade_attempt` grades the
  whole lesson in one batch and `public_block()` never emits answers.
- **Self-hosted fonts.** Manrope 700/800, Inter 400/500/600, JetBrains Mono 400/500, with
  Google's `unicode-range` split preserved (latin / latin-ext / vietnamese).

## TESTED

| Command / probe | Exit | Result |
|---|---|---|
| `cd frontend && npx tsc --noEmit` | 0 | No errors |
| `cd frontend && npm run lint` | 0 | No issues |
| `cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8001 npm run build` | 0 | Compiled; 11 routes |
| `npx next start -p 3001` + `GET /` | — | HTTP 200, production bundle |
| Font delivery in built CSS | — | 21 `/fonts/*.woff2` references present in `f04118c76dbb7467.css` |
| `document.fonts` in the production page | — | Active Manrope/Inter faces report `loaded`; a 24 px Inter run containing `ặệỡử` measures differently from `monospace`, proving the Vietnamese subset applies |
| Lesson at 1440, 768, 390 — light | — | Header 872@x285 / 720@x24 / 366@x12; bottom bar 97 / 97 / 81 px; `scrollWidth == clientWidth` at all three |
| Lesson at 1440, 768, 390 — dark | — | Shell `rgb(18,14,32)`, title `rgb(239,233,252)`, primary `rgb(155,123,255)`, bar `rgb(25,20,48)` |
| Contrast, all six lesson blocks, light | — | **0 WCAG failures.** Lowest 4.69:1 (primary CTA) against a 4.5 floor |
| Outline sheet open/close/select/keyboard | — | Opens (sheet x=1060 w=380), lists 6 blocks, jumps to step 4 on select, closes on `Escape` and backdrop |
| Submit → result state | — | One POST, graded response rendered; fully-correct run shows the `--moss-wash` perfect band |

Verification ran against `next start` (the production bundle), not `next dev`. That matters:
the original failure only appeared in the webpack build path, so a dev-server pass would
not have proven anything.

## Root causes found and fixed this pass

1. **`npm run build` — `next/font` null dereference.**
   `TypeError: Cannot read properties of null (reading '1')` at
   `@next/font/dist/google/loader.js:122:78`, i.e.
   `const ext = /\.(woff|woff2|eot|ttf|otf)$/.exec(googleFontFileUrl)[1];`.
   Ruled out by bisection: Google Fonts reachability (200 on both families), the UA
   (the exact Mac Chrome/104 UA returns `.woff2`), Node `fetch` vs `node:https`, the CSS
   parsers (`findFontFilesInCss` returned seven `.woff2` files), and the loader itself
   (run standalone for all three families → `[ 'ok', 'ok', 'ok' ]`). The defect is confined
   to the webpack path. Fixed by self-hosting (D-12).

2. **`NEXT_PUBLIC_API_URL` is inlined at build time.** The first production build defaulted
   to `http://localhost:8000` (`lib/api.ts:1`), so every API call failed and the app bounced
   to `/login`. Rebuilt with the variable set; `localhost:8001` now appears in the emitted
   chunk. Anyone building this artifact must export the variable — it is not read at runtime.

3. **Global `button` rule leaked into two overlays.** `.tutor-backdrop` is a full-viewport
   `<button>`, so `border-radius: var(--radius-pill)` turned the 1440×900 scrim into a giant
   violet ellipse, and `min-height: 48px` + ember background made it flash solid. `.outline-item`
   inherited `justify-content: center`, so the index pills formed a ragged column
   (x = 1135 / 1089 / 1096 / 1111 / 1150 / 1092). Both reset explicitly; after the fix the
   backdrop reports `border-radius: 0px` and all outline rows align at x = 1077.

4. **Lesson header was short by one control.** The row was sized for close + progress +
   counter (816 px) and had no room for the outline button. Measured against the reference
   (872 px wide at x = 285, overhanging the 720 px column by ~75 px each side) and fixed with
   `width: calc(100% + 152px); margin-left: -75px`.

## NOT TESTED

- Playwright/E2E: still absent; every flow above was driven by hand over CDP.
- Screen-reader pass (NVDA/VoiceOver) — **NOT MEASURED**.
- Tutor sheet focus trap / `aria-modal` — `Escape` works, trapping unmeasured.
- Dark captures for `/login`, `/new/interview`, `/new/proposal`, `/new/generating`.
- 390×844 captures for `/new/interview` and `/new/proposal`.
- Automated pixel-diff; all comparisons are DOM measurements plus visual inspection.
- Backend `pytest` — not run this session (backend untouched).

## BLOCKED / API GAP

Five gaps were added this pass, bringing the register to **15** (see
`../api-gap-register.md`):

| ID | Gap |
|---|---|
| GAP-11 | Per-question feedback band — impossible without a per-block grading endpoint |
| GAP-12 | Lesson duration, type tag, lock state, unit ordering — not in `LessonOut` |
| GAP-13 | Offline save / download — no export contract |
| GAP-14 | Vocabulary list + lesson summary sheet — no such collections |
| GAP-15 | Seven-step structure — SopiSkill lessons ship six blocks; the counter reports the true count |

No endpoint was added, changed, or simulated. Nothing renders placeholder data.

## API contract / security review

- `frontend/src/lib/api.ts` unchanged.
- HttpOnly cookie + CSRF and `credentials: 'include'` preserved.
- Session-scoped TanStack Query keys unchanged.
- `clientAttemptId` stability and `contentVersion` handling unchanged.
- Answer-key scan: `solution` / `answerKey` / `correctOption` / `answer_key` absent from the
  DOM before submit. The outline sheet reads only `block.type` and the public prompt, so it
  cannot leak a key either.
- No PolySkill API was called and no PolySkill asset was copied. The self-hosted fonts are
  Manrope / Inter / JetBrains Mono — an openly licensed generic stack, not PolySkill's.

## Visual comparison

`MATCHED (metrics + flow model)` — the lesson player, which was the open item. One block per
screen, fixed chrome bands, 872 px header row at 1440, 0 horizontal overflow at 768 and 390,
dark tokens identical to the measured set.

`MATCHED (metrics)` — everything previously confirmed for the other routes; unchanged.
`PARTIAL` / `NOT IMPLEMENTED` — unchanged; see `../visual-comparison.md`.

## Known limitations

1. `NEXT_PUBLIC_API_URL` must be exported **before** `npm run build`; it is baked into the
   bundle and cannot be changed at runtime.
2. Running `npm run build` while `next dev` serves the same directory corrupts `.next`.
   Stop dev first.
3. `--ink-3` is deliberately darker than the reference so it clears 4.5:1 (documented
   divergence, not an error).
4. Tutor sheet is 380 px vs the reference's ~360–380 px.
5. The reference's 7-step lesson structure cannot be matched while lessons ship 6 blocks.

## Privacy

No new captures contain personal data. The verification session used the existing test
account `rea.verify@test.dev`; no owner account was accessed this pass. Earlier redactions
are unchanged — see `../evidence-register.md#privacy-redaction`.

## Rollback

Pure Git. The font self-hosting is additive (`fonts.css` + `public/fonts/`); reverting
`layout.tsx` to `next/font/google` restores the previous behaviour (and the build failure).

```bash
git checkout -- frontend/src/app/{layout.tsx,globals.css}
rm -f frontend/src/app/fonts.css
rm -rf frontend/public/fonts
```

No migrations, no backend changes, no data mutation.

## PHASE GATE

**PASS** for the two objectives of this phase: the step-based lesson player is implemented
and verified across all six block types at three viewports in both themes, and the production
build is green with fonts proven to load from the shipped bundle.

Still **PARTIAL** overall by the same three gaps as before — no automated E2E assertions, no
screen-reader pass, and an unmeasured Tutor focus trap — none of which this phase claimed to
close.

## NEXT

1. Commit the work; the tree has been uncommitted across two phases.
2. Playwright E2E for creation → proposal → generating → lesson → quiz, with assertions.
3. Tutor sheet focus trap + `aria-modal`, measured via `activeElement` after each `Tab`.
4. Dark captures for `/login` and `/new/*`; 390×844 for `/new/interview` and `/new/proposal`.
