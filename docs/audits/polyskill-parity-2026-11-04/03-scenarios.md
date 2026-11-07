# 03 — Scenarios

Audit: `polyskill-parity-2026-11-04`
Reference: PolySkill (`https://web.polyskill.app`, API `https://api.polyskill.app/v1`)
Target: SopiSkill, HEAD `d747e78` + dirty working tree

This chapter defines the **50 scenarios** that the parity matrix (`05`) scores. Every scenario is
stated before its score so the scoring is auditable; none was rewritten after a result was seen.

## 1. Method and vocabulary

### 1.1 Scenario result classes

| Class | Meaning in this audit |
|---|---|
| `OBSERVED` | Both sides have an observation sufficient to assign a match value. |
| `PARTIAL` | One side is observed, the other is only partly observable (e.g. runtime blocked but tests pass). |
| `BLOCKED` | The behaviour could not be produced on at least one side because of configuration/permission, not because of product code. |
| `NOT OBSERVABLE` | The reference never exercised the behaviour; no match value can be assigned. |

`NOT OBSERVABLE` is **not** a gap claim. Per `02` §1, absence of a capture is not evidence of absence.

### 1.2 Match values

`1` = matched (both sides achieve the same core business outcome, even with different field names or
mechanisms) · `0.5` = partial · `0` = missing on the SopiSkill side while a reference fact exists ·
`UNKNOWN` = no reference observation. `UNKNOWN` is never counted as a match.

### 1.3 Weight allocation (declared before scoring)

The eight area weights are fixed by mandate §7.1 and were **not** adjusted after results were seen:
A=8, B=18, C=14, D=18, E=12, F=18, G=9, H=3 → 100.

Scenario counts inside each area were chosen so the area weight divides exactly where possible.
Where it does not, integer sub-weights are assigned and sum exactly to the area weight. Half-point
weights (H) are exact in binary floating point and introduce no rounding.

| Area | Scenarios | Count | Sub-weights |
|---|---|---|---|
| A — onboarding/auth/dashboard/profile | A01–A04 | 4 | 2 each |
| B — topic → interview → proposal → edit/approve | B01–B06 | 6 | 3 each |
| C — generation/status/retry/reliability | C01–C05 | 5 | 3,3,3,3,2 |
| D — lesson blocks/path/figures/glossary/navigation | D01–D09 | 9 | 2 each |
| E — quiz/grading/progress/attempts/rewards | E01–E05 | 5 | 3,3,2,2,2 |
| F — tutor context/streaming/history/tools/allowance | F01–F09 | 9 | 2 each |
| G — sources PDF/web/arXiv/provenance/citations | G01–G06 | 6 | 2,2,2,1,1,1 |
| H — UX/accessibility/robustness | H01–H06 | 6 | 0.5 each |
| **Total** | | **50** | **100** |

### 1.4 Standing caveat on every SopiSkill frontend observation

The container runs HEAD `d747e78`. The working tree is dirty (`01` §1). Every frontend statement
below is either `HEAD/BUILD` (the built bundle) or `WORKING_TREE` (the file on disk). The two are
never merged into a single claim, and no runtime UI behaviour was exercised in a browser this
audit — **no screenshot-verified UI claim is made anywhere in this audit.**

---

## 2. Area A — onboarding / auth / dashboard / profile (8)

### A01 — Authenticate and establish a session (weight 2)
- **Precondition / steps:** No session. Register a new account, then replay a mutating request with and without the CSRF token.
- **Expected (reference):** A session is established and subsequent mutations are authorised.
- **Reference evidence:** `PS-S-API-01` — `/auth/exchange`, `/auth/refresh`, `/auth/signout` are declared in the bundle (E0); `PS-R-REFRESH-01` — a 7×401 burst recovered via `POST /auth/refresh → 200` (E1). The `/auth/*` routes themselves were **never exercised** in the captured sessions; the session is only implied by the fact that every recorded owner session was `EXECUTED`.
- **SopiSkill evidence:** `SS-T-E2E-01` step 1 — `POST /v1/auth/register → 201` sets HttpOnly `access_token` + readable `csrf_token`; `SS-T-SEC-04/05/08` — POST without CSRF `403`, wrong CSRF `403`, tampered JWT `401`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Mechanism differs (JWT cookie vs OAuth exchange) — an `INTENTIONAL_DIFFERENCE` that loses no business behaviour. Because the reference evidence is E0+inference, this row does not count toward Evidence Coverage.

### A02 — Dashboard / home surface (weight 2)
- **Precondition / steps:** Authenticated user with at least one course opens the home screen.
- **Expected (reference):** Home lists courses and shows XP; `/me/stats` returns XP/streak/hearts.
- **Reference evidence:** `PS-R-ENTITLE-01` — `GET /me/entitlement → 200` (E2); `PS-S-API-01` — `/me/stats`, `/home`, `/me/notifications` declared; `GET /v1/home 200` and `GET /me/stats 200` appear in the `polyskill-dynamic-analysis.md` request log (E1, body unparsed).
- **SopiSkill evidence:** `SS-C-FRONT-01` — `frontend/src/app/page.tsx` renders the course list, `totalXp`, resume lesson; `SS-T-E2E-02` — `GET /v1/me/stats` and `/v1/me/entitlement` → **404** (routes do not exist).
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Medium — the dashboard exists but the stats/entitlement surface is absent. **Notes:** Absence of `/me/stats` is recorded as a missing endpoint, not as a bug; no notification surface exists on either side that this audit observed.

