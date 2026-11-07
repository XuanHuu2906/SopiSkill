# P1-QUIZ-BLANK Result

- **Timestamp:** 2026-11-04
- **Branch:** `feat/p6.0-ci-pipeline`
- **HEAD:** `d747e78` (unchanged; no commit, no push)
- **Scope:** backend validator + worker gate. **No frontend file was edited.**
- **Production files changed:** 2 · **Test files added/changed:** 2 · **Migrations:** none

---

## 1. Audit — what the contract actually is

The precondition for rejecting multi-gap blanks was to prove the current contract does **not**
support them. Four independent layers agree:

| Layer | Location | Fact |
|---|---|---|
| Schema | `backend/app/schemas/schemas.py` — `BlankBlock` | one scalar `answer: str`; there is no `blanks[]` field |
| Grader | `backend/app/services/lesson_content.py` — `grade_blank` | compares the whole normalized string against `block["answer"]` |
| Frontend | `frontend/src/app/lesson/[lessonId]/page.tsx` | renders exactly one `<input id="blank-N">`; submits one string |
| Projection | `backend/app/services/lesson_content.py` — `public_block` | sends only `{"type","sentence"}`; no answer key |

⇒ A question with 2 gaps and 1 answer is **unanswerable**. Rejecting it is the correct MVP.
Supporting N gaps would require an `M`-sized contract change (`blanks[]` positional answers,
N inputs, N-way grading) — explicitly out of scope for this phase.

### Defect reproduction (before any fix)

`backend/tests/test_quiz_blank.py` was written first and failed 4 / passed 10:

```
FAILED test_blank_with_two_gaps_and_one_answer_is_rejected
FAILED test_blank_with_two_bracket_gaps_is_rejected
FAILED test_blank_with_zero_gaps_is_rejected
FAILED test_blank_repair_does_not_create_a_second_gap
4 failed, 10 passed
```

The fourth failure is a *separate* defect discovered by the same investigation:

```
assert 2 == 1
 +  where 2 = _slots('____ là gì? Điền: ____')
```

`_mask_answer_in_sentence` masked the answer **again** even though the sentence already had a gap,
manufacturing a second one from a valid single-gap question.

## 2. Implementation (minimal)

### `backend/app/providers/validation.py`
- Added `BLANK_SLOT_COUNT = 1` and `_count_blank_slots()`.
- Counting rule: strict markers first (`_{3,}` runs + `[...]`); only if that count is 0, fall back to
  `…` / a lone `...`.
  - **Why strict-first:** in the real corpus there are 340 `____` runs, 0 `[...]`, 0 `…`, and exactly
    **1** literal `...` — and that one is `conn.execute(...)`, which already carries a `____`. Counting
    `...` unconditionally would false-positive on code syntax.
- The blank branch now raises unless `_count_blank_slots(...) == 1`. The message covers both 0 and 2+.
- `_mask_answer_in_sentence` no longer re-masks when the sentence already contains a marker.

### `backend/app/worker/generation.py`
- Calls `validate_lesson(content)` before writing the lesson row.
- **Why:** the OpenAI provider validates its own output (`openai_compatible_provider.py:215`), but
  `MockProvider` and any test/fake provider do **not**. Without a worker-level gate, "content failing
  schema must not be saved as `ready`" depended on which provider happened to be configured.
- This is a system boundary, so validation here is appropriate rather than redundant.
- `SchemaInvalidError` is already classified `("PROVIDER_SCHEMA_INVALID", False)` — no retry, no
  wasted paid call.

### What was deliberately *not* done
- No `short` validator change: `acceptedAnswers: list[str] = Field(min_length=1)` already makes an
  empty/missing list a Pydantic `ValidationError`, and `_validate_block` already rejects
  whitespace-only entries. The DB lint found **0** of 335 short blocks with this shape.
  - The judge note "Bài 4 short question thiếu acceptedAnswers" in the audit is most likely a
    **truncation artifact**: `judges.py` sends `str(lesson)[:3000]` per lesson.
- No answer rewriting: the 7 stored bad lessons are **left byte-identical**. Changing their sentences
  or answers could alter question meaning.
- No DB schema change, no migration.
- No severity ramp (`warning` → `error`): the audit's `07-gap-backlog.md` proposed a staged rollout,
  but the operator instruction for this phase is unconditional rejection. Divergence is recorded in
  §7 rather than silently ignored.

