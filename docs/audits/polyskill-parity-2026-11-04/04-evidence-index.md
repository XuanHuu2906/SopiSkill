# 04 — Evidence Index

Audit: `polyskill-parity-2026-11-04` · Generated: 2026-11-04 (Asia/Ho_Chi_Minh, +07:00)
Reference: PolySkill `web.polyskill.app` · Target: SopiSkill HEAD `d747e78` + dirty working tree

Every row below is an actually-executed probe, an actually-read file, or an actually-captured
session. Rows marked `OWNER_REPORTED` were transcribed by the product owner, not machine-captured.
No template row was retained.

Prefixes per §6.1: `PS-R-` PolySkill runtime, `PS-S-` PolySkill static, `SS-C-` SopiSkill code,
`SS-T-` SopiSkill test.

## 1. PolySkill — runtime (PS-R)

| Evidence ID | System | Source type | Scenario | Timestamp (+07:00) | File/path/hash hoặc CLI log | Finding | Caveat |
|---|---|---|---|---|---|---|---|
| PS-R-HARNESS-01 | PolySkill | CDP passive | ENV-HARNESS | 2026-10-31T11:02:51 | `evidence/observations-redacted.json` → ENV-HARNESS | REA 6.7.0 reaches CDP, applies origin filters; 2 page targets, `disallowed_origin=0` | Verifies the harness, **not** any AI capability. `network.requests=0` (idle page) |
| PS-R-INGEST-01 | PolySkill | runtime HTTP | ENV-INGEST | 2026-10-31T11:05:20 | same → ENV-INGEST; `evidence/runs.csv` | 20 requests; `POST /v1/sources/upload → 201`, `POST /sources/{id}/ingest → 202`, poll → brief populated | Chunker strategy is INFERENCE; section count == page count is not proof of strategy |
| PS-R-BRIEF-01 | PolySkill | runtime body | ENV-INGEST | 2026-10-31T11:05:20 | `reports/blackbox-findings.md` RAG-2 | `brief={what, claims[10], notation[9], assumes[5], sections[3]{anchor,heading,gist}}` | Field names are facts; values redacted |
| PS-R-COURSEGEN-01 | PolySkill | runtime HTTP | ENV-COURSEGEN | 2026-10-31T11:10:07 | `evidence/runs.csv` | `POST /v1/courses → 201`; 5 interview answers; `/approve → 200`; `/generation → 200` ×56; lesson grounded | Generation-time grounding only, **not** query-time retrieval |
| PS-R-LESSON-01 | PolySkill | runtime body | ENV-COURSEGEN | 2026-10-31T11:10:07 | `polyskill-dynamic-analysis.md` §2.2 | `blocks[]` all 6 types; `figure{kind,nodes,rows,head,edgeLabels,groupLabels}`; `paragraphs[].termKey`; `terms[]`; `contentVersion`; `source:null` | Topic-based course, no external source |
| PS-R-ATTEMPT-01 | PolySkill | runtime body | Phase 2 quiz | 2026-10-30 | `polyskill-dynamic-analysis.md` §2.2 | `POST /lessons/{id}/attempts → 201`; req `{clientAttemptId,contentVersion,durationMs,startedAt,results[]}`; res `{attemptId,completedAt,duplicate,score,rewards}` | `rewards` shape captured; **behaviour** of streak/hearts/goal unmeasured |
| PS-R-REWARDS-01 | PolySkill | runtime body | Phase 2 quiz | 2026-10-30 | same | `rewards={xp,totalXp,streakDays,streakExtended,freezeBanked,hearts{count,max,nextRefillAt},goal{earnedToday,target,met},levelsEarned[],milestonesEarned[],flagged}` | Names only. Refill cadence, freeze rules, `flagged` meaning = UNKNOWN |
| PS-R-PATH-01 | PolySkill | runtime body | Phase 2 navigation | 2026-10-30 | `polyskill-dynamic-analysis.md` §2.2; `blackbox-findings.md` §4 | `units[]{kicker,blurb,tone,paywalled,nodes[]{kind,lessonId,state,ready,format,contentVersion}}`; `progress{completed,total,percent}`; `upNextLessonId` | `paywalled:true` on 2/3 units observed; **enforcement** never triggered |
| PS-R-GLOSSARY-01 | PolySkill | runtime body | Phase 2 navigation | 2026-10-30 | `GET /courses/{id}/glossary → 200` (2.2 KB); `blackbox-findings.md` RAG-11 | `terms[11]={key,kind,name,short,more,teaser,firstSeen{unit,lesson}}` | Provenance is unit/lesson, never a source page — design choice |
| PS-R-ENTITLE-01 | PolySkill | runtime body | Phase 2 home | 2026-10-30 | `GET /me/entitlement → 200` | `{tier,expiresAt:null,subscription:null,limits{courses{limit,used},openUnits,tutorAllowance{limit,remaining}}}` | Free tier, no subscription |
| PS-R-TUTOR-01 | PolySkill | runtime body | A1/A2 + U7/U13 | 2026-10-31T11:16 / 12:33 | `blackbox-findings.md` AG-2/AG-3/AG-7; `phase3-…md` §2 | `GET /tutor` → `messages[8→16]`, `contextLabel` 8/8 & 16/16, `toolCalls[4]`, `action:null` | Tool **names** never exposed. `action` null is not proof `confirm` doesn't exist |
| PS-R-TUTOR-02 | PolySkill | runtime body | A1 | 2026-10-31T11:16 | `blackbox-findings.md` AG-2; `runs.csv` A1 | POST body `{clientMessageId,entryPoint,contextRef{lessonId,blockIndex},text,threadId}`; `entryPoint=teach_block` | Context **sent** ≠ context **consumed** |
| PS-R-ALLOW-01 | PolySkill | runtime body | A2 | 2026-10-31T11:33 | `blackbox-findings.md` AG-7 | `allowance{limit,remaining}` + `limit{resetAt}`; UI 19 → 18 after one turn | `limit` vs `allowance` both present; semantics not fully separated |
| PS-R-SSE-01 | PolySkill | owner-reported | U13 | 2026-10-31T12:33 | `phase3-…md` §2; `test-matrix.md` U13 | `delta {text}`, `done` (keys incl `threadId`,`message`) | **OWNER_REPORTED**. REA 6.7.0 has no SSE parser → `body_shapes.response=ABSENT` |
| PS-R-CITE-01 | PolySkill | runtime accessibility | A3 / U8 | 2026-10-31T11:18 / 12:20 | `runs.csv` A3; `phase3-…md` U8 | 1 citation as inert `StaticText` `Trang 1 — Quy trình LUMORA-731`; `states:[]`; 0/33 buttons | Label↔page correct; `anchor` never machine-checked; not navigable in that view |
| PS-R-CITE-02 | PolySkill | runtime a11y text | U8 | 2026-10-31T12:20 | `phase3-…md` §3.1 | Tutor prefix rendered `Nguyên văn trang 3 一 Ngoại lệ MƯA TÍM…` (U+4E00 where a dash belongs) | Cause not inferred. Substituting `-` matches page-3 heading literally |
| PS-R-RAGPROBE-01 | PolySkill | runtime body | R1–R5 | 2026-10-31T11:16 | `runs.csv` R1–R5 | 6 oracle questions: 3 stages in order; paraphrase identified; 17 vs 71 no contamination; page-3 quote verbatim; clean refusal | n=1 per question. Mock-free live reference, but single trial |
| PS-R-QUICKACT-01 | PolySkill | runtime a11y | A2 / D2 | 2026-10-31T11:33 | `blackbox-findings.md` AD-2; `test-matrix.md` Phase-3 findings | 3 distinct label sets depending on thread state/session; 1 click → 1 turn, `toolCalls` 3→4 | Label set is **not** a stable contract |
| PS-R-REFRESH-01 | PolySkill | runtime HTTP | AG-8 | 2026-10-31 | `blackbox-findings.md` AG-8 | 7× `401` burst → `POST /auth/refresh → 200` → originals reissued at `200` | Client behaviour; server contract inferred from response codes |
| PS-R-D2-01 | PolySkill | runtime | D2 | 2026-10-31T11:33 | `runs.csv` D2; `observations-*.json` blocked | Difficulty actions only on empty thread; attempt window ended `target_changed` | `INCONCLUSIVE`. `contentVersion` never compared before/after |

