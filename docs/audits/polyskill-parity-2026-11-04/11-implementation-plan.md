# 11 — Implementation Plan to Reach Target

Audit: `polyskill-parity-2026-11-04`
Source of work items: `07-gap-backlog.md` (all items `PROPOSAL — CHƯA TRIỂN KHAI`)
Status of this document: **PLAN — CHƯA TRIỂN KHAI**

> This is the execution plan for the backlog. No product code has been changed to produce it. Every
> phase names the measurable figure it moves and a gate that must pass before the next phase starts.

---

## 0. Target reality check — read this before the phases

The mandate's target is 99 % on three figures. Current values:

| Figure | Now | Gate |
|---|---|---|
| Evidence Coverage | 53.0 % | ≥ 95 % |
| Measured Parity | 74.7 % | ≥ 99 % |
| Conservative Floor | 62.0 % | ≥ 95 % |

**Implementation alone cannot reach 99 %.** The figures measure *evidence*, not code quality — so
half the work is a capture campaign that only the owner can authorise (`10` §5). The plan therefore
has **two tracks running in parallel**, and the target is reached only when both land.

### The arithmetic ladder (what each phase buys)

Weighted match is 62.0 today. Each row's maximum contribution is its weight.

| Phase | Work | Max gain | Ceiling after |
|---|---|---|---|
| **0** | Owner-driven reference capture (no engineering) | 0 parity, **+~26 coverage** | Coverage ~79 %, Parity 74.7 % |
| **1** | Tutor on + `/me/*` surface + rate limiter | up to **+6** (F06/F08/F09 resolve) | Parity ~84 %, coverage ~85 % |
| **2** | D-area content surfaces (glossary, `termKey`, figures, prefetch) | **+8** (D04/D05/D06/D08) | **Parity ~94 %** |
| **3** | Generation quality (truncation, language, blank, level) | **+1** parity (A04) + AI-quality axis | Parity ~95 % |
| **4** | Sources (brief, web/arXiv) | up to **+4** (G02, G03, G04) | Parity ~99 % on scorable weight |
| **5** | Gamification surface (E05) | **+2** | — |
| **6** | Remaining unknowns (B04 revise, C03 retry) | up to **+6** | — |
| **7** | A11y harness (H01–H06) | up to **+3** | — |

**Ceiling statement, stated plainly:** a fully executed Phase 1–7 reaches **≈ 90–93 % measured
parity**, not 99 %. The last 6–9 points require *every* partial to upgrade **and** *every* one of the
17 unknown rows to resolve favourably on the reference side. That is a probability, not a commitment.
**99 % is reachable in the arithmetic only if the reference is shown to have all six unknown
capabilities and SopiSkill matches each on the first attempt.** The plan targets the 93 % plateau as
the engineering commitment and treats 99 % as the evidence-dependent stretch.

**Coverage 95 % is the harder gate** and it is gated almost entirely on Phase 0 + a11y. Without a
fresh owner capture, coverage cannot move at all. This is not a scheduling preference; it is the
binding constraint.

---

## 1. Two tracks and their critical path

```
TRACK A — EVIDENCE (owner-gated)            TRACK B — ENGINEERING (no owner gate)
────────────────────────────────            ──────────────────────────────────────
Phase 0  owner capture w/ bodies            Phase 1  tutor flag + /me + limiter   (S)
   │                                        Phase 2  D-area content surfaces     (L)
   ├──► unlocks F area measurement          Phase 3  generation quality fixes    (S/M)
   ├──► unlocks B04 / C03 / F08 / F09       Phase 4  sources: brief + web/arxiv  (M/L)
   └──► unlocks H (needs a11y harness)      Phase 5  gamification surface        (M)
                                            Phase 6  revise + retry surfaces     (M)
                                            Phase 7  a11y harness                (L)
   │                                              │
   └──────────────► both required for 99 % ◄──────┘
```

Track B can start immediately and in any order among Phases 1/2/3. Track A must start first if the
goal is the *evidence* gates; Track B can start first if the goal is *user-visible parity*. They do
not block each other technically — only the final 99 % claim needs both.

