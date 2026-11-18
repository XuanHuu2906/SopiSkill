# 02 — Reference Evidence (PolySkill)

Audit: `polyskill-parity-2026-11-04`
Reference product: `https://web.polyskill.app` (API `https://api.polyskill.app/v1`)
Target product: SopiSkill, local repo, HEAD `d747e78`

This chapter registers **only what the reference product was actually observed doing**. It is
the denominator for every "PolySkill evidence" cell in `05-parity-matrix.md`. Three rules govern
this document and were applied without exception:

1. A **client bundle declaration** is never promoted to runtime behaviour.
2. An **owner transcript** (DevTools read by the owner) is recorded as `OWNER_REPORTED`, not `CAPTURED`.
3. **Absence of a capture is not evidence of absence.** A capability that was never exercised says
   `UNKNOWN`, never `MISSING`.

## 1. Evidence tiers used in this audit

| Tier | Label in matrix | Meaning |
|---|---|---|
| E0 | `PS-S-…` static | Present in the Metro bundle / client schema. Proves the client knows the name. Proves nothing about the server. |
| E1 | `PS-R-…` transport | A request/response was observed, but the body was filtered, truncated or not parsed. |
| E2 | `PS-R-…` runtime body | A response body shape was observed at runtime. Field **names** and types are facts. Field **values** are redacted or absent. |
| E2O | `PS-R-…` owner-reported | Runtime value transcribed by the product owner from DevTools. Not machine-captured. Weaker than E2. |
| — | `UNKNOWN_REFERENCE` | No observation exists. Not a gap claim. |

**Async-usage constraint:** the reference was exercised by the **owner**, not by the agent. Every
session was `mode: EXECUTED` or `EXECUTED_PARTIAL` with `actions_by_agent: []` and
`owner_ui_actions_performed: 14` / `3`. The agent ran only passive REA inspection windows
(`inspect-web-page`, `list-browser-targets`). This is why several cells below are `OWNER_REPORTED`.

## 2. Sessions and capture quality

| Session | Date (local, +07:00) | Mode | REA | Windows | Quality |
|---|---|---|---|---|---|
| `ps-bbx-2026-10-31` | 2026-10-31 11:02–11:34 | EXECUTED | 6.7.0 | ENV-HARNESS, ENV-INGEST, ENV-COURSEGEN, R1–R5, A1–A3, D2 | 3× `COMPLETE_WITHIN_WINDOW`, 2× `POLICY_FILTERED`, 1× `INCONCLUSIVE` |
| `ps-bbx-2026-10-31-p3` | 2026-10-31 12:05–12:33 | EXECUTED_PARTIAL | 6.7.0 | P3-PREFLIGHT, U8, U7/U13 (150 s) | 1× `COMPLETE_WITHIN_WINDOW`, 2× `POLICY_FILTERED` |
| Phase 1/2 baseline | 2026-10-30 | runtime (imported) | earlier | 10 observation rounds | imported, **not re-verified** |
| Phase 1 static | 2026-10-30 | bundle read | earlier | — | static only |

Origin-filter discipline: the correct usage (`--allowed-origins` repeated per origin) produced
`disallowed_origin: 0` and `dropped_events.total: 0` in the Phase-3 150-second window. Earlier
rounds with a wrong origin configuration dropped **93 API requests** (82 course-creation, 11 tutor)
— proving volume only, no body content. Those 93 are recorded as a **method lesson**, not as evidence.

## 3. Runtime-observed contracts (E2, usable as reference)

Each row is a shape the reference was seen returning. Field names are facts; values are redacted.

### 3.1 Course path

```
GET /v1/courses/{courseId}/path → 200
units[]: { kicker, blurb, tone, paywalled,
           nodes[]: { kind, lessonId, state, ready, format, contentVersion } }
progress: { completed, total, percent }
upNextLessonId: string
```
`paywalled: true` was observed on 2 of 3 units in the Phase-2 course.
Source: `polyskill-dynamic-analysis.md` §2.2; `blackbox-findings.md` §4. ID `PS-R-PATH-01`.

### 3.2 Glossary

```
GET /v1/courses/{courseId}/glossary → 200 (2.2 KB)
terms[11]: { key, kind, name, short, more, teaser, firstSeen: { unit, lesson } }
```
Provenance resolves to **unit/lesson, never to a source page** — a design choice, not a defect
(`blackbox-findings.md` RAG-11). ID `PS-R-GLOSSARY-01`.

### 3.3 Lesson payload