### A03 — Profile / learner-view surface (weight 2)
- **Precondition / steps:** Authenticated user opens the profile area.
- **Expected (reference):** A profile view distinct from the course list.
- **Reference evidence:** `GET /me/profile 200` in the reference request log (E1); `PS-S-API-01` declares `/me/profile`, `/me/onboarding`, `/me/identities`.
- **SopiSkill evidence:** `SS-C-AUTH-01` — `UserOut = {id,email,displayName,xp}` and no profile route; the learner profile exists only as `proposal.payload.learnerProfile` (`SS-T-E2E-01` step 9).
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Low. **Notes:** The learner-profile *data* exists and is richer than a bare user record, but there is no surface to view or edit it.

### A04 — Interview-driven personalization (weight 2)
- **Precondition / steps:** New course; answer 5 interview questions including style/depth preferences.
- **Expected (reference):** Answers drive a learner profile used to shape the course.
- **Reference evidence:** `POST /courses/{id}/interview/answer → 200` ×5 (E1, body unparsed). The reference's profile shape and extraction accuracy are `UNKNOWN` at every tier.
- **SopiSkill evidence:** `SS-T-E2E-01` steps 3–8 — 5 deterministic questions, `completedCount` 0→5; `SS-C-PEDAGOGY-01` — `learnerProfile` shape verified, but four provider-independent extraction defects reproduced by direct call (`'3 gio tuan' → 3` should be 180; `'mình muốn hiểu sâu' → balanced` should be deep; `'đồ thị và ví dụ thực tế' → []`; goal = longest answer).
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Medium — personalization is the product's differentiator and it currently mis-extracts common Vietnamese inputs. **Notes:** The reference's extraction quality is unmeasured, so this is a **SopiSkill-internal defect**, not a proven parity gap. It is still a P1 backlog item on its own merits.

---

## 3. Area B — topic → interview → proposal → approve (18)

### B01 — Create a course from a topic (weight 3)
- **Precondition / steps:** Authenticated. Submit a topic string.
- **Expected (reference):** A course record is created in an interview-pending state.
- **Reference evidence:** `PS-R-COURSEGEN-01` — `POST /v1/courses → 201` (E1).
- **SopiSkill evidence:** `SS-T-E2E-01` step 2 — `POST /v1/courses` + CSRF → `201 {id, topic, status, clientCourseId}`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill additionally accepts a client-supplied `clientCourseId` for idempotency; the reference's equivalent is `clientCourseId` in the bundle but was not observed.

### B02 — Five-question interview with progress (weight 3)
- **Precondition / steps:** Course in `interview` state. Answer questions 1..5.
- **Expected (reference):** Exactly 5 questions; progress advances per answer.
- **Reference evidence:** 5 × `POST /interview/answer → 200` in one session (E1). The question count is inferred from 5 POSTs, not read from a response body (E1-strength only).
- **SopiSkill evidence:** `SS-T-E2E-01` steps 3–8 — 5 questions, `completedCount` 1→2→3→4→5; `course_service.INTERVIEW_QUESTIONS_COUNT = 5`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Reference progress field not captured; the 5-POST count is the evidence, and it is recorded as such.

### B03 — Proposal payload (weight 3)
- **Precondition / steps:** All 5 answers submitted. Open the proposal.
- **Expected (reference):** A structured plan the learner reviews before generation.
- **Reference evidence:** `POST /courses/{id}/approve → 200` (E1) proves a reviewable proposal step exists; `PS-S-API-01` declares `GET /courses/{id}/plan`. The reference **proposal payload shape was never captured** (`/plan` was never exercised).
- **SopiSkill evidence:** `SS-T-E2E-01` step 9 — `GET /proposal → 200`, `version:1`, `approved:false`, `units[2]`, `skills[4]`, `outcomes[2]`, prerequisite chain, `learnerProfile`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Scored 1 on the *outcome* (a proposal is produced and reviewed), not on field identity. The reference's payload contract is `UNKNOWN`; no similarity claim is made about its contents.

