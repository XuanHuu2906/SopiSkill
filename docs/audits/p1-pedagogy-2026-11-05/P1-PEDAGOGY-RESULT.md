# GATE P1-PEDAGOGY — Result

- **Date:** 2026-11-05
- **Branch:** `feat/p6.0-ci-pipeline` · **HEAD:** `d747e78` (unchanged — no commit, no push)
- **Scope:** fix deterministic learner-profile extraction only. No LLM added, no schema change, no data migration.
- **Classification:** **IMPLEMENTED · TESTED** — *not deployed* (deploy was explicitly out of scope).

---

## 1. Root causes, per observed error

All four defects live in `backend/app/services/pedagogy.py` and share one theme: the parser compared **accented lexicons against un-normalised text**.

| # | Symptom | Root cause |
|---|---|---|
| C1 | `"3 gio tuan"` → **3** minutes (60× too low) | `_TIME_UNIT_MINUTES` was `{"phút":1, "giờ":60, "tiếng":60, "h":60, "hour":60, "min":1}`. The regex matched `gio`, then the `startswith` loop found no key ⇒ `factor` kept its initial `1`. `3 × 1 = 3`. |
| C2 | `"2 tieng/tuan"` → **None** | The regex alternation listed `phut|gio` unaccented but **not** `tieng`. The backlog's own claim that this case "should work" was wrong — it never matched. |
| C3 | `"mình muốn hiểu sâu"` → `balanced`; `"phu rong kien thuc"` → `balanced` | `_DEPTH_DEEP` had `"đi sâu"`/`"chuyên sâu"` but **not** `"hiểu sâu"`, and `_contains_any` was a bare `needle in text` with **no diacritic folding**, so every unaccented answer missed every accented lexicon entry. |
| C4 | `"đồ thị và ví dụ thực tế"` → `[]` | `_STYLE_VISUAL` lacked `"đồ thị"`; `_STYLE_HANDS_ON` lacked `"ví dụ thực tế"`. |

A fifth, latent defect surfaced while fixing: `_contains_any` had **no word boundaries**, so a short needle like `"h"` or `"rộng"` could match inside longer words (`"4th"`, `"trong"`). The backlog flagged this exact risk ("Lexicon growth increases false positives… Guard with word boundaries").

---

## 2. Files changed

| File | Change | Lines |
|---|---|---|
| `backend/app/services/pedagogy.py` | the fix | +96 / −27 |
| `backend/tests/test_p1_pedagogy.py` | **new** regression suite, 54 tests | new file |

No other file was touched. No schema, migration, route, or frontend change.

### 2.1 `pedagogy.py` — change map

| Line(s) | Change |
|---|---|
| 16–17 | `import unicodedata`, `from functools import lru_cache` |
| 60–69 | `_STYLE_HANDS_ON` gains `"ví dụ thực tế"` |
| 71 | `_STYLE_VISUAL` gains `"đồ thị"`, `"minh hoạ"`, `"minh họa"` |
| 74–82 | `_DEPTH_DEEP` gains `"hiểu sâu"` |
| 84–100 | `_TIME_UNIT_MINUTES` gains `phut`, `gio`, `tieng`, `mins`, `hours`, `hrs`, `hr` (both accented and unaccented forms) |
| 102–105 | **new** module-level `_TIME_UNIT_PATTERN` with `(?<![0-9a-z])` / `(?![a-z])` lookarounds |
| 115–123 | **new** `_fold()` — NFD decompose, strip `Mn`, `đ`→`d` |
| 126–128 | **new** `_fold_needle()` — `@lru_cache(maxsize=256)` |
| 131–149 | `_contains_any()` rewritten: folds haystack **and** needle, then rejects any match whose adjacent character is alphabetic |
| 155–173 | `_parse_weekly_minutes()` matches on folded text; unit lookup is now an exact `dict.get` instead of a `startswith` loop with a silent `1` default |
| 207–216 | `_detect_depth()` now returns `(depth, warnings)` and emits a warning on the deep/broad conflict |
| 237–238 | `extract_learner_profile()` unpacks the tuple and extends `warnings` |

**Design choice:** diacritic folding at one chokepoint, rather than hand-adding an unaccented twin for every lexicon entry. One mechanism covers all four lexicons and keeps them readable.

---

## 3. FAIL before → PASS after

### 3.1 Before the fix

`tests/test_p1_pedagogy.py` (Phase 2 suite, written **before** any source change):