```
GET /v1/lessons/{lessonId}?prefetch=1 → 200 (2.8 KB)
lesson.blocks[]: teach | mc | blank | order | match | short
                 + figure { kind, nodes, rows, head, edgeLabels, groupLabels }
lesson.paragraphs[]: carries termKey  (glossary linkage)
lesson.terms[], lesson.contentVersion: int
lesson.source: null      (topic-based course — no arxiv/web/pdf)
cite: { anchor: string, label: string }     present on 3 of 7 blocks in the source-backed course
```
`figure.kind` client enum: `formula | visual | diagram` (E0 for the enum, E2 for the field name).
ID `PS-R-LESSON-01`.

### 3.4 Attempt submission and rewards

```
POST /v1/lessons/{lessonId}/attempts → 201 (533 B)
REQ: { clientAttemptId, contentVersion, durationMs, startedAt,
       results[]: { index, type, correct, timeMs, answer: { option } } }
RES: { attemptId, completedAt, duplicate,
       score: { correct, total },
       rewards: { xp, totalXp, streakDays, streakExtended, freezeBanked,
                  hearts: { count, max, nextRefillAt },
                  goal: { earnedToday, target, met },
                  levelsEarned[], milestonesEarned[], flagged } }
```
Note the client sends `correct` and `timeMs` per result; the server-side grading policy is
**UNKNOWN** — the client-supplied `correct` was observed in the request body, not proven trusted.
ID `PS-R-ATTEMPT-01`.

### 3.5 Entitlement / limits

```
GET /v1/me/entitlement → 200
{ tier, expiresAt: null, subscription: null,
  limits: { courses: { limit, used }, openUnits,
            tutorAllowance: { limit, remaining } } }
```
Observed account was free-tier with no subscription. ID `PS-R-ENTITLE-01`.

### 3.6 Tutor thread and allowance

```
GET /v1/courses/{courseId}/tutor[?entryPoint=…&lessonId=…&blockIndex=…&threadId=…] → 200
{ threadId, kind, sealed, title: null, nextCursor: null,
  messages[N]: { id, role, content, createdAt, contextLabel, toolCalls[], action },
  allowance: { limit, remaining },
  limit: { limit, remaining, resetAt } }
```
Measured on two independent sessions: `messages[8]` with `contextLabel` on 8/8 and `toolCalls[4]`
(Phase 2); `messages[16]` with `contextLabel` on 16/16, `toolCalls` at 4, and `action: null` on
16/16 (Phase 3). `allowance` decremented 19 → 18 after one turn (AG-7). ID `PS-R-TUTOR-01`.

### 3.7 Tutor POST body

```
POST /v1/courses/{courseId}/tutor/messages → 200, content-type: text/event-stream
{ clientMessageId, entryPoint, contextRef: { lessonId, blockIndex }, text, threadId }
```
`entryPoint` observed value: `teach_block`. ID `PS-R-TUTOR-02`.

### 3.8 Source ingest brief

```
source.brief = { what, claims[≤10], notation[≤20], assumes[≤10],
                 sections[]: { anchor, heading, gist } }
```
Fixture with 3 pages produced exactly 3 section objects with anchor+heading+gist, matching page
count. Chunker strategy itself is `INFERENCE`. ID `PS-R-BRIEF-01`.

### 3.9 SSE event names — OWNER_REPORTED only

`delta { text }` and `done` (keys include `threadId`, `message`) were transcribed by the owner from
DevTools. REA 6.7.0 has **no `text/event-stream` parser** (`body_shapes.response = ABSENT`;
verified by grep over the installed package dist). Therefore:

- `delta`, `done` → **E2O** (owner-reported, not machine-captured).
- `tool`, `confirm`, `error`, `restarted` → **not seen** in the excerpt. This is **not evidence of
  absence**; the client enum still declares all six. ID `PS-R-SSE-01`.

## 4. Negative / blocked observations — recorded, never promoted

