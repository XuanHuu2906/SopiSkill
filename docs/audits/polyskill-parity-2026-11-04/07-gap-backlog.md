# 07 — Gap Backlog

Audit: `polyskill-parity-2026-11-04`
Target: SopiSkill, branch `feat/p6.0-ci-pipeline`, HEAD `d747e78` + dirty working tree

**Every item in this chapter is `PROPOSAL — CHƯA TRIỂN KHAI`.** Nothing here was implemented,
committed, deployed or tested-as-fixed during this audit. The audit was read-only.

Ordering follows the mandated critical path:

`functional blockers / security → course generation & content quality → lesson/quiz coverage →
Tutor SSE/context → source ingestion/citations → personalization → UX/i18n/gamification → billing`

No dates are given. Estimates are `S` / `M` / `L` only.

## 1. Top 10

| # | ID | Item | Pri | Weight at stake | Est. |
|---|---|---|---|---|---|
| 1 | P0-TUTOR-FLAG | Tutor is shipped disabled; the whole tutor chain is unreachable at runtime | P0 | Operational (blocks F01–F09) | S |
| 2 | P1-CONTENT-TRUNC | Lessons are silently truncated at the 4800-token cap; 7 of 11 judged topics show a cut lesson | P1 | C02, plus content quality | M |
| 3 | P1-LANG | Provider has no `language` parameter; 6/6 English topics delivered in Vietnamese | P1 | H05, plus every en topic | M |
| 4 | P1-QUIZ-BLANK | Blank blocks contain 2 blanks but exactly 1 answer — unanswerable as rendered | P1 | E01, content quality | S |
| 5 | P1-PEDAGOGY | Deterministic learner-profile extraction mis-reads common Vietnamese input | P1 | A04 | S |
| 6 | P1-PROPOSAL-EDIT | No way to revise a proposal before approving | P1 | B04 (3, `UNKNOWN`) | M |
| 7 | P1-GLOSSARY | Glossary surface and inline `termKey` linkage are entirely absent | P1 | D05 + D06 (4) | L |
| 8 | P1-LEVEL-FIT | `learnerProfile.currentLevel` contradicts the requested level in 8 of 11 judged topics | P1 | A04, content quality | S |
| 9 | P2-FIGURES | No figure block type; a whole content modality is absent | P2 | D04 (2) | L |
| 10 | P2-BRIEF | No source ingest brief; the human-readable source→course bridge is absent | P2 | G02 (2) | M |

Rationale for the first item being P0 and operational rather than a parity gap: the tutor is the
reference's flagship differentiator and SopiSkill's code for it exists and its tests pass, but with
default configuration it returns `503 TUTOR_DISABLED`. A user cannot reach the feature at all. That
is more urgent than any parity delta, and it is a configuration/rollout question, not a build task.

---

## 2. Item contracts

