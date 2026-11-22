# 00 — Executive Summary

Audit ID: `polyskill-parity-2026-11-04`
Reference: **PolySkill** — `https://web.polyskill.app`, API `https://api.polyskill.app/v1`
Target: **SopiSkill** — `D:\Reverse Engineer`, branch `feat/p6.0-ci-pipeline`, HEAD `d747e78`
Date: 2026-11-04
Mode: **AUDIT-ONLY / READ-ONLY**

---

## Verdict

> ## `CHƯA ĐỦ CĂN CỨ ĐỂ XÁC NHẬN 99%`
>
> **Evidence Coverage 53.0 %** (gate ≥ 95 %) · **Measured Parity 74.7 %** (gate ≥ 99 %) ·
> **Conservative Floor 62.0 %** (gate ≥ 95 %) · **1 of 5 gates passes** · P0 chain gap in the tutor.
>
> **Even a perfect resolution of every unknown row would cap at 88.0 %**, because 12.0 weight of
> hard `MISSING` rows are implementation work, not evidence work.

**Audit status: `PARTIAL AUDIT`** (mandate §11). Not because the work is incomplete, but because the
reference-side runtime gate is unachievable in this environment (§3, §10 of `10`).

**What is genuinely good news:** the core spine — topic → 5-question interview → proposal → approve →
generation → lessons → quiz — is **verified end-to-end** and scores **100 %** on every point that could
be measured (areas B and C). That is a real, defensible strength, not a consolation prize.

**Where parity is actually lost:** area D (lesson/path/figures/glossary, weight 18) sits at **50 %**.
Glossary, inline `termKey`, figures, and prefetch are hard absences against runtime-established
reference facts.

---

## The three mandated figures

| # | Figure | Value | Denominator |
|---|---|---|---|
| 1 | Evidence Coverage | **53.0 %** | 100 (all weight) |
| 2 | Measured Parity | **74.7 %** | 83 (weight with reference observation on both sides) |
| 3 | Conservative Floor | **62.0 %** | 100 (all weight) |
| — | Unknown / Blocked Weight | **17.0 %** | 100 |
| — | Optional upper bound (floor + unknown) | 79.0 % | **not a measured score** |

Measures are computed row-by-row in `06` §2.2 (a 50-row auditable ledger) and `06` §3.

### Per-area parity — the audit's most actionable table

| Area | Weight | Weighted match | Eligible | Parity |
|---|---|---|---|---|
| A — onboarding/auth/dashboard/profile | 8 | 5.0 | 8 | 62.5 % |
| B — topic→interview→proposal→approve | 18 | 15.0 | 15 | **100.0 %** |
| C — generation/status/retry | 14 | 11.0 | 11 | **100.0 %** |
| D — lesson/path/figures/glossary | 18 | 9.0 | 18 | **50.0 %** |
| E — quiz/grading/rewards | 12 | 9.0 | 12 | 75.0 % |
| F — tutor | 18 | 9.0 | 12 | 75.0 % |
| G — sources/citations | 9 | 4.0 | 7 | 57.1 % |
| H — UX/a11y/robustness | 3 | 0.0 | 0 | not measurable |
| **Total** | **100** | **62.0** | **83** | **74.7 %** |

---

## The ten mandated answers

### 1. Repo, branch, HEAD, dirty state

`feat/p6.0-ci-pipeline` · HEAD `d747e78ee8392a354db79805fe73b1477bc0c531` · **0 behind / 38 ahead** of
`origin/main` (never pushed) · **DIRTY: 15 modified + 8 untracked**, `+6574 / −1348`, **no backend file
modified**. All SopiSkill test results are against the dirty tree, not clean HEAD. (`01` §1)

### 2. REA version, commands used, and the origin-filter question

- **REA `rea-agents` 6.8.0 via MCP.** The `rea` CLI is **absent** on this host — no CLI version/help/
  doctor output exists and none was fabricated. (`01` §1.3)
- Historical reference captures were produced by **REA 6.7.0** and are therefore `REPORTED`, not
  reproducible here.
- **Origin filter:** in the recorded reference sessions, correct `--allowed-origins` produced
  `disallowed_origin: 0` and `dropped_events.total: 0`. An **earlier misconfiguration dropped 93 API
  requests** (82 course-creation + 11 tutor) — recorded as a **method lesson**, never as evidence. In
  *this* session's `list_browser_targets`, all exclusion counters were 0 while `targets` was empty,
  proving the filter excluded nothing and **no page target existed at all**. (`02` §2, `01` §1.12)