---

## 2. Phase 0 — Reference capture campaign (owner action, no engineering)

**Moves:** Evidence Coverage 53.0 % → ~79 %; resolves nothing in parity by itself.

**Why it is first:** `06` §2.2 shows every area-A and area-B row is E1-only. No amount of code reading
raises them. `10` §2 records Phase B as `BLOCKED` with `targets: []` — the agent cannot log in as the
owner.

**What the owner must do:** one session with **response bodies enabled**, exercising:

| Journey | Raises these rows to E2 |
|---|---|
| Register → onboarding → dashboard | A01, A02, A03 (+26 weight with B) |
| Topic → 5 interview answers → proposal | B01, B02, B03, B05, B06 |
| **Revise** the proposal before approving | **B04 (3, UNKNOWN)** |
| Approve → generation → lesson open | C01, C04, C05 |
| **Retry a failed generation** | **C03 (3, UNKNOWN)** |
| Tutor: send turn, **stop mid-stream**, reload with `Last-Event-ID` | F01–F03, F05, F07, **F08, F09** |
| Trigger the tutor **confirm** gate | **F06 (2, UNKNOWN)** |
| Open glossary + click a `termKey` | D05, D06 (confirms the contract we must build) |

**Gate:** `04-evidence-index.md` shows every A/B row at tier E2. Recompute `06` §2 → Evidence Coverage
≥ 79 %.

**Risk:** the owner may not be able to exercise `confirm` (it was declined before, `02` §4). If it
stays unexercised, F06 remains `UNKNOWN` and 2 points are permanently unreachable. Record it; do not
manufacture the interaction.

**Blocked-by:** owner login permission. **Nothing in Track B depends on this phase.**

---

## 3. Phase 1 — Unblock the chain (P0)

**Moves:** removes the only P0 chain gap; up to +6 parity if F06/F08/F09 resolve.

### 3.1 P0-TUTOR-FLAG (S)

| | |
|---|---|
| **Change** | `backend/app/core/config.py:95` `tutor_enabled: bool = False` → enable in a non-prod env; add budget decision for real-provider tokens |
| **Also** | same for `tutor_tools_enabled`, `rag_enabled` as they are exercised |
| **Why it is S** | the code exists and its tests pass (`tests/test_p30_tutor.py`); only the flag and the spend decision are missing |
| **Acceptance (Gherkin)** | *Given* a course with a ready lesson, *When* a learner opens the tutor, *Then* `GET /tutor/threads` returns **200** with a thread and no `503 TUTOR_DISABLED` |
| | *Given* the flag is off, *When* the same call runs, *Then* it still returns `503` with a clear message (negative case preserved) |
| **Test** | `pytest tests/test_p30_tutor.py` + one live E2E step replacing the current 503 step in `logs/e2e-chain.log` |
| **Rollback** | set the flag back to `false`; no migration involved |

### 3.2 M1-ME-SURFACE (M)

| | |
|---|---|
| **Change** | add `/v1/me/stats` and `/v1/me/entitlement` — **both currently 404** (`routes.py` has no such route; `04` SS-C rows recorded the 404) |
| **Shape to return** | `stats`: streak/xp/progress summary. `entitlement`: `{tier, limits{courses{limit,used}, openUnits, tutorAllowance{limit,remaining}}}` — mirror `02` §3.5 since that shape was **observed at runtime** on the reference |
| **Acceptance** | *Given* an authenticated user, *When* `GET /v1/me/entitlement`, *Then* 200 with `tier` and `limits.tutorAllowance`. *Given* no cookie, *Then* 401, not 404 |
| **Test** | new `tests/test_me_surface.py`; must include the 401 negative |
| **Rollback** | route removal is additive-safe |

### 3.3 M1-SEC-LIMITER (S)

