# 05 — Parity Matrix

Audit: `polyskill-parity-2026-11-04`
Reference: PolySkill (`https://web.polyskill.app`, API `https://api.polyskill.app/v1`)
Target: SopiSkill, branch `feat/p6.0-ci-pipeline`, HEAD `d747e78` + dirty working tree

This chapter scores the **50 scenarios defined in `03`**. Every row carries the evidence tier of its
reference cell, so the audit's central rule — *a client bundle declaration is never promoted to
runtime behaviour* — is auditable line by line rather than asserted once in prose.

No row was added, removed or re-scored after a score was computed.

## 1. Column and tier legend

### 1.1 Matrix columns (mandate §6.2)

`ID | Requirement/hành vi tham chiếu | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match 0/0.5/1/UNKNOWN | Severity | Gap type | Next test/fix`

### 1.2 Reference evidence tiers (`02` §1)

| Tier | Meaning | May be scored? |
|---|---|---|
| `E2` | Response **body** observed at runtime; field names/types are facts, values redacted | Yes |
| `E2O` | Runtime value transcribed by the owner from DevTools; not machine-captured | Yes, with the label |
| `E1` | Request/response observed, body filtered/truncated/unparsed | **No** — transport proves volume, not contract |
| `E0` | Declared in the Metro bundle / client schema only | **No** — proves the client knows the name |
| `UNKNOWN_REFERENCE` | No observation at any tier | No — **not** a gap claim |

### 1.3 Match values and gap types (`03` §1.2, mandate §6.3)

`1` matched · `0.5` partial · `0` reference fact exists, SopiSkill has nothing · `UNKNOWN` no
reference observation. Gap types: `MATCHED`, `PARTIAL`, `MISSING`, `UNTESTED`,
`UNKNOWN_REFERENCE`, `INTENTIONAL_DIFFERENCE`, `BLOCKED`.

**Severity is the severity of the *gap*, not of the requirement.** A `MATCHED` row is `—`.

---

