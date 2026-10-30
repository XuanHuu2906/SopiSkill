---
name: sopi-alembic-migrations
description: Use for PostgreSQL SQLAlchemy schema changes, Alembic revisions, zero-data-loss upgrades, indexes, or model changes in SopiSkill.
---

# PostgreSQL & Alembic migrations

## Touchpoints
`backend/app/models/models.py`, `backend/app/db/session.py`, `backend/app/main.py`, `docker-compose.yml`, `docs/database-design.md`.

## Current repo caveat
Startup uses SQLAlchemy `create_all()` and an Alembic baseline has not been verified. Treat the existing volume as valuable user data.

## Procedure
1. Inspect actual schema, constraints and existing volumes; back up before risky changes.
2. Define migration path for (a) fresh DB, (b) existing populated DB. Decide carefully whether stamping is safe after comparing schemas.
3. Produce small reversible Alembic revisions; use data migration separately if necessary. Beware PostgreSQL enums, JSONB, uniqueness and cascade behavior.
4. Test upgrade on fresh DB, upgrade of copy of populated DB, and downgrade/forward recovery if safe. Verify rollback and columns/constraints.
5. In deployment, avoid `create_all()` as a substitute for migrations.
6. Record precise commands, revision IDs, database state before/after and evidence.

## Do not
Never run `DROP DATABASE`, `drop_all`, `docker compose down -v`, destructive table rewrites or blind `alembic stamp head` without explicit approval and backups.
