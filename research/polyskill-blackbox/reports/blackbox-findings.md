# Black-box Findings — PolySkill RAG / Agent / Adaptive

**Session:** `ps-bbx-2026-10-31`
**Environment:** Chrome/156.0.8078.76, REA 6.7.0, Windows, isolated CDP profile on `127.0.0.1:9222`
**Fixture:** `rag_synthetic_v1.pdf` — 3 fictional pages, sha256 `fc333de6f9170d2d…`, no personal data
**Method:** owner drove every UI action; agent performed passive CDP observation only (no clicks, no typing, no uploads, no API replay)

---

## 0. Executive summary

A source-backed course was built from a user-owned 3-page fictional PDF. **All six oracle
questions were answered correctly**, including a paraphrase probe, a near-miss numeric pair
(17 vs 71, no contamination), a citation-requested question, and a question whose answer is
absent from the source (clean refusal). Three tool calls were recorded in the tutor thread,
and the counter rose 3 → 4 when exactly one quick action was clicked.

**What is now FACT:** source grounding at both generation time and query time; structured
lesson context passing; tool execution at runtime; a clean refusal path on an unanswerable
question; citations exist as `{anchor, label}` on lesson blocks.

**What remains UNKNOWN:** the retrieval mechanism (dense/sparse/hybrid), embeddings, the
chunker, the reranker, the LLM provider, the identity of the executed tools, and any
progress-driven adaptation.

---

## 1. Fact / Inference / Unknown register

### 1.1 RAG and grounding — upgraded this session

| ID | Claim | Level | Evidence | Honest limit |
|---|---|---|---|---|
| RAG-1 | A user-owned PDF can be uploaded, ingested asynchronously, and polled to `ready` | **FACT** (E1) | `POST /sources/upload → 201`, `POST /sources/{id}/ingest → 202`, `GET /sources/{id} → 200` ×10 until brief populated | State *names* were not read; only that the object changed from null-brief to populated-brief |
| RAG-2 | Ingest produces a structured brief with 3 section anchors | **FACT** (E1) | `source.brief` = `{what, claims[10], notation[9], assumes[5], sections[3]}`; each section `{anchor, heading, gist}` | 3 sections matching 3 pages is *consistent with* page-level chunking but does not prove the chunker |
| RAG-3 | A source-backed course sets a non-null `source` on the lesson | **FACT** (E2) | lesson payload `source = {id, kind, title, byline:null, canonicalUrl:null}` | The earlier session saw `source: null` on a topic-only course — same field, different value |
| RAG-4 | Generated lesson content is grounded in the uploaded PDF | **FACT** (E2) | Accessibility text contains every unique fixture fact: LUMORA-731, the 3 stages, MƯA TÍM, ORBIT-294, "ORBIT-249 … ngưỡng 71" | Grounding at generation time ≠ retrieval at query time |
| RAG-5 | **Query-time answers are grounded in the source** | **FACT** (E2) | 6/6 oracle questions correct, including a paraphrase and a negative probe | n=1 per question; no repeat trials |
| RAG-6 | Near-miss values are not cross-contaminated | **FACT** (E2) | ORBIT-294 → 17, ORBIT-249 → 71, in separate turns; answer warns not to mix | One pair only; other confusable pairs untested |
| RAG-7 | The system refuses when the answer is absent from the source | **FACT** (E2) | R5: "Không có trong tài liệu", stated it re-read all 3 pages, invented no author/year | Single negative probe; sycophantic failure under pressure untested |
| RAG-8 | Citations exist as structured objects on lesson blocks | **FACT** (E1) | `lesson.blocks[].cite = {anchor: string, label: string}` on 3 of 7 blocks | — |
| RAG-9 | Citations are **navigable/clickable** to the source span | **NOT OBSERVED** | 31 buttons enumerated; `cite.label` rendered as `StaticText` ("Trang 1 — Quy trình LUMORA-731"); no citation chip | Absence in this one view ≠ absent app-wide |
| RAG-10 | Citation locator accuracy | **PARTIAL** | R4 quoted the page-3 sentence verbatim and said "nguyên văn trang 3" | The structured `anchor` was never string-matched against fixture text; not machine-verified |
| RAG-11 | Glossary provenance links to source page | **NEGATIVE** | `terms[].firstSeen = {unit, lesson}` — unit/lesson, **not** page | This is a design choice, not a defect |
| RAG-12 | Server-side retrieval of any kind | **INFERENCE** | Consistent with all observations; not directly visible | Context stuffing, caching, or a long-context window would look identical from the client |
| RAG-13 | Vector DB / embeddings / chunker / reranker | **UNKNOWN** | No signal at any client-reachable layer | Permanently out of scope for black-box |

