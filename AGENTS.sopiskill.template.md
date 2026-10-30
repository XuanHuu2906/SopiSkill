# SopiSkill — mandatory agent rules

> Copy into project-root `AGENTS.md` after reviewing and merging with existing rules; this file is a template, not an installed global policy.

## Project identity
- SopiSkill is an independent AI learning platform. PolySkill static/dynamic reports only inform observed product behavior; never copy proprietary code, branding, assets, prompts or infer its backend algorithms as facts.
- Current architecture: `backend/` FastAPI + SQLAlchemy async + Celery; `frontend/` Next.js 15 + TanStack Query; PostgreSQL + Redis in Docker Compose on Windows/WSL2. Verify every claim against the live repository; do not overwrite source or change stack blindly.
- Follow `docs/development-progress.md` as a status ledger, but independently verify code and tests. `MockProvider` is not a real LLM.

## Before editing
1. Inspect git status, branch, relevant files and existing tests; read skill `sopi-repo-audit` for implementation tasks.
2. Present scoped plan: context, modules, ordered steps, acceptance, tests to execute, exclusions.
3. Select task-specific skills as needed (`sopi-fastapi-auth`, `sopi-alembic-migrations`, `sopi-celery-reliability`, `sopi-llm-structured-output`, `sopi-quiz-progress`, `sopi-tutor-sse`, `sopi-rag-provenance`, `sopi-ai-evaluation`).
4. Keep changes small and reversible; preserve existing API contracts unless explicitly approved.

## Safety and evidence
- User/course/lesson/source/contextRef ownership is enforced on the server using authenticated identity. Never trust arbitrary client IDs, source content, model output, or frontend answer keys.
- Keep secrets server-side; protect from SSRF, prompt injection, leaking PII or provider keys. API schema validation, rate limits, idempotency, capped retries, timeouts and sanitized logs are required where relevant.
- No destructive database/volume operations without explicit approval and backup. Do not use `docker compose down -v`, drop tables or blindly stamp Alembic.
- No unauthorized reverse engineering or calls to third-party endpoints without permission.
- Report every milestone as IMPLEMENTED / TESTED / NOT TESTED / BLOCKED. Never announce PASS without executed tests and visible evidence.
- Run `sopi-verification-report` at task end and record exact commands and failure limitations.