| | |
|---|---|
| **Change** | `app/core/limits.py` is in-memory per-process — move to Redis (already a dependency) or document as single-process-only |
| **Acceptance** | *Given* two backend workers, *When* N+1 requests hit the limit, *Then* the (N+1)th is rejected regardless of which worker handled it |
| **Test** | concurrency test with two workers; the existing `test_pNN_*_postgres_concurrency.py` naming convention is the template |
| **Risk if skipped** | rate limiting silently stops working under any horizontal scale — a security regression, not a UX one |

**Gate:** E2E chain step 16/17 turn 200; `me/*` steps turn 200; no `503` in `logs/e2e-chain.log`.
Then re-run the F-area scoring in `05` with the new runtime evidence.

---

## 4. Phase 2 — Area D content surfaces (largest parity gain)

**Moves:** **+8.0 weighted match** (D04 2, D05 2, D06 2, D08 2). This is the single biggest lever in
the whole plan and where parity is currently lost.

### 4.1 P1-GLOSSARY (L) — D05 + D06 = 4.0

| | |
|---|---|
| **Current state** | confirmed absent — `grep glossary\|termKey` over `backend/app` returns **zero** hits |
| **Reference contract** (E2, `02` §3.2, §3.3) | `GET /courses/{id}/glossary → terms[]{key, kind, name, short, more, teaser, firstSeen{unit, lesson}}`; lesson `paragraphs[]` carries `termKey`; `firstSeen` resolves to **unit/lesson, never to a source page** |
| **Change** | (a) add `termKey` to the teach paragraph model in `schemas.py`; (b) new `GlossaryTerm` table + Alembic migration; (c) generation extracts terms and links them; (d) `GET /courses/{id}/glossary` route; (e) frontend renders a term popover |
| **Acceptance** | *Given* a generated course, *When* `GET /courses/{id}/glossary`, *Then* ≥ 1 term with `firstSeen{unit,lesson}` pointing at a real lesson |
| | *Given* a `termKey` with no glossary entry, *Then* generation validation **rejects** it (no dangling links) |
| | *Given* another user's course, *Then* 404 (tenancy preserved) |
| **Test** | `tests/test_glossary.py` — positive link, dangling-link rejection, cross-tenant 404 |
| **Rollback** | feature-flag the glossary route; the migration is additive (`ADD COLUMN nullable`) |
| **Risk** | **M** — this is the only item needing a DB migration; per `10` §5 it needs owner approval first |

### 4.2 P2-FIGURES (L) — D04 = 2.0

| | |
|---|---|
| **Current state** | schema has `Teach/MC/Blank/Order/Match/Short` only (`schemas.py:471-507`); no `figure` |
| **Reference contract** (E2) | `figure{kind, nodes, rows, head, edgeLabels, groupLabels}`, `kind ∈ {formula, visual, diagram}` |
| **Change** | add a `FigureBlock` to the `AnyBlock` union; extend `validate_lesson`; render on the frontend |
| **Acceptance** | *Given* a lesson requesting a diagram, *Then* at least one `figure` block with valid `kind`; *Given* an unknown `kind`, *Then* schema rejection |
| **Test** | `tests/test_figure_block.py` |
| **Risk** | **L** — new content modality; the renderer is the bulk of the work |

### 4.3 M3-PREFETCH (S) — D08 = 2.0

| | |
|---|---|
| **Current state** | `GET /lessons/{id}` (`routes.py:200`) has **no** `?prefetch=1` handling |
| **Reference contract** (E2) | `?prefetch=1` observed in the request log (`02` §3.3) |
| **Change** | accept the query param; when set, return the lesson plus the next lesson's summary so the client can warm it |
| **Acceptance** | *Given* `?prefetch=1`, *Then* the response includes a next-lesson hint; *Given* the last lesson, *Then* no hint and no error |
| **Test** | `tests/test_lesson_prefetch.py` |

**Gate:** `05` D area recomputed ≥ 17.0/18; `06` Measured Parity ≥ 92 %.

---

## 5. Phase 3 — Generation quality (the AI axis + A04)

