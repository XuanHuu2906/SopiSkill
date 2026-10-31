# Phase 3 — PolySkill black-box follow-up (U7/U13, U8, D2/U9)

**Session:** `ps-bbx-2026-10-31-p3`
**Date:** 2026-10-31, 12:00–12:35 (+07:00)
**Fixture:** `research/polyskill-blackbox/fixtures/rag_synthetic_v1.pdf`, sha256 `fc333de6…41ee0`, 3 pages, fictional
**Method:** the owner drove every UI action and every quota-spending action; the agent ran passive `rea inspect-web-page` windows only. No clicks, no typing, no uploads, no API replay, no source-code changes.
**Verdict summary:** U7/U13 = **PARTIAL** (transport + tool-record delta confirmed; event names owner-reported only; no tool name). U8 = **PARTIAL** (1 citation, page label correct, content correct, not navigable, anchor unverified). D2/U9 = **BLOCKED**.

---

## 1. EXECUTION

### 1.1 Repository state before any change

```
branch : main
HEAD   : 5e5f9cd496a22e6c1b10b535efd1fdeece43c6c9
status : clean except untracked PHASE3_OPENCODE_POLYSKILL.md and research/
```

No application source file was read for modification, and none was modified.

### 1.2 Tooling actually used

| Item | Value | How verified |
|---|---|---|
| Working dir | `D:\Reverse Engineer` | `git status --short`, `git rev-parse HEAD` |
| REA | `6.7.0` at `C:\nvm4w\nodejs\rea.cmd` | `rea --version` |
| Node / npm | `24.11.1` / `11.6.4` | `node --version`, `npm --version` |
| Chrome | `156.0.8078.76`, protocol `1.3` | `GET /json/version` and REA `list-browser-targets` |
| CDP | `http://127.0.0.1:9222` reachable at preflight | `curl -o /dev/null -w %{http_code}` → `200` |
| PDF extractor | `pypdf 6.13.0`, pre-installed | import check; **nothing was installed** |

### 1.3 Two plan preconditions that do not exist in REA 6.7.0

| Plan requirement | Finding |
|---|---|
| `REA_BROWSER_OBSERVE_ENABLED` | **not present** in rea-agents 6.7.0 (0 grep hits over the installed package) |
| `REA_BROWSER_CDP_ENDPOINTS_JSON` | **not present** |
| `REA_BROWSER_ALLOWED_ORIGINS_JSON` | **not present** |
| REA can expose SSE event names | **false** — no `text/event-stream` handling exists in `dist/` |

Consequence: all origin scoping was done with repeated CLI flags, and U13 event names had to be owner-reported from DevTools rather than captured. This is recorded as `PLAN_PRECONDITION_ADJUSTED`, not as a product finding.

### 1.4 Windows-specific technical limitation encountered

Background (detached) process launch from this shell is killed by the harness (`ChildProcess.kill`), and PowerShell `Start-Process` produced the same result. Every observation window was therefore run as a **foreground timed command**, which caps a window at the tool timeout and requires the owner to act inside that window. Two timed windows of 15 s were used for idle snapshots and one window of 150 s for the single tutor turn.

---

## 2. PHASE 1 — U7 (tool identity) and U13 (SSE event names)

**PRECONDITION.** Owner opened lesson 1 of the fixture-backed course, enabled DevTools → Network → *Preserve log*, filtered `tutor/messages`, and confirmed readiness. A 150 s passive window was armed before the message was sent. Consent for one quota-spending tutor message was granted explicitly before arming.

**OBSERVATION_WINDOW.** `2026-10-31T05:14:02.981Z → 05:16:33.031Z` (150 000 ms), target `…/lesson/{lessonId}` on `web.polyskill.app`, both origins allowlisted.

**Capture quality.** `disallowed_origin = 0`, `truncated_sections = []`, `unavailable_sections = []`, `dropped_events.total = 0`, `target_changed = false`. `attach_limited = true` because REA only observes from attach onward.

**EVIDENCE.**

| # | Method | Path | Status | MIME |
|---|---|---|---|---|
| 0 | POST | `/v1/courses/{courseId}/tutor/messages` | 200 | **text/event-stream** |
| 1 | GET | `/v1/courses/{courseId}/path` | 200 | json |
| 2 | GET | `/v1/courses/{courseId}/tutor?entryPoint=teach_block&lessonId={lessonId}&blockIndex=0&threadId={threadId}` | 200 | json |
| 3 | GET | `/v1/home` | 200 | json |
| 4 | GET | `/v1/me/stats` | 200 | json |
| 5 | GET | `/assets/…/logo.*.png` | 200 | image/png |

