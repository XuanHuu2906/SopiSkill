---
name: sopi-tutor-sse
description: Use for building AI Tutor in SopiSkill: authenticated lesson contextRef, SSE streaming, allowlisted tools, saved thread history, stop/cancel and quotas.
---

# AI Tutor SSE with grounded context

## Scope
New tutor modules/routes plus authenticated lesson ownership. Tutor is **not implemented in reviewed baseline**.

## Procedure
1. Define the server-owned `thread/message` contract and `contextRef(lessonId, blockIndex)`; verify owner + block bounds at API boundary and each tool call.
2. Compose context from server-stored lesson, user profile and permitted source chunks; never trust arbitrary client context or instructions embedded inside retrieved documents.
3. Implement SSE event contract with `delta`, `tool`, `confirm`, `done`, `error`. Define ordering, monotonic event IDs, stop semantics and disconnect behavior.
4. Use a strict tool allowlist (e.g., read_lesson, explain_deeper); gate actions that modify state by explicit confirmation and authorization.
5. Store message history idempotently by clientMessageId and owner/thread; distinguish generated content from committed messages.
6. Apply model timeout, token budget, rate limits, usage metering, cancellation and privacy-aware logging.
7. Tests: two users isolated, bad lessonId, invalid blockIndex, duplicate sends, stop, stream error, rate-limit and replay/reconnect if supported.

## Do not
No arbitrary tool execution, secrets in SSE, fake citations, or invented guarantee of SSE resume unless proven by tests.