## 2. PolySkill — static (PS-S)

| Evidence ID | Source type | File | Finding | Caveat |
|---|---|---|---|---|
| PS-S-SSE-01 | bundle declaration | `polyskill-analysis-report.md` §4; BASE-STATIC-1 | Client handles `delta, tool, confirm, done, error, restarted` | E0. Proves client knows names, not server emission |
| PS-S-TOOLS-01 | bundle declaration | `polyskill-analysis-report.md` §4; BASE-STATIC-2 | Tools `regenerate_unit, flag_question, explain_deeper, read_lesson, revise_proposal, read_source` | E0. No execution claim |
| PS-S-CITESCHEMA-01 | bundle declaration | same | `citationSchema{anchor, heading, gist}` | E0. G3 requires runtime resolution to count |
| PS-S-ENTRY-01 | bundle declaration | `polyskill-analysis-report.md` §4 | Entry points `tab, wrong_answer, teach_block, term, path_harder, proposal` | Only `teach_block` observed at runtime |
| PS-S-DIFFICULTY-01 | bundle declaration | same | Difficulty actions `harder, easier, more_practical` | Effect `UNKNOWN` |
| PS-S-API-01 | bundle call-sites | `polyskill-analysis-report.md` §3 | ~30 endpoints across auth/me/billing/courses/sources/tutor/lessons | Declared only. 16 runtime-confirmed, rest never exercised |
| PS-S-BILLING-01 | bundle call-sites | same | SePay: `/billing/plans`, `/checkout`, `/portal`, `/sync`, `/sepay/plans`, `/sepay/orders` | Never exercised → H06 `UNKNOWN_REFERENCE` |
| PS-S-I18N-01 | bundle strings | `polyskill-analysis-report.md` §4 | ~12 languages incl. Italian strings ("Il ragionamento di Pol") | Never switched at runtime |
| PS-S-FIGENUM-01 | bundle schema | same | `figure.kind ∈ {formula, visual, diagram}` | Enum only; no rendered formula captured |
| PS-S-STACK-01 | bundle metadata | `01-repo-and-tool-baseline.md` §1.5 | Expo SDK 57 / RN Web / React 19.2.3 / Metro 5,849,374 B sha256 `e7f84aaf…5d4ce` | Reference stack; not a parity requirement per se |

