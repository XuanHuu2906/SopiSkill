# 08 — AI Quality Evaluation

Audit: `polyskill-parity-2026-11-04`
Subject: SopiSkill course-generation and tutor **output quality** (not parity)
Mandate: §7.3 — a five-criterion 0–4 rubric, reported separately, never folded into parity

> **Scoping statement, read before the numbers.** This chapter measures the *quality of generated
> content*. It is **not** a parity score and contributes **zero** to `06`'s figures. The reference
> product's model and provider are `UNKNOWN` (`02` §4, §10); no attempt is made to imitate them.
> Everything below scores **SopiSkill's own output** against a rubric, not against PolySkill.
>
> **And the most important caveat of all:** the numbers in §4 come from a run whose provider was a
> **real external model** (`openai_compatible`), *not* the default `mock` provider. SopiSkill ships
> with `LLM_PROVIDER=mock` by default (`01` §1.7). A `mock` provider cannot be scored on any of these
> criteria in any meaningful sense — see §2.

## 1. What was actually measured, and what was not

| Dimension | Status | Why |
|---|---|---|
| Course generation (profile → proposal → lessons → quizzes) with a real provider | **MEASURED** | `p22_openai_compatible_20261031_192252.json` — 12 topics, 149 LLM calls, judge requested |
| Judge scoring of the above | **MEASURED, 11/12** | One topic hit `PROVIDER_BUDGET_EXCEEDED`; 11 scored |
| Tutor response quality | **NOT MEASURED** | `tutor_enabled: bool = False` at `config.py:95`; live surface returned `503 TUTOR_DISABLED`; no real-provider tutor transcript exists |
| Retrieval / RAG answer quality | **NOT MEASURED as generation quality** | Benchmarks exist (`rag_20261031_232936.json`) but they measure retrieval recall, not answer quality; and `503 RAG_NOT_ENABLED` on the live path |
| Mastery modelling (BKT) | **NOT quality-measured** | A simulation exists (`bkt_simulated_20261102_125015.json`) but it is a synthetic simulation, not content quality |
| Human expert scoring | **NOT PERFORMED** | This audit's reviewer is an LLM (see §3); no human rater panel was used |

**Consequence for the final report:** five of six quality dimensions are unmeasured. The AI-quality
section of `00` must carry that limitation explicitly, not bury it.

## 2. Why "mock provider" must never be scored as quality

SopiSkill's default `LLM_PROVIDER=mock` returns fixture-shaped, deterministic output. Three
independent reasons it cannot enter a quality rubric:

1. **It is not the product's real output.** Scoring it would measure the fixture generator's
   author, not the system's capability.
2. **It cannot fail the criteria that matter.** Level fit, language match, and truncation are
   properties of a real model's token budget and prompting — a deterministic stub has neither.
3. **It would flatter the product.** A clean-looking mock transcript would produce a high score
   from zero capability, which is exactly the "valid JSON ≠ quality" error the mandate forbids.

Therefore §4 scores **only** the real-provider run. The `mock` path is recorded as *operationally
default* and *quality-unmeasured*, and the backlog item `P0-TUTOR-FLAG` in `07` exists partly
because a stakeholder could mistake `503 TUTOR_DISABLED` (a flag) for "the tutor is broken" (a
defect) — neither of which is a quality statement.

## 3. Reviewer, rubric, and its authority limits

### 3.1 Reviewer

The judge is an LLM, configured in SopiSkill's own eval harness (`backend/evals/`), prompt version
`p2.2-judge-v1`. It scored 11 of 12 topics — `judge.scored: 11`, `judge.notRun: 0`, one excluded
by budget. It is **not** a human expert and **not** this audit's author.

The harness records its own disclaimer verbatim; the audit reproduces it without softening:

> *"Điểm do LLM chấm chỉ là tín hiệu tham khảo, không phải ground truth và không thay thế người chấm."*

("LLM scores are only a reference signal, not ground truth, and do not replace a human scorer.")

**This is the single most important line in this chapter.** Every number in §4.2 is that kind of
signal. It is strong enough to identify *defect classes* (a truncated lesson is truncated regardless
of who noticed) and weak enough that the *magnitude* of a 3.17 cannot be read as "good" or "bad"
against an absolute standard.

### 3.2 The mandated five-criterion rubric (0–4)

The mandate (§7.3) names five criteria. The harness's nine criteria map onto them as follows; the
mapping is declared here so no reader has to reverse-engineer it, and gaps are stated honestly.

