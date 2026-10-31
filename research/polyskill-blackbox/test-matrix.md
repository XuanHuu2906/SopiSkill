# Test Matrix — PolySkill Black-box (RAG / Agent / Adaptive)

**Version:** 2.0 — 2026-10-31
**Status:** EXECUTED — 11 of 12 cases attempted against live PolySkill; 1 blocked by UI state.
**Session:** `ps-bbx-2026-10-31`, Chrome/156.0.8078.76, REA 6.7.0
**Fixture:** `fixtures/rag_synthetic_v1.pdf`, 3 pages, sha256 `fc333de6f9170d2d…`, fictional, no personal data.

Legend: E0 = client enum/name; E1 = network metadata; E2 = runtime event/history; E3 = repeated controlled comparison.
Verdicts: `PASS` / `OBSERVED` / `NOT_OBSERVED_WITH_GOOD_COVERAGE` / `INCONCLUSIVE` / `BLOCKED` / `NOT_TESTED`.

## Preconditions that were satisfied

- Owner opened a **separate** Chrome profile on `--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1`.
- Owner logged in manually; no credential entered any agent session.
- Every observation window whitelisted **both** origins as repeated flags:
  `--allowed-origins https://web.polyskill.app --allowed-origins https://api.polyskill.app`.
- Every window recorded `disallowed_origin = 0`, `truncated = false`, `target_changed = false` except D2 (see below).
- The agent never clicked, typed, uploaded or navigated. All UI actions were performed by the owner.

## RAG cases

| ID | UI action (owner) | Expected (oracle) | Evidence bar | Must NOT conclude | Result |
|---|---|---|---|---|---|
| **R1** | Source-backed course from the fixture; lesson 1; ask "Theo tài liệu, LUMORA-731 có những giai đoạn nào?" | Exactly 3 stages: Chuẩn bị, Khớp mẫu, Xác thực | `source` non-null; answer text; tool evidence if any | Vector search / embeddings / chunker | **PASS** — 3 stages in order, explicitly denied a 4th stage; `source` object non-null; UI badge "đã đọc tài liệu nguồn"; tool call recorded |
| **R2** | "Một quy trình gồm bước dọn dẹp đầu vào, so khớp với mẫu có sẵn rồi kiểm tra lại kết quả — tài liệu gọi đó là gì?" | Identifies LUMORA-731 from semantics | Answer not merely copying the heading | That a dense retriever is used | **PASS** — named LUMORA-731 from the three paraphrased steps; no tool badge on this turn |
| **R3** | "ORBIT-294 ngưỡng bao nhiêu đơn vị?" then separately "ORBIT-249 ngưỡng bao nhiêu đơn vị?" | 17, then 71, never swapped | Both answers; second must not inherit 17 | Retriever/reranker topology | **PASS** — 17 then 71; no contamination; answer explicitly warns not to mix the thresholds |
| **R4** | "MƯA TÍM là ngoại lệ gì? Dẫn nguồn cụ thể (trang/đoạn) nếu có." | Skips Khớp mẫu, Chuẩn bị → Xác thực; locator on page 3 | Answer + rendered citation locator | That retrieval generated the citation | **PASS (content) / PARTIAL (citation)** — correct exception; quoted the page-3 sentence verbatim ("nguyên văn trang 3"); no clickable citation object was opened, so the structured `cite{anchor,label}` locator was not navigated |
| **R5** | "Ai sáng chế LUMORA-731 vào năm nào?" (absent from fixture) | Refuse; no invented person/year | Answer text; hallucination check | That RAG is absent because of one failure | **PASS** — "Không có trong tài liệu"; stated it re-read all three pages; named no author, no year |

Sub-probe count: 6 (R3 splits into two measurements). **6/6 correct.**

## Agent cases