### Anti-hollow-test check
Temporarily replaced `validate_lesson(content)` with `pass` in the worker →
`test_invalid_blank_content_is_never_saved_ready` **FAILED**. Restored → **passed**. The worker
assertion is not vacuous.

## 3. Tests

| # | Command | Exit | Result | Log |
|---|---|---|---|---|
| 1 | `pytest tests/test_quiz_blank.py` (before fix) | 1 | 4 failed, 10 passed — defect reproduced | — |
| 2 | `pytest tests/test_quiz_blank.py` (after fix) | 0 | **14 passed** | `logs/pytest-targeted.log` |
| 3 | `pytest tests/test_quiz_blank.py tests/test_job_reliability.py` | 0 | **39 passed** | `logs/pytest-targeted.log` |
| 4 | `pytest` (full backend suite) | 0 | **714 passed, 29 skipped** | `logs/pytest-full.log` |
| 5 | `npx tsc --noEmit` | 0 | No errors | — |
| 6 | `npm run build` | 0 | Next 15.5.28, **11/11 routes** | — |
| 7 | `e2e_acceptance.py` (live, rebuilt containers, mock) | 0 | **61/61 PASS** | `logs/e2e.log` |
| 8 | Offline lint, 12 eval dataset topics | 0 | 48 lessons / 48 blanks / **0 invalid** | — |
| 9 | Read-only DB lint over stored lessons | 0 | 346 lessons · 341 blanks · **7 invalid** · 335 shorts · **0 invalid** | `logs/db-lint.log` |

Coverage of the required cases:

- **0 gaps** — `test_blank_with_zero_gaps_is_rejected`
- **1 gap** — `test_blank_with_one_gap_is_accepted`, `test_single_gap_public_block_hides_answer_and_grades`
- **2+ gaps** — `test_blank_with_two_gaps_and_one_answer_is_rejected`, `test_blank_with_two_bracket_gaps_is_rejected`
- **repair side effect** — `test_blank_repair_does_not_create_a_second_gap`,
  `test_blank_repair_fills_missing_gap_when_answer_is_in_sentence`
- **empty answer** — `test_blank_with_empty_answer_is_rejected`
- **short acceptedAnswers** — `test_short_with_empty_accepted_answers_is_rejected`,
  `test_short_missing_accepted_answers_is_rejected`, `test_short_with_blank_only_answer_is_rejected`
- **malformed input** — `test_blank_sentence_must_be_string`, `test_blank_answer_must_be_string`
- **not saved as ready** — `test_invalid_blank_content_is_never_saved_ready`
- **public projection leak** — asserts `pub == {"type": "blank", "sentence": ...}` and `"answer" not in pub`

The `skipped` count is unchanged from baseline (29, all `POSTGRES_TEST_URL`-gated).

## 4. Real-data lint (read-only)

Exported with `docker compose exec -T db psql -U ailp -d ailp` — `SELECT`, no writes, no deletions.
Both the *pre-fix* export (338 lessons) and a *post-E2E* export (346 lessons) were linted.

| Metric | Value |
|---|---|
| Lessons with content | 346 |
| Blank blocks | 341 |
| Blank blocks with invalid gap count | **7** (all pre-existing) |
| `short` blocks | 335 |
| `short` blocks with missing/empty `acceptedAnswers` | **0** |

The 8 lessons generated **after** the fix by the E2E run added **zero** new violations — the count
stayed at the same 7 rows, which is direct evidence the gate works end-to-end on the real
generation path.

The 7 offenders (left unmodified):

```
4363061a… block3  'Muốn lặp lại khối lệnh khi điều kiện còn đúng, ta dùng vòng lặp ____, ví dụ: ____ tong < 10: tong += 1.'  answer=while
d0860691… block3  'Với `ds = [1, 2, 2, ____]`, biểu thức `set(ds)` cho tập có ___ phần tử.'                                    answer=3
cdc8ce40… block3  'Trong Flask, ___ là ánh xạ giữa URL và hàm xử lý; ____ giúp framework biết cần gọi hàm nào.'               answer=route
c06f8d76… block3  'Khối ___ (tiếng Anh: ____) dùng để bao đoạn mã có thể gây lỗi, …'                                           answer=try
a85b613d… block2  'Từ khóa dùng để trả kết quả từ hàm là ____; khi viết mã ta đặt ____ ở cuối hàm.'                            answer=return
08d74996… block2  'Để thêm một phần tử vào cuối list, ta dùng phương thức ___; phương thức này là ____.'                       answer=append
30f90780… block2  'Để ghi log mức lỗi trong Python, ta dùng logging.____('Thông báo lỗi'); mức log này có tên là ____.'        answer=error
```

