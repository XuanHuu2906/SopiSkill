# 09 — Command and Test Log

Audit: `polyskill-parity-2026-11-04`
Purpose: every command executed against SopiSkill, with its exit code and its verdict — and an
honest list of what was **not** run.

The mandate (§10 Q9) requires null commands/exit codes/pass-fail-skip and what remains unrun. The
raw logs live beside this file in `logs/`; this chapter is the index, the verdict, and the gaps.

## 1. Environment under test

| Item | Value |
|---|---|
| Repo | `D:\Reverse Engineer` (git `XuanHuu2906/SopiSkill`) |
| Branch | `feat/p6.0-ci-pipeline` |
| HEAD | `d747e78ee8392a354db79805fe73b1477bc0c531` |
| Working tree | **DIRTY** — 15 modified + 8 untracked (see `01` §1) |
| Backend stack | Docker Compose: `reverseengineer-backend-1` (`:8001`), Postgres `:5433`, Redis `:6379`, MinIO, Celery worker + beat |
| `LLM_PROVIDER` | **`mock`** for all runtime logs in this chapter unless a row says otherwise |
| Python | 3.13 (host venv, torch/vietocr installed) |
| Node | Next.js 15.5.28, React 19 |
| Host OS | Windows 11, PowerShell 5.1 |

**All SopiSkill test evidence below was produced against the dirty working tree**, not against clean
HEAD `d747e78`. `03` §1.4 states this caveat once for the whole audit; it applies to every row here.

## 2. Backend test suite

| Command | Result | Log |
|---|---|---|
| `pytest` (backend, full suite) | **699 passed, 29 skipped, 17 warnings in 112.97 s** · `EXITCODE=0` | `logs/backend-pytest-raw.log` |

```
699 passed, 29 skipped, 17 warnings in 112.97s (0:01:52)
EXITCODE=0
```

**Reading the skip count.** 29 skipped is 4.0 % of 728 collected. The skips in this suite are
feature-gated paths (tutor, RAG, OCR, web ingest) that short-circuit when the flag is off — they are
**not** passing tests, and they are why `07`'s `M1-CI-GATE` exists. The audit does not count a skip
as coverage.

**Warnings seen (17, all benign, recorded because "0 warnings" was never claimed):**
- `StarletteDeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated` — appears at
  `app/services/tutor_service.py:442`, `app/api/v1/tutor.py:139`, `app/services/lesson_service.py:99`.
  Cosmetic; a rename to `HTTP_422_UNPROCESSABLE_CONTENT` clears it.
- `torch … enable_nested_tensor is True, but self.use_nested_tensor is False` —
  `tests/test_p43_ocr.py::test_real_vietocr_preserves_vietnamese_diacritics`. This is the one test
  that touches a **real** OCR model; it passed.

No test failure, no error, no xfail.

## 3. Frontend type-check and build

| Command | Result | Log |
|---|---|---|
| `cd frontend && npx tsc --noEmit` | **No errors found** · `EXITCODE=0` | `logs/frontend-tsc.log` |
| `cd frontend && npm run build` | Next.js 15.5.28, compiled in **4.2 s**, **11/11 static pages** · `EXITCODE=0` | `logs/frontend-build.log` |

Build routes observed (from `logs/frontend-build.log`):

```
○ /                        7.21 kB   127 kB
ƒ /course/[courseId]       5.15 kB   125 kB
ƒ /lesson/[lessonId]      11.8 kB    132 kB
○ /login                   2.15 kB   122 kB
○ /new                     2.3 kB    122 kB
○ /new/generating          3.51 kB   124 kB
○ /new/interview           3.92 kB   124 kB
○ /new/proposal            4.15 kB   124 kB
○ /review                  3.71 kB   124 kB
○ /sources                 7.04 kB   127 kB
```

`tsc` passing and `next build` passing establish **that the UI compiles**. They do **not** establish
that any screen renders correctly or that any flow works in a browser — no browser-driven UI
assertion was run (see §8).

## 4. Security probes — 8/8 PASS

| Command | Result | Log |
|---|---|---|
| Negative security probe script, target `http://localhost:8000` | **S1–S8 all PASS** · `EXITCODE=0` | `logs/security-probes.log` |

