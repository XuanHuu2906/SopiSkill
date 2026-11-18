# Evidence register

Every artefact in `evidence/` and `screenshots/`, what it demonstrates, and — equally
important — what it does **not** demonstrate. Nothing is listed as collected unless the
file exists in this repository.

Two families:

- **`dom-*` / `inspect-*` / `shot-*`** — captured from `https://web.polyskill.app` (reference).
- **`local-*`** — captured from the SopiSkill build on `http://localhost:3000` (our product).

Both are JSON produced by the same read-only CDP probe, so their shapes are directly
comparable. Each DOM dump records `url`, `path`, `title`, `viewport{w,h,dpr}`, `scroll`,
`theme`, `bodyBg`, `rootVars` (CSS custom properties), `elements[]` (tag, role, label,
text, x/y/w/h, background) and sometimes `fonts`.

## Reference artefacts

| Evidence ID | Screen | Viewport | File | Shows | Does not show |
|---|---|---|---|---|---|
| EV-R01 | S01 sign-in | 1440×900, 768×1024, 390×844 | `dom-signin-*` + `signin-*.png` | Centred panel geometry, 420×56 pill button, radius 999, type scale | Sign-up: the reference has OAuth only, so SopiSkill's email/password form is a **PROPOSAL** |
| EV-R02 | S02 dashboard | 1440, 390 | `dom-home-*` + `home-*.png` | Side nav 264, content 1040, hero 1040×156, greeting 48/52, course card | Server logic behind progress; nothing about ranking |
| EV-R03 | S02 dark | 1440, 390 | `dom-home-dark-*` + `home-dark-*.png` | Dark token values, shadow set, dark surface stack | A user-driven dark toggle: dark was forced with `Emulation.setEmulatedMedia`, so this is a **token FACT**, not a recorded user action |
| EV-R04 | S07 course | 1440, 768, 390 | `dom-course-*` + `course-*.png` | Unit/lesson hierarchy, 74 px lesson rows, locked styling, `Pro` chip | Per-lesson duration comes from the reference payload; SopiSkill has no such field |
| EV-R05 | S08 lesson | 1440, 390 | `dom-lesson-1440x900.json`, `dom-lesson-390x844.json` | Reading column, header bar, block eyebrow/title/prose scale | Lesson authoring rules |
| EV-R06 | S08 stepping | 1440 | `dom-lesson-step2..7`, `lesson-step*-*.png`, `lesson-teach3`, `lesson-summary` | Real step-through: teach → quiz trigger → summary | Only the block types that course used (teach, mc, blank) |
| EV-R07 | S09 quiz | 1440 | `dom-quiz-1`, `-selected`, `-result`, `-done` + PNGs | Option geometry 68 px/radius 16, selected state, feedback band, completion | Grading: whichever option was selected is not asserted to be right by the client |
| EV-R08 | S15 tutor | 1440 | `dom-tutor-open.json` + PNG | Sheet geometry, bubbles, composer, history already present | Tutor SSE contract: response shape and backend behaviour were not read |
| EV-R09 | S03 new | 1440 | `dom-new-1440x900.json` + PNG | Topic screen quota state, chips, launcher | Quota rules (server-side) |
| EV-R10 | S04/S05 interview+plan | 1440 | `dom-interview-done-1440x900.json` + PNG | Completed transcript, generated plan layout | The in-progress interview screen: the only course available was already answered, so the running state is **INFERENCE** from the transcript + tokens |
| EV-R11 | S06 generating | 1440 | `dom-generating-1440x900.json` + PNG | Four-stage terminal list | The running state: capture happened after completion; stage labels are FACT, timing is not |
| EV-R12 | profile | 1440 | `dom-profile-1440x900.json` + PNG | Stat tiles, weekly chart, 46 milestones, tier chips | Anything SopiSkill renders: no matching endpoint (**API GAP**) |
| EV-R13 | homepage a11y tree | 1440 | `inspect-home.json` (REA `inspect-web-page`) | Accessible names/roles from the reference AX tree | Not a SopiSkill audit; used as naming reference only |
| EV-R14 | static bundle | — | (not stored; hash recorded in `reference-audit.md`) | Token tables, route list, i18n strings | Source code: the bundle is minified, so only literal constants were taken |

## Local (SopiSkill) artefacts