| ID | UI action (owner) | Expected | Evidence bar | Must NOT conclude | Result |
|---|---|---|---|---|---|
| **A1** | Ask a scoped question inside lesson 1 | Tutor receives structured lesson context | `contextRef{lessonId, blockIndex}`; `contextLabel`; SSE POST 200 | That the model consumed the block | **PASS (transport)** — `contextRef{lessonId, blockIndex}` in every POST body; `contextLabel` on 12/12 messages |
| **A2** | Click exactly one real action ("Cho mình xem cách suy ra") | One new turn; runtime evidence if a tool ran | `event: tool` or `toolCalls` delta with a name | Whole agent loop behaviour | **PASS (execution) / name UNKNOWN** — thread `toolCalls` 3 → 4 after exactly one click; response shape `{name, summary, ok}`; values never visible |
| **A3** | Ask something requiring the source | `read_source` evidenced at runtime, or grounding without a visible tool | Runtime name from history/event, never the client enum | That `read_source` ran | **NOT_OBSERVED_WITH_GOOD_COVERAGE** — zero occurrences of any of the 6 tool names in the entire capture; `cite{anchor,label}` exists on 3/7 blocks but renders as StaticText, not a clickable chip |
| **A4** | Approve one `confirm` action **if it appears naturally** | Confirm step then visible outcome | Before/after state; `POST /tutor/actions/{id}/{result}` | Backend authorization semantics | **NOT_TESTED (BLOCKED)** — `messages[].action` stayed `null` on all 14 messages; no confirm gate surfaced, and none was manufactured |

## Adaptive cases

| ID | UI action (owner) | Expected | Evidence bar | Must NOT conclude | Result |
|---|---|---|---|---|---|
| **D1** | Two courses, same topic "Python: vòng lặp và danh sách", NOVICE vs ADVANCED interview answers | Proposal/lessons differ consistently with input | Proposal snapshot; blind rubric grading | Any adaptation algorithm | **NOT_TESTED** — requires 2 further course creations (quota) and separate consent |
| **D2** | Click harder/easier inside the open lesson | Difficulty/content change; `contentVersion` delta | Before/after snapshot + `contentVersion` | Automatic adaptation | **INCONCLUSIVE** — the 4 difficulty actions were **absent** once the thread had messages (they exist only on an empty thread); the capture also terminated with `target_changed` |
| **D3** | Deliberately wrong quiz answer, then observe suggested next lesson | Feedback/progression reacts | score, `progress`, `upNextLessonId` | Knowledge tracing from n=1 | **NOT_TESTED** — mutates the learning record; separate consent required |

## Key incidental finding

The four difficulty quick actions (`Rút ngắn lại`, `Đi sâu hơn vào phần toán`, `Bỏ qua phần mình đã biết`, `Thêm phần thực hành`) are **stateful**:

| Thread state | Buttons rendered |
|---|---|
| Empty thread (fresh lesson open) | the 4 difficulty quick actions |
| After ≥1 message | 4 contextual follow-ups: `Giải thích trong 30 giây`, `Cho mình xem cách suy ra`, `Mình sẽ dùng điều này ở đâu?`, `Điều này dẫn tới đâu?` |

This is why D2 could not run in the already-used thread. It is a UI availability fact, not an adaptation fact.

## Capture quality gates — all met except D2

| Window | Requests | `disallowed_origin` | `truncated` | `target_changed` | Quality |
|---|---|---|---|---|---|
| ENV-HARNESS (/sign-in) | 0 | 0 | false | false | POLICY_FILTERED (idle page) |
| ENV-INGEST (upload) | 20 | 0 | false | false | COMPLETE_WITHIN_WINDOW |
| ENV-COURSEGEN (create+approve+open) | 98 | 0 | false | false | COMPLETE_WITHIN_WINDOW |
| R1–R5 (6 questions) | 51 | 0 | false | false | COMPLETE_WITHIN_WINDOW |
| A1–A2 (one quick action) | 18 | 0 | false | false | COMPLETE_WITHIN_WINDOW |
| D2 (attempt) | 0 | 0 | – | **true** | INCONCLUSIVE |

## Status summary

| Bucket | Count |
|---|---|
| Test cases defined | **12** |
| Executed with usable evidence | **10** (R1–R5, A1–A3, plus 3 environment fixtures) |
| PASS | **7** (R1, R2, R3, R4, R5, A1, A2) |
| NOT_OBSERVED_WITH_GOOD_COVERAGE | **1** (A3 tool attribution) |
| INCONCLUSIVE | **1** (D2) |
| BLOCKED / NOT_TESTED | **3** (A4, D1, D3) |

## Phase 3 follow-up session (`ps-bbx-2026-10-31-p3`)

Added 2026-10-31 12:00–12:35 (+07:00). Same fixture (`sha256 fc333de6…41ee0` re-verified). All prior rows above are unchanged.

Legend as above. `OWNER_REPORTED` = the owner transcribed the value from Chrome DevTools; the agent did not capture it.