| # | Probe | Expected | Observed | Verdict |
|---|---|---|---|---|
| S1 | Account B reads account A's course | 404 | 404 `COURSE_NOT_FOUND` | **PASS** |
| S2 | Account B lists courses | only own | 200 `{"items":[],"total":0}` | **PASS** |
| S3 | Account B answers account A's interview | 404 | 404 `COURSE_NOT_FOUND` | **PASS** |
| S4 | Authenticated POST without `X-CSRF-Token` | 403 | 403 `CSRF_INVALID` | **PASS** |
| S5 | Authenticated POST with wrong `X-CSRF-Token` | 403 | 403 `CSRF_INVALID` | **PASS** |
| S6 | Unauthenticated GET on existing course | 401 | 401 `NOT_AUTHENTICATED` | **PASS** |
| S7 | Forged `X-User-Id` with `ALLOW_DEMO_HEADER=false` | 401 | 401 `NOT_AUTHENTICATED` | **PASS** |
| S8 | Tampered JWT in `access_token` cookie | 401 | 401 `TOKEN_INVALID` | **PASS** |

**Limitations of these probes, stated so the PASS is not over-read:**
- They ran on the **host `:8000`** process (§5 explains why that environment is misconfigured for
  generation). Auth/CSRF/tenancy code is environment-independent, so the results transfer; the
  *generation* chain does not, and the chain was run separately on `:8001` (§5).
- S7 is the only probe that substantively tests the demo-header bypass: `app/api/deps.py:44-46`
  gates it on `allow_demo_header AND env == "development"`, and it was verified **live** inert with
  `ALLOW_DEMO_HEADER=false`, not by reading.
- The rate limiter (`app/core/limits.py`) is **in-memory per-process**. It is effective in this
  single-process dev setup and would not be shared across workers. Recorded as a scaling
  limitation, not a parity gap (`07` → `M1-SEC-LIMITER`).
- No fuzzing, no dependency-CVE scan, no load test, no container escape test was run.

## 5. E2E chain — 18 steps, verified to `ready`

| Command | Result | Log |
|---|---|---|
| `python audit_e2e2.py` (stdlib driver, cookie jar + CSRF) → `http://127.0.0.1:8001` | **18 steps, chain reaches `ready`** · `EXITCODE=0` | `logs/e2e-chain.log` |

| # | Request | HTTP | Observed |
|---|---|---|---|
| 1 | `POST /v1/auth/register` | 201 | user created; HttpOnly `access_token` + readable `csrf_token` |
| 2 | `POST /v1/courses` + CSRF | 201 | `crs_8c004cb7-…`, `status:"interview"` |
| 3 | `GET /v1/courses/{id}/interview` | 200 | 5 deterministic questions, `completedCount: 0` |
| 4–8 | `POST …/interview/answer` ×5 | 200 ×5 | `completedCount` 1→2→3→4→5 |
| 9 | `GET …/proposal` | 200 | `version:1`, `approved:false`, `units[2]`, `skills[4]`, `outcomes[2]`, `learnerProfile` |
| 10 | `POST …/approve` + CSRF | 202 | `{"jobId":"job_24d863a0-…","status":"queued"}` |
| 11 | `GET …/generation` poll 0 | 200 | `queued`, `dispatched:true`, `lessonsDone:0` |
| 12 | `GET …/generation` poll 1 (+2 s) | 200 | **`ready`**, `stage:"done"`, `lessonsDone:4/4`, `attempts:1` |
| 13 | `GET /v1/courses/{id}` | 200 | 2 units × 2 lessons, all `ready`, `contentVersion:1`, `progress{0,4,0}` |
| 14 | `GET /v1/lessons/{id}` ×4 | 200 ×4 | 6 blocks each: `teach, mc, blank, order, match, short` |
| 15 | `POST …/attempts` ×4 + CSRF | 201 ×4 | `score{correct:0,total:5}`, `rewards{xp:0,xpEarned:0}`, per-block `solution` |
| 16 | `GET …/tutor/threads` | **503** | `TUTOR_DISABLED` |
| 17 | `POST …/tutor/messages` | **503** | `TUTOR_DISABLED` |
| 18 | `GET /v1/me/stats`, `/v1/me/entitlement` | **404** | routes do not exist |

**Environment correction that this run established.** `:8000` was a **host `uvicorn`** whose CWD was
the Python install directory; `SettingsConfigDict(env_file=".env")` is CWD-relative, so it never read
the repo `.env` and fell back to `celery_broker=None` — generation enqueued but never dispatched. The
earlier "generation BLOCKED" finding was **retracted** and re-attributed to this environment
misconfiguration, not to product code. `:8001` (the Compose backend with a real worker, Postgres,
Redis, MinIO) is what §5's results come from. This correction is recorded in `05` §11 and `06` §7.