**Moves:** +1.0 parity (A04) and the **entire AI-quality axis** from 3.17/4 toward 3.5+.
Does not move parity much — it moves *product quality*, which is a separate figure (`08`).

### 5.1 P1-CONTENT-TRUNC (M)

**Root cause verified:** `config.py:27` `llm_max_output_tokens_lesson: int = 3000`, and the escalation
path at `openai_compatible_provider.py:492` caps at `1.6×` — the eval's 4800 ceiling. Truncation
appeared on **7 of 11 topics**.

**Change:** raise the lesson budget and/or instruct the model to cap block count. The prompt at
`:228` already says "3-5 block"; the cap and the prompt disagree with what the model actually emits.

**Acceptance:** *Given* the 12-topic eval, *Then* **zero** `PROVIDER_BUDGET_EXCEEDED` and zero
mid-token cuts. Negative: pushing the budget above `generation_max_tokens_per_job` (`:40`, 400 000)
must fail loudly, not silently.

### 5.2 P1-LANG (M)

**Root cause verified — this is a one-line class of bug with a wide blast radius:**
`openai_compatible_provider.py:58` hardcodes `"hãy tạo proposal khóa học bằng tiếng Việt"` and
`:228` hardcodes `"Soạn 1 bài học ngắn (3-5 block), tiếng Việt, ..."`. `CourseCreateRequest`
(`schemas.py:521`) has **no `language` field**. So 6/6 English topics returning Vietnamese is
deterministic, exactly as `08` §4.4 records.

**Change:** add `language: str = "vi"` to `CourseCreateRequest` + the `Course` model; thread it into
both prompts; replace the hardcoded `"tiếng Việt"` with the requested locale.

**Acceptance:** *Given* `language: "en"`, *Then* generated lesson text is English (checked by a
language-detection assertion in the eval, not by eyeball). *Given* no `language`, *Then* defaults to
`vi` (backward compatible).

### 5.3 P1-QUIZ-BLANK (S)

**Root cause verified:** `schemas.py:484-488` — `BlankBlock.answer: str` is a **single** string while
`sentence` can contain multiple `___`. 5 of 11 topics produced 2 blanks / 1 answer.

**Change:** either enforce exactly one blank per block at validation, or change to
`answers: list[str]` with a count match.

**Acceptance:** *Given* a sentence with 2 blanks and 1 answer, *Then* `validate_lesson` rejects it.
*Given* N blanks, *Then* exactly N answers.

### 5.4 P1-LEVEL-FIT + P1-PEDAGOGY (S)

**Root cause verified** (`pedagogy.py:66,90`): the regex at `:90` accepts undiacritized `phut|gio` but
`_TIME_UNIT_MINUTES` has **no `"gio"`/`"phut"` key**, so `factor` stays `1` — `"3 gio tuan"` → `3`
instead of `180`, a silent **60× underestimate**. `_DEPTH_DEEP` lacks `"hiểu sâu"`; `_STYLE_VISUAL`
lacks `"đồ thị"`.

**Change:** add `"gio": 60, "phut": 1, "tieng": 60` to the table; add the missing phrases. Also stop
`currentLevel` from leaking into lessons generated for a different requested level.

**Acceptance:** the 11-case probe in `logs/e2e-chain.log` returns all-CORRECT. This is a pure unit
test — no provider needed.

**Gate:** re-run the eval → `language_quality` and `level_fit` ≥ 3.0, zero truncation. `05` A04 → 1.

---

## 6. Phase 4 — Sources and citations

**Moves:** up to +4.0 (G02 2, G03 upgrade 1, G04 1). **Gated on the SSRF/legal decision (`10` §5).**

### 6.1 P2-BRIEF (M) — G02 = 2.0

**Reference contract (E2, `02` §3.8):** `brief{what, claims[≤10], notation[≤20], assumes[≤10],
sections[]{anchor, heading, gist}}` — 3 pages produced exactly 3 sections.
**Current state:** ingest returns 3 **chunks**, not an authored brief (`logs/domain-g-ingest.log`).

**Change:** add a brief-generation step after chunking; new `brief` JSON on the source.