| Mandate criterion | Harness criterion mapped | Complete? |
|---|---|---|
| 1. Profile / topic alignment | `level_fit` + `objective_clarity` | **Yes** |
| 2. Proposal / lesson coherence, difficulty, example, activity | `structural_logic` + `example_correctness` + `repetition` | **Yes** |
| 3. Quiz correctness / consistency | `quiz_alignment` + `answer_consistency` | **Yes** |
| 4. Tutor scaffolding / misconception repair / lesson-groundedness | *(none)* | **NO — tutor never ran** |
| 5. No fabricated citations / correct insufficient-source handling | *(none)* | **NO — sources path disabled** |

So of the five mandated criteria, **three were measurable and two were not**. Criterion 4 is
unmeasurable because the tutor has never served a real response (`tutor_enabled=False`); criterion 5
is unmeasurable because the web/arXiv ingest path returned `503 RAG_NOT_ENABLED` and the source
course's citations were never exercised end-to-end with an enforcer active. The audit does not
substitute proxy evidence for either.

An additional harness criterion, `language_quality`, has no direct home in the five but is reported
because it produced the clearest defect class in the whole run (§4.4).

## 4. Measured results

### 4.1 Run identity (all facts from the JSON)

| Field | Value |
|---|---|
| Report file | `backend/evals/reports/p22_openai_compatible_20261031_192252.json` |
| `evalVersion` | `p2.2-v1` |
| `provider` | `openai_compatible` (real, not mock) |
| `model` | `deepseek-ai/deepseek-v4.1-flash-1017` |
| `promptVersion` | `p3.0-v1` |
| `usedRealProvider` | `true` |
| Dataset | 12 topics; languages `[en, vi]`; levels `[advanced, beginner, intermediate]`; ambiguity `[ambiguous, broad, clear]` |
| Totals | **12 topics, 12 passed, `passRate 1.0`** |
| LLM calls | 149 |
| Tokens | 103 984 prompt + 339 926 completion |
| Cost | `costEstimateUsd: null`, `costKnown: false` (**unknown spend**) |
| Judge | `requested: true`, `scored: 11`, `notRun: 0`, `averageScore: 3.17` |
| Judge prompt | `p2.2-judge-v1` |

Thresholds the run self-declared and met: `lessonPassRate 1.0`, `quizPerLesson 1.0`,
`minTeachRatio 0.15`, `minAvgTeachChars 60`, `maxDuplicateTitleRatio 0.0`,
`maxCrossLessonDuplicateQuestionRatio 0.35`, `minLessonQuizAlignment 1.0`.

**Note what `passRate 1.0` means and does not mean.** It means every topic produced output that
satisfied the harness's *structural* assertions — the right number of lessons, at least one quiz
each, a teach-ratio floor, no duplicate titles. It is a **schema/shape** pass, not a quality pass.
The judge scored the *same* outputs at a mean of 3.17/4 with a visible defect in 11 of 11 scored
topics. That gap between "12/12 passed" and "every scored topic had at least one defect" is the
central lesson of this chapter and should be quoted that way.

### 4.2 Per-criterion means (n = 11, 0–4 scale)

| Criterion | Mean | Reading |
|---|---|---|
| `safety` | **4.000** | Ceiling. No harmful content observed at all |
| `repetition` | 3.727 | Little cross-lesson duplication — genuinely good |
| `structural_logic` | 3.545 | Lesson sequencing coherent |
| `example_correctness` | 3.455 | Examples mostly correct, some truncated |
| `objective_clarity` | 3.273 | Objectives stated, sometimes vaguely |
| `quiz_alignment` | 3.091 | Quizzes usually match the lesson, not always |
| `answer_consistency` | 2.818 | **Weak** — answers contradict or are underspecified |
| `level_fit` | **2.364** | **Lowest** — generated level does not match the requested level |
| `language_quality` | **2.273** | **Second-lowest** — requested language not honoured |

**Overall mean: 3.17/4.** The ordering is the finding: the system is *safe* and *well-structured*
but *miscalibrated on level* and *unreliable on language*, with *inconsistent answers* behind them.
Two criteria below 2.5 on a 0–4 scale is not a marginal shortfall; it is a systematic one, and it
recurs per-topic (§4.5) rather than being driven by one outlier.

### 4.3 Score distribution (n = 11)

`mean 3.1718 · median 3.22 · min 2.67 · max 3.56 · stdev 0.315`

| Topic | Score |
|---|---|
| vi-beginner-python | 3.56 |
| vi-beginner-cooking | 3.56 |
| vi-intermediate-sql | 3.44 |
| vi-advanced-behavioural-econ | 3.33 |
| vi-advanced-statistics | 3.33 |
| en-beginner-guitar | 3.22 |
| vi-ambiguous-ai | 3.11 |
| en-ambiguous-productivity | 3.00 |
| en-advanced-climate | 3.00 |
| en-intermediate-writing | 2.67 |
| en-advanced-distributed | 2.67 |