| Capability | Result | Why it is not a "missing" claim |
|---|---|---|
| `confirm` gate (A4) | `messages[].action` stayed `null` on 14/14 and 16/16 messages | Deliberately not manufactured; the owner declined the required action. `UNKNOWN`. |
| `read_source` tool attribution (A3, U7) | tool **name** never exposed; `toolCalls` count stayed at 4 | 0 occurrences of any tool name in captures. Enum existence is E0 only. `UNKNOWN`. |
| Difficulty quick actions (D2) | Not testable — only rendered on an **empty** thread, and the only empty-thread lesson was consumed by U7/U13 | `INCONCLUSIVE`, not `MISSING`. |
| Citation navigation (RAG-9, U8) | 1 citation rendered as inert `StaticText`; `states: []`; 0 of 33 buttons matched | **Positive** observation: not navigable in that view. |
| `Last-Event-ID` resume | Declared in bundle header list; never exercised | `UNKNOWN`. |
| Adaptive difficulty effect | `contentVersion` never compared before/after | `UNKNOWN` — the mechanism exists; the effect is unmeasured. |
| Server-side RAG / retrieval | `INFERENCE` only | No client signal. Embeddings/vector DB `UNKNOWN`. |
| LLM provider / model | `UNKNOWN` | Entirely server-side; no client-side signal. |

## 5. Quick-action label sets — three observed sets, no stable contract

The label set is **state-dependent and session-dependent**. It must never be asserted as a product
contract. All three observed sets:

| State | Session | Labels |
|---|---|---|
| Empty thread, course/gen view | Phase 2 | `Giải thích trong 30 giây` · `Mình nên tập trung vào đâu?` · `Cho chương sau khó hơn` · `Mình đang học đến đâu rồi?` |
| After ≥1 message | Phase 2 | `Giải thích trong 30 giây` · `Cho mình xem cách suy ra` · `Mình sẽ dùng điều này ở đâu?` · `Điều này dẫn tới đâu?` |
| Earlier session | 2026-10-31 earlier | `Rút ngắn lại` · `Đi sâu hơn vào phần toán` · `Bỏ qua phần mình đã biết` · `Thêm phần thực hành` |

Course-level copy: `Nhờ Pol điều chỉnh khóa học này` / `Hãy nói với Pol, các chương tiếp theo sẽ
được soạn lại cho hợp với bạn.` ID `PS-R-QUICKACT-01`.
Quick actions are **stateful** (AD-2): one click produced exactly one new turn and `toolCalls`
rose 3 → 4.

## 6. Citation honesty ladder — observed behaviour

| Aspect | Observation | Tier |
|---|---|---|
| Structured cites exist | `cite={anchor,label}` on 3 of 7 blocks | E2 |
| Content match | `CITATION_CONTENT_MATCH true` — label names page 1 and page-1 heading verbatim | E2 |
| Page match | `CITATION_PAGE_MATCH true` | E2 |
| Locator validated | `PARTIAL` — anchor never string-matched against source text | E2 |
| Navigable | `false` — inert `StaticText`, `states: []`, 0/33 buttons | E2 |
| Anchor machine-checked | `false` | E2 |

**Known emitted-text defect (U+4E00):** one tutor inline citation prefix rendered
`Nguyên văn trang 3 一 Ngoại lệ MƯA TÍM và ORBIT-249` — a CJK ideograph used where a dash belongs.
Substituting `-` makes the string match the page-3 heading literally. Cause not inferred; recorded
as an observation, not a diagnosis. 3 accessibility nodes carried it. ID `PS-R-CITE-02`.

## 7. Baseline imported (Phase 1/2) — explicitly not fresh evidence

`observations-redacted.json` imports five baseline records kept **separate** from fresh
observations to avoid implying they were re-verified:

| ID | Assertion | Claim | Level |
|---|---|---|---|
| BASE-STATIC-1 | Client declares SSE events `delta, tool, confirm, done, error, restarted` | FACT | E0 |
| BASE-STATIC-2 | Client declares 6 tool names and `citationSchema{anchor, heading, gist}` | FACT | E0 |
| BASE-DYN-1 | 4 tutor POSTs returned 200 treated as SSE in one window | FACT | E1 |
| BASE-DYN-2 | `GET /tutor` returned 8 messages, `toolCalls[4]`, `contextLabel` on all | FACT | E2 |
| BASE-DYN-3 | Tutor POST carried `contextRef{lessonId, blockIndex}`, `entryPoint`, `clientMessageId`, `text` | FACT | E2 |
| BASE-DYN-4 | Topic-based lesson returned `source: null` | FACT | E2 |
| BASE-DYN-5 | Server-side RAG is INFERENCE; embeddings UNKNOWN | INFERENCE | E0/E1 |

## 8. API surface declared by the client (E0)

Enumerated from bundle call-sites — **declared, not proven live**:

