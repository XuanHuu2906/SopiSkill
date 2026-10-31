# Unknowns and Next Tests

**Session:** `ps-bbx-2026-10-31` — updated after execution
**Purpose:** turn each remaining UNKNOWN into a specific, owner-gated, evidence-producing action.

---

## 1. Closed this session

| # | Unknown | Result | Evidence |
|---|---|---|---|
| U1 | Does a source-backed course ground answers in the source PDF? | **CLOSED — YES** | R1–R5: 6/6 oracle correct |
| U2 | Are near-miss values disambiguated? | **CLOSED — YES** | R3: 17 then 71, no contamination |
| U3 | Is there a refusal path for absent answers? | **CLOSED — YES** | R5: clean refusal, no invented person/year |
| U4 | Does the tutor receive structured lesson context? | **CLOSED — YES** | `contextRef{lessonId,blockIndex}` in 6 POSTs; `contextLabel` 12/12 |
| U5 | Do tool calls actually execute? | **CLOSED — YES** | `toolCalls` 3 → 4 after one click |
| U6 | Does the source pipeline report intermediate states for a real PDF? | **PARTIAL** | 201 → 202 → polled 200 ×10 until brief; individual state strings not read |

## 2. Still open

| # | Unknown | Why it matters to *our* product | Cheapest test that closes it | Consent needed |
|---|---|---|---|---|
| U7 | **Which tool** ran on each turn? | Decides our tool allowlist and audit schema (P3) | Capture with `--include-console-text`; or open DevTools EventStream during a turn and record `event: tool` payload **names only** | Tutor message |
| U8 | Are citations navigable, and is `anchor` literally correct? | Decides whether our citation contract must carry page/chunk provenance | Click the citation label in a lesson where it renders as a chip; or string-match `anchor` against fixture text via a second capture | None beyond opening a lesson |
| U9 | Does harder/easier change content or only wording? | Decides regeneration pipeline vs prompt hint (P3/P5) | **Open a fresh lesson** (empty thread) so the 4 difficulty actions are visible, click one, compare `contentVersion` before/after | Rewrites one lesson |
| U10 | Do interview answers materially change the course? | Decides how much to invest in the interview step (P1/P2) | Create NOVICE + ADVANCED courses on the same topic; blind rubric grading | 2 courses of quota |
| U11 | Is there progress-driven adaptation? | Decides whether adaptive learning belongs in our roadmap | Wrong answer ×1, then watch `upNextLessonId`, `progress`, difficulty | Mutates learning record |
| U12 | Does a `confirm` gate exist? | Security-relevant for any consequential agent tool | Wait for a naturally occurring confirm on a consequential action; never manufacture one | Per-action approval |
| U13 | Which SSE event names are actually emitted? | Tells us which event contract is real | Owner opens DevTools → Network → EventStream during one tutor turn; record names and counts only | None beyond a tutor message |

## 2b. Phase 3 session deltas (`ps-bbx-2026-10-31-p3`)

Appended 2026-10-31. Nothing below closes an unknown without executed evidence; the table above is unchanged.

| # | Unknown | Phase 3 result | Evidence | What is still missing |
|---|---|---|---|---|
| U7 | Which tool ran on each turn? | **STILL OPEN** | `toolCalls` stayed at 4 across one tutor turn; `{name,summary,ok}` shape only, values never exposed | A turn that actually invokes a tool, plus a payload whose key values are readable |
| U8 | Are citations navigable, and is `anchor` literally correct? | **SPLIT** | Navigability: **tested negative** in this view (1 citation, inert `StaticText`, 0 citation buttons). Content/page: **PASS** for that citation (label = page-1 heading). Locator: **NOT TESTED** — no lesson payload captured | The raw `cite.anchor` string, readable locally |
| U9 | Does harder/easier change content? | **STILL OPEN — BLOCKED** | No lesson had an empty thread; owner declined a rewrite/new course | An empty-thread lesson + 1 difficulty click + `contentVersion` before/after |
| U13 | Which SSE event names are actually emitted? | **PARTIALLY CLOSED** | Owner read DevTools EventStream: `delta` (`{text:string}`), `done` (keys incl. `threadId`, `message`); `tool`/`confirm`/`error`/`restarted` not seen | Machine-level confirmation; REA 6.7.0 cannot parse `text/event-stream` at all |
| — | NEW: why can a grounded answer run with zero tool calls? | **NEW UNKNOWN** | Correct page-3 answer, 0 new tool calls, 0 new source badge, `toolCalls` flat at 4 | A design where grounding evidence is observable independently of tool calls |

### Phase 3 method lessons (append to §3 above)

