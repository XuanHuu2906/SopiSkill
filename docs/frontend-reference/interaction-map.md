# Interaction map — observed behaviour

Every entry distinguishes what was **executed** during recon from what was **inferred**
from the bundle or evidence. All actions were performed against the reference product;
SopiSkill behaviour is listed separately in the right-hand column.

## Global

| # | Trigger | Reference behaviour (observed) | Confidence | SopiSkill implementation |
|---|---|---|---|---|
| G1 | Viewport < 1024 px | Tab bar moves to the bottom (5 tabs at 390 px: Trang chủ, Học, Mới, Pol, Bạn), `TAB_BAR_HEIGHT` 50 within a bar that also reserves the safe-area inset | FACT (measured y=786, h=50, five 75 px cells) | Same breakpoint and bottom bar; labels reuse SopiSkill routes |
| G2 | Viewport ≥ 1024 px | 264 px side nav, content max 1040 px, content padding 48/48/72 | FACT | Same |
| G3 | `data-theme` unset + OS dark | Dark token set applies | FACT (forced `prefers-color-scheme: dark`: paper #120E20, ink #EFE9FC, ember #9B7BFF, surface #1F1839) | SopiSkill adds a real light/dark/system toggle with `data-theme` |
| G4 | Hover on nav row | Background `--c-bone`; pressed scale 0.98 / 120 ms `cubic-bezier(.23,1,.32,1)` | INFERENCE from bundle `PressableScale` + measured transition duration 120 ms | Reproduced in CSS |
| G5 | Reduced motion | `prefers-reduced-motion` shortens animation to ~0 | FACT (bundle reads the media query) | Already handled by `globals.css` |

## Authentication

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| A1 | Open `/sign-in` | Centred marketing block + two OAuth pills | FACT | SopiSkill keeps email/password (its own backend), same visual frame |
| A2 | Toggle login/register | No equivalent (OAuth only) | UNKNOWN | SopiSkill keeps its mode toggle, styled as a text button |
| A3 | Invalid credentials | Not reachable | UNKNOWN | Inline `role="alert"` under the fields, using `--c-danger` |

## Dashboard

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| D1 | Open `/home` | Greeting + resume hero + course card | FACT | Same composition from `/v1/auth/me` + `/v1/courses` |
| D2 | Click resume pill | Navigates to the current lesson | FACT (`resumeLessonId` equivalent) | `resumeLessonId` from `CourseListItem` |
| D3 | Click a course card | Navigates to `/course/{id}` | FACT | Same |
| D4 | Overflow menu (32 px) | Menu opens with options incl. delete | FACT (element present), menu items UNKNOWN | Omitted; no delete contract in scope |
| D5 | No courses | Not observed | UNKNOWN | Existing empty state, restyled |

## Course creation → generation

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| C1 | Submit topic | Creates course, enters interview | FACT (network captured in an earlier session) | `POST /v1/courses` → `/new/interview` |
| C2 | Answer a question | Bubble appears, progress advances | FACT (transcript measured) | `POST /v1/courses/{id}/interview/answer` |
| C3 | 5th answer | Plan card replaces the composer | FACT (`Kế hoạch học đã sẵn sàng`) | `/new/proposal` (SopiSkill has a separate proposal route) |
| C4 | Approve | Generation screen with 4 stages | FACT (stage labels) | `POST /approve` → `/new/generating` |
| C5 | Generation terminal | `Khóa học đã sẵn sàng` + `Mở lộ trình` | FACT | `status === "ready"` → `/course/{id}`, with retry on `failed` |
| C6 | Polling | Poll stops on terminal state | FACT (earlier capture: 56 polls then ready) | Existing `refetchInterval` guard is preserved |

## Course overview

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| O1 | Click `Tiếp tục` | Opens resume lesson | FACT | `resumeLessonId` |
| O2 | Click an unlocked lesson | Opens lesson | FACT | Same |
| O3 | Click a locked lesson | No navigation (row is a disabled hit area) | FACT (rows have no navigation effect in evidence) | SopiSkill shows the status but still opens (its own progression contract), so it renders a lock **badge** rather than disabling the link — documented difference |
| O4 | `Quá dễ? Quá khó?` | Opens tutor for course-level adjustment | FACT (label), effect UNKNOWN | Not rendered (no contract) |

## Lesson player

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| L1 | Next concept | Same route, block index changes, progress bar advances | FACT (`1/7` → `3/7`) | SopiSkill scrolls a single page; the progress indicator is recomputed from the worked block count |
| L2 | Back concept | Previous concept restored | FACT (button exists, `Khái niệm trước`) | Same |
| L3 | Glossary button | Opens glossary sheet | FACT (button), content UNKNOWN | Only rendered when lesson exposes glossary terms; otherwise hidden |
| L4 | `Hỏi Pol` | Opens the tutor sheet, docks it as a 400 px rail, narrows and re-centres the reading column | FACT (column moves 360 → 160, track 348 → 148, fixed CTA 866 → 666, page background unchanged, rail x 1040..1439) | Docked at ≥1024 px with a matching geometry (measured 2026-11-04); modal overlay below 1024 px, where a 720 px column and a 400 px rail cannot both fit |
| L5 | Close lesson | Returns to course overview | FACT | `router.push('/course/{id}')` with fallback to `/` |
| L6 | Inline term tap | Highlighted as a button (19/31 semibold ember) | FACT | Rendered as non-interactive emphasis unless a glossary exists |

## Quiz

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| Q1 | Select an option | Fill `--c-wash`, border 2 px `--c-ember`, letter turns white | FACT | Same |
| Q2 | `Kiểm tra` with no selection | Button disabled (`--c-sand` fill) | FACT | Disabled until every block is answered |
| Q3 | Submit | Inline feedback replaces the option row; correct band `--c-mossDeep` | FACT | Server grades; SopiSkill shows `✓ Đúng` / `✗ Sai` per block inline, plus the score box |
| Q4 | Wrong answer | Not observed | UNKNOWN | SopiSkill uses `--c-danger` / `--c-clayWash` for the wrong band |
| Q5 | Fill-in-the-blank | Tap a word chip to fill the next slot; tap a slot to remove | FACT | SopiSkill uses an input per blank (keeps the same visual chips for the sentence) |
| Q6 | After feedback | `Tiếp tục` advances | FACT | Next block / summary |

## Tutor

| # | Trigger | Reference | Confidence | SopiSkill |
|---|---|---|---|---|
| T1 | Open panel | Right sheet, 302 px content, header `Pol` + allowance | FACT | Right sheet, header shows course/lesson context and remaining quota from `/tutor/usage` |
| T2 | Send message | User bubble right-aligned ember, assistant bubble white with tool badge | FACT | Streaming text in the assistant bubble with a caret |
| T3 | Tool activity | Badge line (`đã đọc tài liệu nguồn`) under the assistant bubble | FACT | `tool` SSE events render as badges |
| T4 | Quick replies | 4 chips above the composer; the set changes after the first message | FACT | Contextual chips only when a thread has no messages yet is **PROPOSAL**; SopiSkill renders its own suggestion row from the current block |
| T5 | Stop | Not observed in this session | UNKNOWN | Existing `stopTutorMessage` + abort is preserved and rendered as `Dừng` |
| T6 | Quota exhausted | Composer disabled | INFERENCE (allowance shown) | Disabled with an explanatory notice |
