---
name: sopi-llm-structured-output
description: Use for integrating real Transformer/LLM provider adapters, course interviews, course proposals and lesson generation in SopiSkill with validated structured outputs and cost control.
---

# LLM provider & structured course generation

## Touchpoints
`backend/app/providers/base.py`, `backend/app/providers/__init__.py`, `backend/app/providers/mock_provider.py`, `backend/app/schemas/schemas.py`, `backend/app/worker/generation.py`.

## Existing contract
Provider methods: `generate_interview_questions`, `generate_proposal`, `generate_lesson`. Preserve `MockProvider` deterministic offline. If configured real provider is unsupported or not configured, **fail explicitly**, not silently fall back to MockProvider.

## Procedure
1. Verify provider SDK/API signatures against current official docs before editing code.
2. Implement a bounded adapter and keep credentials in server env. Model names, endpoints, timeout, retry, token and cost limits must be configurable.
3. Validate parsed JSON against Pydantic, then apply domain checks: five interview questions, unique lesson titles, Bloom learning objectives where applicable, prerequisites ordered without cycles, valid answer keys, and coherent teaching material.
4. Separate planner/proposal from individual lesson calls; persist prompt version, model, usage and sanitized error metadata.
5. Retry only recoverable errors; cap retries and avoid accidental duplicate billable calls after task redelivery.
6. Unit-test adapter with mocked HTTP; use opt-in real provider integration test only when keys/budget are explicitly available.
7. Evaluate content over >=10 varied topics and record schema pass rate, correctness issues, latency and cost.

## Do not
No claim of 'AI thật' for mock. No secret in browser or logs. No hallucinated citations or claims that PolySkill uses a particular model.
