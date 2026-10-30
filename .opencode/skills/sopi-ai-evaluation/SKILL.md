---
name: sopi-ai-evaluation
description: Use to create evidence-based evaluations of SopiSkill LLM-generated courses, quiz correctness, AI Tutor grounding and RAG retrieval; compare real vs mock outputs.
---

# AI evaluation and evidence

## When to use
Before accepting any change to real LLM adapter, lesson generation, tutor, RAG or personalization. This is evaluation guidance, not a promise of model accuracy.

## Procedure
1. Capture baseline version/commit, provider/model, prompt version, dataset and budget. Separate offline deterministic unit tests from paid integration tests.
2. Build a >=10 topic evaluation fixture varying complexity, language, prerequisite structure and ambiguity. Keep expected properties, not brittle exact natural-language strings.
3. Course eval: Pydantic pass rate, output factuality by human/domain rubric, lesson uniqueness, prerequisite consistency and answer-key correctness.
4. Tutor eval: context faithfulness, correct refusal when source absent, tool authorization, contextRef scoping, latency/tokens/cost and streaming completion.
5. RAG eval: retrieval recall@k, citation precision, supported-claim rate, owner-scope leakage and negative/irrelevant queries.
6. Report n, pass/fail per case, rubric, real logs (redacted), limitations and regression comparison. Keep automated grading results distinct from human judgments.
7. Label each capability IMPLEMENTED / TESTED / NOT TESTED / BLOCKED; never infer effectiveness from 1 demo.

## Do not
Don't evaluate by self-congratulating LLM output, claim production readiness from schema validation alone, or report mock calls as paid LLM inference.
