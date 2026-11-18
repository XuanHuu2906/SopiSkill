# PHASE REPORT — FRONTEND RECONSTRUCTION (R0–F5 equivalent)

Format follows §11 of `docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`.

## Metadata

- **Date:** 2026-11-03
- **Repository / branch / HEAD:** SopiSkill · `feat/p6.0-ci-pipeline` · `d747e78ee8392a354db79805fe73b1477bc0c531`
- **Working tree at start:** clean
- **Working tree at end:** modified (15 files) + untracked (`docs/SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`,
  `docs/frontend-reconstruction-log.md`, `docs/frontend-reference/`, `frontend/src/components/`)
- **Commits created:** none

## Reference observed

- Screen IDs: S01, S02, S03, S04/S05 (completed transcript), S06 (terminal), S07, S08, S09,
  S12–S14 partial, S15, profile.
- Viewports: 1440×900, 768×1024, 390×844 (DPR 1).
- Evidence: `docs/frontend-reference/evidence/` (52 files) and `screenshots/`.

## NOT OBSERVED

| Screen | Reason |
|---|---|
| S04 interview, in progress | The only available course was already fully answered |
| S06 generation, running | Capture happened after completion; only stage labels are FACT |
| S10 `blank`, S11 `order`, S12 `match`, S13 `short` as reference UI | The open lesson only reached the blank block; those layouts are PROPOSAL built from the same tokens |
| S16 proposal editing, S17 source ingest UI | Not present in the observed reference session |
| Sign-up | The reference uses OAuth only |

## Objective and scope

Re-implement the SopiSkill frontend against observed PolySkill behaviour and measured
tokens, keeping the FastAPI backend contract, auth/session security, and server grading
untouched.

## Files changed

Modified: `docs/development-progress.md`, `frontend/src/app/{globals.css,layout.tsx,providers.tsx,page.tsx,login/page.tsx}`, `frontend/src/app/new/{page,interview/page,proposal/page,generating/page}.tsx`,
`frontend/src/app/course/[courseId]/page.tsx`, `frontend/src/app/lesson/[lessonId]/{page,TutorPanel}.tsx`.
Added: `frontend/src/components/{ui/*,layout/*}`, the whole of `docs/frontend-reference/`, and the work log.

## IMPLEMENTED

- Token layer (light + dark) and typography in `globals.css`.
- Primitives: `Button`, `Card`, `Field`, `Badge`, `Progress`, `Skeleton`, `Icon`.
- Shell: `AppFrame` (264 side nav, 1040 content, 50 tab bar, lesson focus mode), `TabBar`,
  `ThemeToggle`, `ThemeProvider`.
- All app routes restyled: login, dashboard, topic, interview, proposal, generating, course,
  lesson, tutor panel.
- Quiz rendering for `mc`, `blank`, `order`, `match`, `short` with keyboard-operable controls.

## TESTED

| Command | Exit | Result |
|---|---|---|
| `cd frontend && npx tsc --noEmit` | 0 | No errors |
| `cd frontend && npm run lint` (`--max-warnings=0`) | 0 | No issues |
| `cd frontend && npm run build` | 0 | Compiled; 11 routes |
| Throwaway DB migrate (`ailp_ui_check`) | — | `0016_p52_exposure (head)`; main DB untouched |
| Seed via real HTTP (register → course → 5 answers → propose → approve) | — | generation `ready`, 4/4 lessons, 6 block types |
| DOM measurement, local vs reference, 1440/768/390 | — | Shell 264/1040, hero 1040×155, quiz option 68/radius 16, lesson column 720@x=353, header 872 |
| Account switch user1 → user2 | — | `leakedUser1=false`, `leakedCourse1=false`, `ownCourse=true`; cross-user lesson returns ownership message |
| Answer-key DOM scan | — | `solution`/`answerKey`/`correctOption`/`answer_key` absent before submit |
| Lesson a11y probe | — | 20 controls, `unnamed=0`, `tabReachable=20`, focus ring `#7b5be6` |

### Added by FR-2 (review pass) and FR-3 (accessibility closure)

| Command | Result |
|---|---|
| `npx tsc --noEmit` / `npm run lint` / `npm run build` | exit 0; build now 11 routes incl. `/_not-found` |
| axe-core `axe.run(document,{resultTypes:['violations']})`, 9 routes, light **and** dark | **0 violations, 18 runs** |
| Colour contrast (axe) | 0 failures, both themes |
| Named controls / headings probe, 7 routes | 0 unnamed, 100 % tab-reachable, 0 negative `tabindex`, 0 `input` without `type`, 0 `img` without `alt`; every route starts at `H1` |
| Horizontal overflow, 9 routes × 3 viewports | `scrollWidth == clientWidth` in **27/27** |
| 200 % zoom (720×450 CSS, DPR 2), 6 routes | `overflowX = 0`, no offenders |
| Screenshot matrix | 768×1024 for 10/10 routes; 390×844 for 9; dark 1440×900 for 6 routes + 2 quiz states; 69 files total |

