---
name: sopi-verification-report
description: Use before declaring any SopiSkill task done; collect actual test commands, exit codes, architecture impact, API behavior, security gates and progress report evidence.
---

# Verify before completion

## Checklist
1. `git diff --check` and inspect actual changes and unrelated files.
2. Run focused tests for touched modules, then `cd backend && python -m pytest -q` when environment supports it.
3. For frontend changes: `cd frontend && npm run build`; run lint only if a working lint script exists (do not claim success for a broken or obsolete command).
4. For runtime changes: `docker compose config`, `docker compose up --build -d`, `docker compose ps`; if needed run `backend/e2e_acceptance.py` with explicit `E2E_BASE` and valid auth under the updated contract.
5. Check DB migration revisions and backward compatibility on a safe DB copy; do not wipe existing volume.
6. For worker: inspect Celery logs, job state and duplicate behavior under retry.
7. For AI: use deterministic fake provider in CI; mark paid model tests separately with model/version, budget and sanitized evidence.
8. Update `docs/development-progress.md` to list exact test runs and failures, affected files, migration IDs, commit SHA, and remaining risks.

## Output template
- IMPLEMENTED: [code + files]
- TESTED: [command, environment, exit code, assertion/count]
- NOT TESTED: [why]
- BLOCKED: [missing tool/credential/dependency]
- ROLLBACK: [specific safe action]

## Do not
Never write PASS without actual executed commands; never use fabricated logs. Avoid misleading acceptance claims such as 'reload persisted attempts' unless a persisted attempt was actually retrieved/verified.