Steps 16–18 are **runtime P0 blockers**, not tested passes: the tutor flag is off
(`tutor_enabled: bool = False`, `config.py:95`) and the `/me/stats` + `/me/entitlement` routes are
absent. They are the source of `07`'s `P0-TUTOR-FLAG` and `M1-ME-SURFACE`.

### 5.1 Server-side grading observation (from the same run)

All four attempts submitted deliberately-wrong answers and graded `score{correct:0,total:5}`,
`xpEarned:0`; `results[]` returned the correct `solution` per block, and `teach` blocks were
correctly excluded from grading (5 gradable of 6). The request schema `AttemptAnswer` is
`extra="forbid"` and rejects client booleans — so **the client-supplied `correct` flag the PolySkill
client sends cannot be accepted here**, which is a real behavioural improvement over the reference's
unmeasured grading policy (`02` §3.4).

`rewards.xp` (absolute) vs `rewards.xpEarned` (this attempt) is a **naming divergence** from
PolySkill's `rewards.totalXp`, not a behaviour gap (`05` E04/E05).

## 6. Domain G — source ingest chain

| Command | Result | Log |
|---|---|---|
| `python audit_g_ingest.py` → `http://127.0.0.1:8001` | register→create→upload→ingest→ready; RAG **503** | `logs/domain-g-ingest.log`, `logs/domain-g-ingest-result.json` |

Observed sequence:

| Step | HTTP | Key fact |
|---|---|---|
| `ingest_config` | 200 | `pipelineVersion: "p4.0-v1"`, `embeddingProvider: "hashing"`, `embeddingDimension: 256`, **`ragEnabled: false`**, `webEnabled: false`, `arxivEnabled: false`, `ocrEnabled: false` |
| `create_source` | 201 | source created |
| `upload_document` | 202 | 3-page synthetic PDF accepted |
| `documents_final` | 200 | `status:"ready"`, `pageCount:3`, `chunkCount:3`, `textSource:"native"`, `ocrPages:0`, `attempts:1` |
| `document_detail` | 200 | preview text confirms real extraction (page 1 content present) |
| `rag_search` | **503** | **`RAG_NOT_ENABLED`** |
| `rag_search_negative` | **503** | same |
| `source_evaluation` | 200 | 6-criterion rubric, `verdict:"moderate"`, `weightedScore:0.55`, `knownWeight:0.55` |

The `source_evaluation` response is worth recording because it is honest about its own limits —
verbatim from the log: `"Điểm phản ánh metadata, KHÔNG phải độ đúng nội dung hay độ tin cậy tuyệt
đối."` ("The score reflects metadata, NOT content correctness or absolute trustworthiness.")

The 3-page → 3-chunk correspondence is a **SopiSkill** ingest observation. It does **not** establish
parity with PolySkill's `brief.sections[]` (3 pages → 3 sections, `02` §3.8): SopiSkill returns
chunks, PolySkill returns an authored brief with `what/claims/notation/assumes/heading/gist`. That is
`07`'s `P2-BRIEF` and `05` G02's `MISSING`.

## 7. Deterministic profile-extraction probe

| Command | Result | Log |
|---|---|---|
| Direct call of `pedagogy.py` extractors | 11 cases; **4 wrong** | captured in `logs/e2e-chain.log` §"Deterministic profile-extraction defects" |

```
_parse_weekly_minutes('5 giờ mỗi tuần')  -> 300   CORRECT
_parse_weekly_minutes('3 gio tuan')      -> 3     WRONG (should be 180)
_parse_weekly_minutes('3 gio/tuan')      -> 3     WRONG (should be 180)
_parse_weekly_minutes('2 tieng/tuan')    -> None  WRONG (should be 120)
_parse_weekly_minutes('90 phut')         -> 90    CORRECT
_parse_weekly_minutes('5-6h moi tuan')   -> 300   CORRECT
_parse_weekly_minutes('10 hours per week')-> 600  CORRECT

_detect_depth('mình muốn hiểu sâu')      -> balanced  WRONG (expected deep)
_detect_depth('đi sâu vào chi tiết')     -> deep      CORRECT
_detect_depth('hiểu sâu để áp dụng')     -> balanced  WRONG (expected deep)
_detect_depth('phủ rộng kiến thức')      -> broad     CORRECT

_detect_styles('thích học qua đồ thị và ví dụ thực tế hơn là công thức') -> []
_detect_styles('học qua sơ đồ trực quan')-> ['visual']   CORRECT
_detect_styles('làm ví dụ và bài tập')   -> ['hands_on'] CORRECT
_detect_styles('thích lý thuyết')        -> ['theory']   CORRECT
```