Two genuine defects were found by axe and fixed before the run went green:
`color-contrast` on `/` (`.hero-kicker` 4.23:1, `.hero-step` 3.36:1 — `opacity` compositing
white over `--ember #7b5be6`) and `landmark-one-main` + `region` on `/login` (auth shell
rendered outside any `<main>`).

The pre-FR-3 hand-written contrast probe reported 0 failures on `/` while those two failures
existed; it did not model `opacity` compositing. Only the axe run surfaced them. Recorded here
because the probe's green result was misleading, not merely incomplete.

## NOT TESTED

- Playwright/E2E: not present in the project, not added.
- Backend `pytest`: not run this session (backend untouched).
- Docker image builds for frontend/backend with the new UI.
- Screen-reader pass (NVDA/VoiceOver) — **NOT MEASURED**; axe is not a substitute.
- Tutor sheet focus trap / `aria-modal` — `Escape` closes it; trapping not measured.
- Dark-mode captures for `/login`, `/new/interview`, `/new/proposal`, `/new/generating`.
- 390×844 captures for `/new/interview` and `/new/proposal`.
- Automated pixel-diff; comparisons are DOM measurements.
- Self-hosted fonts (first build still needs network).

## BLOCKED / API GAP

10 gaps recorded in [`../api-gap-register.md`](../api-gap-register.md): lesson duration,
unit tone/paywall, milestones/league/weekly chart, interview quick-answer chips, prefetch,
glossary terms, named tutor tools, proposal editing, reference source ingest, dark toggle
shape. No endpoint added or changed; no PolySkill API called.

## API contract / security review

- `frontend/src/lib/api.ts` unchanged (839 lines).
- Session-scoped query keys, HttpOnly cookie + CSRF, `credentials: 'include'` all retained.
- `clientAttemptId` fingerprint and `contentVersion` handling unchanged.
- Answer keys never rendered before the server returns `results`.
- Ownership enforced server-side; client guards are UX-only.
- `providers.tsx` change is additive (`ThemeProvider` wrapper); the old `AuthBar` moved into
  `AppFrame`, so no auth logic was dropped.

## Visual comparison

`MATCHED` — shell geometry, tokens, type scale, card/quiz dimensions, lesson column.
`PARTIAL` — tutor sheet width; proposal/interview structure (contract differs).
`NOT OBSERVED` — the five screens listed above.
`NOT MATCHED` — none claimed; no pixel-diff performed.

## Regression results

0 regressions in anything executed. `tsc`/`lint`/`build` pass. Session isolation, ownership,
and answer-key scans all pass on the throwaway environment.

## Known limitations

1. `next/font/google` needs network on first build; offline CI would fail.
2. Tutor sheet 380 px vs reference ~360–380 px.
3. Interview/proposal structure diverges by contract, not by accident (PARTIAL).
4. Running `npm run build` while `npm run dev` serves the same directory corrupts `.next`;
   recover by stopping dev, removing `.next`, restarting.
5. `--ink-3` is deliberately darker than the reference (`#645c81` light vs `#8a82a6`) so it
   clears 4.5:1; measured 3.12–3.61:1 before, ≥4.78:1 after. A visual deviation, not an error.
6. The CDP audit driver scripts live in `%TEMP%/opencode/ps-recon/*.mjs`, outside the repo.
   `axe-core` is in `node_modules`, but re-running the sweep requires rewriting the driver.

Corrected 2026-11-03: an earlier revision of this report listed `/review` and `/sources` as
unstyled, and 768-wide captures as missing for the learning screens, and the checklist as
overstating three-viewport coverage. All three are now false — both routes render on the new
primitives, and 768/390 captures exist (with the two documented exceptions above).

## Privacy

Owner name redacted from 7 JSON files, 1 Markdown file, and 4 PNGs (replaced with
"Người học", or painted over with the background colour). See
[`../evidence-register.md`](../evidence-register.md#privacy-redaction).

## Rollback

Revert the frontend diff and delete the untracked additions:

```bash
git checkout -- frontend/src/app
rm -rf frontend/src/components docs/frontend-reference
git checkout -- docs/development-progress.md
```

No migrations, no backend changes, no data mutation, so rollback is pure Git. The
throwaway database `ailp_ui_check` can be dropped independently.

## PHASE GATE

**PARTIAL** — typecheck, lint, build, axe (9 routes × 2 themes, 0 violations), contrast,
overflow (27/27) and the capture matrix all pass against the real local build. Held back from
PASS by: no automated E2E assertions, no screen-reader pass, and an unmeasured Tutor sheet
focus trap.

## NEXT

1. Playwright E2E for the 5-question creation flow → proposal → generating → lesson → quiz,
   with assertions.
2. Tutor sheet focus trap + `aria-modal`, measured via `activeElement` after each `Tab`.
3. Dark captures for `/login` + `/new/*`; 390×844 for `/new/interview` and `/new/proposal`.