Operational verdicts:

- `SOURCE_GROUNDING_OBSERVED` = **YES** (R1–R5)
- `CITATION_GROUNDED` = **PARTIAL** (content correct and page-named; anchor not machine-verified; not clickable)
- `NEGATIVE_REFUSAL_OBSERVED` = **YES** (R5)
- `RAG_MECHANISM_UNKNOWN` = **retained permanently**

### 1.2 Agent / tool calling

| ID | Claim | Level | Evidence | Honest limit |
|---|---|---|---|---|
| AG-1 | Tutor streams over SSE | **FACT** (E1) | 6× `POST /tutor/messages → 200`, each followed by `GET /tutor` refresh | SSE frame bodies still not retained by REA; event *names* not seen in DevTools EventStream this session |
| AG-2 | Tutor receives structured lesson context | **FACT** (E2) | POST body `{clientMessageId, entryPoint, contextRef{lessonId, blockIndex}, text, threadId?}`; `contextLabel` on 12/12 then 14/14 messages | Sent ≠ consumed by the model |
| AG-3 | Tool calls execute at runtime | **FACT** (E2) | thread `toolCalls[]` = 3 entries during R1–R5; rose to **4** after exactly one quick-action click; each entry `{name, summary, ok: boolean}` | — |
| AG-4 | **Which** tool executed | **UNKNOWN** | zero occurrences of any of the 6 enum names anywhere in the capture (accessibility, body shapes, summaries) | Cannot attribute `read_source` vs `explain_deeper` |
| AG-5 | A UI badge "đã đọc tài liệu nguồn" appears on source-reading turns | **FACT** (E2) | 3 badges in R1–R5 (R1, R4, R5) and 1 after the A2 click — exactly matching the 4 tool calls | A UI label is not a tool name |
| AG-6 | A `confirm` gate exists at runtime | **NOT OBSERVED** | `messages[].action` stayed `null` on all 14 messages | Not manufactured; a confirm may require a consequential action never attempted |
| AG-7 | Tutor quota is enforced and visible | **FACT** (E2) | `allowance{limit, remaining}` + `limit{resetAt}`; UI decremented 19 → 18 after one turn | — |
| AG-8 | Client silently refreshes an expired token mid-session | **FACT** (E2) | 7× `401` burst → `POST /auth/refresh → 200` → original GETs reissued at `200` | Client behaviour, not an AI capability |

### 1.3 Adaptive learning

| ID | Claim | Level | Evidence | Honest limit |
|---|---|---|---|---|
| AD-1 | Four difficulty quick actions exist | **FACT** (E2) | `Rút ngắn lại`, `Đi sâu hơn vào phần toán`, `Bỏ qua phần mình đã biết`, `Thêm phần thực hành` | — |
| AD-2 | Quick actions are **stateful** | **FACT** (E2) | Present on an empty thread; replaced by 4 follow-up suggestions once messages exist. Verified by set comparison of two snapshots | — |
| AD-3 | Clicking harder/easier changes lesson content | **UNKNOWN** | D2 could not run: the actions were gone in the used thread; the attempt window also failed `target_changed` | `contentVersion` was never compared |
| AD-4 | Interview answers materially change the course | **UNKNOWN** | D1 not run (needs 2 more course creations) | — |
| AD-5 | Adaptation from quiz performance | **UNKNOWN** | D3 not run (mutates learning record) | A recommended next lesson is not mastery modelling |

Three distinct levels that must never be conflated:
`PERSONALISATION_FROM_INPUT` (D1) ≠ `USER_TRIGGERED_ADJUSTMENT` (D2) ≠ `PROGRESS_DRIVEN_ADAPTATION` (D3).
Only D2 evidence touches the middle level, and only partially.

---

## 2. Status table (required format)