Request body shape (value-free): `clientMessageId:string, contextRef{lessonId:string, blockIndex:number}, entryPoint:string, text:string, threadId:string`.

Thread body shape (value-free, post-turn): `messages` array with **16** observations; every message has `contextLabel:string` (16/16); `action` is `null` (16/16); `toolCalls` array exists on all 16 but only **4** carry an element; each element is `{name:string, summary:string, ok:boolean}` and **no value is exposed**. `allowance{limit, remaining}` present.

**U7 — tool identity.**

| Metric | Value |
|---|---|
| `tool_calls_before` | 4 |
| `tool_calls_after` | 4 |
| delta | **0** |
| `new_tool_ok` | **unknown** (no value readable) |
| tool badge `đã đọc tài liệu nguồn` count | 4 before, 4 after, **not attached** to the new answer |

The answer produced in this turn is nonetheless correct and grounded: it says the effect falls on stage 2 (`Khớp mẫu`), that `Chuẩn bị` and `Xác thực` still run, that the document only states the path effect, and that `MƯA TÍM` does not waive the ORBIT-294 ≥ 17 start condition. All of those clauses are literally present on pages 2 and 3 of the fixture.

**U13 — SSE event names.**

| Item | Value |
|---|---|
| HTTP status of SSE POST | 200 |
| SSE response body shape from REA | `ABSENT` (no parser exists) |
| Event names from capture | **none available** |
| Event names owner-reported from EventStream | `delta`, `done` |
| `delta` payload shape owner saw | `{text: string}` |
| `done` payload keys owner saw | `threadId`, `message`, … |
| `tool` / `confirm` / `error` / `restarted` | **not seen** in the excerpt the owner pasted |

**VERDICT.**
- `SSE_HTTP_200` = **true**.
- `EVENTS_OBSERVED` = **OWNER_REPORTED ONLY** (`delta`, `done`).
- `EVENT_NAMES_UNKNOWN_BY_CAPTURE` = **true** — retained, because capture could not produce names.
- `TOOL_RECORD_OBSERVED` (this turn) = **false**.
- `TOOL_NAME_CONFIRMED` = **false**.
- `read_source` attribution = **UNKNOWN**, unchanged.

**LIMITATION.** Event names rest on owner transcription, not on machine evidence. Because this turn executed zero tool calls, it says nothing about whether a `tool` event exists or what its payload contains. The absence of `tool`/`confirm`/`error` in the pasted excerpt is not evidence of absence.

---

## 3. PHASE 2 — U8 citation evaluation (no data change)

**PRECONDITION.** Owner opened lesson 1 (`/lesson/{lessonId}`) of the fixture-backed course. Fixture hash was re-verified against `oracle.local.json` before grading: match. No fixture or answer key was altered during evaluation.

**OBSERVATION_WINDOW.** `2026-10-31T05:07:25.263Z → 05:07:40.321Z` (15 000 ms), `--include-accessibility-text --include-json-body-shapes`.

**Capture quality.** `disallowed_origin = 0`, `truncated = false`, `target_changed = false`, `network_requests = 0`. **The lesson JSON was fetched when the owner navigated, i.e. before attach**, so no lesson payload was captured (`attach_limited`). This window therefore supports UI-shape claims only.

**EVIDENCE.**

| Item | Observation |
|---|---|
| Citation elements rendered in this view | **1** |
| Node role | `StaticText` |
| Node name | `Trang 1 — Quy trình LUMORA-731` |
| Parent role | `generic` |
| Interaction states on the node | `[]` — not focusable, not a button, not a link |
| Buttons whose name contains `Trang` or `nguồn` | 0 of 33 |
| Lesson progress marker | `Khái niệm 1/3` (only block 1 rendered) |
| `contentVersion` | **not observed** (payload unavailable) |

Offline grading against the PDF (pypdf 6.13.0; NFC; NBSP→space; U+2013/U+2014/U+4E00→`-`; whitespace collapsed; 1-indexed):

