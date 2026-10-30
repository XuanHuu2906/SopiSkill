---
name: sopi-repo-audit
description: Use before changing SopiSkill architecture, repository, dependencies, or code; audit current branch, files, constraints, baseline tests and prepare a bounded implementation plan.
---

# Repository audit and scoped implementation

## When to use
Every implementation or code-review task in SopiSkill, especially if the request presumes a feature exists.

## Ground truth
Read `README.md`, `docs/development-progress.md`, `docs/architecture.md`, relevant files and tests, then compare claims with actual code. Repository is organized as `backend/` (FastAPI/Python), `frontend/` (Next.js 15), `docker-compose.yml` (PostgreSQL/Redis/Celery). **Do not treat PolySkill frontend observations as evidence of its backend algorithms.**

## Procedure
1. Inspect `git status --short`, current branch and commit. Never overwrite unrelated changes.
2. Locate real code paths and tests; check dependencies and data contracts before coding.
3. State FACT / INFERENCE / UNKNOWN / PROPOSAL where research influences designs.
4. Write a short plan with purpose, scope, affected modules, ordered steps, acceptance, commands to run, rollback and explicit exclusions.
5. Implement only the smallest independently testable slice. Keep feature flags and mocks explicit.
6. Verify with executable commands; collect exit code, count and meaningful logs.
7. Conclude each item as IMPLEMENTED / TESTED / NOT TESTED / BLOCKED. Do not call a mocked response an LLM inference.

## Acceptance
No existing unrelated change overwritten; every claim points to code, a test run or a clearly labeled assumption.

## Do not
Do not clone PolySkill internals, fabricate test results, silently change stack, reveal credentials or run destructive database commands.