These are **already persisted** rows. The validator runs at generation time, so it prevents new
occurrences but does not retroactively rewrite them. They remain answerable by the frontend's single
input only if the learner types the single accepted answer — the second gap stays unfilled. That is a
**content defect**, not a code defect, and fixing it means rewriting question text, which this phase
was told not to do silently.

## 5. Regression evidence

Live E2E on the rebuilt containers (mock provider, `TUTOR_ENABLED=false`):

```
[PASS] 7. Mo bai hoc (blocks day du) blocks=['blank','match','mc','order','short','teach'] contentVersion=1
[PASS] 8. Quiz cham dung 100% score=5/5 xpEarned=70
[PASS] 8c. Nop lai khong farm XP xpEarned=0
[PASS] 9b. Progress tinh tu attempt progress={'completed': 1, 'total': 4, 'percent': 25}
[PASS] 9d. Stale contentVersion -> 409 status=409
[PASS] 10b. Dashboard co tien do + resume
[PASS] 12. Tutor flag tat -> 503 co ma loi code=TUTOR_DISABLED
===== KET QUA: 61/61 PASS =====
```

Quiz grading, XP idempotency, progress, `contentVersion` conflict handling, and the Tutor-disabled
path are all unchanged. `TUTOR_ENABLED` default remains `false`.

## 6. NOT TESTED

- **Browser UI** — the repo has no e2e/browser harness (`package.json` has no test script, no
  Playwright/Cypress/Vitest). `tsc` + `build` prove compilation only.
- **Real paid provider** — not called. All provider activity is `MockProvider` (marker
  `"chế độ MOCK"` in stream bodies). Zero paid calls.
- **Post-fix pass-rate on newly generated content under a real LLM** — the 12-topic offline lint and
  the 7-row DB lint are static checks, not a quality benchmark. The audit warned that tightening the
  validator could temporarily lower the pass rate; that risk is **unmeasured** here because measuring
  it requires paid generation.
- **PostgreSQL concurrency** — 29 skips are `POSTGRES_TEST_URL`-gated, same as baseline.

## 7. Deviations and open items

1. **Severity model.** `07-gap-backlog.md` proposed starting at `warning` and flipping to `error`
   after the prompt was fixed. This phase applies `error` immediately per the operator's instruction.
   Consequence: a provider that still emits 2-gap blanks will now fail its lesson (job →
   `PROVIDER_SCHEMA_INVALID`, non-retryable) instead of shipping it. For the real OpenAI path the
   prompt already says "đáp án blank phải xuất hiện trong sentence", but it does **not** yet say
   "đúng một chỗ trống". **Recommended follow-up (not done here):** add that sentence to
   `LESSON_SYSTEM` — it is a one-line prompt change that would make the failure mode rarer without
   weakening the gate.
2. **7 legacy rows** remain invalid. Remediation requires content rewriting, which is out of scope.
3. **Celery stale worker** — see the separate report; not fixed here.

## 8. Acceptance checklist

| Criterion | Status |
|---|---|
| 0 blank questions with invalid gap count **in the eval set** | ✅ 48/48 mock eval lessons, 0 invalid |
| Content failing schema is not saved as `ready` | ✅ enforced in worker + covered by test (proved non-vacuous) |
| No regression in quiz / progress / XP / Tutor | ✅ 714 passed, 29 skipped; E2E 61/61 |
| Report with logs and exit codes | ✅ this file + `logs/` |
| No push to main, no volume/database deletion, no migration edit | ✅ |
| 15 pre-existing modified files untouched | ✅ only `backend/app/providers/validation.py`, `backend/app/worker/generation.py`, 2 test files touched |

## Artifact hashes (SHA-256)

```
f397f1b681d96d03f126538f5249b328a40d3b1437c998a329ce4ef1931f4fe1  logs/db-lint.log
ee7f19d22e29e1772eccb504874a4a9c6de2dc4cdd2feefcbc81367ee7633b66  logs/e2e.log
eddec2e4f27112de9513a2d8cf661f26ff91c2d99a1151a7281a7ea0478c5ee2  logs/pytest-full.log
0a5c3e0bcfbce9bf8127fa732642614a4b19203897ddc747ed920b1437696b1f  logs/pytest-targeted.log
```