### 3. What was truly observed at runtime vs only declared in the client bundle

| Tier | Meaning | Applied to |
|---|---|---|
| **E2** | Response body shape observed at runtime | Path, glossary, lesson payload, attempts/rewards, entitlement, tutor thread, tutor POST body, ingest brief |
| **E2O** | Owner-transcribed from DevTools (weaker) | SSE `delta` / `done` |
| **E1** | Transport seen, body filtered/unparsed | Almost all of areas A and B — `/courses`, 5× `/interview/answer`, `/approve`, `/me/*`, 56× `/generation` |
| **E0** | Bundle declaration only | Billing/SePay, `Last-Event-ID`, 6 tutor tools, client SSE event enum, i18n, expo-sqlite, MathJax |
| `UNKNOWN_REFERENCE` | No observation at any tier | Billing behaviour, paywall enforcement, hearts/streak/goal triggers, `levelUp`, server-side grading policy |

**The pivotal honest sentence:** the journey a stakeholder cares most about — onboarding — is the
**least** evidenced part of the reference (E1 only). Closing that needs a fresh owner-driven capture
with bodies enabled, not more code reading. (`02` §3–§9, `06` §2.3)

### 4. SopiSkill: coded / E2E-run / only-mocked / untested

| Status | Features |
|---|---|
| **Coded and E2E-verified** (real HTTP, 18 steps, `EXITCODE=0`) | auth+CSRF, course create, interview ×5, proposal, approve, generation polling to `ready`, lesson fetch ×4 (6 block types), attempt submission ×4 |
| **Coded and unit-tested** (699 passed) | grading, quiz integrity, FSRS, BKT, RAG offline, chunker, OCR (real vietocr), tutor core/tools/stream (flag-gated), pedagogy, cost budget, migrations |
| **Coded but flag-disabled at runtime** | tutor (`503 TUTOR_DISABLED`), tutor tools, RAG (`503 RAG_NOT_ENABLED`), web/arXiv ingest, OCR, P5.0 review, P5.2 recommendations |
| **Coded but returning 404** | `/v1/me/stats`, `/v1/me/entitlement` |
| **Only-mocked** | All live generation (`LLM_PROVIDER=mock`) — content quality from mock is explicitly **not** scored |
| **Untested** | Browser UI interaction, load/concurrency, dependency CVE scan, i18n switching, a11y traversal |

### 5. Scenario counts

**50 scenarios:** **36 OBSERVED · 2 PARTIAL · 1 BLOCKED · 11 NOT OBSERVABLE**.
OBSERVED carries **83 of 100** weight; Unknown/Blocked = **17.0 %**. (`03` §10)

### 6. The three scores with exact denominators

`Evidence Coverage = 53.0/100` · `Measured Parity = 62.0/83 = 74.7 %` · `Conservative Floor = 62.0/100`.
`UNKNOWN` is excluded from Measured Parity's numerator **and** denominator, and contributes 0 to the
floor. It is never counted as MATCHED and never called a failure. (`06` §2–§5)

### 7. Can 99 % be confirmed? No — and precisely why

**1 of 5 gates passes.** Reasons, in order of weight:

1. **Evidence Coverage 53.0 % vs 95 %.** Areas A and B are E1 only; you cannot confirm a contract from
   a status code.
2. **Conservative Floor 62.0 % vs 95 %.** 12.0 weight of hard `MISSING` rows (glossary 2, `termKey` 2,
   figures 2, prefetch 2, gamification 2, ingest brief 2) are provable absences.
3. **P0 chain gap.** Tutor returns `503 TUTOR_DISABLED`; glossary/`termKey` absent.
4. **Ceiling:** resolving **all 17 unknown points favourably** yields **88.0 %**, still 11 points short.
   `99 %` requires closing the 12 hard gaps **and** upgrading 9 partials **and** resolving all 17
   unknowns **and** re-observing the whole matrix.

### 8. Top 10 gaps and fix order