```
22 failed, 31 passed, 2 warnings in 2.30s     EXIT 1
```
Log: `logs/p1ped-before.log`

Failing groups:

| Group | Cases |
|---|---|
| weekly minutes | `3 gio tuan`, `3 gio/tuan`, `2 tieng/tuan`, `3 gio moi tuan`, `hoc khoang 2 tieng moi tuan`, `2 tieng moi tuan` |
| depth | `mình muốn hiểu sâu`, `hiểu sâu để áp dụng`, `minh muon hieu sau`, `hieu sau de ap dung`, `phu rong kien thuc`, `can tong quan` |
| depth conflict warning | `test_conflicting_depth_warns_instead_of_guessing` |
| styles | `đồ thị và ví dụ thực tế`, `do thi va vi du thuc te`, `hoc qua so do truc quan`, `lam vi du va bai tap`, `thich ly thuyet` |
| level | `minh da hoc qua roi`, `minh da co nhieu nam kinh nghiem` |
| pass-through | `test_api_proposal_receives_parsed_profile`, `test_provider_prompt_carries_corrected_profile` |

### 3.2 After the fix

```
54 passed, 2 warnings in 2.76s                EXIT 0
```
Log: `logs/p1ped-after.log`

Every one of the 22 previously-failing cases now passes, and 23 further cases (added in Phase 4) also pass — so the suite grew from 53 to 54 tests while staying green.

### 3.3 The pass-through chain, proven end-to-end

`test_full_chain_from_unaccented_answers_to_quiz` walks **topic → interview (5 unaccented answers) → learner profile → proposal → approve → generation → lesson → quiz attempt**, and asserts at every hop:

```
payload.learnerProfile.weeklyMinutes == 180
payload.learnerProfile.depth         == "deep"
payload.learnerProfile.preferredStyles == ["hands_on", "visual"]
payload.learnerProfile.currentLevel  == "beginner"
→ generation status "ready"
→ lessons exist; public blocks leak no answer key
→ correct answers score full marks
```

To prove the test is not hollow, `pedagogy.py` was temporarily stashed back to its pre-fix state and the test re-run:

```
assert 3 == 180                               EXIT 1
```
Log: `logs/p1ped-chain-before.log` — that `3` is the exact 60× underestimate from C1, observed through the real API stack rather than the parser in isolation. Restoring the fix flips it to **1 passed, EXIT 0**.

---

## 4. Test runs — commands, counts, exit codes

| Suite | Command | Result | Exit |
|---|---|---|---|
| P1-PEDAGOGY regression | `pytest tests/test_p1_pedagogy.py -q` | **54 passed** | 0 |
| Pedagogy + API-flow + provider + grading | `pytest tests/test_p1_pedagogy.py tests/test_p21_pedagogy.py tests/test_api_flow.py tests/test_llm_provider.py tests/test_grading.py -q` | **146 passed** | 0 |
| Pedagogy + API flow (named gate) | `pytest tests/test_p1_pedagogy.py tests/test_p21_pedagogy.py tests/test_api_flow.py -q` | **85 passed** | 0 |
| Quiz / QUIZ-BLANK isolation | `pytest tests/test_quiz_blank.py tests/test_quiz_integrity.py -q` | **27 passed** | 0 |
| **Full backend** | `python -m pytest -q` | **774 passed, 29 skipped** | 0 |
| Frontend typecheck | `npm run typecheck` (`tsc --noEmit`) | clean | 0 |

Baseline before this gate: 720 passed / 29 skipped. 720 + 54 = 774 — every new test counted, nothing regressed.

---

## 5. Live probe of the mandated inputs

Run against the fixed module, UTF-8 console:

```
10/10 correct          (logs/p1ped-probe.log)
```
Covers the four mandated time cases, both mandated depth cases, the mandated style case, an unaccented broad case, an unaccented advanced-level case, and a genuinely ambiguous case falling back to `balanced`.

### 5.1 Anti-false-positive checks

```
10/10 correct          (logs/p1ped-boundary.log)
```

| Check | Result |
|---|---|
| `"mình đang ở tầng 4th"` | `None` — the letter `h` inside `4th` is not an hour |
| `"học lớp 4th"` | `None` |
| `"minh hoc sau khi di lam"` | `balanced` — `sau` (= after) is not a depth signal |
| `"minh hoc 3 gio trong tuan"` | `balanced` — `rong` inside `trong` does not fire |
| `"kien thuc trong tam"` | `balanced` |
| `"5 gio"` | `300` — a digit may precede the unit |
| `""` | `None` |
| `"999 gio"` | `None` — rejected by the 10 080-minute ceiling |
| deep + broad in one answer | `balanced` **and** a warning naming both `sâu` and `rộng` |

