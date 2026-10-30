---
name: sopi-celery-reliability
description: Use for Celery background course generation, Redis jobs, transactional dispatch, idempotency, retries, asyncpg loops and job cancellation in SopiSkill.
---

# Celery job reliability

## Touchpoints
`backend/app/worker/generation.py`, `backend/app/worker/celery_app.py`, `backend/app/services/course_service.py`, `backend/app/models/models.py`, `backend/app/db/session.py`.

## Observed constraints
Worker uses a new async SQLAlchemy engine per task to avoid asyncpg pool crossing event loops. Preserve or safely redesign this behavior with tests.

## Procedure
1. Map state transitions `queued -> running -> ready|failed`, commit boundaries and dispatch path after `approve`/`retry`.
2. Check duplicate delivery and simultaneous workers. Use atomic claim / row lock / guarded update and durable uniqueness; don't rely solely on checking `ready`.
3. Consider outbox or recovery sweep for DB commit succeeded but Celery dispatch failed. Avoid inline generation in production unless deliberately configured.
4. Make lesson writes and contentVersion safe under retries. Verify a rerun does not duplicate units/lessons/XP or destroy attempts.
5. Limit retries, exponential backoff, timeouts, failure codes; redact provider errors and record actual cost/latency.
6. Test two workers racing, redelivery, worker death, Redis down, provider timeout, partial generation and retry; include PostgreSQL+Redis integration where possible.

## Do not
Do not claim exactly-once execution from Celery alone. Do not implement an unbounded retry loop or reuse a pooled asyncpg engine across independent event loops.