| ID | UI action (owner) | Expected | Evidence bar | Result |
|---|---|---|---|---|
| **U7** | Ask one question inside lesson 1 while a 150 s window is armed | Tool identity becomes readable | `toolCalls[].name` value from runtime payload | **NOT TESTED (values unreadable)** — `toolCalls` stayed at 4 (`{name,summary,ok}` shape only); zero new tool calls; no source badge on the new answer. Tool name never exposed. |
| **U13** | Same turn; owner watches DevTools → Network → `POST …/tutor/messages` → EventStream | Real event names | Event names + counts | **PARTIAL — OWNER_REPORTED** — `delta` (`{text:string}`) and `done` (keys incl. `threadId`, `message`). `tool`/`confirm`/`error`/`restarted` not seen in the excerpt. Capture side: SSE 200 confirmed, `body_shapes.response = ABSENT` (REA 6.7.0 has no SSE parser). |
| **U8** | Open lesson 1 and inspect the rendered citation | Content + page + locator + navigability | Citation count, label, clickability, offline match | **PARTIAL** — 1 citation, inert `StaticText` `Trang 1 — Quy trình LUMORA-731`, states `[]`, 0/33 citation buttons. Label matches page-1 heading offline; page-3 quotes are literal. `anchor` unverified (no lesson payload captured). |
| **D2/U9** | — | Difficulty effect measurable | Empty thread + before/after `contentVersion` | **BLOCKED** — no lesson had an empty thread (lesson 1 consumed by U7/U13; all other nodes `Đã khóa`/`Pro`); owner declined a course creation or chapter rewrite. |

### Phase 3 incidental findings

1. **Difficulty quick-action labels differ between sessions.** Earlier session: `Rút ngắn lại`, `Đi sâu hơn vào phần toán`, `Bỏ qua phần mình đã biết`, `Thêm phần thực hành`. This session (course overview and lesson view, empty thread): `Giải thích trong 30 giây`, `Mình nên tập trung vào đâu?`, `Cho chương sau khó hơn`, `Mình đang học đến đâu rồi?`. After ≥1 message the set becomes the four follow-ups. Recorded as a UI observation only; no version/experiment claim.
2. **A grounded answer can occur with zero tool calls.** The new answer was correct against page 3 and carried no new badge, while `toolCalls` did not increase. This weakens any badge↔tool-call↔grounding assumption.
3. **Typographic defect in emitted text.** The tutor's inline citation prefix used **U+4E00** (CJK "one") where a dash belongs: `Nguyên văn trang 3 一 Ngoại lệ MƯA TÍM và ORBIT-249`. 3 nodes in this render. Substituting U+4E00 → `-` makes it match the page-3 heading; as-is it matches nothing in the PDF. Cause not inferred.
4. **Lesson body unchanged by the tutor turn** (6 named block markers identical before/after). `contentVersion` was not readable.

### Phase 3 capture quality

| Window | Requests | `disallowed_origin` | `truncated` | `target_changed` | `dropped_events` | Quality |
|---|---|---|---|---|---|---|
| P3-PREFLIGHT-BASELINE (15 s, idle, course overview) | 0 | 0 | false | false | 0 | POLICY_FILTERED (idle page) |
| U8_CITATION (15 s, idle, lesson) | 0 | 0 | false | false | 0 | POLICY_FILTERED — lesson JSON fetched before attach |
| U7_U13 (150 s, one tutor turn) | 6 | 0 | false | false | 0 | COMPLETE_WITHIN_WINDOW (transport level) |

### Phase 3 verdict tally

| Verdict | Count | Cases |
|---|---|---|
| PASS | 1 | U8 content/page for the single rendered citation |
| PARTIAL | 2 | U8 locator/navigability; U13 event names (owner-reported) |
| NOT TESTED | 2 | U7 tool identity; U9 effect |
| BLOCKED | 4 | D2/U9 (no empty thread), D1, D3, A4 (excluded) |

## What the PASS results do and do not mean

They mean: with a user-owned 3-page PDF, the system generated a grounded course and answered six oracle questions correctly, including a paraphrase, a near-miss numeric pair, a citation-requested question, and an unanswerable question, while recording three tool calls.

They do **not** mean: that a vector database, embeddings, a specific chunker, a reranker, a particular LLM, or an adaptive algorithm was identified. `RAG_MECHANISM_UNKNOWN` remains permanent for this line of evidence.