6. **`toolCalls` count is not a grounding signal.** A correct, cited answer arrived with no new tool call and no new badge. The earlier 1:1 badge↔tool-call correlation holds only for turns that do invoke a tool.
7. **A quick-action label set is not stable across sessions.** The four actions differ between the 2026-10-31 session and this one. Never assert a specific label as a product contract.
8. **REA 6.7.0 cannot see SSE.** `body_shapes.response` is absent for `text/event-stream`, and no `text/event-stream` handling exists in the installed package. Any event-name evidence must come from DevTools by the owner, and must be labelled `OWNER_REPORTED`.
9. **The three `REA_BROWSER_*` environment variables in the Phase 3 plan do not exist** in rea-agents 6.7.0. Scope origins with repeated `--allowed-origins` CLI flags only.
10. **Background launches are killed in this environment.** Backgrounding `rea` (including via PowerShell `Start-Process`) is terminated by the harness; use a foreground timed command and have the owner act inside the window.
11. **Raw `anchor` is the single cheapest remaining U8 win.** A locally-readable `cite` object needs no quota and no CDP.

### Phase 3 architecture implications (append to §6 above)

9. **Never let a label stand in for a locator.** `Trang 1 — …` matched the page heading yet was inert and unverifiable at span level. Store `page`, `chunk_id`, `quote_sha256` and validate by program.
10. **Emit citation separators through one normalizer.** A CJK U+4E00 substituted for a dash silently broke literal quote matching; validate emitted punctuation and keep a fidelity regression test.
11. **Keep difficulty affordances reachable after the first message.** Hiding them makes the feature both unusable and untestable, which is exactly how U9 stayed blocked.

## 3. Important method lessons from this session

1. **The 4 difficulty quick actions are stateful.** They render only on an **empty** tutor
   thread. Once a message exists they are replaced by follow-up suggestions. To test D2 you
   must open a lesson that has no prior messages.
2. **`target_changed` kills a window silently.** The D2 window returned
   `{"code":"target_unavailable","reason":"target_changed"}` with 0 requests. Always check the
   JSON envelope, not just the absence of output.
3. **One action per window still works.** 98 requests across create/interview/approve/generate
   were captured cleanly in a single window because the whole flow was one continuous action.
4. **Tool name values are never in the capture.** REA keeps `{name, summary, ok}` shapes but
   the string values do not surface in accessibility text either. Only DevTools EventStream or
   a console-text capture can reveal them.
5. **A UI badge is not a tool name.** "đã đọc tài liệu nguồn" correlates perfectly with tool
   calls (4 badges / 4 calls) but cannot be mapped to `read_source` by name.

## 4. Next session, ordered

1. **U7 + U13 first** (no data mutation): open a fresh lesson, arm a window **with
   `--include-console-text`**, ask one question, and have the owner watch DevTools →
   Network → `POST /tutor/messages` → EventStream. Record event names/counts and any tool
   name that appears. This is the cheapest way to attribute tools.
2. **U9** (one lesson rewrite): open a *fresh* lesson so quick actions are visible, click
   `Đi sâu hơn vào phần toán`, compare `contentVersion`.
3. **U8** (no mutation): in a lesson where `cite` renders, try clicking the label; if it is not
   clickable, record that as a definitive product observation.
4. **U10** (2 courses): NOVICE vs ADVANCED, blind rubric.
5. **U11** (mutates progress): only with explicit consent.
6. **U12**: opportunistic only.

## 5. What the next report may claim, and what it may never claim

**May claim:** grounded answers on a specific fixture; correct disambiguation of a near-miss
pair; a working refusal path; tool execution with a count; structured context passing; citation
structure present; stateful quick actions.

**May never claim, from black-box observation:**
- the LLM provider or model;
- embeddings, vector database, BM25, hybrid search, or reranking;
- system prompt contents;
- mastery modelling / knowledge tracing;
- that `read_source` specifically executed, while its name remains unobserved;
- that the 4 difficulty actions change content, since D2 never completed.

## 6. Architecture implications for SopiSkill (PROPOSAL)

Derived from this session's evidence discipline, not copied from PolySkill:

1. **Every citation must be machine-checkable.** Store `source_id, page, chunk_id, quote_sha256`
   so CI can assert the cited text exists in the cited chunk. PolySkill's `{anchor,label}` was
   not navigable in the view we saw — aim higher.
2. **Make refusals first-class and test them in CI.** PolySkill passed our negative probe; our
   own R5-equivalent must be in the regression suite, not assumed.
3. **Persist tool audit server-side:** `tool_name, arguments_digest, ok, latency_ms`. Black-box
   observation could not attribute a tool name — our own product should make that trivial.
4. **Resolve lesson context server-side** from `(lesson_id, block_index)` with an ownership
   check. PolySkill sends exactly this shape; we should also *enforce* it.
5. **Keep the three adaptation levels separate** in code and telemetry: input personalisation,
   user-requested adjustment, progress-driven adaptation.
6. **Stateless quick actions are a UX trap.** PolySkill hides them after the first message.
   If we expose difficulty controls, keep them reachable, or users cannot revisit them.
7. **Reuse the LUMORA oracle pattern** (unique facts + near-miss pair + negative probe + a
   paraphrase) as a CI regression template for our RAG.
8. **Handle 401 refresh transparently**, as PolySkill does mid-session, but make the retry
   budget explicit and bounded.