| # | Item | Priority | Size |
|---|---|---|---|
| 1 | P0-TUTOR-FLAG — tutor shipped disabled | P0 | S |
| 2 | P1-CONTENT-TRUNC — lessons cut at 4800-token cap (7/11 topics) | P1 | M |
| 3 | P1-LANG — no `language` parameter; 6/6 English topics delivered Vietnamese | P1 | M |
| 4 | P1-QUIZ-BLANK — 2 blanks, 1 answer (5/11 topics) | P1 | S |
| 5 | P1-PEDAGOGY — Vietnamese profile extraction mis-reads common input | P1 | S |
| 6 | P1-PROPOSAL-EDIT — no revise-before-approve | P1 | M |
| 7 | P1-GLOSSARY — glossary + inline `termKey` absent | P1 | L |
| 8 | P1-LEVEL-FIT — requested level contradicted by generated profile | P1 | S |
| 9 | P2-FIGURES — no figure block type | P2 | L |
| 10 | P2-BRIEF — no source ingest brief | P2 | M |

Ordering follows the mandated critical path: **blockers/security → generation quality → lesson/quiz →
tutor → sources/citations → personalization → UX/i18n/gamification → billing** (`M8-BILLING` is
explicitly **do not start** until the reference is captured). Every item carries all 12 mandated
fields and the status `PROPOSAL — CHƯA TRIỂN KHAI`, with S/M/L estimates and no invented dates (`07`).

### 9. Tests run — commands, exit codes, pass/fail/skip

| Run | Result | Exit |
|---|---|---|
| Backend `pytest` | **699 passed, 29 skipped**, 112.97 s | **0** |
| `tsc --noEmit` | No errors | **0** |
| `next build` | 15.5.28, 4.2 s, 11/11 static pages | **0** |
| Security probes S1–S8 | **8/8 PASS** (cross-tenant → 404, CSRF → 403, JWT tamper → 401) | **0** |
| E2E chain | **18 steps**, reaches `ready`; tutor 503 / `/me/*` 404 recorded | **0** |
| Domain G ingest | 3 pages → 3 chunks `ready`; RAG **503** | **0** |
| Profile-extraction probe | 11 cases, **4 wrong** (findings, not failures) | **0** |

**Not run (the honest holes):** browser UI assertions, real-provider E2E through the UI, tutor
runtime, live RAG, web/arXiv ingest, live OCR, P5.0/P5.2, billing, load/concurrency, CVE/SAST, i18n
switch, a11y traversal. **No command exited non-zero — because the probes that would fail were not
run.** (`09` §8)

### 10. Decisions requiring owner approval

Enabling the tutor with real tokens · choosing/budgeting a real LLM provider · enabling RAG and
choosing an embedding backend (note: current embeddings are **lexical hashing n-grams, not semantic**)
· enabling web/arXiv ingest (SSRF + copyright posture) · **authorising a fresh owner-driven PolySkill
capture with bodies enabled** (the only way to lift Evidence Coverage above 53 %) · defining
paywall/hearts/streak/billing semantics (currently `UNKNOWN` — implementing from guesses would invent a
contract) · approving any new DB migration · approving a browser UI test harness.
(`10` §5)

---

## AI quality — a separate axis, never folded into parity

Measured on a **real** provider (`openai_compatible`, `deepseek-v4.1-flash-1017`, prompt `p3.0-v1`),
12 topics, 149 LLM calls, **N = 11 scored** (one hit `PROVIDER_BUDGET_EXCEEDED`):

- **Mean 3.17 / 4** (median 3.22, min 2.67, max 3.56, stdev 0.315)
- Lowest criteria: **`language_quality` 2.273**, **`level_fit` 2.364**, `answer_consistency` 2.818
- Highest: `safety` **4.000**, `repetition` 3.727
- Defects recurring across topics: truncation **7/11**, language mismatch **6/6 en**, level mismatch
  **8/11**, multi-blank ambiguity **5/11**, one technical error (p99), one missing `acceptedAnswers`
- The harness's structural suite passes **12/12** on the *same* output — proof that "valid JSON +
  green suite" ≠ quality
- The judge's own disclaimer is reproduced verbatim in `08`: *"Điểm do LLM chấm chỉ là tín hiệu tham
  khảo, không phải ground truth và không thay thế người chấm."*
- **2 of the mandate's 5 criteria are UNMEASURED** — tutor scaffolding (tutor disabled) and
  citation/insufficient-source honesty (RAG disabled). They are not "passing".