| Capability | IMPLEMENTED | TESTED | NOT TESTED | BLOCKED |
|---|---|---|---|---|
| Research scaffolding, redaction schema, matrix | Yes | Yes (JSON parses, CSV 12 columns) | – | – |
| Synthetic PDF fixture + oracle | Yes | Yes (3 pages, Unicode verified, `ALL PASS: True`) | – | – |
| CDP harness + dual-origin filter | Yes | Yes (6 windows, `disallowed_origin = 0` throughout) | – | – |
| Source upload + ingest | – | Yes (20 reqs, 201/202/200-poll) | – | – |
| Source-backed course generation | – | Yes (98 reqs, grounded content) | – | – |
| R1 three stages | – | **PASS** | – | – |
| R2 paraphrase | – | **PASS** | – | – |
| R3 17 vs 71 | – | **PASS** | – | – |
| R4 exception + citation | – | **PASS (content) / PARTIAL (citation)** | – | – |
| R5 unanswerable | – | **PASS** | – | – |
| A1 context passing | – | **PASS (transport)** | – | – |
| A2 tool execution | – | **PASS (execution)** | – | tool **name** unknown |
| A3 `read_source` attribution | – | **NOT_OBSERVED_WITH_GOOD_COVERAGE** | – | Values never visible |
| A4 confirm flow | – | – | **NOT TESTED** | No confirm surfaced; not manufactured |
| D1 novice vs advanced | – | – | **NOT TESTED** | Needs 2 courses + consent |
| D2 harder/easier effect | – | **INCONCLUSIVE** | – | Actions absent in used thread; `target_changed` |
| D3 post-quiz adaptation | – | – | **NOT TESTED** | Mutates learning record; consent required |

---

## 3. Comparison with the earlier baseline

| Topic | Earlier reports (2026-10-30) | This session (2026-10-31) | Delta |
|---|---|---|---|
| Source-backed lesson | never observed (`source: null`) | **observed**, `source` object populated | **new** |
| Grounding in a user PDF | UNKNOWN | **FACT** — 6/6 oracle correct | **new** |
| Citation structure | `citationSchema{anchor,heading,gist}` from static analysis | `cite{anchor,label}` observed in lesson payloads | confirmed at runtime |
| Citation clickability | assumed | **not clickable** in this view | **new negative** |
| Tool calls exist | 4 entries, names hidden | 4 entries (3 → 4 after a click), names still hidden | confirmed + causality |
| Tool identity | UNKNOWN | **still UNKNOWN** | none |
| Refusal on missing evidence | untested | **PASS** | **new** |
| Lesson context passing | `contextRef` observed once | confirmed on 6 POSTs, `contextLabel` 12/12 | strengthened |
| Adaptive difficulty | client enum only | actions exist but are **stateful**; effect untested | **new** |
| Embeddings / vector DB | UNKNOWN | **still UNKNOWN** | none |
| LLM provider | UNKNOWN | **still UNKNOWN** | none |

---

## 4. Incidental observations worth recording

1. **Ingest brief shape**: `{what, claims[10], notation[9], assumes[5], sections[3]}` — the brief is a structured summary, matching the static report's prediction.
2. **Course path shape**: `units[3].nodes[16]` each with `{kind, lessonId, state, ready, format, contentVersion, position, meta, title}`; `progress{completed,total,percent}`; `upNextLessonId`; `units[].paywalled` true on 2 units.
3. **Entitlement shape**: `{tier, expiresAt:null, subscription:null, limits{courses{limit,used,resetAt}, openUnits, tutorAllowance{limit,remaining}}}` — free tier, no subscription.
4. **Glossary shape**: `terms[11]` with `{key, kind, name, short, more, teaser, firstSeen{unit,lesson}}`.
5. **Token refresh**: a 401 burst is handled by `POST /auth/refresh` and transparent retry — worth mirroring in our own client.

---

## 5. Bottom line

**Verified:** the product can ingest a user's PDF, generate a grounded course from it, and
answer questions about it accurately — including paraphrase, near-miss disambiguation, a
citation request, and a refusal — while executing tool calls and passing structured lesson
context. That is a real, working RAG-shaped pipeline at the behavioural level.

**Not verified, and not verifiable this way:** the retrieval algorithm, embeddings, chunker,
reranker, LLM provider, tool identities, and any progress-driven adaptation. Grounding does
not identify the retriever. Three tests (A4, D1, D3) remain untested, and D2 is inconclusive.

No `RAG_MECHANISM_UNKNOWN` claim has been upgraded.