**Why this probe matters:** these functions are **provider-independent**. The defects hold for the
real provider too, which is why they are scored in `05` A04 and carried as `07`'s `P1-PEDAGOGY` and
`P1-LEVEL-FIT` rather than being dismissed as `mock` artefacts.

Root cause (confirmed by reading `pedagogy.py:79-103`): the regex at `:90` accepts undiacritized
`phut|gio` but `_TIME_UNIT_MINUTES` has no `"gio"`/`"phut"` key, so the unit lookup falls through and
`factor` stays `1` — a silent **60× underestimate**. `"2 tieng/tuan"` fails differently: the
alternation lists `tiếng` but not `tieng`, so the regex does not match and returns `None`.

The `mock`-provider content defects (C1–C3, C6 in `logs/e2e-chain.log`) are **labelled mock** and are
**not** used as evidence of real-provider behaviour. Only the provider-independent defects above are.

## 8. What was NOT run — the honest gaps

This is the section the mandate's DoD (§11) turns on. Everything here is a hole in the evidence, not
a passing result.

| Not run | Consequence |
|---|---|
| **Browser-driven UI test** (Playwright/CDP click-through) | No screenshot-verified UI claim is made anywhere in this audit (`03` §1.4). `tsc` + `next build` prove compilation only |
| **Real-provider E2E through the UI** | The 18-step chain used `LLM_PROVIDER=mock`. Real-provider behaviour is covered only by the offline eval (`08`), not by a live UI flow |
| **Tutor runtime** | `503 TUTOR_DISABLED`; no SSE frame, tool call, allowance decrement, or citation observed live |
| **RAG live path** | `503 RAG_NOT_ENABLED`; retrieval measured only offline (`rag_20261031_232936.json`) |
| **Web / arXiv ingest** | `webEnabled: false`, `arxivEnabled: false`; only self-authored PDF was ingested |
| **OCR live path** | `ocrEnabled: false`; only the unit test `test_real_vietocr_preserves_vietnamese_diacritics` touched a real OCR model |
| **Review scheduling (P5.0)** | `P50_ENABLED=false`; never exercised |
| **Recommendation events (P5.2)** | Flag off; never exercised |
| **Billing / SePay** | No billing surface exercised; the reference's billing is `E0` only (`02` §8) |
| **Load / concurrency test** | No multi-worker, no rate-limiter-under-contention test |
| **Dependency CVE scan / SAST / image scan** | Not run |
| **i18n switching** | No language switch exercised on either side |
| **Keyboard / screen-reader traversal** | No a11y harness on either side (`05` H01–H06 all `UNKNOWN`) |

**The standing caveat that governs all of §8:** `05` scores these rows `UNKNOWN` (not `MISSING`),
and `06` charges them 0 toward the Conservative Floor while excluding them from Measured Parity's
denominator. Not-run is never evidence of absence.

## 9. Exit-code summary

| Run | Exit code | Verdict |
|---|---|---|
| Backend `pytest` | **0** | 699 passed / 29 skipped |
| Frontend `tsc --noEmit` | **0** | no errors |
| Frontend `npm run build` | **0** | 11 static pages |
| Security probes S1–S8 | **0** | 8/8 PASS |
| E2E chain (18 steps) | **0** | reaches `ready`; tutor/me-surface 503/404 recorded |
| Domain G ingest | **0** | ingest `ready`; RAG 503 recorded |
| Profile-extraction probe | **0** | probe ran; 4 wrong outputs are findings, not failures |

**No command in this audit exited non-zero**, and that is a statement about the harness, not about the
product: the probes that *would* fail (tutor, RAG, browser UI) were **not run at all**, so their
absence cannot appear as a red exit code. A reader who saw only this table would over-estimate
coverage. §8 exists to prevent exactly that misread.

## 10. Command inventory (for reproduction)

The commands whose raw output is in `logs/`:

```
pytest                                        → logs/backend-pytest-raw.log
cd frontend && npx tsc --noEmit               → logs/frontend-tsc.log
cd frontend && npm run build                  → logs/frontend-build.log
python <security probe script>               → logs/security-probes.log
python audit_e2e2.py                          → logs/e2e-chain.log
python audit_g_ingest.py                      → logs/domain-g-ingest.log (+ result json)
python -c "<pedagogy direct-call probe>"      → embedded in logs/e2e-chain.log
```

Drivers were stdlib-only and live in `%TEMP%`; they are **not** part of the repo and are not
product code. They registered two disposable accounts per run (`audit_*@example.test`), used
self-authored data only, and touched no production system. Re-running them would be a **new**
observation and must not be merged with these logs without a new audit ID.