| Evidence ID | Route | Viewport | File | Shows |
|---|---|---|---|---|
| EV-L01 | `/login` (anonymous) | 1440, 768, 390 | `local-signin-*` | Panel 420, h1 40/44 Manrope 800, button 420×56 |
| EV-L02 | `/` (anonymous) | 1440, 390 | `local-home-anon-*` | Hero card, "start in a minute" state, sign-in CTA |
| EV-L03 | `/` (signed in) | 1440, 768, 390 | `local-home-*` | Greeting, resume hero, course card, shell 264/1040 |
| EV-L04 | `/` dark | 1440 | `local-home-dark-1440x900.png` + JSON | Dark token parity (`paper #120E20`, dark shadows) |
| EV-L05 | `/` second account | 1440 | `local-home-user2-*` | Session isolation: user 1's course and name are absent |
| EV-L06 | `/course/{id}` | 1440, 390 | `local-course-*` | Progress hero 10 px, lesson rows 74 px, units |
| EV-L07 | `/lesson/{id}` | 1440, 390 | `local-lesson-*` | Focus mode: column 720, header 872 (superseded by EV-L18 for the paginated player) |
| EV-L08 | quiz states | 1440 | `local-quiz-*`, `local-quiz-result-*` | Option 68/radius 16, selected `#EBE3FF`+`#7B5BE6`, disabled CTA `#CDC1EF`, result band |
| EV-L09 | `/new` | 1440 | `local-new-*` | Column 680, h1 48/52, chips |
| EV-L10 | `/new/interview` | 1440 | `local-interview-*`, `local-interview-progress-*` | Question bubble 604, progress 6 px, `Câu n/5` |
| EV-L11 | `/new/proposal` | 1440 | `local-proposal-*` | Plan card, 3-stat strip, unit list, CTA |
| EV-L12 | tutor sheet | 1440 | `local-tutor-*` | Sheet 380, composer 50, send 48 |
| EV-L13 | `/course/{id}` | 768 | `local-course-768x1024.png` + JSON | Tablet layout, `scrollWidth 753 == clientWidth 753` (no overflow) |
| EV-L14 | `/lesson/{id}` | 768 | `local-lesson-768x1024.png` + JSON | Focus mode at tablet width; 72 elements, content height 2209 |
| EV-L15 | quiz selected | 768 | `local-quiz-768x1024.png` + JSON | Option selected state at tablet; `selected=1`, no overflow |
| EV-L16 | `/review` | 768, 1440 | `local-review-*` + PNG | Restyled page after this pass; renders the 503 "feature disabled" state |
| EV-L17 | `/sources` | 768, 1440 | `local-sources-*` + PNG | Restyled page; field geometry measured at 53 px height / radius 16 / border `#E6DEFA` |
| EV-L18 | `/lesson/{id}` — **production build** | 1440, 768, 390 | `prod-lesson-teach-{1440,768,390}.png` | Step-based player running from `next start` (not `next dev`). Header 872 at x=285 / 720 at x=24 / 366 at x=12; bottom bar 97 / 97 / 81 px; counter `1/6` |
| EV-L19 | `/lesson/{id}` dark — production build | 1440, 768, 390 | `prod-lesson-teach-dark-{1440,768,390}.png` | Dark tokens in the shipped bundle: paper `rgb(18,14,32)`, title `rgb(239,233,252)`, primary `rgb(155,123,255)`, bar `rgb(25,20,48)` |
| EV-L20 | font delivery | 1440 | built CSS `f04118c76dbb7467.css` (21 `/fonts/*.woff2` refs) + live `document.fonts` read-back | Self-hosted faces are `loaded` in production and a 24 px Inter run with `ặệỡử` measures differently from `monospace`, proving the Vietnamese subset applies |
| EV-L21 | contrast across all six lesson blocks | 1440 | live probe, composited foreground over ancestor background | 0 WCAG failures in light theme; lowest ratio 4.69 (primary CTA), floors 4.5 / 3.0 |

**Viewport coverage:** 1440×900 and 390×844 for the learning screens; 768×1024 now exists
for sign-in, home, course, lesson, quiz, review and sources. `/new`, interview, proposal and
generating remain at 1440 only. The lesson player additionally has a full 1440/768/390
matrix in **both themes** captured against the production build (EV-L18, EV-L19).

## Screenshot index

Reference PNGs: `signin-*`, `home-*`, `home-dark-*`, `course-*`, `lesson-*`,
`lesson-step*-*`, `lesson-teach3-*`, `lesson-summary-*`, `quiz-*`, `tutor-open-*`,
`new-*`, `interview-done-*`, `generating-*`, `profile-*`.

Local PNGs: every `local-*` file listed above, plus the production-build matrix
`prod-lesson-teach-{1440,768,390}.png` and `prod-lesson-teach-dark-{1440,768,390}.png`.

## Privacy redaction

The capture session was an owner session, so the display name appeared in the greeting
and profile header. Before storage it was replaced with **"Người học"**:

- JSON / Markdown: string replacement in `dom-home-1440.json`, `dom-home-390x844.json`,
  `dom-home-dark-1440x900.json`, `dom-home-dark-390x844.json`, `dom-course-768x1024.json`,
  `dom-profile-1440x900.json`, `inspect-home.json`, `screen-inventory.md`.
- PNG: the name band was filled with the surrounding background colour in
  `home-dark-1440x900.png`, `home-390x844.png`, `home-dark-390x844.png`,
  `profile-1440x900.png`.

Unredacted originals were kept outside the repository for the session only. No cookie,
token, email address, or private page body was ever stored. The redacted JSON files were
re-validated with `json.load` after editing.

## Reproducing

The probe scripts live outside this repository (`%TEMP%/opencode/ps-recon/`) and are not
committed, since they are disposable tooling. Reproduce with REA CLI plus a loopback CDP
probe; see `reference-audit.md` for the exact tool and flags.