---

## Judgement

**SopiSkill is a credible, well-tested implementation of the core learning-product spine, whose parity
with PolySkill cannot be established on today's evidence.** The 74.7 % measured parity is a *floor on
the visible portion*, not a quality verdict; the 53.0 % coverage means roughly half the weighted
requirements rest on transport-level observations or client declarations. The most useful single
sentence the owner can take away: **the parts that are measurable are strong, the parts that matter
most to a learner (glossary, figures, tutor, sources) are the parts least measured and most absent.**

Two things must not be confused:

- A **flag that is off** (`TUTOR_ENABLED=false`) is an **operational** fact. It blocks measurement; it
  does not prove the tutor is missing. `05` scores those rows `UNKNOWN`, not `MISSING`.
- A **hard absence** (no glossary, no `termKey`, no figure block, no `?prefetch=1`, no ingest brief)
  is a **parity** fact, proven against runtime-established reference behaviour, and costs 12 of 100
  weight outright.

---

## Three priority next implementation steps

**1. Raise evidence before writing more code (owner action, no engineering).**
Authorise a fresh owner-driven PolySkill session with response bodies enabled, covering onboarding,
course creation, and glossary/lesson payloads. This is the *only* lever that moves Evidence Coverage
above 53 %, and it is a prerequisite for scoring areas A and B at all. Without it, any 99 % claim is
arithmetically impossible regardless of implementation quality. **Gate: Evidence Coverage ≥ 95 %.**
*(Depends on: owner login permission — `10` §5.)*

**2. Turn the tutor on in a non-production environment and close the P0 chain gap.**
`P0-TUTOR-FLAG` is size **S** — a flag plus a budget decision — but it unblocks the entire F area
(weight 18, currently 75 % on partial evidence) and removes the only P0 chain gap. In the same pass,
add the missing `/v1/me/stats` + `/v1/me/entitlement` surface (`M1-ME-SURFACE`) and move the rate
limiter off per-process memory (`M1-SEC-LIMITER`). **Gate: tutor returns 200 with a real stream, no
503 in the E2E chain.** *(Depends on: step 1's environment decision; independent of reference
capture.)*

**3. Fix generation quality at the source — three small, high-leverage items.**
`P1-CONTENT-TRUNC` (raise/stream the token cap), `P1-LANG` (thread a `language` parameter through the
provider), and `P1-QUIZ-BLANK` (one answer per blank or N answers for N blanks). All three are
**S/M** sized, all three are backed by verbatim eval evidence in `08`, and together they clear the
three lowest-scoring criteria. `P1-PEDAGOGY` (the `gio`/`phut` unit-table gap at `pedagogy.py:90`) is
an **S**-sized rider on the same branch. **Gate: a re-run eval shows `language_quality` and
`level_fit` ≥ 3.0 with zero truncation events.** *(Depends on: step 2's provider/budget choice.)*

---

## Artifact index

| File | Contents |
|---|---|
| `00-executive-summary.md` | This document — verdict + 10 answers |
| `01-repo-and-tool-baseline.md` | Branch/HEAD/dirty, toolchain, REA identity, Phase B BLOCKED |
| `02-reference-evidence.md` | PolySkill tiers E0/E1/E2/E2O, contracts, negative observations |
| `03-scenarios.md` | 50 scenarios, sub-weights declared before scoring, result classes |
| `04-evidence-index.md` | 13 PS-R + 11 PS-S + 34 SS-C + 19 SS-T evidence IDs |
| `05-parity-matrix.md` | 50-row matrix with tier on every reference cell |
| `06-scores-and-confidence.md` | The three figures + 50-row coverage ledger + ceiling analysis |
| `07-gap-backlog.md` | Top 10 + 8 milestones, all `PROPOSAL`, 12 fields each |
| `08-ai-quality-evaluation.md` | Five-criterion rubric, N/means/distribution, verbatim defects |
| `09-command-and-test-log.md` | Every command, exit code, and what was **not** run |
| `10-security-and-limitations.md` | Permission posture, REA delta, secret handling, gates |
| `logs/` | Raw logs — pytest, tsc, build, security probes, E2E chain, domain G |
| `captures/` | **Empty by design** — Phase B BLOCKED; no fabricated artifacts (`10` §8) |