### B04 — Edit / revise the proposal before approving (weight 3)
- **Precondition / steps:** Proposal displayed. Learner tries to change scope, difficulty or unit order, then approve.
- **Expected (reference):** Proposal is editable prior to approval.
- **Reference evidence:** `PS-S-TOOLS-01` — `revise_proposal` is one of the 6 declared tutor tools (E0); `/courses/{id}/plan` declared (E0). **Never exercised at runtime.** This is `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `backend/app/api/v1/routes.py:100` — only `GET /courses/{id}/proposal` exists; no `PATCH`/`PUT`; `frontend/src/app/new/proposal/page.tsx` has an approve control and an approved banner but **no edit/revise controls**.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** **Medium — highest-severity unknown in area B.** The capability is plausibly present in the reference and provably absent in SopiSkill. **Notes:** Satisfying §6.3, it is not scored `MISSING` because the reference proof is E0 only. It is still a P1 backlog item: edit-before-approve is a normal product expectation and the absence is confirmed on the SopiSkill side independently of the reference.

### B05 — Approve → generation dispatch (weight 3)
- **Precondition / steps:** Learner approves the proposal.
- **Expected (reference):** Approval enqueues generation; subsequent polls advance.
- **Reference evidence:** `PS-R-COURSEGEN-01` — `/approve → 200`, then `/generation → 200` ×56 (E1).
- **SopiSkill evidence:** `SS-T-E2E-01` step 10 — `POST /approve` → `202 {jobId, status:"queued"}`; step 11 — poll 0 `dispatched:true`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill returns `202` with a job id where the reference returned `200`; a transport difference with no business-outcome loss.

### B06 — Course list and continue-learning (weight 3)
- **Precondition / steps:** Learner with ≥1 course opens the app root.
- **Expected (reference):** Courses listed; the in-progress course is resumable.
- **Reference evidence:** `GET /v1/home → 200` (E1); `PS-R-PATH-01` — `upNextLessonId` in the path response (E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 13 — `GET /v1/courses/{id}` with `progress{completed,total,percent}`; `SS-C-FRONT-01` — `resumeLessonId`/`resumeLessonTitle` drive the home and course pages.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** `resumeLessonId` vs `upNextLessonId` is a naming difference, not a behaviour difference.

---

## 4. Area C — generation / status / retry / reliability (14)

### C01 — Status polling until ready (weight 3)
- **Precondition / steps:** Approval accepted. Client polls generation status.
- **Expected (reference):** Client polls and stops on a terminal state.
- **Reference evidence:** `PS-R-COURSEGEN-01` — `/generation → 200` ×56 (E1); `polyskill-dynamic-analysis.md` §3 FACT — TanStack Query `refetchInterval` returns 2000 ms unless `ready`/`failed`.
- **SopiSkill evidence:** `SS-T-E2E-01` steps 11–12 — poll 0 `queued/dispatched:true`, poll 1 `ready/stage:"done"`; `SS-C-FRONT-01` — course page uses `refetchInterval` 2000 unless ready/failed.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Both sides converge on 2 s polling. SopiSkill exposes richer counters (`lessonsDone`, `lessonsTotal`, `llmCalls`, `attempts`).

### C02 — Generation reaches a ready state (weight 3)
- **Precondition / steps:** Observe generation to completion.
- **Expected (reference):** Lessons become available.
- **Reference evidence:** 56 generation polls in `PS-R-COURSEGEN-01` followed by grounded lesson content (E1/E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 12 — `ready` in ~2 s, 4 lessons of 4; `SS-T-EVAL-P22-01` — 12/12 topics pass with a **real** provider (`deepseek-ai/deepseek-v4.1-flash-1017`), `REPORTED`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Medium — the E2E run used `LLM_PROVIDER=mock`; real-provider reliability comes from the eval report, not from this audit's run. **Notes:** The 12/12 pass includes one topic whose judge did not score (`en-beginner-excel`, `PROVIDER_BUDGET_EXCEEDED`).

### C03 — Retry a failed generation (weight 3)
- **Precondition / steps:** Force or encounter a failed generation; retry.
- **Expected (reference):** Retry re-enqueues generation.
- **Reference evidence:** `PS-S-API-01` — `POST /courses/{id}/retry` declared (E0); **never exercised**. `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `backend/app/api/v1/routes.py:135` — `POST /courses/{id}/retry → 202` exists; not exercised in this audit's E2E run.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Medium. **Notes:** Code exists on the SopiSkill side; per §6.3 "code present ≠ test passed", no parity credit is taken.