The last row is the acceptance criterion "a genuinely ambiguous answer yields `balanced` **and** a `warnings[]` entry rather than a confident wrong guess."

---

## 6. E2E — what was and was not run, and why

**`backend/e2e_acceptance.py` was NOT run.** Two independent reasons, both verified rather than assumed:

1. **It would exercise pre-fix code.** The running `backend` container was built 9 hours ago and still carries the old file. Proven read-only:
   ```console
   $ docker compose exec -T backend sh -c "grep -c _fold /app/app/services/pedagogy.py"
   0
   $ ls -l /app/app/services/pedagogy.py
   -rwxr-xr-x 1 root root 12856 Oct 31 06:36
   ```
   A green E2E there would say nothing about this fix.
2. **It writes to the live PostgreSQL database** (`E2E_PG_DSN` → `127.0.0.1:5433`) — real-data writes were forbidden by this gate.

Rebuilding or restarting the containers was also forbidden, so there was no compliant way to point the script at the fixed code.

**Substitute evidence, and why it is stronger rather than weaker:** `test_full_chain_from_unaccented_answers_to_quiz` drives the identical request sequence through the real FastAPI app over ASGI (same routes, same services, same DB layer), reads the private lesson content from the DB the same way `tests/support.py` does for the E2E loader, and — critically — fails on pre-fix code with `assert 3 == 180`. That reproduction is what an E2E against stale containers could not have given.

---

## 7. Classification

| Aspect | Status |
|---|---|
| Root cause identified per error, from real code | **DONE** |
| Regression tests written before the fix | **DONE** — 22 failing cases recorded |
| Fix implemented, deterministic, no LLM | **DONE** |
| Substring false positives guarded | **DONE** — boundary checks + 10 probe cases |
| Ambiguous input yields value + warning | **DONE** |
| Backward compatibility of the profile contract | **KEPT** — no field added/removed/renamed; literals unchanged |
| Old courses' stored profiles auto-updated | **NO** — not touched, as instructed |
| Full backend suite | **774 passed / 29 skipped, exit 0** |
| Frontend | **No code change needed**; `tsc --noEmit` exit 0 |
| Deployed / live-verified | **NOT DONE** — out of scope for this gate |
| Commit / push | **NOT DONE** — out of scope |

**Verdict: IMPLEMENTED · TESTED.** Deployment is a separate gate.

---

## 8. Risks

| # | Risk | Status |
|---|---|---|
| R1 | Broader lexicons raise false-positive rates | **Mitigated** — `_contains_any` now enforces alphabetic boundaries, and 10 explicit anti-false-positive probes pass. Residual risk is a *legitimate* phrase that happens to contain a keyword; those land as a wrong-but-harmless style badge, never as data corruption. |
| R2 | Behaviour changes for unaccented answers that previously produced `None`/`balanced` | **Intended** — that is the fix. Any consumer that encoded the old wrong values would see different numbers; no such consumer exists (grep found no external callers of the changed helpers). |
| R3 | Previously stored proposals keep their old, wrong profiles | **By design** — the gate forbids rewriting old data. New courses get correct values. |
| R4 | `_fold` uses NFD + `Mn` stripping, which does not normalise some edge cases (e.g. `ơ`/`ư` are single codepoints) | **Low** — both compose to the same folded form as their decomposed spelling, so matching is unaffected. `đ` is handled explicitly. |
| R5 | `warnings` is capped at 8 by the schema; a pathological answer set could push a warning out | **Low** — the depth warning is appended after at most 1 level warning, far below the cap. |

---

## 9. Rollback

Pure source revert — no migration, no data write, no image:

```bash
git checkout -- backend/app/services/pedagogy.py
rm backend/tests/test_p1_pedagogy.py
```

Nothing in the database changes shape or contents under either state.

---

## 10. Remaining work

- **P1-LEVEL-FIT** — the sibling backlog item that reads the same `pedagogy.py`; explicitly out of scope here.
- **P1-LANG** and **P1-CONTENT-TRUNC** — explicitly out of scope, not started.
- **Deployment** of this fix to the containers is a separate gate; the running images are still pre-fix (proven in §6).
- Optional, not recommended by this gate: adding `"đúng một chỗ trống"` to `LESSON_SYSTEM` (that is P1-QUIZ-BLANK's R2, untouched).
