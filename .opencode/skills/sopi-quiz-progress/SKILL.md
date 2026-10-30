---
name: sopi-quiz-progress
description: Use for SopiSkill quiz answer security, deterministic grading, XP, idempotent attempts, contentVersion and persisted course progress correctness.
---

# Quiz grading and progress integrity

## Touchpoints
`backend/app/services/grading_service.py`, `backend/app/services/lesson_service.py`, `backend/app/services/course_service.py`, `backend/app/schemas/schemas.py`, `frontend/src/app/lesson/[lessonId]/page.tsx`.

## Current caveats
The lesson GET response currently includes answer keys. `get_course_detail` initializes `completed=0` without deriving persisted progress. Existing E2E constructs perfect answers from returned keys; this tests mechanics, not quiz integrity.

## Procedure
1. Define a separate learner-safe lesson DTO; keep answerIndex, acceptedAnswers and correct associations server-side until policy authorizes reveal.
2. Keep deterministic grading for mc/blank/order/match and restricted exact-match short answers; free-form short answers need explicit rubric/LLM grading with separate status.
3. Validate attempts against current contentVersion and ownership; enforce idempotency using DB uniqueness + transaction under concurrent requests.
4. Specify completion rule (first submitted vs pass threshold) and calculate progress from persisted attempts, not in-memory page state.
5. Prevent duplicate XP under replay/concurrency and provide stable response to duplicate clientAttemptId.
6. Add tests for quiz without answer leakage, incomplete answer, manipulated results, cross-user attempt, progress after reload, version mismatch, race/idempotency.

## Do not
Do not trust client-provided `correct`, score, XP, or lesson ownership. Don't call exact string matching semantic grading.