- **Auth:** `POST /auth/exchange`, `/auth/refresh`, `/auth/signout`, `/auth/link/confirm`; OAuth callbacks.
- **Me:** `GET /me`, `/me/profile`, `/me/stats`, `/me/onboarding`, `/me/entitlement`, `/me/notifications`, `/me/identities`.
- **Billing (SePay):** `/billing/plans`, `/checkout`, `/portal`, `/sync`, `/billing/sepay/plans`, `/billing/sepay/orders`.
- **Courses:** `POST /courses`, `POST /courses/{id}/interview/answer`, `POST /courses/{id}/approve`, `GET /courses/{id}/generation`, `POST /courses/{id}/retry`, `GET /courses/{id}/plan`, `/path`, `/glossary`, `DELETE /courses/{id}`.
- **Sources:** `POST /sources/upload`, `POST /sources/{id}/ingest`, `GET /sources/{id}`, `DELETE /sources/{id}`; enum `arxiv|web|pdf`; states `awaiting_upload → pending → extracting → ready|failed`.
- **Tutor:** `POST /courses/{id}/tutor/messages`, `POST /courses/{id}/tutor/sessions`, `GET /tutor/sessions`, `POST /courses/{id}/tutor/messages/{messageId}/stop`, `POST /courses/{id}/tutor/actions/{actionId}/{result}`.
- **Lessons:** `GET /lessons/{id}`, `POST /lessons/{id}/retry`, `POST /lessons/{id}/attempts`, `POST /lessons/{id}/blocks/{index}/grade`, `POST /lessons/{id}/grades/{gradeId}/dispute`, `POST /lesson/{id}/complete`.

Runtime-confirmed from this list (E1+): `/courses` (POST 201), `/interview/answer` (200 ×5),
`/approve` (200), `/generation` (200 ×56), `/lessons/{id}` (200), `/lessons/{id}/attempts` (201),
`/path` (200), `/glossary` (200), `/home` (200), `/me/stats` (200), `/me/profile` (200),
`/me/entitlement` (200), `/me/notifications` (200), `/tutor` (200), `/tutor/messages` (200 SSE),
`/courses/{id}/tutor?entryPoint=…` (200).
Never exercised: the entire billing set, `/blocks/{index}/grade`, `/grades/{gradeId}/dispute`,
`/lesson/{id}/complete`, `/courses/{id}/plan`, `/courses/{id}/retry`, `/me/identities`,
`/auth/*`, `/tutor/messages/{id}/stop`, `/tutor/actions/{actionId}/{result}`, `/tutor/sessions`.

## 9. Reference gaps that force `UNKNOWN_REFERENCE` in the matrix

The following have **no observation at any tier** and therefore cannot be scored as MATCHED or
MISSING. They suppress Evidence Coverage and contribute 0 to the Conservative Floor:

| Area | Status |
|---|---|
| Billing / SePay checkout behaviour, plan gating, upgrade flow | declared only (E0) |
| `paywalled` unit enforcement (what happens on click) | field observed (E2); **enforcement** UNKNOWN |
| `hearts` depletion, refill, freeze-bank behaviour | shape observed (E2); **behaviour** UNKNOWN |
| `streak` break/restore rules | shape observed (E2); **rules** UNKNOWN |
| `goal` reset cadence and `levelsEarned`/`milestonesEarned` triggers | shapes observed (E2); **triggers** UNKNOWN |
| `flagged` semantics (anti-cheat? moderation?) | field observed (E2); **meaning** UNKNOWN |
| `levelUp` / XP curve | no observation at any tier |
| `timeMs` server trust (client-reported per-block timing) | field observed in request (E2); **policy** UNKNOWN |
| `Last-Event-ID` resume | declared (E0); never exercised |
| `confirm` action gate | never surfaced |
| `regenerate_unit`, `flag_question`, `revise_proposal` tools | enum (E0); never attributed at runtime |
| i18n switching (~12 languages) | bundle strings only; never switched |
| Offline / expo-sqlite behaviour | bundle only; never exercised |
| MathJax rendering of formula figures | bundle only; `figure.kind` enum, no rendered formula captured |

## 10. What this chapter does **not** claim

- It does not claim the reference's backend is RAG-backed. That remains `INFERENCE`.
- It does not claim the reference grades attempts server-side. The client sends `correct`; the
  server policy is `UNKNOWN`.
- It does not claim any SSE event other than `delta`/`done`, and even those are `OWNER_REPORTED`.
- It does not claim the reference's tutor consumed the lesson context. `contextRef` being **sent**
  is a fact; **consumption** is `UNKNOWN`.
- It does not treat the 93 origin-filtered requests as content evidence.