## 2. Area A — onboarding / auth / dashboard / profile (weight 8)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| A01 | Authenticate and establish a session; mutations authorised | `PS-S-API-01` `/auth/exchange`, `/auth/refresh`, `/auth/signout` declared — **E0**. `PS-R-REFRESH-01` 7×401 burst recovered by `POST /auth/refresh → 200` — **E1**. `/auth/*` themselves never exercised | `SS-T-E2E-01` step 1: `POST /v1/auth/register → 201`, HttpOnly `access_token` + readable `csrf_token`. `SS-T-SEC-04/05/08`: no CSRF `403`, wrong CSRF `403`, tampered JWT `401` | Partial (E1) | **1** | — | `MATCHED` + `INTENTIONAL_DIFFERENCE` | None. Mechanism differs (JWT cookie vs OAuth exchange) with no business-outcome loss. Not counted toward Evidence Coverage |
| A02 | Dashboard / home surface | `PS-R-ENTITLE-01` `GET /me/entitlement → 200` `{tier,expiresAt,limits{courses,openUnits,tutorAllowance}}` — **E2** (adjacent surface). `GET /v1/home 200`, `GET /me/stats 200` — **E1**, body unparsed | `SS-C-FRONT-01` `frontend/src/app/page.tsx` renders course list, `totalXp`, resume lesson. `SS-T-E2E-02`: `GET /v1/me/stats` and `/v1/me/entitlement` → **404** | Partial (E1 for the scenario's own behaviour) | **0.5** | P2 | `PARTIAL` | Add `GET /v1/me/stats` + `/me/entitlement`. Capture the reference's `/home` body to fix the payload contract before building it |
| A03 | Profile / learner-view surface | `GET /me/profile 200` — **E1**, body unparsed. `PS-S-API-01` declares `/me/profile`, `/me/onboarding`, `/me/identities` — **E0** | `SS-C-AUTH-01` `UserOut = {id,email,displayName,xp}`; no profile route. Learner profile exists only as `proposal.payload.learnerProfile` (`SS-T-E2E-01` step 9) | No (E1/E0) | **0.5** | P2 | `PARTIAL` | Reference profile body was never captured — do **not** design from the field list. Build the surface from SopiSkill's own `learnerProfile` and reconcile later |
| A04 | Interview-driven personalization | 5 × `POST /courses/{id}/interview/answer → 200` — **E1**. Profile shape and extraction accuracy **UNKNOWN** at every tier | `SS-T-E2E-01` steps 3–8: 5 deterministic questions, `completedCount` 0→5. `SS-C-PEDAGOGY-01`: 4 provider-independent extraction defects (`'3 gio tuan' → 3`; `'mình muốn hiểu sâu' → balanced`; `'đồ thị và ví dụ thực tế' → []`; goal = longest answer) | Partial (E1) | **0.5** | P1 | `PARTIAL` | **SopiSkill-internal defect, not a proven parity gap.** Fix `_TIME_UNIT_MINUTES` (`gio`/`phut` absent), the depth parser and the style extractor. Backlog item stands on its own merits |

## 3. Area B — topic → interview → proposal → edit/approve (weight 18)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| B01 | Create a course from a topic | `PS-R-COURSEGEN-01` `POST /v1/courses → 201` — **E1** | `SS-T-E2E-01` step 2: `POST /v1/courses` + CSRF → `201 {id,topic,status,clientCourseId}` | Partial (E1) | **1** | — | `MATCHED` | SopiSkill additionally accepts a client `clientCourseId`; the reference's equivalent is declared **E0** only |
| B02 | Five-question interview with progress | 5 × `POST /interview/answer → 200` in one session — **E1**. The count is inferred from 5 POSTs, not read from a body | `SS-T-E2E-01` steps 3–8: `completedCount` 1→2→3→4→5; `course_service.INTERVIEW_QUESTIONS_COUNT = 5` | Partial (E1) | **1** | — | `MATCHED` | Reference progress field never captured. Scored on outcome + the 5-POST observation |
| B03 | Proposal payload | `POST /courses/{id}/approve → 200` — **E1** proves a reviewable proposal step exists. `GET /courses/{id}/plan` — **E0**. **Proposal payload shape never captured** | `SS-T-E2E-01` step 9: `GET /proposal → 200`, `version:1`, `approved:false`, `units[2]`, `skills[4]`, `outcomes[2]`, prerequisite chain, `learnerProfile` | Partial (E1) | **1** | — | `MATCHED` | Scored on the **outcome** (a proposal is produced and reviewed), not field identity. No similarity claim is made about contents |
| B04 | Edit / revise the proposal before approving | `PS-S-TOOLS-01` `revise_proposal` is one of 6 declared tutor tools — **E0**. `/courses/{id}/plan` — **E0**. Never exercised | `backend/app/api/v1/routes.py:100` — only `GET /proposal`. **No `PATCH`/`PUT` anywhere in `backend/app/api`.** `frontend/src/app/new/proposal/page.tsx` has approve + approved banner, no edit/revise control | No | `UNKNOWN` | P1 | `UNKNOWN_REFERENCE` | **Highest-severity unknown in area B**: plausibly present in the reference, provably absent in SopiSkill. Build edit-before-approve on product grounds; re-score when the reference behaviour is captured |
| B05 | Approve → generation dispatch | `PS-R-COURSEGEN-01`: `/approve → 200` then `/generation → 200` ×56 — **E1** | `SS-T-E2E-01` step 10: `POST /approve → 202 {jobId,status:"queued"}`; step 11: poll 0 `dispatched:true` | Partial (E1) | **1** | — | `MATCHED` | `202` + job id vs `200`: transport difference, no outcome loss |
| B06 | Course list and continue-learning | `GET /v1/home → 200` — **E1**. `PS-R-PATH-01` `upNextLessonId` — **E2** | `SS-T-E2E-01` step 13: `progress{completed,total,percent}`. `SS-C-FRONT-01`: `resumeLessonId`/`resumeLessonTitle` drive home + course pages | Partial (E1 + E2 on the resume half) | **1** | — | `MATCHED` | `resumeLessonId` vs `upNextLessonId` is naming only |

## 4. Area C — generation / status / retry / reliability (weight 14)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| C01 | Status polling until ready | `/generation → 200` ×56 — **E1**. `refetchInterval` 2000 ms unless ready/failed — **E0/STATIC** from the bundle | `SS-T-E2E-01` steps 11–12: poll 0 `queued/dispatched:true`, poll 1 `ready/stage:"done"`. `SS-C-FRONT-01`: same 2000 ms rule | Partial (E1 + static) | **1** | — | `MATCHED` | SopiSkill exposes richer counters (`lessonsDone`, `lessonsTotal`, `llmCalls`, `attempts`) |
| C02 | Generation reaches a ready state | 56 generation polls followed by grounded lesson content — **E2** (the lesson body is E2) | `SS-T-E2E-01` step 12: `ready` in ~2 s, 4 lessons of 4. `SS-T-EVAL-P22-01`: 12/12 topics pass with a **real** provider (`REPORTED`) | Yes (E2) | **1** | — | `MATCHED` | The E2E run itself used `LLM_PROVIDER=mock`; real-provider reliability is `REPORTED`, not observed here. One topic (`en-beginner-excel`) had `PROVIDER_BUDGET_EXCEEDED` |
| C03 | Retry a failed generation | `POST /courses/{id}/retry` — **E0**. Never exercised | `backend/app/api/v1/routes.py:135` `POST /courses/{id}/retry → 202`; not exercised in this audit | No | `UNKNOWN` | P2 | `UNKNOWN_REFERENCE` | Code present ≠ test passed (§6.3: no parity credit). Add a forced-failure E2E that asserts re-enqueue + idempotency |
| C04 | Generated course structure | `PS-R-PATH-01` `units[]` with `nodes[]{kind,lessonId,state,ready,format,contentVersion}` — **E2** | `SS-T-E2E-01` step 13: 2 units × 2 lessons, all `status:"ready"`, `contentVersion:1` | Yes (E2) | **1** | — | `MATCHED` | The flat `lessons[]` vs `nodes[]` shape difference is scored once, in D01 |
| C05 | Generation progress detail | 4 stage labels observed at runtime (`Đọc câu trả lời của bạn`, `Bổ sung kiến thức nền còn thiếu`, `Phác thảo lộ trình`, `Soạn bài học 1`) — **E2**, server-returned | `SS-T-E2E-01` step 12: `stage:"done"`, `lessonsDone`, `lessonsTotal`. `frontend/src/app/new/generating/page.tsx` uses **client-side** `STAGES` constants | Yes (E2) | **1** | — | `MATCHED` | Same outcome, different source of truth. If stage copy must match, move it server-side first |

## 5. Area D — lesson blocks / path / figures / glossary / navigation (weight 18)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| D01 | Learning-path structure and lock state | `PS-R-PATH-01`: `paywalled:true` on 2 of 3 units; node fields `state`, `ready`, `format`, `contentVersion` — **E2** | `SS-C-COURSE-01` `get_course_detail` returns `units[].lessons[]{id,orderIndex,title,status,contentVersion,completed}` + `progress`; **no** `paywalled`/`state`/`ready`/`format`/`nodes[]`. `SS-C-PATH-01` `learning-path` exists behind `P50_ENABLED` with a different contract. `SS-C-FRONT-01` 0 hits for `paywal|upNext|format` | Yes (E2) | **0.5** | P2 | `PARTIAL` | Scores the **field surface**, not enforcement (`paywalled` enforcement is `UNKNOWN`, `02` §9). Add `state`/`format` to the course contract; decide on `paywalled` only when billing is in scope |
| D02 | Continue/next-lesson marker | `PS-R-PATH-01` `upNextLessonId: string` — **E2** | `SS-T-E2E-01` step 13 + `SS-C-FRONT-01`: `resumeLessonId` drives the resume control on home and course pages | Yes (E2) | **1** | — | `MATCHED` + `INTENTIONAL_DIFFERENCE` | Field name only |
| D03 | Lesson payload with all six block types | `PS-R-LESSON-01`: `teach \| mc \| blank \| order \| match \| short` — **E2** | `SS-T-E2E-01` step 14: 6 blocks each, exactly `teach, mc, blank, order, match, short`. `SS-C-BLOCKS-01`: all six renderers exist | Yes (E2) | **1** | — | `MATCHED` | **Strongest single parity result**: identical six-type taxonomy reached independently |
| D04 | Figures (formula / visual / diagram) | `PS-R-LESSON-01`: `figure{kind,nodes,rows,head,edgeLabels,groupLabels}` — **E2**. `kind ∈ {formula,visual,diagram}` — **E0**. **No rendered formula captured** | `SS-C-NOFIG-01`: no `figure` field on any block schema. `SS-C-FRONT-01`: 0 hits for `figure` in the lesson page; no figure component in `frontend/src/components/` | Yes (E2 for the field) | **0** | P2 | `MISSING` | Reference rendering fidelity is `UNKNOWN`; the gap is scored on the **modality**, proven on both sides. New block type + renderer + prompt schema change |
| D05 | Glossary | `PS-R-GLOSSARY-01` `GET /courses/{id}/glossary → 200` (2.2 KB), `terms[11]{key,kind,name,short,more,teaser,firstSeen{unit,lesson}}` — **E2** | `SS-C-NOGLOSS-01`: `glossary`, `termKey`, `term_key` **absent from the entire repo**; no glossary component, no route | Yes (E2) | **0** | P1 | `MISSING` | Whole navigation surface absent. The reference's unit/lesson provenance (never a source page) is a **design choice**, not a defect — replicate the choice, not the code |
| D06 | Inline term linkage (`paragraphs[].termKey`) | `PS-R-LESSON-01` `lesson.paragraphs[].termKey` — **E2** | `SS-C-NOGLOSS-01`: no `termKey` anywhere; `teach` blocks are `{title,paragraphs: string[]}` with no linkage | Yes (E2) | **0** | P1 | `MISSING` | Depends on D05. Requires a content-generation change, not only a UI change |
| D07 | Block-by-block navigation | `PS-R-LESSON-01` establishes an ordered `blocks[]` — **E2**. The stepper control itself was not separately captured | `SS-C-BLOCKS-01` + `SS-C-FRONT-01`: the 828-line lesson page implements an ordered stepper over the same six types | Yes (E2 for ordering) | **1** | — | `MATCHED` | Scored on the ordered-block business outcome. The reference's exact stepper UI is **not** asserted |
| D08 | Next-lesson prefetch | `GET /v1/lessons/{id}?prefetch=1 → 200 (2.8 KB)` — **E2**, parameter and use directly observed | `SS-C-FRONT-01`: **0 hits** for `prefetch` in `frontend/src`; the lesson endpoint accepts no such parameter | Yes (E2) | **0** | P3 | `MISSING` | Perceived-latency feature, not functional. **Justify by measurement**, not by imitation — TanStack Query caching may already cover it |
| D09 | Content version exposure | `PS-R-LESSON-01` `lesson.contentVersion: int` — **E2**. The reference's stale-handling behaviour is `UNKNOWN` | `SS-C-VERSION-01`: `409 CONTENT_VERSION_MISMATCH` on submitted-version mismatch, verified by test. `SS-T-E2E-01` step 14: `contentVersion:1` on every lesson | Yes (E2 for the field) | **1** | — | `MATCHED` | SopiSkill's behaviour is strictly stronger; the reference's is unmeasured |

## 6. Area E — quiz / grading / progress / attempts / rewards (weight 12)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| E01 | Server-side grading of all five quiz types | `PS-R-ATTEMPT-01` `POST /lessons/{id}/attempts → 201`, `score{correct,total}` — **E2**. The **client sends `correct` per result**; server grading policy **UNKNOWN** | `SS-C-GRADE-01` (`lesson_content.py:155–258`): `mc` matches `answerIndex`, rejects `bool`; `blank`/`short` `_normalize_text` (strip+casefold+collapse), `short` against **every** `acceptedAnswers`; `order` un-shuffles then demands the exact permutation; `match` requires **every** left paired and rejects any wrong pair. `SS-T-E2E-01` step 15: 4 attempts → `201`, `score{correct:0,total:5}`, per-block `solution` | Yes (E2) | **1** | — | `MATCHED` | SopiSkill's grading is provably server-authoritative; the reference's is not established either way |
| E02 | Attempt idempotency and version pinning | `PS-R-ATTEMPT-01`: request carries `clientAttemptId` + `contentVersion`; response carries `duplicate` — **E2** | `SS-C-ATTEMPT-01/02`: idempotent on `(lesson,user,clientAttemptId)`; `409` on version mismatch; `AttemptAnswer(extra="forbid")` rejects a client `correct` flag; XP re-checked under `SELECT … FOR UPDATE` (`lesson_service.py:117`) | Yes (E2) | **1** | — | `MATCHED` | Same three concepts, independently derived |
| E03 | Progress accounting | `PS-R-PATH-01` `progress{completed,total,percent}` — **E2** | `SS-T-E2E-01` step 13: `progress{completed:0,total:4,percent:0}`; completion `correct*100 >= total*80` (`lesson_content.py:316–323`) | Yes (E2) | **1** | — | `MATCHED` | The reference's completion threshold is `UNKNOWN`; SopiSkill's 80 % rule is a documented `PROPOSAL` |
| E04 | XP and rewards | `PS-R-REWARDS-01` `rewards{xp,totalXp,streakDays,streakExtended,freezeBanked,hearts{count,max,nextRefillAt},goal{earnedToday,target,met},levelsEarned[],milestonesEarned[],flagged}` — **E2 names only**; every behaviour `UNKNOWN` | `SS-C-XP-01` `rewards{xp,xpEarned}`; monotonic top-up `max(0, desired − already)`; `XP_PER_CORRECT=10`, `XP_LESSON_COMPLETED_BONUS=20`; `rewards.xp` is absolute user XP | Yes (E2) | **0.5** | P2 | `PARTIAL` | XP works; the broader reward vocabulary is absent. `totalXp` vs `xp` naming is recorded in `e2e-chain.log` and is not itself a gap |
| E05 | Streak / hearts / goal / levels / milestones / flagged | `PS-R-REWARDS-01` — **E2** field names are facts; depletion, refill, freeze, reset cadence and `flagged` semantics are **all `UNKNOWN`** (`02` §9) | `SS-C-STREAK-01` `User.streak_days` column exists but is **never exposed in any API response**. `SS-C-FRONT-03`: 0 occurrences of `hearts`/`streak` in the frontend; no goal/level/milestone logic | Yes (E2 for the surface) | **0** | P2 | `MISSING` (surface) | No behavioural parity requirement is proven — only the surface. **A column is not a feature.** Do not build mechanics whose rules are unobserved |

## 7. Area F — tutor context / streaming / history / tools / allowance (weight 18)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| F01 | Course-scoped tutor thread | `PS-R-TUTOR-01` `GET /courses/{id}/tutor?entryPoint=…&lessonId=…&blockIndex=…&threadId=… → 200` returning `{threadId,kind,sealed,title,nextCursor,messages,allowance,limit}` — **E2**; the 328 B init response is consistent with an empty thread | `SS-C-TUTOR-04` + `SS-C-FRONT-04`: `POST /tutor/messages` creates/continues via `threadId`; `GET /tutor/threads` + `/threads/{id}` exist; `x-tutor-thread-id` surfaces the id | Yes (E2) | **1** | — | `MATCHED` | Reference fetches-or-creates on GET; SopiSkill creates on first POST. SopiSkill does not expose `kind`/`sealed`/`nextCursor` |
| F02 | Message history with per-message context label | `PS-R-TUTOR-01` `contextLabel` on **8/8** and again **16/16** messages across two independent sessions — **E2** | `SS-C-FRONT-04` `TutorMessage` has `contextRef: Record<string,unknown> \| null`, not a label; no `contextLabel` string in the codebase | Yes (E2) | **0.5** | P3 | `PARTIAL` | History persists; only the human-readable label is missing. `contextRef` carries the same information in machine form |
| F03 | Request carries an entry point and context reference | `PS-R-TUTOR-02` POST body `{clientMessageId,entryPoint,contextRef{lessonId,blockIndex},text,threadId}`; `entryPoint` observed `teach_block` — **E2**. 6 declared entry points — **E0** | `SS-C-TUTOR-04` `{clientMessageId,threadId?,text,contextRef{lessonId,blockIndex}}`, `extra="forbid"`; **no `entryPoint`**. `SS-C-FRONT-04`: 0 hits for `entryPoint` in `TutorPanel.tsx` | Yes (E2) | **0.5** | P2 | `PARTIAL` | Server cannot distinguish `wrong_answer` from `teach_block`, limiting analytics. **SopiSkill is stronger on one axis**: it re-resolves `contextRef` from the DB and bounds-checks `blockIndex` (`tutor.py:10–14`) |
| F04 | SSE streaming of the reply | `PS-R-SSE-01` `delta {text}` then terminal `done {threadId,message}` — **E2O** (owner-transcribed). REA 6.7.0 has **no `text/event-stream` parser** | `SS-C-TUTOR-01` emits `delta, done, error, tool, citations, cancelled, heartbeat`; `SS-C-FRONT-04` parses all but `heartbeat`; `test_sse_frame_escapes_newlines_and_is_single_data_line`. **Runtime BLOCKED**: `TUTOR_ENABLED=false` → `503 TUTOR_DISABLED` (`SS-T-E2E-03`) | Partial (E2O) | **1** | — | `MATCHED` (runtime `UNTESTED`) | Both implement delta+done. The **runtime** claim is withheld. Re-run behind `TUTOR_ENABLED=true` and capture frames |
| F05 | Tool calls surfaced to the learner | `PS-R-TUTOR-01` `toolCalls[4]` observed, rising 3→4 after one quick action — **E2**; **no tool name ever exposed**. 6 names declared — **E0** | `SS-C-TOOLS-01`: 3 tools (`read_lesson, explain_deeper, read_source`), `extra="forbid"`. `SS-C-TOOLS-02`: `{name, summary, ok→status}` recorded per execution and surfaced in the UI | Yes (E2 for the surface) | **0.5** | P2 | `PARTIAL` | Reference names 6 but never proved 3 of them run. SopiSkill's 3 are implemented and attributable. `regenerate_unit`/`flag_question`/`revise_proposal` have no counterpart |
| F06 | Confirmation gate for side-effecting actions | `PS-S-SSE-01` `confirm` declared — **E0**. At runtime `action` stayed `null` on **14/14 and 16/16** messages; the owner deliberately declined to manufacture it | `SS-C-TUTOR-01`: no `confirm` event; no action/approval model anywhere in the tutor | No | `UNKNOWN` | P2 (latent) | `UNKNOWN_REFERENCE` | Low today; **high if** the confirm gate is what makes `regenerate_unit`/`revise_proposal` safe. Prerequisite for F05 expansion |
| F07 | Tutor allowance / quota | `PS-R-ALLOW-01` `allowance{limit,remaining}` + `limit{limit,remaining,resetAt}`; UI 19 → 18 after one turn — **E2** | `SS-C-TUTOR-05` `{messagesPerDay,tokensPerDay,maxConcurrentStreams}` + `remaining{messages,tokens}` + `tokensKnown`; `GET /tutor/usage` verified **not** to consume quota (`tutor.py:211`); panel renders `còn X/Y lượt` | Yes (E2) | **1** | — | `MATCHED` | SopiSkill uses a 24 h window; the reference's two-level `limit`/`allowance` semantics were never fully separated |
| F08 | Stop / regenerate an in-flight reply | `POST /courses/{id}/tutor/messages/{messageId}/stop` — **E0**. Never exercised | `SS-C-TUTOR-03`: `cancel_requested_at` flag, producer stops, emits `cancelled` with partial content; `TutorPanel.tsx` handles `status === "cancel_requested"` and `TUTOR_STOP_NOT_FOUND` | No | `UNKNOWN` | P3 | `UNKNOWN_REFERENCE` | Best-effort cancel; does not refund provider cost. SopiSkill may be **ahead**, but the reference never demonstrated it → no credit |
| F09 | Resume a stream via `Last-Event-ID` | `last-event-id` in the bundle's SSE header list — **E0**. Never exercised | `SS-C-TUTOR-02`: an explicit documented decision — resume **not supported**, `replaySupported=false` returned to the client | No | `UNKNOWN` | P3 | `UNKNOWN_REFERENCE` | Honest documented divergence. Becomes P2 if resume proves load-bearing for mobile network loss |

## 8. Area G — sources: PDF / web / arXiv / provenance / citations (weight 9)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| G01 | Upload and ingest a PDF | `PS-R-INGEST-01` `POST /v1/sources/upload → 201`, `POST /sources/{id}/ingest → 202`, poll until the brief is populated — **E2** | `SS-T-INGEST-01`: create `201`, upload `202 {status:"queued",pageCount:3}`, poll[0] `queued` → poll[1] `ready`, `chunkCount:3`, `textSource:"native"`, preview populated | Yes (E2) | **1** | — | `MATCHED` | Pipeline `p4.0-v1`; PDFs capped at 20 MiB / 300 pages (`SS-C-INGEST-02`) |
| G02 | Source ingest brief | `PS-R-BRIEF-01` `brief{what,claims[≤10],notation[≤20],assumes[≤10],sections[]{anchor,heading,gist}}` — a 3-page fixture produced exactly 3 section objects — **E2**. Chunker strategy `INFERENCE` | `SS-C-INGEST-01`: 15 source routes, **no brief concept** anywhere; the document endpoint returns status/chunkCount/preview only | Yes (E2) | **0** | P2 | `MISSING` | The brief is the reference's human-readable bridge from source to course. Scored on existence, proven on both sides. Section-count==page-count is **not** evidence of chunking strategy (`02` §3.8) |
| G03 | Source kinds: PDF / web / arXiv | `PS-S-API-01` enum `arxiv\|web\|pdf` — **E0**; the upload path exercised with a PDF — **E2**. Web/arXiv rejection reasons declared, never triggered | `SS-C-INGEST-02`: `ingestEnabled:true`, `webEnabled:false`, `arxivEnabled:false`; kind enum `official_documentation\|academic\|user_document\|webpage`. `SS-T-INGEST-02`: RAG search `503` | Partial (E2 for PDF only) | **0.5** | P2 | `PARTIAL` | PDF works end-to-end; web ingest is **coded but disabled**; arXiv absent. Enum naming is not itself a gap — the capability is |
| G04 | Link a source to a course, with source evaluation | Not exercised — the reference course was topic-based with `source: null` (`PS-R-LESSON-01`, E2) | `SS-T-INGEST-01`: `POST /courses/{id}/sources → 201` returns source + 6-criterion evaluation (`authority 0.45 weak`, `relevance 0.9`, `freshness unknown`, `evidence 0.65`, `consistency unknown`, `licensing 0.6`, `weightedScore 0.55`, `verdict moderate`) | No | `UNKNOWN` | P3 | `UNKNOWN_REFERENCE` | Independent surface with no observed counterpart. `SS-T-INGEST-03` records that unknown criteria are **excluded** from the weighted score rather than scored zero |
| G05 | Citation contract and honesty | `PS-R-CITE-01`: `cite{anchor,label}` on 3 of 7 blocks; label↔page and content match verified; locator `PARTIAL` (anchor never string-matched); **not navigable** — inert `StaticText`, `states:[]`, 0/33 buttons matched — **E2**. `PS-R-CITE-02` U+4E00 defect — **E2** | `SS-C-CITE-01`: real citation card with title/url, `sourceVersion`, `pageNumber`, `validationStatus` badge, `evidenceText` quote, honesty caveat, separate `insufficientEvidence` path. `SS-C-CITE-02`: 4-level honesty ladder with `evidenceSupported` **always false** in P4.1 | Yes (E2) | **1** | — | `MATCHED` + `INTENTIONAL_DIFFERENCE` (in SopiSkill's favour) | SopiSkill is strictly more honest and more usable (navigable, explicit insufficient-evidence state). The reference's U+4E00 defect has no counterpart |
| G06 | Query-time retrieval (RAG) | **`INFERENCE` only** — no client-side signal proves server-side RAG (`02` §10); embeddings and vector store `UNKNOWN`. **Not a gap claim** | `SS-T-INGEST-02`: both a positive and a negative query returned `503 RAG_NOT_ENABLED`. `SS-T-EVAL-RAG-01` (offline, enabled): recall@6 `1.0`, MRR `0.9643`, abstention `1.0`, using a **lexical** hashing embedding — explicitly not semantic | No | `UNKNOWN` | — | `BLOCKED` | Configuration state, not a code defect: the path exists and has an eval. No parity claim is possible in either direction |

## 9. Area H — UX / accessibility / robustness (weight 3)

| ID | Requirement | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| H01 | Keyboard navigation and focus order | A11y tree captured (33 buttons in one view) — **E2**; **no keyboard traversal**, no focus order recorded | No a11y or keyboard audit run. `useModalPanel`/`useMediaQuery` helpers exist; no documented focus-management contract | No | `UNKNOWN` | P2 | `UNKNOWN_REFERENCE` | Untested on both sides; requires an explicit a11y harness. Not inferable from source |
| H02 | Accessible names and semantics | A11y tree captured with labelled `StaticText` and 33 buttons — **E2**; a CJK mis-render appeared in 3 a11y nodes (`PS-R-CITE-02`) | No a11y tree captured; no evidence either way | Partial (E2, incomplete) | `UNKNOWN` | P2 | `PARTIAL` | The only H row with any reference observation, still insufficient to score |
| H03 | Responsive / mobile layout | `PS-S-STACK-01` Expo SDK 57 / RN Web — **E0**. No viewport-specific rendering captured | `frontend/src/app/globals.css` (78.3 K, self-authored) + `useMediaQuery`; **no viewport test run**, no screenshot | No | `UNKNOWN` | P2 | `UNKNOWN_REFERENCE` | Per the standing rule (`03` §1.4) no responsive claim is made without browser verification |
| H04 | Error / empty / loading states | None captured. `TUTOR_LIMIT_REACHED` + source rejection reasons declared — **E0**, never triggered | `SS-C-FRONT-01`: `Skeleton`, explicit error copy, `p50Disabled` on 503, `TUTOR_STOP_NOT_FOUND`, `TUTOR_DISABLED` surfaced — **coded, not exercised in a browser** | No | `UNKNOWN` | P3 | `UNTESTED` | Coded states are not verified states |
| H05 | Multi-language UI | `PS-S-I18N-01` bundle strings in multiple languages incl. Italian ("Il ragionamento di Pol") — **E0**. Never switched at runtime | `SS-C-LANG-01`: UI and provider prompts hardcoded Vietnamese; no i18n layer; `LLMProvider` has no `language` parameter in any of its six abstract methods (`providers/openai_compatible_provider.py:58,228`) | No | `UNKNOWN` | P2 | `UNKNOWN_REFERENCE` | Scored `UNKNOWN` because the reference's runtime switching was never exercised. The **SopiSkill-side deficiency is independently proven** by `language_quality = 2.27` and 6/6 English topics delivered in Vietnamese |
| H06 | Rate limiting, long-running work, offline | `PS-S-STACK-01` `expo-sqlite` (WAL) — **E0**, never exercised. `PS-R-REFRESH-01` 7×401 → refresh is a client retry pattern, not a server throttle — **E1** | `SS-T-SEC-01..08`: CSRF/JWT enforced; `app/core/limits.py` is a **per-process in-memory** limiter (scaling limitation, not a parity gap); no offline support | No | `UNKNOWN` | P3 | `UNKNOWN_REFERENCE` | The in-memory limiter is recorded in `10` as a known limitation; it does not affect parity because the reference's limiter was never observed |

---

## 10. Distribution

Every count and weight below is summed from the 50 rows above, not asserted.

| Match | Scenario IDs | Rows | Weight |
|---|---|---|---|
| `1` | A01 · B01 B02 B03 B05 B06 · C01 C02 C04 C05 · D02 D03 D07 D09 · E01 E02 E03 · F01 F04 F07 · G01 G05 | 22 | **53.0** |
| `0.5` | A02 A03 A04 · D01 · E04 · F02 F03 F05 · G03 | 9 | **18.0** |
| `0` | D04 D05 D06 D08 · E05 · G02 | 6 | **12.0** |
| `UNKNOWN` | B04 · C03 · F06 F08 F09 · G04 G06 · H01–H06 | 13 | **17.0** |
| **Total** | | **50** | **100.0** |

The 13 `UNKNOWN` rows are exactly the 11 `NOT OBSERVABLE` scenarios of `03` §10 plus `BLOCKED`
G06, plus all six area-H rows (which `03` classified `NOT OBSERVABLE`/`PARTIAL` but which carry no
match value of any kind). Their weight — 3 + 3 + 2 + 2 + 2 + 1 + 1 + 3 — is **17.0**, matching
`03` §10's `Unknown/Blocked Weight = 17 %` exactly.

### 10.1 Per-area subtotals

| Area | Weight | Weighted match | Scored weight | Unknown weight |
|---|---|---|---|---|
| A — onboarding/auth/dashboard/profile | 8 | 5.0 | 8 | 0 |
| B — topic→interview→proposal→approve | 18 | 15.0 | 15 | 3 |
| C — generation/status/retry | 14 | 11.0 | 11 | 3 |
| D — lesson/path/figures/glossary | 18 | 9.0 | 18 | 0 |
| E — quiz/grading/rewards | 12 | 9.0 | 12 | 0 |
| F — tutor | 18 | 9.0 | 12 | 6 |
| G — sources/citations | 9 | 4.0 | 7 | 2 |
| H — UX/a11y/robustness | 3 | 0.0 | 0 | 3 |
| **Total** | **100** | **62.0** | **83** | **17** |

### 10.2 The three figures this matrix feeds into `06`

| Figure | Value | Definition |
|---|---|---|
| `Measured Parity` | **62.0 / 83 = 74.7 %** | `Σw·match / scored weight`. `UNKNOWN` rows are excluded from both sides — they are neither credit nor penalty |
| `Conservative Floor` | **62.0 %** | `Σw·match / 100`. Unmeasured weight contributes **0** regardless of whether SopiSkill implements it — a **mathematical lower bound**, not a claim that those features are broken or absent |
| `Unknown/Blocked Weight` | **17.0 %** | `Σw(UNKNOWN) / 100` |

The **optional upper bound** (`Floor + Unknown = 79.0 %`) is computable but is **not a measured
score** and must never be reported as one — it assumes every unmeasured row would score `1`.

`Evidence Coverage` is **not** derivable from this table alone: it requires per-row judgement about
whether the reference evidence is *strong runtime* evidence. That computation, with its
row-by-row ledger, is in `06` §2.

### 10.3 Why 74.7 % is not 99 %

The 17 unknown points are excluded from `Measured Parity`, so `74.7 %` is the parity of exactly the
83 points the audit could score — and even there the matrix contains 12.0 weight of hard `MISSING`
(glossary, termKey, figures, prefetch, gamification surface, ingest brief) and 18.0 weight of
`PARTIAL`. Neither 74.7 % nor the 79.0 % upper bound approaches the 99 % gate.

---

## 11. Operational findings that are not parity gaps

These were observed during the run and are recorded here so they are not mistaken for matrix rows.
They are scored nowhere.

| Finding | Class | Consequence |
|---|---|---|
| Tutor returns `503 TUTOR_DISABLED` with default configuration (`tutor_enabled: bool = False`, `config.py:95`) | `SOPISKILL_CODE` + runtime | The E2E chain cannot reach the tutor step. **Operational P0**, not a parity gap — the code path exists and its tests pass. See `07` |
| Running backend reports `provider: "mock"` | Runtime | Every generated lesson in this audit is mock content. Real-provider quality comes only from `REPORTED` eval artefacts. See `08` |
| Earlier "generation BLOCKED" finding | Retracted | Caused by host uvicorn on `:8000` with CWD-relative `.env` → `celery_broker=None`. **Not product code.** Retracted in `logs/e2e-chain.log` |
| `/v1/me/stats`, `/v1/me/entitlement` → `404` | `SOPISKILL_CODE` | Endpoints do not exist. Scored inside A02, not as a separate row |
| No `PATCH`/`PUT` in `backend/app/api` | `SOPISKILL_CODE` | Makes B04 a hard absence on the SopiSkill side |

## 12. What this matrix does not claim

- It does not count any `E0` or `E1` reference cell as a scored contract. Rows resting on `E1` are
  scored on **business outcome**, and that is stated in the row.
- It does not treat an `UNKNOWN` row as a defect in SopiSkill. `UNKNOWN` contributes **zero** to
  both the numerator and the denominator.
- It does not claim any SopiSkill UI behaviour was verified in a browser.
- It does not claim the reference grades attempts server-side, consumes its `contextRef`, or runs
  retrieval — all three remain `UNKNOWN`/`INFERENCE`.
- It does not give any row credit for matching endpoint names, component names or schemas. D03 and
  E01–E02 are `1` because the **outcomes** match; D01 and E04 are `0.5` despite similar names.