### 6.2 M5-WEB-ARXIV (L) — G03 upgrade + G04

**Current state:** `webEnabled:false`, `arxivEnabled:false`; only PDF exercised.
**Change:** enable behind a flag with an allowlist; **SSRF guard is mandatory** (block private ranges,
redirects, and non-listed hosts) before this ships.
**Acceptance:** *Given* a host outside the allowlist, *Then* fetch is refused, not attempted.

### 6.3 M5-RAG (L)

**Current state:** `503 RAG_NOT_ENABLED` live; embeddings are **hashing n-gram (lexical), dim 256**,
not semantic; `rag_bench` says `needPgvector: true`.
**Change:** pick a real embedding backend. **Do not present lexical retrieval as semantic** in any UI
copy — `07` carries this as a hard acceptance criterion.

**Gate:** G area ≥ 8/9; RAG returns 200 on a source-backed course.

---

## 7. Phase 5 — Gamification surface

**Moves:** E05 = 2.0. The reference's `rewards{}` *shape* is E2 (`02` §3.4) but the **behaviour**
(streak rules, hearts refill, freeze bank, goal reset) is `UNKNOWN` (`02` §9).
**Plan:** implement the surface (XP, streak counter, hearts display) matching the observed field names;
**do not invent the rules.** Where a rule is unknown, leave it configurable and document the unknown.
**Blocked-by:** Phase 0 capture, if the rules are ever to be confirmed.

---

## 8. Phase 6 — Revise and retry

| Item | Current | Needed |
|---|---|---|
| B04 revise proposal | no `PATCH`/`PUT` anywhere in `backend/app/api` | `POST /courses/{id}/proposal/revise` returning a new version |
| C03 retry generation | `/courses/{id}/retry` exists (`routes.py:135`) but never exercised | verify it end-to-end; add the failure path test |

**Acceptance (B04):** editing an **already-approved** proposal → **409**; another user's proposal →
**404**; a valid edit bumps `version`.

---

## 9. Phase 7 — Accessibility harness

**Moves:** up to +3.0 **and** it is required for Coverage ≥ 95 %. H01–H06 are `UNKNOWN` today because
**no a11y or keyboard harness exists on either side** (`03`, `06` §5).

**Change:** add a Playwright/CDP a11y pass over the 10 built routes; assert keyboard traversal,
focus order, labels, and viewport behaviour.
**Note:** this is also the harness that makes the first **screenshot-verified UI claim** possible —
`03` §1.4 currently forbids any such claim.

---

## 10. What cannot be planned away

| Constraint | Why |
|---|---|
| Owner login for Phase 0 | The agent cannot authenticate as the owner (`10` §2) |
| `confirm` gate may stay unobservable | The owner declined it before (`02` §4); 2 points may be permanently unreachable |
| Reference model/provider is `UNKNOWN` | Parity is judged on contract + behaviour only, never implementation |
| Every SopiSkill test is against a **dirty tree** | The audit cannot claim clean-HEAD results (`01` §1) |
| H is unmeasurable without Phase 7 | 3 points exist only if both sides are harnessed |

---

## 11. Decision needed before Phase 1 starts

Three things need the owner's word, in this order:

1. **Phase 0 first or Phase 1–3 first?** They are independent. Phase 0 is the only thing that moves
   *Evidence Coverage*; Phase 1–3 is the only thing that moves *user-visible parity*. If the goal is
   a defensible 99 % claim, Phase 0 must start in parallel.
2. **Provider and budget** — `mock` cannot ship; Phase 3's acceptance depends on a real model.
3. **DB migration approval** — Phase 2.1 (glossary) is the only item that needs one.

**Recommendation:** start **Phase 1.1 (tutor flag, S) and Phase 3.4 (pedagogy table, S)** immediately —
both are small, unblocked, and produce visible evidence — while the owner schedules the Phase 0
capture. Do **not** start Phase 2's migration until the owner approves it, and do **not** start
`M8-BILLING` until the reference billing behaviour has been captured.