| Check | Result |
|---|---|
| Rendered label normalizes to page-1 heading | **match, page 1** |
| R4 verbatim quote `Trong điều kiện MƯA TÍM, … Xác thực` | **literal match, page 3** |
| R4 second quoted sentence `Điều kiện MƯA TÍM là ngoại lệ duy nhất…` | **literal match, page 3** |
| `lớn hơn hoặc bằng 17` (supports answer's ≥ claim) | **literal match, page 2** |
| Cross-page leakage | literal `17` absent from page 3, literal `71` absent from page 2 |
| Oracle `quote` fields for R1/R2/R5 | **not literal substrings** — they are synthesized descriptions; graded by clause, never by whole-string match |

**VERDICT.**

| Verdict key | Result | Basis |
|---|---|---|
| `CITATION_CONTENT_MATCH` | **true** | quoted sentences are literal page-3 text |
| `CITATION_PAGE_MATCH` | **true** | label says page 1, page-1 heading matches |
| `CITATION_LOCATOR_VALIDATED` | **PARTIAL** | page label matches; the raw `anchor` string was never readable, so span-level locator validity is unproven |
| `CITATION_NAVIGABLE_IN_THIS_VIEW` | **false** | node is inert `StaticText`; no citation chip, no navigation |
| `CITATION_ANCHOR_MACHINE_CHECKED` | **false** | no lesson payload captured |

**LIMITATION.** Only 1 of the 3 cited blocks was rendered; the other two were not visible. An inert label in one view is not proof that the product has no citation viewer anywhere. `anchor` correctness remains unverified for the same reason.

### 3.1 Incidental finding — a real character defect in emitted text

The tutor's own inline citation prefix rendered as `Nguyên văn trang 3 **一** Ngoại lệ MƯA TÍM và ORBIT-249`, where the separator is **U+4E00 (CJK ideograph "one")** instead of an em dash. In this render it appears **3** times (one text node plus its `StaticText`/`InlineTextBox` duplicates). Substituting U+4E00 → `-` makes the string match the page-3 heading literally; as-is it matches nothing in the PDF.

This is recorded as an observation of emitted content. No cause is inferred: it could be model output, a tokenizer/decoder artifact, or a rendering substitution.

---

## 4. PHASE 3 — D2/U9 difficulty quick action

**PRECONDITION ATTEMPTED.** The owner checked whether any lesson in this course had an empty tutor thread, which is the documented precondition for the four difficulty quick actions.

**RESULT.** None did. The only empty-thread lesson was lesson 1, and it received a message during Phase 1. Every remaining lesson node in the path was `Đã khóa` or `Pro`.

**EVIDENCE (availability only, no action taken).**

| View | Quick actions rendered |
|---|---|
| Course overview and lesson view before the turn (empty thread) | `Giải thích trong 30 giây`, `Mình nên tập trung vào đâu?`, `Cho chương sau khó hơn`, `Mình đang học đến đâu rồi?` |
| Same views after ≥1 message | `Giải thích trong 30 giây`, `Cho mình xem cách suy ra`, `Mình sẽ dùng điều này ở đâu?`, `Điều này dẫn tới đâu?` |
| Earlier session (2026-10-31 report) | `Rút ngắn lại`, `Đi sâu hơn vào phần toán`, `Bỏ qua phần mình đã biết`, `Thêm phần thực hành` |

The label sets are **not** the same between the earlier session and this one. That difference is recorded as an observation about the UI only; no product-version or experimentation claim is made.

Course-level copy also observed: `Nhờ Pol điều chỉnh khóa học này` and `Hãy nói với Pol, các chương tiếp theo sẽ được soạn lại cho hợp với bạn.`

**VERDICT.** `BLOCKED` — precondition (empty thread) unreachable and the owner declined spending quota on a new course or a chapter rewrite. This is **not** `INCONCLUSIVE`: no attempt was made, so there is no partial measurement to interpret.

**LESSON-MUTATION CONTROL (free, collected anyway).** Comparing the lesson-body markers before and after the tutor turn:

| Marker | Before | After |
|---|---|---|
| `Khái niệm 1/3` | present | present |
| `Ba trạm nối tiếp` | present | present |
| `Chặng sau chỉ chạy khi chặng trước đã chạy xong.` | present | present |
| `Thuật ngữ chính` | present | present |
| `Ba chặng, đúng thứ tự` | present | present |
| `Trang 1 — Quy trình LUMORA-731` | present | present |

The lesson body did not change; only the chat panel grew (StaticText 53 → 46 because the avatar picker closed, with 26 newly added chat items). `contentVersion` was never read, so this is a text-level observation only.

**LIMITATION.** Not calling D2 "progress-driven adaptive learning", and not calling it "adaptive learning" at all. Nothing here tests D1, D3 or A4, which were excluded by the owner.

---

## 5. CLAIM REGISTER

### 5.1 FACT (this session, executed evidence)

| ID | Claim | Evidence | Limit |
|---|---|---|---|
| P3-F1 | `POST /v1/courses/{id}/tutor/messages` returns `200` with `text/event-stream` | window U7_U13, request 0 | n=1 |
| P3-F2 | The tutor POST body carries `contextRef{lessonId:string, blockIndex:number}` plus `entryPoint`, `text`, `clientMessageId`, `threadId` | value-free body shape | shape only, no values |
| P3-F3 | The thread response carries `messages[].toolCalls[]{name,summary,ok}` and `messages[].contextLabel` | value-free body shape, 16 messages, 4 tool-call elements | values never exposed |
| P3-F4 | One tutor turn left `toolCalls` at 4 and `action` at null for all 16 messages | count comparison | single turn |
| P3-F5 | A correct, page-3-grounded answer was produced with **zero** new tool calls and **zero** new source badge | answer text + counts | n=1; reuse of already-loaded context not excluded |
| P3-F6 | Tutor free-question counter moved 18 → 17 for exactly one turn | UI text before/after | — |
| P3-F7 | In the inspected lesson view exactly one citation renders, as inert `StaticText` labelled `Trang 1 — Quy trình LUMORA-731` | accessibility nodes, states `[]` | one view, one block of three |
| P3-F8 | That label matches the fixture's page-1 heading after Unicode/dash normalization | pypdf offline check | label→page only, not anchor→span |
| P3-F9 | Quoted page-3 sentences in the R4 answer are literal fixture text | pypdf substring check | quote-level, not locator-level |
| P3-F10 | Emitted tutor text contained U+4E00 (CJK "one") used as a dash, 3 nodes in this render | codepoint inspection | cause unknown |
| P3-F11 | Difficulty-type quick actions are only present while the thread is empty, and the current label set differs from the earlier session's set | 3 snapshots compared | UI labels only |
| P3-F12 | Lesson body markers were unchanged across the tutor turn | marker set comparison | `contentVersion` unread |
| P3-F13 | The SSE response body is not retained by REA 6.7.0 in any form | `body_shapes.response` absent; no `text/event-stream` in package | tool limitation, not product |

### 5.2 INFERENCE

| ID | Claim | Basis | Why it stays inference |
|---|---|---|---|
| P3-I1 | The two owner-reported events (`delta`, `done`) are what a working turn normally emits | owner read them from the live EventStream during the captured turn | not machine-captured |
| P3-I2 | A `tool` event probably exists but did not fire because no tool ran | client enum declares it; no tool call occurred this turn | unobserved |
| P3-I3 | Answers can be grounded without a fresh source-read call, plausibly because lesson/source context is already in the model's context | correct page-3 answer with 0 new tool calls | alternative explanations not excluded |
| P3-I4 | The 4 pre-existing tool calls came from earlier turns (R1/R4/R5/A2 pattern) | counts and badges match the earlier session | carried, not re-measured |

### 5.3 UNKNOWN (unchanged or newly retained)

| ID | Unknown | Status after this session |
|---|---|---|
| U7 | Which tool ran on any specific turn | **OPEN** — values still unreadable |
| U8 | Whether `anchor` is literally correct / machine-verifiable | **OPEN** — no lesson payload captured |
| U9 | Whether harder/easier changes content, and whether `contentVersion` moves | **OPEN** — BLOCKED on empty thread |
| U10 | Whether interview answers materially change the course | **OPEN** — out of scope |
| U11 | Whether progress-driven adaptation exists | **OPEN** — out of scope |
| U12 | Whether a `confirm` gate exists | **OPEN** — out of scope |
| U13 | Which SSE event names are actually emitted | **PARTIALLY CLOSED** — `delta`/`done` owner-reported; capture still cannot confirm |
| — | Retrieval mechanism, embeddings, chunker, reranker | **UNKNOWN**, retained permanently |
| — | LLM provider / model | **UNKNOWN** |
| — | Why a grounded answer ran with no tool call | **NEW UNKNOWN** |

### 5.4 PROPOSAL (for the AI Learning Platform, not implemented)

1. **Make tool identity auditable server-side**: persist `tool_name, args_digest, ok, latency_ms` per call. Black-box observation of PolySkill could not read a single tool name across two sessions; that must be trivial in our own product.
2. **Separate "answer was grounded" from "a tool ran."** This session produced a correct, cited answer with zero tool calls, so a tool-call counter is not a grounding signal. Our telemetry should record retrieval evidence independently.
3. **Make citations machine-checkable**: store `source_id, page, chunk_id, quote_sha256` and assert in CI that the quoted text exists in the cited chunk. A label like `Trang 1 — …` is not a locator.
4. **Render citations as real controls** with an accessible role and a navigation target, then assert it in a UI test. An inert `StaticText` fails both accessibility and verifiability.
5. **Guard against typographic corruption in emitted text**: a CJK "one" standing in for a dash is the kind of defect that silently breaks quote matching. Normalize and validate citation separators before rendering, and keep a regression test for em-dash/quote fidelity.
6. **Keep difficulty controls reachable.** If quick actions exist only on an empty thread, users can never revisit them; that also makes the feature untestable.
7. **Treat "quick action label set" as an unstable contract.** The set differed between two sessions on the same course type; do not hard-code copy in our own product, and version any such affordance.

---

## 6. Status board

| Capability | IMPLEMENTED | TESTED | NOT TESTED | BLOCKED |
|---|---|---|---|---|
| Preflight: repo/branch/commit, tool versions, fixture hash | Yes | **Yes** (hash match, 3 pages) | – | – |
| Offline oracle self-check with pypdf | Yes | **Yes** (R1/R3/R4/S2/S3 literal checks pass) | – | – |
| REA harness against live site | Yes | **Yes** (3 windows, `disallowed_origin = 0`) | – | – |
| U7 tool identity | – | – | **NOT TESTED (values unreadable)** | Tool-name exposure is the blocker |
| U13 SSE event names | – | **PARTIAL — OWNER_REPORTED** (`delta`, `done`) | machine capture **NOT TESTED** | REA 6.7.0 has no SSE parser |
| U8 citation content/page | – | **PASS (1 citation)** | – | – |
| U8 citation locator/`anchor` | – | – | **NOT TESTED** | Lesson payload not captured |
| U8 citation navigability in this view | – | **TESTED — negative** | – | – |
| D2/U9 difficulty effect | – | – | **NOT TESTED** | **BLOCKED** — no empty thread; quota declined |
| D1, D3, A4 | – | – | **NOT TESTED** | Explicitly excluded this session |

**No item is reported as PASS on product behaviour beyond the specific U8 content/page check listed above. No `RAG_MECHANISM_UNKNOWN` claim was upgraded. D2 is not called adaptive learning.**

---

## 7. NEXT (max 3, with consent and quota notes)

1. **Close U8 locator (`anchor`) without quota.** Owner opens DevTools → Network → `GET /v1/lessons/{lessonId}` and reports only the `blocks[].cite.anchor` **shape and length** (not the value), or exports the `cite` object to a scratch file the agent may read locally. **Consent:** none beyond reading a local file. **Quota:** 0.
2. **Close U9 properly.** Requires a course or lesson whose tutor thread is empty, then one difficulty action plus a `contentVersion` read before/after. **Consent:** explicit approval for a lesson rewrite and 1 tutor turn. **Quota:** 1 turn, plus course cost if a new course is needed.
3. **Retry U7 with a turn that is forced to use a tool.** A question that must consult the source rather than reuse loaded context, with the owner reading the `tool` event payload's key names from DevTools. **Consent:** 1 tutor turn. **Quota:** 1. This is the only path to a tool name without instrumenting the client.

---

## 8. Files touched

| File | Change |
|---|---|
| `research/polyskill-blackbox/reports/phase3-sse-citation-difficulty.md` | new (this report) |
| `research/polyskill-blackbox/evidence/phase3-observations-redacted.json` | new, redacted metadata only |
| `research/polyskill-blackbox/test-matrix.md` | appended Phase 3 rows, history preserved |
| `research/polyskill-blackbox/reports/unknowns-and-next-tests.md` | appended Phase 3 deltas, nothing closed without evidence |

No raw capture, no PDF, no oracle file, and no real identifier was added to the repository. Application source code was not modified and nothing was committed.
