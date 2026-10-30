---
name: sopi-fastapi-auth
description: Use for SopiSkill FastAPI authentication, user identity, authorization checks, JWT/cookies, session security and multi-tenant access tests.
---

# FastAPI Auth & ownership

## Current repo touchpoints
`backend/app/api/v1/routes.py`, `backend/app/services/user_service.py`, `backend/app/services/course_service.py`, `backend/app/services/lesson_service.py`, `backend/app/models/models.py`, `frontend/src/lib/api.ts`.

## Known risk in reviewed commit
The current demo API accepts `X-User-Id` supplied by the browser. Database ownership checks exist, but headers are not authentication. Never report this as production-safe auth.

## Procedure
1. Audit actual identity flow and user model, and list all routes needing auth.
2. Propose compatible migration from demo identity to server-authenticated user: Argon2id password hashing and validated signed access credentials, lifecycle and error cases; explain JWT or cookie design. Prefer HttpOnly cookie plus CSRF controls when using cookies; avoid storing bearer secrets in localStorage.
3. Derive `current_user` only from verified authentication; do not trust userId, courseId, lessonId or contextRef sent by client for authorization.
4. Scope course/lesson/source/tutor/attempt queries to user server-side, preferably as a single restricted DB query.
5. Preserve idempotency per *authenticated* owner and avoid data loss for demo users; plan migration before altering the user schema.
6. Add positive/negative integration tests: no credentials (401), wrong identity, forged X-User-Id, expired/invalid token, cross-user read and write, session continuation.
7. Run backend tests and frontend build; document untested security assumptions.

## Do not
No hardcoded JWT signing keys, no credentials in logs, no open demo fallback in production, no unauthorized access just because a UUID is known.