### C04 — Generated course structure (weight 3)
- **Precondition / steps:** Generation complete. Read the course.
- **Expected (reference):** Units containing lessons, each with readiness.
- **Reference evidence:** `PS-R-PATH-01` — `units[]` with `nodes[]{kind,lessonId,state,ready,format,contentVersion}` (E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 13 — 2 units × 2 lessons, all `status:"ready"`, `contentVersion:1`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** The *shape* differs (flat `lessons[]` vs `nodes[]` with `state`/`format`); the contract-level difference is scored in D01, not double-counted here.

### C05 — Generation progress detail (weight 2)
- **Precondition / steps:** Watch the generating screen.
- **Expected (reference):** Named stage progression.
- **Reference evidence:** `polyskill-dynamic-analysis.md` §3 — 4 stage labels observed at runtime: `Đọc câu trả lời của bạn`, `Bổ sung kiến thức nền còn thiếu`, `Phác thảo lộ trình`, `Soạn bài học 1` (E2 for the text; server-returned, not client-invented).
- **SopiSkill evidence:** `SS-T-E2E-01` step 12 — `stage:"done"`, `lessonsDone`, `lessonsTotal`; `frontend/src/app/new/generating/page.tsx` has its own client-side `STAGES` labels.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill's stage labels are client-side constants; the reference's were server-returned. Same outcome, different source of truth.

---

## 5. Area D — lesson blocks / path / figures / glossary / navigation (18)

### D01 — Learning-path structure and lock state (weight 2)
- **Precondition / steps:** Open a generated course's path.
- **Expected (reference):** Units with `kicker`, `blurb`, `tone`, `paywalled`; nodes with `state`, `ready`, `format`, `contentVersion`.
- **Reference evidence:** `PS-R-PATH-01` — `paywalled:true` observed on 2 of 3 units; all node fields named (E2).
- **SopiSkill evidence:** `SS-C-COURSE-01` — `get_course_detail` returns `units[].lessons[]{id,orderIndex,title,status,contentVersion,completed}` + `progress`; **no** `paywalled`, `state`, `ready`, `format`, `upNextLessonId`, `nodes[]`; `SS-C-PATH-01` — `learning-path` exists but behind `P50_ENABLED` with a different contract; `SS-C-FRONT-01` — the course page has 0 hits for `paywal|upNext|format`.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** **Medium** — the path exists and is usable, but lock/paywall state is absent, so the reference's gating UI cannot be reproduced. **Notes:** `paywalled` **enforcement** was never triggered on the reference (`02` §9); this row scores the field surface, not the enforcement.

### D02 — Continue/next-lesson marker (weight 2)
- **Precondition / steps:** Return to a partially completed course.
- **Expected (reference):** A single "next" lesson is identified.
- **Reference evidence:** `PS-R-PATH-01` — `upNextLessonId: string` (E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 13 + `SS-C-FRONT-01` — `resumeLessonId` drives the resume control on both the home and course pages.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** `INTENTIONAL_DIFFERENCE` in field name only.

### D03 — Lesson payload with all six block types (weight 2)
- **Precondition / steps:** Open a generated lesson.
- **Expected (reference):** Blocks of types `teach | mc | blank | order | match | short`.
- **Reference evidence:** `PS-R-LESSON-01` (E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 14 — 6 blocks each, exactly `teach, mc, blank, order, match, short`; `SS-C-BLOCKS-01` — all six renderers exist.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** The strongest single parity result in the audit: an identical six-type taxonomy reached independently.

### D04 — Figures (formula / visual / diagram) (weight 2)
- **Precondition / steps:** Lesson contains a figure block.
- **Expected (reference):** `figure{kind,nodes,rows,head,edgeLabels,groupLabels}` rendered, with `kind ∈ {formula, visual, diagram}`.
- **Reference evidence:** `PS-R-LESSON-01` — `figure` field observed at runtime (E2); `PS-S-FIGENUM-01` — enum from the bundle (E0). **No rendered formula was captured.**
- **SopiSkill evidence:** `SS-C-NOFIG-01` — no `figure` field on any block schema; `SS-C-FRONT-01` — 0 hits for `figure` in the lesson page; no figure component in `frontend/src/components/`.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** **Medium** — a whole content modality is absent. **Notes:** The reference's *rendering* fidelity is `UNKNOWN` (no formula captured), so the gap is scored on the field/modality, which is proven on both sides.

### D05 — Glossary (weight 2)
- **Precondition / steps:** Open the course glossary.
- **Expected (reference):** `terms[]{key,kind,name,short,more,teaser,firstSeen{unit,lesson}}`.
- **Reference evidence:** `PS-R-GLOSSARY-01` — `GET /courses/{id}/glossary → 200` (2.2 KB), `terms[11]` (E2).
- **SopiSkill evidence:** `SS-C-NOGLOSS-01` — `glossary`, `termKey`, `term_key` are **absent from the entire repo**; no glossary component, no route.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** **Medium** — a whole navigation surface is absent. **Notes:** `04` records the reference's provenance choice (unit/lesson, never source page) as a design choice, not a defect.

### D06 — Inline term linkage (`paragraphs[].termKey`) (weight 2)
- **Precondition / steps:** Read a lesson paragraph containing a linked term.
- **Expected (reference):** Paragraph-level term keys connect prose to glossary entries.
- **Reference evidence:** `PS-R-LESSON-01` — `lesson.paragraphs[].termKey` (E2).
- **SopiSkill evidence:** `SS-C-NOGLOSS-01` — no `termKey` anywhere; lesson `teach` blocks are `{title, paragraphs: string[]}` with no linkage.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** Medium. **Notes:** Requires both a glossary and a content-generation change; dependency of the D05 backlog item.

### D07 — Block-by-block navigation (weight 2)
- **Precondition / steps:** Move forward/back through lesson blocks.
- **Expected (reference):** Progressive disclosure through the lesson.
- **Reference evidence:** `PS-R-LESSON-01` establishes an ordered `blocks[]` (E2); the reference's stepper control itself was not separately captured.
- **SopiSkill evidence:** `SS-C-BLOCKS-01` + `SS-C-FRONT-01` — the 828-line lesson page implements an ordered stepper over the same six types.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Scored on the ordered-block business outcome, which is E2 on the reference and E2E-verified on SopiSkill. The reference's exact stepper UI is not asserted.

### D08 — Next-lesson prefetch (weight 2)
- **Precondition / steps:** Finish a lesson.
- **Expected (reference):** The next lesson is preloaded so navigation is instant.
- **Reference evidence:** `GET /v1/lessons/{id}?prefetch=1 → 200 (2.8 KB)` in the reference request log (E2 — the prefetch parameter and its use are directly observed).
- **SopiSkill evidence:** `SS-C-FRONT-01` — **0 hits** for `prefetch` in `frontend/src`; the lesson endpoint accepts no prefetch parameter.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** Low–Medium — a perceived-latency feature, not a functional gap. **Notes:** May be unnecessary if SopiSkill's lesson payloads are small and cached by TanStack Query; the backlog item should justify prefetch by measurement, not by imitation.

### D09 — Content version exposure (weight 2)
- **Precondition / steps:** Read a lesson; regenerate so the version changes.
- **Expected (reference):** `contentVersion` is part of the lesson contract; stale submissions are detectable.
- **Reference evidence:** `PS-R-LESSON-01` — `lesson.contentVersion: int` (E2). The reference's *stale-handling behaviour* is `UNKNOWN`.
- **SopiSkill evidence:** `SS-C-VERSION-01` — `409 CONTENT_VERSION_MISMATCH` when the submitted version differs, verified by test; `SS-T-E2E-01` step 14 shows `contentVersion:1` on every lesson.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill's behaviour is strictly stronger; the reference's is simply unmeasured.

---

## 6. Area E — quiz / grading / progress / attempts / rewards (12)

### E01 — Server-side grading of all five quiz types (weight 3)
- **Precondition / steps:** Submit deliberately wrong answers for mc/blank/short/order/match.
- **Expected (reference):** A scored attempt is returned with per-block results.
- **Reference evidence:** `PS-R-ATTEMPT-01` — `POST /lessons/{id}/attempts → 201`, `score{correct,total}` (E2). Note the reference **client sends `correct` per result**; its server-side grading policy is `UNKNOWN`.
- **SopiSkill evidence:** `SS-C-GRADE-01` (verified this session at `lesson_content.py:155–258`): `mc` matches `answerIndex` and rejects booleans; `blank`/`short` normalise with `_normalize_text` (strip + `casefold` + whitespace-collapse) — `short` against **every** `acceptedAnswers` entry; `order` un-shuffles and compares the exact permutation; `match` requires **every** left to be paired and rejects any mismatched pair. `SS-T-E2E-01` step 15 — 4 attempts → `201`, `score{correct:0,total:5}`, per-block `solution`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Scored on the outcome (a scored attempt with per-block verdicts). SopiSkill's grading is provably server-authoritative; the reference's is not established either way.

### E02 — Attempt idempotency and version pinning (weight 3)
- **Precondition / steps:** Re-submit the same `clientAttemptId`; submit against a stale `contentVersion`.
- **Expected (reference):** `clientAttemptId`, `contentVersion` and a `duplicate` flag are part of the contract.
- **Reference evidence:** `PS-R-ATTEMPT-01` — request carries `clientAttemptId` and `contentVersion`; response carries `duplicate` (E2).
- **SopiSkill evidence:** `SS-C-ATTEMPT-01/02` — idempotent on `(lesson, user, clientAttemptId)`; `409` on version mismatch; `AttemptAnswer(extra="forbid")` rejects a client `correct` flag.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** Same three concepts, independently derived. SopiSkill adds a re-check under row lock (`lesson_service.py:117`).

### E03 — Progress accounting (weight 2)
- **Precondition / steps:** Complete some lessons; read course progress.
- **Expected (reference):** `progress{completed,total,percent}`.
- **Reference evidence:** `PS-R-PATH-01` (E2).
- **SopiSkill evidence:** `SS-T-E2E-01` step 13 — `progress{completed:0,total:4,percent:0}`; completion policy `correct*100 >= total*80` (`lesson_content.py:316–323`).
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** The reference's completion threshold is `UNKNOWN`; SopiSkill's 80% rule is a documented `PROPOSAL`.

### E04 — XP and rewards (weight 2)
- **Precondition / steps:** Score a lesson; read the rewards block.
- **Expected (reference):** `rewards{xp,totalXp,streakDays,streakExtended,freezeBanked,hearts{…},goal{…},levelsEarned[],milestonesEarned[],flagged}`.
- **Reference evidence:** `PS-R-REWARDS-01` (E2) — names only; every listed behaviour is `UNKNOWN`.
- **SopiSkill evidence:** `SS-C-XP-01` — `rewards{xp,xpEarned}`; monotonic top-up `max(0, desired − already)` so retries cannot farm XP; `XP_PER_CORRECT=10`, `XP_LESSON_COMPLETED_BONUS=20`; `rewards.xp` is absolute user XP.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Low–Medium — XP works, but the reference's broader reward vocabulary is absent. **Notes:** Naming divergence (`totalXp` vs `xp`) is recorded in `e2e-chain.log` and is not itself a gap.

### E05 — Streak / hearts / goal / levels / milestones / flagged (weight 2)
- **Precondition / steps:** Return on consecutive days; exhaust hearts; hit a daily goal.
- **Expected (reference):** The full gamification surface listed in E04.
- **Reference evidence:** `PS-R-REWARDS-01` (E2) — field names are facts; depletion, refill, freeze, reset cadence and `flagged` semantics are **all `UNKNOWN`** (`02` §9).
- **SopiSkill evidence:** `SS-C-STREAK-01` — `User.streak_days` column exists but is never exposed in any API response; `SS-C-FRONT-03` — 0 occurrences of `hearts`/`streak` in the frontend; no goal, level or milestone logic.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** Low–Medium — a motivational surface is absent, but the reference's behaviour is unmeasured, so no behavioural parity requirement is proven. **Notes:** Gap type `MISSING (surface)`; severity P2. A column alone is not a feature.

---

## 7. Area F — tutor context / streaming / history / tools / allowance (18)

### F01 — Course-scoped tutor thread (weight 2)
- **Precondition / steps:** Open the tutor from within a course.
- **Expected (reference):** A thread scoped to the course, initialised on demand.
- **Reference evidence:** `PS-R-TUTOR-01` — `GET /courses/{id}/tutor?entryPoint=…&lessonId=…&blockIndex=…&threadId=… → 200` returns `{threadId, kind, sealed, title, nextCursor, messages[], allowance, limit}` (E2). The reference thread-initialisation call was 328 B — consistent with an empty thread.
- **SopiSkill evidence:** `SS-C-TUTOR-04` + `SS-C-FRONT-04` — `POST /tutor/messages` creates/continues a thread via `threadId`; `GET /tutor/threads` and `/threads/{id}` exist; `x-tutor-thread-id` header surfaces the id.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** The reference fetches-or-creates with GET; SopiSkill creates on first POST. Same outcome. SopiSkill does not expose `kind`/`sealed`/`nextCursor`.

### F02 — Message history with per-message context label (weight 2)
- **Precondition / steps:** Reopen a thread with prior turns.
- **Expected (reference):** Messages carry a human-readable context label.
- **Reference evidence:** `PS-R-TUTOR-01` — `contextLabel` present on **8/8** and again on **16/16** messages across two independent sessions (E2).
- **SopiSkill evidence:** `SS-C-FRONT-04` — `TutorMessage` has `contextRef: Record<string, unknown> | null`, not a label; no `contextLabel` string exists in the codebase.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Low — history exists and is persisted; only the displayed label is missing. **Notes:** `contextRef` carries the same information in machine form; the gap is presentational plus a small API addition.

### F03 — Request carries an entry point and context reference (weight 2)
- **Precondition / steps:** Ask a question from a specific lesson block.
- **Expected (reference):** The request identifies both the surface that opened the tutor and the block context.
- **Reference evidence:** `PS-R-TUTOR-02` — POST body `{clientMessageId, entryPoint, contextRef{lessonId, blockIndex}, text, threadId}`; `entryPoint` observed value `teach_block` (E2); `PS-S-ENTRY-01` — 6 declared entry points (E0).
- **SopiSkill evidence:** `SS-C-TUTOR-04` — `{clientMessageId, threadId?, text, contextRef{lessonId, blockIndex}}`, `extra="forbid"`; **no `entryPoint`**; `SS-C-FRONT-04` — 0 hits for `entryPoint` in `TutorPanel.tsx`.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Low–Medium — context is rich, but the server cannot distinguish a `wrong_answer` entry from a `teach_block` entry, which limits personalization and analytics. **Notes:** The server re-resolves `contextRef` from the DB and rejects out-of-bounds block indices — **stronger** than the reference on that axis.

### F04 — SSE streaming of the reply (weight 2)
- **Precondition / steps:** Send a tutor message; consume the stream.
- **Expected (reference):** `delta` increments then a terminal `done`.
- **Reference evidence:** `PS-R-SSE-01` — `delta {text}` and `done {threadId, message}` **owner-transcribed from DevTools** (E2O). REA 6.7.0 has no `text/event-stream` parser, so no machine capture exists.
- **SopiSkill evidence:** `SS-C-TUTOR-01` — emits `delta, done, error, tool, citations, cancelled, heartbeat`; `SS-C-FRONT-04` — the client parses `delta/done/error/tool/citations/cancelled`; tested by `test_sse_frame_escapes_newlines_and_is_single_data_line`. **Runtime was BLOCKED**: `TUTOR_ENABLED=false` → `503 TUTOR_DISABLED` (`SS-T-E2E-03`).
- **Result:** `PARTIAL` · **Match:** 1
- **Risk:** Medium — the only evidence is owner transcription plus passing tests; no frame was observed end-to-end in this audit. **Notes:** Scored 1 because both sides demonstrably implement delta+done streaming. The *runtime* claim is explicitly withheld.

### F05 — Tool calls surfaced to the learner (weight 2)
- **Precondition / steps:** Ask a question that triggers a server-side tool.
- **Expected (reference):** `toolCalls[]{name, summary, ok}` in the message.
- **Reference evidence:** `PS-R-TUTOR-01` — `toolCalls[4]` observed and rising 3→4 after one quick action (E2), but **no tool name was ever exposed**; `PS-S-TOOLS-01` — 6 names declared (E0).
- **SopiSkill evidence:** `SS-C-TOOLS-01` — 3 tools (`read_lesson, explain_deeper, read_source`), `extra="forbid"`; `SS-C-TOOLS-02` — `{name, summary, ok→status}` recorded per execution and surfaced in the UI.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Low–Medium — a narrower tool allowlist. **Notes:** The reference names 6 tools but never proved 3 of them run. SopiSkill's 3 are implemented and attributable; `regenerate_unit`, `flag_question`, `revise_proposal` have no SopiSkill counterpart.

### F06 — Confirmation gate for side-effecting actions (weight 2)
- **Precondition / steps:** Trigger an action that requires explicit learner confirmation.
- **Expected (reference):** `messages[].action` becomes non-null and a `confirm` event appears.
- **Reference evidence:** `PS-S-SSE-01` — `confirm` declared in the client enum (E0). At runtime `action` stayed `null` on **14/14 and 16/16** messages; the owner deliberately declined to manufacture the action. `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `SS-C-TUTOR-01` — no `confirm` event; no action/approval model anywhere in the tutor.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low today, **high if** the reference's confirm gate is what makes `regenerate_unit`/`revise_proposal` safe to expose. **Notes:** A prerequisite for the F05 tool expansion.

### F07 — Tutor allowance / quota (weight 2)
- **Precondition / steps:** Send messages until the UI shows a remaining count.
- **Expected (reference):** Remaining allowance is visible and decrements per turn.
- **Reference evidence:** `PS-R-ALLOW-01` — `allowance{limit,remaining}` + `limit{limit,remaining,resetAt}`; UI went 19 → 18 after one turn (E2).
- **SopiSkill evidence:** `SS-C-TUTOR-05` — `{messagesPerDay, tokensPerDay, maxConcurrentStreams}` + `remaining{messages,tokens}` + `tokensKnown`; `GET /tutor/usage` verified to not consume quota; the panel renders `còn X/Y lượt`.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill's quota is a 24 h windowing model; the reference's `resetAt` semantics (`limit` vs `allowance` both present) were never fully separated.

### F08 — Stop / regenerate an in-flight reply (weight 2)
- **Precondition / steps:** Start a reply, then stop it.
- **Expected (reference):** The stream is cancelled server-side.
- **Reference evidence:** `PS-S-API-01` — `POST /courses/{id}/tutor/messages/{messageId}/stop` declared (E0); **never exercised**. `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `SS-C-TUTOR-03` — `cancel_requested_at` flag, producer stops, emits `cancelled` with partial content; `TutorPanel.tsx` expects `status === "cancel_requested"` and handles `TUTOR_STOP_NOT_FOUND`.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low. **Notes:** Best-effort cancel; it does not refund provider cost. SopiSkill may be **ahead** here, but the reference never demonstrated the behaviour so no parity credit is taken.

### F09 — Resume a stream via `Last-Event-ID` (weight 2)
- **Precondition / steps:** Drop the connection mid-stream and reconnect.
- **Expected (reference):** The stream resumes from the last received event.
- **Reference evidence:** `last-event-id` is declared in the bundle's SSE header list (E0); **never exercised**. `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `SS-C-TUTOR-02` — an explicit documented decision: resume is **not supported**, `replaySupported=false` is returned to the client.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low–Medium — an honest documented divergence, but the reference has the capability. **Notes:** If the reference's resume is load-bearing for mobile network loss, this becomes P2 when the reference behaviour is eventually captured.

---

## 8. Area G — sources: PDF / web / arXiv / provenance / citations (9)

### G01 — Upload and ingest a PDF (weight 2)
- **Precondition / steps:** Upload a PDF, poll until ingested.
- **Expected (reference):** Upload accepted, ingestion reaches a terminal ready state with chunking.
- **Reference evidence:** `PS-R-INGEST-01` — `POST /v1/sources/upload → 201`, `POST /sources/{id}/ingest → 202`, poll until the brief is populated (E2).
- **SopiSkill evidence:** `SS-T-INGEST-01` — create source `201`, upload `202` `{status:"queued", pageCount:3}`, poll[0] `queued` → poll[1] `ready`, `chunkCount:3`, `textSource:"native"`, preview populated.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill's pipeline version is `p4.0-v1`; PDFs are capped at 20 MiB / 300 pages (`SS-C-INGEST-02`).

### G02 — Source ingest brief (weight 2)
- **Precondition / steps:** Open an ingested source's brief.
- **Expected (reference):** `brief{what, claims[≤10], notation[≤20], assumes[≤10], sections[]{anchor,heading,gist}}`.
- **Reference evidence:** `PS-R-BRIEF-01` — a 3-page fixture produced exactly 3 section objects with anchor+heading+gist (E2). Chunker strategy is `INFERENCE`.
- **SopiSkill evidence:** `SS-C-INGEST-01` — 15 source routes, but **no brief concept** anywhere; the document endpoint returns status/chunkCount/preview only.
- **Result:** `OBSERVED` · **Match:** 0
- **Risk:** **Medium** — the brief is the reference's human-readable bridge from a source to a course. **Notes:** Section count matching page count is noted in `02` as insufficient to infer chunking strategy; the gap is scored on the brief's existence, which is proven on both sides.

### G03 — Source kinds: PDF / web / arXiv (weight 2)
- **Precondition / steps:** Ingest one PDF, one URL, one arXiv id.
- **Expected (reference):** `arxiv | web | pdf` accepted.
- **Reference evidence:** `PS-S-API-01` — enum declared (E0) and the upload path exercised with a PDF (E2). Web/arXiv rejection reasons are declared (`unsupported, unreachable, paywalled, no_text, too_short, too_long, unsafe, not_teachable, internal`) but were never triggered.
- **SopiSkill evidence:** `SS-C-INGEST-02` — `ingestEnabled:true`, `webEnabled:false`, `arxivEnabled:false`; the source kind enum is `official_documentation|academic|user_document|webpage`; `SS-T-INGEST-02` — RAG search `503`.
- **Result:** `OBSERVED` · **Match:** 0.5
- **Risk:** Medium. **Notes:** PDF works end-to-end. Web ingest is **coded but disabled**; arXiv is absent. The enum names differ but that is not itself a gap — the capability is.

### G04 — Link a source to a course, with source evaluation (weight 1)
- **Precondition / steps:** Attach an ingested source to a course.
- **Expected (reference):** A source can back a course.
- **Reference evidence:** The reference's course-creation flow used a **topic-based** course with `source: null` (`PS-R-LESSON-01`); linking a source to a course was **not exercised**. `UNKNOWN_REFERENCE`.
- **SopiSkill evidence:** `SS-T-INGEST-01` — `POST /courses/{id}/sources → 201` returns the source plus a 6-criterion evaluation (`authority 0.45 weak`, `relevance 0.9`, `freshness unknown`, `evidence 0.65`, `consistency unknown`, `licensing 0.6`, `weightedScore 0.55`, `verdict moderate`).
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low. **Notes:** SopiSkill's evaluation is an independent surface with no observed reference counterpart. It excludes unknown criteria from the weighted score rather than scoring them as zero — recorded as honest handling in `SS-T-INGEST-03`.

### G05 — Citation contract and honesty (weight 1)
- **Precondition / steps:** Read a source-grounded lesson with citations.
- **Expected (reference):** `cite{anchor,label}` on block-level content, with resolvable provenance.
- **Reference evidence:** `PS-R-CITE-01` — `cite` on 3 of 7 blocks; label↔page and content match verified; locator `PARTIAL` (anchor never string-matched); **not navigable** — rendered as inert `StaticText`, `states:[]`, 0/33 buttons matched. `PS-R-CITE-02` — one emitted string used a CJK ideograph (U+4E00) where a dash belongs.
- **SopiSkill evidence:** `SS-C-CITE-01` — a real citation card with title/url, `sourceVersion`, `pageNumber`, `validationStatus` badge, `evidenceText` quote and an honesty caveat, plus a separate `insufficientEvidence` path; `SS-C-CITE-02` — a 4-level honesty ladder with `evidenceSupported` **always false** in P4.1.
- **Result:** `OBSERVED` · **Match:** 1
- **Risk:** Low. **Notes:** SopiSkill is strictly more honest and more usable here (navigable, explicit insufficient-evidence state). `INTENTIONAL_DIFFERENCE` in favour of SopiSkill. The reference's U+4E00 defect has no SopiSkill counterpart.

### G06 — Query-time retrieval (RAG) (weight 1)
- **Precondition / steps:** Ask a question that requires retrieving from an ingested source.
- **Expected (reference):** Retrieval-backed answers.
- **Reference evidence:** **`INFERENCE` only** — there is no client-side signal proving server-side RAG (`02` §10); embeddings and vector store are `UNKNOWN`. This is not a gap claim.
- **SopiSkill evidence:** `SS-T-INGEST-02` — both a positive and a negative query returned `503 RAG_NOT_ENABLED` ("Tìm kiếm tài liệu (RAG) chưa được bật trên hệ thống này."); `SS-T-EVAL-RAG-01` — when enabled and evaluated offline: recall@6 `1.0`, MRR `0.9643`, abstention `1.0`, using a **lexical** hashing embedding, explicitly not semantic.
- **Result:** `BLOCKED` · **Match:** `UNKNOWN`
- **Risk:** Medium. **Notes:** The gate is a configuration state, not a code defect — the code path exists and has an eval. No parity claim is possible in either direction.

---

## 9. Area H — UX / accessibility / robustness (3)

### H01 — Keyboard navigation and focus order (weight 0.5)
- **Precondition / steps:** Navigate the app without a pointer.
- **Expected (reference):** All controls reachable by keyboard with a visible focus order.
- **Reference evidence:** An accessibility tree was captured through REA (33 buttons present in one view), but **no keyboard traversal was performed** and no focus order was recorded.
- **SopiSkill evidence:** No accessibility or keyboard audit was run this audit. The frontend has `useModalPanel`/`useMediaQuery` helpers but no documented focus-management contract.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Medium — untested on both sides. **Notes:** Requires an explicit a11y harness; not inferable from source.

### H02 — Accessible names and semantics (weight 0.5)
- **Precondition / steps:** Inspect the a11y tree for headings, labels and roles.
- **Expected (reference):** Controls carry accessible names.
- **Reference evidence:** `PS-R-CITE-01` — the reference's a11y tree was captured and did contain labelled `StaticText` and 33 buttons; a CJK mis-render appeared in 3 a11y nodes (`PS-R-CITE-02`). This is a **partial** a11y observation, not a full audit.
- **SopiSkill evidence:** No a11y tree captured; no evidence either way.
- **Result:** `PARTIAL` · **Match:** `UNKNOWN`
- **Risk:** Medium. **Notes:** The only H row with any reference observation, and it is still insufficient to score.

### H03 — Responsive / mobile layout (weight 0.5)
- **Precondition / steps:** Open the app at a phone-width viewport.
- **Expected (reference):** Mobile-first layout (the reference is a React Native Web app).
- **Reference evidence:** `PS-S-STACK-01` — Expo SDK 57 / RN Web (E0). No viewport-specific rendering was captured.
- **SopiSkill evidence:** `frontend/src/app/globals.css` (78.3 K, self-authored) plus a `useMediaQuery` hook; **no viewport test was run** and no screenshot was taken.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Medium. **Notes:** Per the audit's own standing rule, no responsive claim is made without browser verification.

### H04 — Error / empty / loading states (weight 0.5)
- **Precondition / steps:** Hit a failing backend and an empty account.
- **Expected (reference):** Graceful error and empty states.
- **Reference evidence:** None captured. The reference's `TUTOR_LIMIT_REACHED` and source rejection reasons are declared (E0) but were never triggered.
- **SopiSkill evidence:** `SS-C-FRONT-01` — `Skeleton` component, explicit error copy, `p50Disabled` handling on 503, `TUTOR_STOP_NOT_FOUND` copy, `TUTOR_DISABLED` surfaced. Coded but **not exercised in a browser**.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low. **Notes:** Coded states are not verified states; see the standing caveat in §1.4.

### H05 — Multi-language UI (weight 0.5)
- **Precondition / steps:** Switch the UI language.
- **Expected (reference):** ~12 languages available.
- **Reference evidence:** `PS-S-I18N-01` — bundle strings in multiple languages, including Italian ("Il ragionamento di Pol") (E0). **Never switched at runtime.**
- **SopiSkill evidence:** `SS-C-LANG-01` — the UI and the provider prompts are hardcoded Vietnamese; there is no i18n layer. The eval confirms the model *cannot* be asked for another language today.
- **Result:** `NOT OBSERVABLE` · `UNKNOWN_REFERENCE` · **Match:** `UNKNOWN`
- **Risk:** Medium — a real capability gap, but the reference's runtime behaviour is undeclared-untested, so it cannot be scored as `MISSING`.
- **Notes:** Ranked P2 in the backlog on product grounds. The SopiSkill-side deficiency is independently proven by `language_quality = 2.27` and 6/6 English topics delivered in Vietnamese.

### H06 — Rate limiting, long-running work, offline (weight 0.5)
- **Precondition / steps:** Burst requests; go offline mid-session.
- **Expected (reference):** Bursts are throttled; offline use degrades gracefully.
- **Reference evidence:** `PS-S-STACK-01` — `expo-sqlite` (WAL) declared (E0); never exercised. `PS-R-REFRESH-01` shows a 7×401 burst followed by a refresh — a client retry pattern, not a server throttle observation.
- **SopiSkill evidence:** `SS-T-SEC-01..08` — CSRF/JWT enforced; `app/core/limits.py` implements a **per-process in-memory** rate limiter (a scaling limitation, not a parity gap); no offline support at all.
- **Result:** `NOT OBSERVABLE` · **Match:** `UNKNOWN`
- **Risk:** Low. **Notes:** The in-memory limiter is recorded in `10` as a known limitation; it does not affect parity because the reference's limiter was never observed.

---

## 10. Scenario counts (audit question 5)

| Result class | Count | Scenario IDs |
|---|---|---|
| `OBSERVED` | **36** | A01–A04, B01–B03, B05–B06, C01–C02, C04–C05, D01–D09, E01–E05, F01–F03, F05, F07, G01–G03, G05 |
| `PARTIAL` | **2** | F04, H02 |
| `BLOCKED` | **1** | G06 |
| `NOT OBSERVABLE` | **11** | B04, C03, F06, F08, F09, G04, H01, H03, H04, H05, H06 |
| **Total** | **50** | |

Scoring consequences, computed in `06`:

- `OBSERVED` weight = **83** (100 − 17 unknown).
- `PARTIAL` does not reduce the weight but caps confidence; F04 is scored 1 on implementation evidence only.
- `BLOCKED`/`NOT OBSERVABLE` weight = **17** → `Unknown/Blocked Weight = 17 %`.
- **No scenario in this audit was scored from a client bundle declaration alone.** Every `0` required a runtime or code-level fact on the reference side as well as on the SopiSkill side.

## 11. What this chapter does not claim

- It does not claim a 99 % or any other headline parity figure; that is computed in `06` from these rows.
- It does not claim any reference behaviour that was only declared in the bundle.
- It does not claim that a `NOT OBSERVABLE` row is a defect in SopiSkill.
- It does not claim any browser-verified UI behaviour for SopiSkill; the frontend was typechecked and built, not exercised.
- It does not claim the reference's tutor consumed the `contextRef` it sent, or that its attempts were graded server-side.