### P0-TUTOR-FLAG — tutor unreachable at runtime

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P0`
- **PolySkill evidence:** `PS-R-TUTOR-01` (E2) — the reference's tutor is live and returns threads, messages, allowance and limits. `PS-R-TUTOR-02` (E2) — POST returns `text/event-stream` 200. Verdict: live.
- **SopiSkill evidence:** `SS-T-E2E-03` — `POST /v1/tutor/messages` → `503 TUTOR_DISABLED`. Cause: `backend/app/core/config.py:95` `tutor_enabled: bool = False`. All 5 tutor routes call `_require_enabled()` first.
- **Current vs expected:** Current: every tutor route 503s under default config. Expected: routes serve the reference's core tutor outcome for an entitled user.
- **Phạm vi sửa đề xuất:** Operational first — set `TUTOR_ENABLED=true` in the deployment environment and confirm the provider key is present. Only if there is a product reason for the default should code change. Do **not** flip the default silently in `config.py` without an owner decision.
- **Dependency / thứ tự:** Blocks all runtime verification of F01–F09. Must precede any tutor parity work.
- **Acceptance criteria:**
  - Positive: with the flag on, `POST /v1/tutor/messages` returns `200` with `content-type: text/event-stream` and at least one `delta` frame followed by `done`.
  - Negative: with the flag off, the route returns `503` with the documented `TUTOR_DISABLED` code and the client renders the disabled copy — it must not hang or crash.
  - Negative: an unentitled user gets the documented quota error, not a stream.
- **Test bắt buộc:** Extend `logs/e2e-chain.log`'s 18-step chain with a tutor step; assert frame names `delta`/`done`; assert `GET /tutor/usage` does not decrement `remaining`.
- **Rủi ro:** Turning the flag on exposes provider spend to any account. Rate/quota gate must be verified first.
- **Rollback / feature flag:** The existing `TUTOR_ENABLED` flag is the rollback. No code change required.
- **Ước lượng:** `S`
- **Không làm:** Do not remove `_require_enabled()`; do not hardcode provider keys; do not bypass the quota meter to make the E2E pass.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-CONTENT-TRUNC — lessons truncated at the token cap

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** `PS-R-LESSON-01` (E2) — the reference returns complete 2.8 KB lesson payloads with 7 blocks and no truncation signal. Its generation budget is `UNKNOWN`.
- **SopiSkill evidence:** `p22_openai_compatible_20261031_192252.json`. The judge notes on **7 of 11** scored topics report a cut lesson, e.g. *"Bài 7 bị cắt cụt giữa ví dụ `diem = [7, 8,`"* (vi-beginner-python), *"Bài 5 bị cắt giữa câu hỏi MC"* (vi-intermediate-sql), *"Bài 4 bị cắt ở phần short answer"* (vi-advanced-behavioural-econ). One topic recorded `PROVIDER_BUDGET_EXCEEDED: Output chạm trần token (4800 >= 4800) và bị cắt.`
- **Current vs expected:** Current: a single completion produces the whole multi-lesson course; content is clipped at 4800 output tokens with no user-visible warning. Expected: every lesson is complete, or the system explicitly regenerates/continues rather than shipping a clipped lesson.
- **Phạm vi sửa đề xuất:** Split generation per lesson (or per block group) so one completion never has to cover a whole course; raise the per-call budget only if the provider allows it. Add a completeness lint to the eval rubric (not only the judge) that fails a lesson ending mid-token. Provider-agnostic — no reference code is involved.
- **Dependency / thứ tự:** After P0. Prerequisite for meaningful E01/E03 scoring, because a clipped lesson cannot be attempted fairly.
- **Acceptance criteria:**
  - Positive: a 4-lesson course generated with the real provider produces 0 lessons whose last character is mid-sentence, judged by a deterministic lint.
  - Negative: when the provider still returns `finish_reason=length`, the lesson is marked incomplete and retried — it is never persisted as `ready`.
- **Test bắt buộc:** Add a truncation assertion to the p2.2 eval; re-run N=12 and report the count of clipped lessons (target 0).
- **Rủi ro:** Per-lesson generation multiplies LLM calls and latency; budget must be re-measured.
- **Rollback / feature flag:** Keep the existing single-call path behind a flag until the eval shows no regression.
- **Ước lượng:** `M`
- **Không làm:** Do not raise the cap to an arbitrary large number to hide the problem; do not strip the judge's truncation notes.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-LANG — no language parameter; English requests get Vietnamese

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** `PS-S-I18N-01` (E0) — the reference bundle carries strings in ~12 languages including Italian. Its **runtime** language switching was never exercised (`UNKNOWN_REFERENCE`), so this is not a proven parity requirement.
- **SopiSkill evidence:** `SS-C-LANG-01` — `backend/app/providers/openai_compatible_provider.py:58,228` hardcode "bằng tiếng Việt" / "tiếng Việt"; `LLMProvider` has **no `language` parameter in any of its six abstract methods**. Eval: `language_quality` mean **2.273** (the second-lowest of nine criteria); judge notes on **6 of 6** English topics state the content is Vietnamese, e.g. *"All lesson content is Vietnamese although requested language is en"*, *"Toàn bộ proposal và bài học viết bằng tiếng Việt dù yêu cầu ngôn ngữ là 'en'"*.
- **Current vs expected:** Current: language is a prompt constant. Expected: a requested language is honoured end-to-end (proposal, lessons, quiz, tutor).
- **Phạm vi sửa đề xuất:** Add `language` to the request/profile model, thread it through `LLMProvider` methods, and compose the prompt locale-sensitively. Do not copy the reference's string tables.
- **Dependency / thứ tự:** After P0/CONTENT-TRUNC. Independent of the glossary work.
- **Acceptance criteria:**
  - Positive: an `en` topic produces an English proposal and lessons in an automated language check.
  - Negative: an unsupported language code is rejected with a validation error, not silently produced in Vietnamese.
  - Negative: a `vi` request still produces Vietnamese (no regression).
- **Test bắt buộc:** Re-run the p2.2 eval on the 6 en topics; `language_quality` must rise above 3.0 and the language-mismatch note must disappear.
- **Rủi ro:** Prompt changes can regress the 3.45/3.27 example/objective scores; re-run the whole rubric.
- **Rollback / feature flag:** `LANGUAGE_AWARE_PROMPTS` flag, defaulting off until eval passes.
- **Ước lượng:** `M`
- **Không làm:** Do not machine-translate output as a post-step; do not assume the reference's provider or model.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-QUIZ-BLANK — multi-blank questions with a single answer

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** `PS-R-LESSON-01` (E2) — the reference has a `blank` block type; its multi-blank semantics were not captured. No parity claim is made about its internals.
- **SopiSkill evidence:** `SS-C-GRADE-01` — `grade_blank` compares the whole answer string to `block["answer"]`; there is no fill-in-the-gap mapping. Judge notes flag the defect on **5 of 11** topics: *"Một số câu blank có 2 chỗ trống nhưng chỉ có một đáp án (Bài 2, 5, 6), gây mơ hồ."*, *"Blank bài 1 có hai chỗ trống nhưng chỉ một đáp án 'Hệ thống 2'"*, *"Bài 4 short question thiếu acceptedAnswers"*.
- **Current vs expected:** Current: prompts may emit questions with two `___` slots and one answer, which is unanswerable. Expected: schema and lint make this unrepresentable.
- **Phạm vi sửa đề xuất:** Either (a) constrain the generator to one blank per question, or (b) add `blanks[]` with per-slot answers and grade positionally. (a) is `S`, (b) is `M`. A validator must reject a rendered blank count ≠ answer count in both cases.
- **Dependency / thứ tự:** Touches the same content-generation prompt as P1-CONTENT-TRUNC; coordinate.
- **Acceptance criteria:**
  - Positive: for every generated blank block, the count of `___` occurrences equals the number of accepted answers, asserted by a deterministic lint over N=12.
  - Negative: a hand-crafted block with 2 blanks and 1 answer is rejected at validation time.
  - Negative: `short` blocks with an empty `acceptedAnswers` are rejected (currently observed on en-ambiguous-productivity).
- **Test bắt buộc:** Unit test for the validator (both directions) + eval lint across the 12 topics.
- **Rủi ro:** Tightening the schema may fail topics that currently pass; expect a temporary pass-rate dip.
- **Rollback / feature flag:** Validator severity starts as `warning`, flips to `error` once the prompt is fixed.
- **Ước lượng:** `S`
- **Không làm:** Do not accept "any of the answers" as a shortcut; do not grade a 2-blank question on a single substring match.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-PEDAGOGY — deterministic learner-profile extraction mis-reads Vietnamese

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** 5 × `POST /courses/{id}/interview/answer → 200` (E1). The reference's profile shape and extraction accuracy are `UNKNOWN` at every tier — **this is a SopiSkill-internal defect, not a measured parity gap.**
- **SopiSkill evidence:** `SS-C-PEDAGOGY-01`, reproduced by direct call:
  - `'3 gio tuan'` → **3** (should be 180). Root cause: `_TIME_UNIT_MINUTES` at `backend/app/services/pedagogy.py:66` is `{"phút":1,"giờ":60,"tiếng":60,"h":60,"hour":60,"min":1}` — **no `"gio"` key**, though the regex at `:90` matches `gio`. The unit falls through the `startswith` loop and factor stays 1.
  - `'2 tieng/tuan'` → `None` (should be 120). Same family: the regex group captures `tiếng/`, then `.rstrip("/")` yields `tiếng`, which *is* in the dict — so this path should work; the failure needs a targeted unit test to pin down.
  - `'mình muốn hiểu sâu'` → `balanced` (should be deep). `_DEPTH_DEEP` at `:64` contains `"đi sâu"` but not `"hiểu sâu"`.
  - `'thích học qua đồ thị và ví dụ thực tế hơn là công thức'` → `[]` (should be `visual` + `hands_on`). `_STYLE_VISUAL` at `:61` has `"sơ đồ"`, not `"đồ thị"`.
  - Goal = longest answer (by design, `:151`).
- **Current vs expected:** Current: common, natural Vietnamese phrasings silently produce wrong profiles, which then shape the whole course. Expected: dialect/accent variants and paraphrases resolve correctly, or the system asks a clarifying question.
- **Phạm vi sửa đề xuất:** Add unaccented forms (`gio`, `phut`, `tieng`) to `_TIME_UNIT_MINUTES`; extend `_DEPTH_DEEP`/`_DEPTH_BROAD`/`_STYLE_*` lexicons; add a clarifying-question fallback when confidence is low. Keep it deterministic — do not switch this to an LLM call.
- **Dependency / thứ tự:** Independent. Affects A04 and every course's personalization.
- **Acceptance criteria:**
  - Positive: a table of ≥20 realistic Vietnamese answers (accented, unaccented, ranges, paraphrases) maps to the expected `LearnerProfile` fields.
  - Negative: a genuinely ambiguous answer yields `None`/`balanced` **and** a `warnings[]` entry rather than a confident wrong guess.
- **Test bắt buộc:** Parametrized unit test over the answer table; include the 4 currently-failing probes as regression cases.
- **Rủi ro:** Lexicon growth increases false positives (e.g. `"h"` matching inside words). Guard with word boundaries.
- **Rollback / feature flag:** Pure function; revert is a code revert.
- **Ước lượng:** `S`
- **Không làm:** Do not add an LLM call here; do not copy the reference's prompt.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-PROPOSAL-EDIT — proposal cannot be revised before approval

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** `PS-S-TOOLS-01` (E0) — `revise_proposal` is one of 6 declared tutor tools; `GET /courses/{id}/plan` declared (E0). **Never exercised at runtime.** `UNKNOWN_REFERENCE` — no parity proof.
- **SopiSkill evidence:** `backend/app/api/v1/routes.py:100` exposes only `GET /courses/{id}/proposal`. **No `PATCH`/`PUT` exists anywhere in `backend/app/api`.** `frontend/src/app/new/proposal/page.tsx` has approve + an approved banner and **no edit/revise control**.
- **Current vs expected:** Current: the proposal is read-only; the only ways forward are approve-as-is or abandon. Expected: scope/difficulty/order are adjustable before approval.
- **Phạm vi sửa đề xuất:** Add a versioned proposal mutation (bump `version`, keep `approved:false`), plus UI controls. The absence is proven on the SopiSkill side independently of the reference.
- **Dependency / thứ tự:** After P0; before any tutor `revise_proposal` tool work (F05).
- **Acceptance criteria:**
  - Positive: editing scope → `version` increments and the new value is returned by `GET`.
  - Negative: editing an already-approved proposal returns `409`, not a silent overwrite.
  - Negative: editing a proposal owned by another user returns `404` (tenant isolation, matching `SS-T-SEC-*`).
- **Test bắt buộc:** API test for the three cases above + an idempotency test on repeated edits.
- **Rủi ro:** Version drift between an open editor and an approval; requires optimistic concurrency.
- **Rollback / feature flag:** `PROPOSAL_EDIT_ENABLED` flag.
- **Ước lượng:** `M`
- **Không làm:** Do not reuse the approve endpoint for edits; do not allow edits after generation has started.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-GLOSSARY — glossary and inline term linkage absent

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** `PS-R-GLOSSARY-01` (E2) — `GET /courses/{id}/glossary → 200` (2.2 KB), `terms[11]{key,kind,name,short,more,teaser,firstSeen{unit,lesson}}`. `PS-R-LESSON-01` (E2) — `lesson.paragraphs[].termKey`. Provenance resolves to unit/lesson, never a source page — a **design choice**, not a defect.
- **SopiSkill evidence:** `SS-C-NOGLOSS-01` — `glossary`, `termKey`, `term_key` are **absent from the entire repo**; no glossary component, no route; `teach` blocks are `{title, paragraphs: string[]}` with no linkage.
- **Current vs expected:** Current: no glossary surface and no way to link prose to a definition. Expected: the reference's outcome — a course-scoped glossary reachable from prose, with unit/lesson provenance.
- **Phạm vi sửa đề xuất:** New `glossary` persistence + `GET /courses/{id}/glossary`; a `termKey` on paragraph items emitted at generation time; a glossary view and inline term affordance in the lesson page. **Replicate the outcome, not the code or copy.**
- **Dependency / thứ tự:** D06 depends on D05. Both need a content-generation change, so sequence after P1-CONTENT-TRUNC.
- **Acceptance criteria:**
  - Positive: a completed course returns ≥1 glossary term with `firstSeen{unit,lesson}` resolving to a real lesson.
  - Positive: at least one lesson paragraph carries a `termKey` present in the glossary.
  - Negative: a `termKey` with no glossary entry is rejected at generation validation (no dangling links).
  - Negative: another user's glossary returns `404`.
- **Test bắt buộc:** Contract test for the glossary endpoint; a cross-reference integration test asserting every emitted `termKey` resolves; tenant-isolation test.
- **Rủi ro:** `L` because it touches schema, generation prompt, API and UI. Might be scoped down to "glossary endpoint + view" first, deferring inline linkage.
- **Rollback / feature flag:** `GLOSSARY_ENABLED`; the extra prompt field can be dropped without breaking lessons if it is optional.
- **Ước lượng:** `L`
- **Không làm:** Do not copy the reference's 6-field term schema wholesale; do not derive provenance from source pages (the reference explicitly does not).
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P1-LEVEL-FIT — requested level contradicted by the generated profile

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P1`
- **PolySkill evidence:** Reference level handling is `UNKNOWN` — its interview bodies were never parsed. No parity claim.
- **SopiSkill evidence:** `SS-C-PEDAGOGY-01` + eval notes. `learnerProfile.currentLevel='beginner'` appears where `intermediate`/`advanced` was requested on **8 of 11** judged topics: vi-intermediate-sql, vi-advanced-behavioural-econ, vi-advanced-statistics, en-intermediate-writing, en-advanced-distributed, en-ambiguous-productivity, en-advanced-climate, and the en-beginner-excel budget failure. `level_fit` mean **2.364** — the lowest of the nine criteria.
- **Current vs expected:** Current: the requested level is not authoritative; the deterministic extractor overrides it. Expected: an explicit requested level wins, and content depth follows it.
- **Phạm vi sửa đề xuất:** Make a declared level a hard constraint that the extractor may only *raise* with evidence, never silently lower; pass the level explicitly into generation prompts. Do not change the extractor's default.
- **Dependency / thứ tự:** Shares `pedagogy.py` with P1-PEDAGOGY; do them together.
- **Acceptance criteria:**
  - Positive: for each of the 12 topics, `learnerProfile.currentLevel` equals the requested level unless the interview answers explicitly state otherwise.
  - Positive: `level_fit` rises above 3.0 on the re-run.
  - Negative: contradictory answers still surface a `warnings[]` entry rather than silently picking one.
- **Test bắt buộc:** Parametrized test asserting level precedence; eval re-run.
- **Rủi ro:** Hardening level precedence can make beginner content too hard if the prompt ignores it; verify both directions.
- **Rollback / feature flag:** `LEVEL_PRECEDENCE` flag.
- **Ước lượng:** `S`
- **Không làm:** Do not raise `level_fit` by loosening the judge rubric.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P2-FIGURES — no figure block type

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P2`
- **PolySkill evidence:** `PS-R-LESSON-01` (E2) — `figure{kind,nodes,rows,head,edgeLabels,groupLabels}`; `kind ∈ {formula,visual,diagram}` (E0). **No rendered formula was captured**, so rendering fidelity is `UNKNOWN`.
- **SopiSkill evidence:** `SS-C-NOFIG-01` — no `figure` field on any block schema; `SS-C-FRONT-01` — 0 hits for `figure` in the lesson page; no figure component in `frontend/src/components/`.
- **Current vs expected:** Current: text and quiz only. Expected: an optional visual modality grounded in the lesson (formula/diagram), not decorative.
- **Phạm vi sửa đề xuất:** New block type + a renderer + a constrained prompt schema. Start with `diagram` (structured nodes/edges) since it is verifiable; treat `formula` as a separate spike because MathJax-class rendering is a dependency decision.
- **Dependency / thứ tự:** After CONTENT-TRUNC and QUIZ-BLANK (same generation pipeline).
- **Acceptance criteria:**
  - Positive: at least one lesson in a course contains a `figure` block that renders in the built frontend.
  - Negative: a `figure` payload referencing a non-existent node id is rejected at validation.
  - Negative: lessons without figures still render exactly as today (no regression).
- **Test bắt buộc:** Schema validation tests (valid/invalid graph) + a component render test + eval lint that figures are grounded (a referenced node term appears in the lesson text).
- **Rủi ro:** `L` — rendering scope can balloon; `formula` may be deferred.
- **Rollback / feature flag:** `FIGURE_BLOCKS_ENABLED`; blocks are additive and optional.
- **Ước lượng:** `L`
- **Không làm:** Do not copy the reference's figure schema verbatim; do not add a heavy math renderer without a dependency review.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

### P2-BRIEF — no source ingest brief

- **Tình trạng:** `MỞ`
- **Mức ưu tiên:** `P2`
- **PolySkill evidence:** `PS-R-BRIEF-01` (E2) — `brief{what, claims[≤10], notation[≤20], assumes[≤10], sections[]{anchor,heading,gist}}`; a 3-page fixture produced exactly 3 sections. Chunker strategy is `INFERENCE`.
- **SopiSkill evidence:** `SS-C-INGEST-01` — 15 source routes, **no brief concept**; the document endpoint returns status/chunkCount/preview only.
- **Current vs expected:** Current: an ingested source yields chunks and a preview. Expected: a human-readable brief a learner can check before trusting the source.
- **Phạm vi sửa đề xuất:** Add a post-ingest brief step producing the reference's *outcome* — what the source is, its claims, notation, assumptions and a section outline. Store it with the source; expose it read-only.
- **Dependency / thứ tự:** After CONTENT-TRUNC (shares the generation budget) and after the English-name deduplication.
- **Acceptance criteria:**
  - Positive: an ingested 3-page PDF returns a brief with ≥1 section whose `anchor`/`heading` correspond to real extracted text.
  - Negative: a source that fails extraction returns no brief rather than a fabricated one.
  - Negative: brief claims are capped at the declared limits (10/20/10).
- **Test bắt buộc:** Ingest integration test asserting section anchors resolve to extracted text; a negative test on a failed extraction.
- **Rủi ro:** A generated brief can hallucinate claims from a source — must be quoted/grounded, not paraphrased freely.
- **Rollback / feature flag:** `SOURCE_BRIEF_ENABLED`.
- **Ước lượng:** `M`
- **Không làm:** Do not infer chunking strategy from the reference's page-count coincidence; do not copy its prompt.
- **Trạng thái:** `PROPOSAL — CHƯA TRIỂN KHAI`

---

## 3. Full backlog by milestone

Remaining items use the same contract fields, compressed. All are `PROPOSAL — CHƯA TRIỂN KHAI`.

### Milestone 1 — functional blockers and security

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1-SEC-LIMITER | Rate limiter is per-process in-memory | P2 | None observed (`UNKNOWN_REFERENCE`) | `app/core/limits.py` in-memory; `SS-T-SEC-01..08` PASS | Bursts are throttled within one process only → throttled across instances | Move to Redis-backed counters; keep the same API | Celery/Redis already present | Positive: two app instances share the counter. Negative: limiter outage fails closed or documented | Integration test with 2 workers | Blocks legitimate traffic if misconfigured | Flag to fall back to in-memory | S | Do not change limits to hide a burst | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M1-ME-SURFACE | Missing `/me/stats`, `/me/entitlement` | P2 | `PS-R-ENTITLE-01` E2 (shape); `/home`, `/me/stats` E1 | 404 in `SS-T-E2E-02` | No stats/entitlement API → present for dashboard parity | Add both endpoints reading existing `User.xp`/`streak_days`; entitlement can return a static free tier until billing exists | After M1-SEC-LIMITER | Positive: `/me/stats` returns XP; `/me/entitlement` returns `{tier,...}`. Negative: unauthenticated → 401 | Contract tests + E2E step | Low | Revert routes | S | Do not invent a `paywalled` enforcement before billing is in scope | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M1-CI-GATE | CI must fail on a hollow gate | P1 | n/a | Branch `feat/p6.0-ci-pipeline`; recent commits show gate fixes | Gate exists but `pytest` skips 29 tests (`logs/backend-pytest-raw.log`) | Audit why 29 are skipped; convert skippable ones or document them | — | Positive: CI red when a required test is skipped. Negative: an intentional skip is explicitly allow-listed | CI config test | Could block unrelated PRs | Revert CI change | S | Do not mark tests skipped to make CI green | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 2 — course generation and content quality

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M2-TUTOR-Q | Concurrent streams capped but untested | P2 | `PS-R-TUTOR-01` E2 (live tutor) | `SS-C-TUTOR-05` `maxConcurrentStreams` declared | Cap is declared, not proven | Prove the cap under the enabled flag | P0-TUTOR-FLAG | Positive: N+1 concurrent streams → documented error. Negative: N streams all complete | Concurrency test | Provider throttling confounds result | Flag | M | Do not raise the cap to pass | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M2-P99 | Professional correctness: p99 misinterpreted | P1 | n/a | Judge note on en-advanced-distributed: *"p99 replication lag bị diễn giải thành '1% đọc thấy dữ liệu cũ tới 2s/3s'; p99 nghĩa là 1% vượt ngưỡng"* | Wrong technical claims can enter lessons → add a factuality lint / better grounding | Prompt + review pass for numeric claims | P1-CONTENT-TRUNC | Positive: a numeric-claim lint flags threshold/percentile misuse. Negative: correct claims pass | Eval lint over N=12 | False positives annoy authors | Warning-only first | M | Do not post-edit content with another LLM without review | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 3 — lesson and quiz coverage

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M3-PREFETCH | No next-lesson prefetch | P3 | `?prefetch=1` E2 observed | 0 hits in `frontend/src` | Navigation may feel slower than the reference → preload next lesson **if measured to help** | Add a query prefetch for the next lesson | Measure first | Positive: p95 nav time improves by a measured margin. Negative: no extra request when the next lesson is unknown | Perf measurement | Wasted requests | Remove prefetch call | S | Do not add prefetch purely to imitate the reference | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M3-NODES | Path lacks `state`/`format`/`nodes[]` | P2 | `PS-R-PATH-01` E2 | `SS-C-COURSE-01` flat `lessons[]` | Path exists but lacks the reference's node vocabulary → add `state` and `format` | Extend the course-detail contract additively | — | Positive: each lesson carries `state` and `format`. Negative: existing clients unaffected (additive only) | Contract test | Churn in the frontend types | Additive, revertible | S | Do not add `paywalled` until billing exists | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 4 — tutor SSE and context

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4-ENTRYPOINT | No `entryPoint` on tutor requests | P2 | `PS-R-TUTOR-02` E2 (`teach_block`) | `SS-C-TUTOR-04` body has no `entryPoint`; `extra="forbid"` | Server cannot distinguish entry surfaces → add `entryPoint` (6 declared values) | Add optional `entryPoint` to the request model; log it; no behaviour change yet | P0-TUTOR-FLAG | Positive: the value round-trips and is stored on the message. Negative: an unknown value → 422 | Contract test | Low | Field optional | S | Do not copy the reference's entry-point semantics blindly | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M4-CTXLABEL | No human-readable `contextLabel` | P3 | `PS-R-TUTOR-01` E2 (8/8, 16/16) | `TutorMessage.contextRef` machine-only | History shows no context label → present one | Derive a label server-side from `contextRef` resolver | M4-ENTRYPOINT | Positive: each message carries a label. Negative: a missing block → generic label, not an error | Serializer test | Localization cost | Label is additive | S | Do not store a stale label; derive it | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M4-TOOLS | 3 of 6 reference tools absent | P2 | `PS-S-TOOLS-01` E0 (6 names; only counts proven at runtime) | `SS-C-TOOLS-01` 3 tools | Narrow allowlist → add `flag_question` first (lowest risk) | Implement `flag_question`; consider `regenerate_unit` only after a confirm gate exists | F06 confirm gate unresolved | Positive: a flagged question is persisted and visible. Negative: flagging another user's lesson → 404 | Contract + isolation tests | Write paths need moderation | Flag off by default | M | Do not add `revise_proposal` before B04 exists | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M4-STREAM-RUNTIME | SSE never observed end-to-end in this audit | P1 | E2O (`delta`/`done`) | tests pass; runtime 503 | Implementation proven, runtime not → capture real frames | Run the tutor with the flag on and capture frames | P0-TUTOR-FLAG | Positive: `delta`×N then `done` captured in a log. Negative: mid-stream provider failure emits `error`, not a truncated stream | E2E with frame assertions | Provider cost | n/a | S | Do not claim SSE parity from tests alone | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 5 — source ingestion and citations

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M5-WEB-ARXIV | Web/arXiv ingest disabled or absent | P2 | enum E0; never exercised | `webEnabled:false`, `arxivEnabled:false` | PDF only → enable web, then arXiv | Enable `webEnabled` behind a flag; add an arXiv resolver if in scope | Ingestion stability | Positive: a URL ingests to `ready`. Negative: an unsafe/unreachable URL returns the declared rejection reason | Ingest tests with a local fixture server | SSRF risk on arbitrary URLs — requires an allowlist and egress controls | Flag off | M | Do not fetch arbitrary URLs without SSRF protection | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M5-RAG | Query-time retrieval returns 503 | P2 | `INFERENCE` only | `503 RAG_NOT_ENABLED`; offline eval recall@6 1.0, MRR 0.9643 on **lexical** hashing | RAG exists but disabled and lexical → enable with honest labelling, or keep disabled | Decide: enable lexical RAG with a "not semantic" caveat, or defer until a semantic embedding is chosen | Product decision | Positive: an enabled query returns grounded chunks + citations. Negative: no match → `insufficientEvidence`, never a fabricated answer | Eval re-run + negative query test | Lexical recall may mislead users | Flag | M | Do not present lexical retrieval as semantic | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 6 — personalization

Covered by P1-PEDAGOGY and P1-LEVEL-FIT above. No additional items.

### Milestone 7 — UX / i18n / gamification

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M7-GAMIFY | No streak/hearts/goal/level surface | P2 | `PS-R-REWARDS-01` E2 (names only; rules `UNKNOWN`) | `streak_days` column never exposed; 0 hits in frontend | XP only → expose the streak at minimum | Surface `streak_days`; do **not** invent hearts/goal rules | Product decision on the rules | Positive: streak appears in the dashboard. Negative: a zero/absent streak renders a neutral state | API + component test | Motivational mechanics with unobserved rules invite bad design | Flag | S (streak only) | Do not build hearts/freeze mechanics whose rules the reference never demonstrated | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M7-A11Y | No a11y/keyboard harness | P2 | partial a11y tree E2; no keyboard traversal | none | Unknown on both sides → establish a baseline | Add an axe/playwright a11y check to CI | — | Positive: CI reports a11y violations. Negative: a new violation fails CI (or warns first) | CI job | Flaky rules | Warn-only first | M | Do not claim WCAG compliance from source inspection | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M7-RESPONSIVE | No viewport verification | P2 | RN Web E0 | `globals.css` + `useMediaQuery`; untested | No evidence either way → capture screenshots at breakpoints | Playwright screenshot set at 3 widths | — | Positive: 3 screenshots render without overflow. Negative: a deliberately narrow width degrades gracefully | Visual test | Snapshot churn | n/a | S | Do not claim responsive correctness without screenshots | `PROPOSAL — CHƯA TRIỂN KHAI` |
| M7-I18N-UI | UI hardcoded Vietnamese | P2 | bundle strings E0; never switched | `SS-C-LANG-01` | Single-language UI → add an i18n layer **if** the language work lands | Extract strings; add a locale provider | P1-LANG | Positive: UI switches to English. Negative: a missing key falls back to Vietnamese, never to a raw key | Component test | Large mechanical diff | Flag | L | Do not machine-translate at runtime | `PROPOSAL — CHƯA TRIỂN KHAI` |

### Milestone 8 — billing

| ID | Item | Pri | PolySkill evidence | SopiSkill evidence | Current → expected | Scope | Depends on | Acceptance | Test | Risk | Rollback | Est | Không làm | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M8-BILLING | No billing/entitlement enforcement | P3 | Declared only (E0); **never exercised**; `UNKNOWN_REFERENCE` | No billing code; `/me/entitlement` 404 | No paid tier → **out of scope until the reference's billing behaviour is captured** | Do not start | Reference capture first | n/a — cannot write acceptance criteria for unobserved behaviour | n/a | Building a paywall model from a field list risks locking in the wrong design | n/a | L | Do not implement `paywalled` enforcement from an E0 field name | `PROPOSAL — CHƯA TRIỂN KHAI` |

---

## 4. Sequencing summary

```
P0-TUTOR-FLAG
   └─ M4-STREAM-RUNTIME, M4-ENTRYPOINT, M4-CTXLABEL, M2-TUTOR-Q
P1-CONTENT-TRUNC
   ├─ P1-QUIZ-BLANK (same generation pipeline)
   ├─ P2-FIGURES (same pipeline)
   └─ P2-BRIEF (same budget)
P1-PEDAGOGY + P1-LEVEL-FIT (same file)
P1-PROPOSAL-EDIT  → prerequisite for M4-TOOLS / revise_proposal
P1-GLOSSARY (D05 → D06)
M1-SEC-LIMITER, M1-ME-SURFACE, M1-CI-GATE (independent, parallel)
M3-PREFETCH (measure first), M3-NODES (additive)
M5-WEB-ARXIV, M5-RAG (product decisions)
M7-* (a11y/responsive harness first; gamification needs a rules decision)
M8-BILLING — blocked on reference capture
```

## 5. What this backlog does not do

- It does not propose a stack rewrite. Every item is additive to the existing FastAPI + Next.js
  architecture.
- It does not copy PolySkill code, UI, assets, prompts or secrets. Where the reference has a
  schema, items say "replicate the outcome, not the code".
- It does not bypass external access, permissions or spend limits.
- It does not assign dates. Estimates are `S`/`M`/`L` only.
- It does not treat an `UNKNOWN_REFERENCE` row as a defect. M8-BILLING is explicitly *not* an
  implementation task until the reference behaviour is observed.