## 3. SopiSkill — code (SS-C)

All paths relative to repo root. Line numbers verified 2026-11-04 against the dirty working tree.

| Evidence ID | Area | File:line | Finding | Caveat |
|---|---|---|---|---|
| SS-C-ROUTES-01 | API surface | `backend/app/api/v1/*.py` | 44 `@router` declarations across 6 modules (auth 4, learner 5, research 4, routes 11, sources 15, tutor 5) | OpenAPI lists 39 path objects; difference = shared paths/methods. See §5 |
| SS-C-AUTH-01 | auth | `backend/app/api/v1/auth.py` `_user_out` | `UserOut = {id,email,displayName,xp}` only | No `stats`, no `entitlement`, no `notifications` endpoint |
| SS-C-COURSE-01 | course detail | `backend/app/services/course_service.py` `get_course_detail` | Returns `units[].lessons[]{id,orderIndex,title,status,contentVersion,completed}` + `progress{completed,total,percent}` | No `paywalled`, no `state`, no `ready`, no `format`, no `upNextLessonId`, no `nodes[]` |
| SS-C-PATH-01 | learning path | `backend/app/services/learning_path_service.py` `build_learning_path` | Returns `{nextLesson, reviewLessonId, reviewDueCount, blockedBy, prerequisitesDag{nodes,edges}}` | Behind `P50_ENABLED`; **different contract** from reference `upNextLessonId` |
| SS-C-LESSON-01 | lesson payload | `backend/app/api/v1/routes.py` `get_lesson` | `LessonOut{id,courseId,title,orderIndex,contentVersion,status,blocks,grounding,citations,evidenceNotice}` | No `figure`, no `termKey`, no `terms[]`, no `source` object |
| SS-C-BLOCKS-01 | block renderers | `frontend/src/app/lesson/[lessonId]/page.tsx:125–190` | All six block types rendered (teach/mc/blank/short/order/match) | No figure block; see SS-C-NOFIG-01 |
| SS-C-GRADE-01 | grading semantics | `backend/app/services/lesson_content.py:155–258` | `short`: `_normalize_text` (strip + `casefold` + whitespace-collapse) compared against every `acceptedAnswers` entry. `match`: iterates the submitted `{leftId:rightId}` map, rejects duplicate/out-of-range ids, rejects any pair that fails the private mapping, then requires `len(seen_lefts) == len(lefts)` — **all-or-nothing, partial maps always false**. `order`: exact permutation after un-shuffling. `mc`: `bool` explicitly rejected. `teach` skipped from `total` (`:296-298`) | Closes the audit's last open evidence question. Behaviour verified by reading the grader, not only the frontend comment |
| SS-C-GRADE-02 | grading is server-side | `lesson_content.py:279–311` `grade_attempt`; `lesson_service.py:99–123` | Grading runs wholly against the **private** blocks; `AttemptAnswer.answer` carries only the learner's value. `contentVersion` mismatch → `409` before grading | Matches the reference's *outcome*; the reference's server policy is `UNKNOWN` (`PS-R-ATTEMPT-01`) |
| SS-C-NOFIG-01 | figures | `backend/app/schemas/schemas.py` `LessonContent` | No `figure` field on any block schema | `figure` matches in backend are `config`/`embedding` false positives |
| SS-C-NOGLOSS-01 | glossary | whole repo | `glossary`, `termKey`, `term_key` **absent** from backend and frontend | Reference has `terms[11]` + `paragraphs[].termKey` |
| SS-C-ATTEMPT-01 | attempts | `backend/app/api/v1/routes.py` `submit_attempt`; `schemas.AttemptRequest` | Req `{clientAttemptId,contentVersion,durationMs,answers[]{index,answer}}`; res `{attemptId,duplicate,score,rewards{xp,xpEarned},results,reviewCardCreated}` | **No** `streak`, `hearts`, `goal`, `levelsEarned`, `milestonesEarned`, `flagged`, `totalXp`, `timeMs`, `startedAt` |
| SS-C-ATTEMPT-02 | answer-key isolation | `schemas.AttemptAnswer` (`extra="forbid"`, `_reject_bool`) | Client cannot submit `correct`; bool rejected explicitly | Stronger than reference (which sends `correct` per result) |
| SS-C-VERSION-01 | content version | `routes.py` `submit_attempt` | `409 CONTENT_VERSION_MISMATCH` when `contentVersion` differs | Verified by test, see SS-T-* |
| SS-C-XP-01 | XP | `backend/app/services/lesson_service.py` | Monotonic top-up `max(0, desired - already)`; `XP_PER_CORRECT=10`; `XP_LESSON_COMPLETED_BONUS=20` | `rewards.xp` is absolute user XP; `xpEarned` is this attempt |
| SS-C-STREAK-01 | streak | `backend/app/models/models.py:157` | `User.streak_days` column exists | Never exposed in any API response; no streak logic surfaced |
| SS-C-TUTOR-01 | SSE events | `backend/app/api/v1/tutor.py` | Emits `delta, done, error, tool, citations, cancelled, heartbeat` | **No** `confirm`, **no** `restarted` |
| SS-C-TUTOR-02 | replay | `tutor.py:19` docstring | Explicit decision: `Last-Event-ID` resume **not supported**; `replaySupported=false` returned | Honest divergence from reference (reference declares `last-event-id`) |
| SS-C-TUTOR-03 | stop/cancel | `tutor.py` `POST /messages/{message_id}/stop` | `cancel_requested_at` flag, producer stops, emits `cancelled` with partial | Best-effort; does not refund provider cost |
| SS-C-TUTOR-04 | context | `schemas.TutorMessageRequest`/`TutorContextRef` | `{clientMessageId, threadId?, text, contextRef{lessonId, blockIndex}}`, `extra="forbid"` | **No `entryPoint`**. Server re-resolves context from DB |
| SS-C-TUTOR-05 | quota | `schemas.TutorQuotaLimitsOut/UsageOut` | `{messagesPerDay, tokensPerDay, maxConcurrentStreams}` + `remaining{messages,tokens}` + `tokensKnown` | Different contract from reference `allowance{limit,remaining}`; `GET /tutor/usage` |
| SS-C-TOOLS-01 | tool allowlist | `backend/app/services/tutor_tools.py` | 3 tools only: `read_lesson, explain_deeper, read_source`; `extra="forbid"`; `blockIndex 0..200` | Reference declares 6 tool names |
| SS-C-TOOLS-02 | tool audit | `tutor_tools.py`, `tutor.py:615` | `{name, summary, ok→status}` recorded per execution | Present; persistence scope needs check in backlog |
| SS-C-CITE-01 | citations | `frontend/src/app/lesson/[lessonId]/page.tsx:439–471` | Real citation card: title/url, `sourceVersion`, `pageNumber`, `validationStatus` badge, `evidenceText` quote, honesty caveat | **Stronger** than reference's inert `StaticText` |
| SS-C-CITE-02 | citation ladder | `backend/app/services/citation_service.py` | 4-level honesty ladder; `evidenceSupported` always `false` in P4.1 | locator ≠ claim support, documented |
| SS-C-INGEST-01 | ingest | `backend/app/api/v1/sources.py` (15 routes) | Create source, upload doc, web-document, list/get/delete docs, evaluation, link-to-course, search | RAG search gated by `RAG_ENABLED` |
| SS-C-INGEST-02 | ingest config | `sources.py` `GET /sources/ingest-config` | Exposes `ingestEnabled, storageConfigured, maxPdfBytes, maxPdfPages, embedding{…}, ragEnabled, webEnabled, arxivEnabled, ocr{…}` | Honest capability advertisement |
| SS-C-PEDAGOGY-01 | profile extraction | `backend/app/services/pedagogy.py:79–103,141–150` | `_TIME_UNIT_MINUTES` lacks `gio`/`phut`; `_DEPTH_DEEP` lacks bare `"hiểu sâu"`; `_STYLE_VISUAL` lacks `"đồ thị"`; `_detect_goal` picks longest answer | Provider-independent defects, reproduced by direct call |
| SS-C-LANG-01 | language | `backend/app/providers/openai_compatible_provider.py:58,228`; `providers/base.py` | `LLMProvider` has **no `language` parameter** in any of its six abstract methods; prompts hardcode "bằng tiếng Việt" (L58) / "tiếng Việt" (L228) | Root cause of `language_quality` eval defects |
| SS-C-FLAGS-01 | feature flags | `backend/.env.example` (156 keys) | All parity-critical gates default **off**: tutor, tutor tools, RAG, web ingest, OCR, P5.0, P5.2 | Runtime `/health` reports `provider:"mock"` |
| SS-C-FRONT-01 | frontend inventory | `frontend/src` | 28 files / 6,302 lines; `lib/api.ts` 839; `lesson page` 828; `sources page` 675; `TutorPanel` 572 | `globals.css` 78.3K self-authored |
| SS-C-FRONT-02 | nav | `frontend/src/components/layout/TabBar.tsx` | Exactly 4 tabs: `/`, `/new`, `/sources`, `/review` | Reference has home/learn/path/profile-style tabs + notifications |
| SS-C-FRONT-03 | gamification UI | whole frontend | Only `xp` rendered. No streak, hearts, goal, levels, milestones UI | Consistent with SS-C-ATTEMPT-01 |
| SS-C-FRONT-04 | tutor UI | `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx` | Frames at 160/171/180/198/210/220: `delta, done, error, tool, citations, cancelled` | Sends `contextRef` but **no `entryPoint`** |
| SS-C-DRIFT-01 | doc drift | `docs/frontend-reference/design-tokens.md:79-80` | Claims `next/font`; `frontend/src/app/fonts.css` is self-hosted | Documentation drift, not runtime defect |
| SS-C-DRIFT-02 | doc drift | `docs/frontend-reference/api-gap-register.md` GAP-07 | Claims generic identifier-less `tool` event | Contradicted: `tutor.py` `tool` frames carry `name`; `TutorPanel.tsx:202` consumes it |