The tight stdev (0.315) over a 2.67–3.56 band means there is **no single bad topic to blame**. The
defects are systemic. Note also the language split in the ranking: the top five are all `vi`; the
bottom four are all `en` — consistent with `language_quality` being a top-two contributor to the
score loss (§4.4, defect class ii).

**Excluded run:** `en-beginner-excel` was not scored —
`PROVIDER_BUDGET_EXCEEDED: Output chạm trần token (4800 >= 4800) và bị cắt.` ("output hit the token
ceiling and was cut"). This is itself a quality observation — the run could not produce a complete
lesson within its own budget — but it is not scored, and the audit does not impute a score for it.

### 4.4 Defect classes found by the judge (verbatim)

Six distinct, recurring defect classes. Quotes are reproduced exactly as the judge wrote them,
because paraphrasing a defect quote would let the audit's reader doubt the finding.

**(i) Truncation — 7 of 11 scored topics.** Output hit the 4 800-token cap mid-content:

> *"Bài 7 bị cắt cụt giữa ví dụ `diem = [7, 8,`"*
> *"Bài 5 bị cắt giữa câu hỏi MC"*
> *"Bài 4 bị cắt ở phần short answer"*

This is the single largest defect class by count. It is a **hard generation failure**, not a
style issue: a lesson that ends mid-array or mid-question is unusable regardless of how well its
first four lessons were written. It is why `P1-CONTENT-TRUNC` is the #2 item in `07`'s Top 10.

**(ii) Language mismatch — 6 of 6 English topics.** Every single `en` topic was generated in
Vietnamese:

> *"All lesson content is Vietnamese although requested language is en"*
> *"Toàn bộ proposal và bài học viết bằng tiếng Việt dù yêu cầu ngôn ngữ là 'en'"*

**6 of 6 is not a flake; it is a deterministic failure** of language propagation into the generation
prompt. It is the #3 item in `07`'s Top 10 (`P1-LANG`) and the reason `language_quality` sits at
2.273.

**(iii) Level mismatch — 8 of 11.** The learner profile's level leaked onto the generated content
even when the request said otherwise:

> `learnerProfile.currentLevel='beginner'` persisted into intermediate/advanced lessons on 8 of 11
> topics.

Corresponds to `level_fit` 2.364 and to `07`'s `P1-LEVEL-FIT` (#8).

**(iv) Multi-blank single-answer ambiguity — 5 of 11.**

> *"Một số câu blank có 2 chỗ trống nhưng chỉ có một đáp án (Bài 2, 5, 6), gây mơ hồ."*
> ("Some blank questions have 2 gaps but only one answer, which is ambiguous.")

This is a **correctness** defect: the quiz is unanswerable as graded. It is `07`'s `P1-QUIZ-BLANK`
(#4) and a direct contributor to `answer_consistency` 2.818.

**(v) One technical error — en-advanced-distributed.**

> *"p99 replication lag bị diễn giải thành '1% đọc thấy dữ liệu cũ tới 2s/3s'; p99 nghĩa là 1% vượt ngưỡng"*
> ("p99 replication lag was interpreted as '1% of reads see stale data up to 2s/3s'; p99 means 1% exceed the threshold.")

A real domain error, and a good illustration that the harness's `safety` 4.0 says nothing about
*correctness*. Low frequency (1 of 11) but high severity per instance because a learner would absorb
the wrong definition.

**(vi) Missing `acceptedAnswers` — en-ambiguous-productivity.**

> *"Bài 4 short question thiếu acceptedAnswers"* ("Lesson 4's short question lacks acceptedAnswers.")

A schema-completeness defect at the edge of the strict schema: the field is optional enough that
the harness's structural pass accepted the output, but the judge — reading it as content — flagged it
as ungradeable.

### 4.5 Disagreement between the two automated views

The harness and the judge **disagree** on the same 11 outputs:

| View | Verdict |
|---|---|
| Structural harness | **12/12 pass**, every threshold met |
| LLM judge | mean **3.17/4**; **a defect present in every scored topic** |

This is not a contradiction to resolve; it is the point. A green structural suite is necessary and
insufficient. `00` must report both numbers side by side and must not let "passRate 1.0" stand alone.

### 4.6 What the score does **not** establish

- It does **not** establish that a human would rate these lessons 3.17/4. The judge is an LLM
  (§3.1). No human rater panel was run.
- It does **not** establish anything about the tutor (never served a real response) or about
  citations/insufficient-source handling (RAG path disabled). Criteria 4 and 5 of the mandate are
  **unmeasured**, not "passed".
- It does **not** establish that the 12-topic dataset is representative. It is 12 synthetic topics
  across 2 languages and 3 levels — small, and `n = 11` after the budget exclusion.
- It does **not** compare to PolySkill. The reference's model is `UNKNOWN`; there is no benchmark to
  compare against and the mandate forbids imitating it.

## 5. Retrieval, sources, and mastery — reported, not quality-scored

These three exist as reports and are recorded so `00` does not omit them, but none is a content-quality
measurement of the five-criterion rubric.

### 5.1 Retrieval benchmark (`rag_20261031_232936.json`)

| Metric | Value | Caveat |
|---|---|---|
| recall@6 | 1.0 | Small fixture corpus |
| MRR | 0.9643 | Same |
| Abstention accuracy | 1.0 | Same |

**Critical scoping fact:** SopiSkill's embeddings are **hashing n-gram vectors, dim 256, lexical** —
*not* semantic embeddings, and **not** pgvector (`rag_bench_20261031_231825.json` records
`needPgvector: true`, i.e. the bench concludes pgvector would be needed for the next step). A
recall@6 of 1.0 on a lexical index over a tiny synthetic corpus says the retriever finds the words
it was given; it says nothing about semantic retrieval, and it must never be presented as "RAG
works". `07`'s `M5-RAG` carries this warning in its own acceptance criteria.

### 5.2 Live retrieval path

`GET`/`POST` on the source-backed path returned **`503 RAG_NOT_ENABLED`**
(`logs/domain-g-ingest.log`). So even the lexical retrieval was not enabled on the live surface at
audit time. The benchmark is a **REPORTED** artifact about an offline harness, not a runtime claim.

### 5.3 Mastery model (`bkt_simulated_20261102_125015.json`)

Gate PASS; simulated AUC 0.86835 vs baseline 0.72069. **This is a simulation**, with synthetic
learners — it demonstrates the BKT update machinery is not obviously broken; it is not evidence that
real learner mastery is tracked well. Recorded as `REPORTED`, never as a content-quality score.

## 6. The verdict on AI quality

Within the one dimension that could be measured honestly:

> **SopiSkill's real-provider course generation is structurally sound and safe, but systematically
> miscalibrated and intermittently broken.** Mean judged quality **3.17/4** (median 3.22,
> n=11), with `level_fit 2.364` and `language_quality 2.273` as the two failing dimensions and
> truncation appearing in 7 of 11 topics. Its own structural harness passes 12/12 on the same
> output, which demonstrates that the harness is a shape check, not a quality gate.

**And, explicitly:** two of the mandate's five criteria — tutor scaffolding (4) and
citation/insufficient-source honesty (5) — are **UNMEASURED** because the corresponding surfaces
were disabled during this audit. They are not "passing". Any statement that "AI quality was
evaluated" must carry that sentence with it.

### 6.1 The three quality defects that map to backlog items

| Defect class | Backlog item (`07`) | Why it is first in line |
|---|---|---|
| Truncation (7/11) | `P1-CONTENT-TRUNC` (#2) | Unusable output; hard failure |
| Language mismatch (6/6 en) | `P1-LANG` (#3) | Deterministic; affects every non-vi user |
| Multi-blank ambiguity (5/11) | `P1-QUIZ-BLANK` (#4) | Ungradeable quiz question |

`P1-LEVEL-FIT` (#8) and `P1-PEDAGOGY` (#5) follow from the same evidence (level leak, profile-
derivation defects in `pedagogy.py`).

## 7. Reproduction

The report is a static JSON artifact. To re-derive every number in §4:

```
backend/evals/reports/p22_openai_compatible_20261031_192252.json
  .totals                       → §4.1 totals, passRate
  .judge.*                      → §4.1 judge block
  .topics[].judge.score         → §4.3 distribution
  .topics[].judge.criteria      → §4.2 nine means
  .topics[].judge.notes         → §4.4 verbatim quotes
  .provider/.model/...          → §4.1 identity
```

No command needs to be re-run to audit this chapter; the artifact is immutable on disk. Re-running a
*fresh* eval would be a new observation with a new model version and must not be merged with this one
without a new report file and a new audit ID.

## 8. What this chapter does not claim

- It does not claim these are **PolySkill's** quality numbers. They are SopiSkill's (`02` §4,
  `02` §10).
- It does not claim the judge is authoritative (§3.1). It is a signal, quoted with its own
  disclaimer.
- It does not claim Tutor quality or citation honesty — both **UNMEASURED** (§1, §6).
- It does not claim the 11-topic sample generalises (§4.6).
- It does not claim `passRate 1.0` means quality passed (§4.1, §4.5).
- It does not report a cost figure: `costEstimateUsd: null`, `costKnown: false` — spend for this
  run is **unknown**, and `00` must not invent one.