## 4. SopiSkill — test / runtime (SS-T)

| Evidence ID | Type | Command / file | Result | Caveat |
|---|---|---|---|---|
| SS-T-PYTEST-01 | backend suite | `logs/backend-pytest-raw.log` | `699 passed, 29 skipped, 17 warnings in 112.97s`, `EXITCODE=0` | Run against dirty working tree |
| SS-T-PYTEST-02 | named tests | same log (warning traces) | `test_sse_frame_escapes_newlines_and_is_single_data_line`, `test_tutor_system_prompt_contains_lesson_but_never_answer_key`, `test_tutor_system_prompt_lists_linked_sources_without_content`, `test_history_is_bounded_and_filters_empty`, `test_block_index_out_of_bounds_is_422`, `test_prepare_turn_rejects_thread_of_other_lesson`, `test_real_vietocr_preserves_vietnamese_diacritics`, `test_duplicate_and_out_of_bounds_answer_index_rejected` | Names from log traces; full pass list not enumerated |
| SS-T-TSC-01 | typecheck | `logs/frontend-tsc.log` | `No errors found`, `EXITCODE=0` | Dirty tree, not HEAD |
| SS-T-BUILD-01 | build | `logs/frontend-build.log` | `next build` 15.5.28, compiled 4.2 s, 11/11 static pages, `EXITCODE=0` | Route table recorded; shared 103 kB |
| SS-T-SEC-01 | security S1 | `logs/security-probes.log` | B reads A's course → `404 COURSE_NOT_FOUND` PASS | No existence leak (404 not 403) |
| SS-T-SEC-02 | security S2 | same | B lists courses → `200 {"items":[],"total":0}` PASS | — |
| SS-T-SEC-03 | security S3 | same | B answers A's interview → `404` PASS | — |
| SS-T-SEC-04 | security S4 | same | POST without `X-CSRF-Token` → `403 CSRF_INVALID` PASS | — |
| SS-T-SEC-05 | security S5 | same | Wrong CSRF → `403` PASS | — |
| SS-T-SEC-06 | security S6 | same | Unauth GET existing course → `401 NOT_AUTHENTICATED` PASS | — |
| SS-T-SEC-07 | security S7 | same | Forged `X-User-Id` (`ALLOW_DEMO_HEADER=false`) → `401` PASS | Verified live, not by reading code |
| SS-T-SEC-08 | security S8 | same | Tampered JWT → `401 TOKEN_INVALID` PASS | — |
| SS-T-E2E-01 | E2E chain | `logs/e2e-chain.log` | topic → interview ×5 → proposal → approve → generation `ready` in ~2 s → 2 units × 2 lessons → 4 lessons with 6 blocks → 4 attempts `201` | `LLM_PROVIDER=mock`; content quality is mock-conditional |
| SS-T-E2E-02 | E2E negative | same | `GET /v1/me/stats`, `/v1/me/entitlement` → `404` — routes do not exist | Not a bug; absence of feature |
| SS-T-E2E-03 | tutor gate | same | `GET/POST …/tutor/*` → `503 TUTOR_DISABLED` | Gate off in container; **no SSE frame observed at runtime** |
| SS-T-INGEST-01 | ingest E2E | `logs/domain-g-ingest.log` | register 201 → create source 201 → upload 202 → poll[0] `queued`, poll[1] `ready`; 3 pages, 3 chunks, `textSource:"native"` | Own synthetic fixture, disposable account |
| SS-T-INGEST-02 | RAG gate | same | `POST /courses/{id}/sources/search` → `503 RAG_NOT_ENABLED` (positive and negative query) | `RAG_ENABLED=false` in this stack |
| SS-T-INGEST-03 | source evaluation | same | 6 criteria `{authority 0.45 weak, relevance 0.9, freshness unknown, evidence 0.65, consistency unknown, licensing 0.6}`; `knownWeight 0.55`, `weightedScore 0.55`, `verdict moderate`, `suggestedVerificationStatus pending_review` | Honest unknown handling (unknown criteria excluded from weighted score) |
| SS-T-EVAL-P22-01 | AI quality (reported) | `backend/evals/reports/p22_openai_compatible_20261031_192252.json` | N=12 topics, 12/12 pass, `deepseek-ai/deepseek-v4.1-flash-1017`, `p3.0-v1`, 149 LLM calls, judge scored 11, mean 3.17 | `REPORTED` — produced by the project's own eval harness, not re-run this audit |
| SS-T-EVAL-P22-02 | judge distribution | same | `objective_clarity 3.27`, `level_fit 2.36`, `structural_logic 3.55`, `example_correctness 3.45`, `quiz_alignment 3.09`, `answer_consistency 2.82`, `repetition 3.73`, `language_quality 2.27`, `safety 4.00` | n=11 judged of 12 |
| SS-T-EVAL-P22-03 | language defect | same, per-topic | 6/6 English-requested topics delivered Vietnamese; `language_quality` = 1.0/1.0/0.0/1.0/1.0 | Pairs with SS-C-LANG-01 root cause |
| SS-T-EVAL-RAG-01 | RAG eval (reported) | `backend/evals/reports/rag_20261031_232936.json` | recall@6 `1.0`, MRR `0.9643`, abstention `1.0`, p50 5.08 ms; en MRR 1.0, vi 0.9375 | `hashing-ngram-v1` = lexical, **not** semantic |
| SS-T-EVAL-BENCH-01 | RAG bench (reported) | `backend/evals/reports/rag_bench_20261031_231825.json` | size 8000 → p95 460.26 ms; decision `needPgvector: true`, `candidateLimit: 2000` | Decision explicitly refuses change "chỉ vì 'nghe hiện đại hơn'" |

## 5. Known discrepancies in this index

1. **39 vs 44.** `01-repo-and-tool-baseline.md` §1.8 records **39 path objects** from the live OpenAPI
   document. Direct enumeration of `@router` decorators gives **44 declarations**. The difference is
   path-object deduplication across methods plus router prefixes. Both are correct measurements of
   different things; §3 SS-C-ROUTES-01 uses 44 for the code-inventory count and this note reconciles it.
2. **`01` line count for the lesson page.** `01` records 829 *changed lines* in the diff. The file
   itself is **828 lines**. Different metrics; not a contradiction.
3. **`01` "no backend file modified".** Still true: `git status` shows zero modified files under
   `backend/`. All SS-C rows describe **existing code on HEAD + dirty frontend**, not new backend code.
4. **SopiSkill `streak`.** A `User.streak_days` column exists (`models.py:157`) but no response
   exposes it and no service updates it beyond user creation default. It is *not* feature parity.
