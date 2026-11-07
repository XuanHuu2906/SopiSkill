# 10 — Security, Permissions, and Limitations

Audit: `polyskill-parity-2026-11-04`
Purpose: state what this audit could and could not do, why, and what a reader must not conclude from
the gaps. Mandate §10 Q10 and §11 land here.

## 1. Permission and conduct boundary actually observed

The mandate imposed a read-only-by-default posture. This table records what was done and what was
deliberately not done.

| Rule (mandate) | This audit | Note |
|---|---|---|
| Never modify product source / DB / migration / `.env` | **HONOURED** | No product file edited. `01` §1 confirms **no backend file modified**; the dirty tree predates the audit |
| No deploy, no push | **HONOURED** | 0 behind / 38 ahead of `origin/main`, never pushed |
| No buying plans / burning quota | **HONOURED** | The one real-provider eval is a **pre-existing** report file (`08` §4.1), not a run paid for by this audit |
| No uploading private sources unapproved | **HONOURED** | All ingest fixtures were **self-authored synthetic** PDFs (`rag_synthetic_v1.pdf`, fictional `LUMORA-731`) |
| No destructive DB/volume ops | **HONOURED** | Compose stack inspected, never reset |
| No out-of-UI endpoint calls to PolySkill | **HONOURED** | The reference was never called by the agent; see §2 |
| Disposable accounts only | **HONOURED** | `audit_*@example.test` accounts, self-created, per run |
| Preserve every claim's label + source class | **HONOURED** | Every matrix cell carries its tier; see §7 |

Nothing in the audit required an approval request that was not granted, because nothing crossed the
read-only line. §5 lists the decisions that **would** need owner approval if the backlog is later
executed — those are not this audit's to take.

## 2. The reference product was never driven by this audit — the central limitation

This is the single most consequential limitation and it governs every PolySkill claim.

Historical sessions (`ps-bbx-2026-10-31`, `ps-bbx-2026-10-31-p3`) were `mode: EXECUTED` /
`EXECUTED_PARTIAL` with **`actions_by_agent: []`** and **`owner_ui_actions_performed: 14` / `3`**
(`02` §1). The owner drove the UI; the agent only ran passive REA inspection windows
(`inspect-web-page`, `list-browser-targets`). That is why several matrix cells are `OWNER_REPORTED`
(E2O) rather than machine-captured E2.

**In this audit's own tool session, Phase B was `BLOCKED`:**

```
mcp__rea__list_browser_targets(
  cdp_endpoint="http://127.0.0.1:9222",
  allowed_origins=["https://web.polyskill.app"]
)
→ targets: []
   exclusion counters: { disallowed_origin: 0, unsupported_url: 0, non_page: 0 }
   browser: Chrome/156.0.8078.76   user agent: HeadlessChrome/156.0.0.0
   evidence id: ev_f7404a13cb326b015f9476383274536434b44305b7aea600b280ed8b4004da14
```

All three counters being zero while `targets` is empty proves **no page target existed at all** — the
origin filter excluded nothing. The endpoint was a bare headless Chrome with no tab on the reference.
A logged-in `web.polyskill.app` session requires the **account owner's interactive login**, which
this audit is not permitted to perform on their behalf.

**Consequences, stated without softening:**

- Every PolySkill runtime fact in `02` is **REPORTED** from the owner's prior sessions, produced with
  **REA 6.7.0** — a different tool version than this audit's 6.8.0 (`01` §1.3). Those captures are
  `REPORTED`, not reproducible in this session.
- No fresh reference capture, no new endpoint, no new contract field was obtained. If a reader wants
  area A or B evidence upgraded from E1 to E2, that requires a new owner-driven session with
  response bodies enabled — which is exactly what `06` §2.3 recommends and what no amount of code
  reading can substitute for.
- This is why `Evidence Coverage` is 53.0 % and why `Measured Parity` is 74.7 % with a hard ceiling
  of 88.0 % even in the perfect-evidence case (`06` §6).

## 3. REA version delta and the missing SSE parser

| Fact | Consequence |
|---|---|
| Historical reference captures used **REA 6.7.0** (`C:\nvm4w\nodejs\rea.cmd`, now absent) | Those captures cannot be re-verified here; recorded as `REPORTED` |
| This session uses **`rea-agents` 6.8.0 via MCP** (server `started_at 2026-11-03T14:00:45.169Z`, protocol `2025-11-25`) | All tool facts are from 6.8.0 |
| `rea` CLI is **not on PATH** on this host | No `rea --version`, `--help`, or `rea doctor` output exists; none was fabricated (`01` §1.3) |
| REA 6.7.0 has **no `text/event-stream` parser** (`body_shapes.response = ABSENT`, verified by grep over the installed package dist) | SSE events on the reference are `E2O` only (`delta`, `done`); `tool`, `confirm`, `error`, `restarted` were **not seen** — and "not seen" is **not** "absent" (`02` §3.9) |

**Do not read this as "the reference has no SSE event types."** The client enum declares all six
(`BASE-STATIC-1`, E0). The audit observed two, recorded them at E2O, and marks the rest `UNKNOWN`.

## 4. Known product-side limitations (operational, not parity gaps)

These are recorded so they are not mistaken for reference-driven gaps. They come from `05` §11.

| Limitation | Where | Class | Does it hurt parity? |
|---|---|---|---|
| `tutor_enabled: bool = False` (`config.py:95`) | Tutor disabled by default | **Operational P0** | It *blocks* the F area from being measured at all. It is the top item in `07` (`P0-TUTOR-FLAG`) precisely because it gates evidence, not because it proves a missing feature |
| `LLM_PROVIDER=mock` default | All live generation is fixture output | Operational | `08` §2 forbids scoring it; real-provider quality comes only from the offline eval |
| Rate limiter is **in-memory, per-process** (`app/core/limits.py`) | Not shared across workers | Scaling limitation | No. Effective in single-process dev; breaks under multi-instance (`07` → `M1-SEC-LIMITER`) |
| `/v1/me/stats`, `/v1/me/entitlement` | **404** — routes do not exist | Functional gap | Yes, area A (`07` → `M1-ME-SURFACE`) |
| No `PATCH`/`PUT` verbs in `backend/app/api` | Proposal edit path is absent | Functional gap | Yes, `07` → `P1-PROPOSAL-EDIT` |
| `RAG_ENABLED=false` → `503 RAG_NOT_ENABLED` | Retrieval off on live surface | Operational | Blocks G measurement (`07` → `M5-RAG`) |
| `webEnabled:false`, `arxivEnabled:false` | Only PDF can be ingested live | Operational | Blocks G03/G04 (`07` → `M5-WEB-ARXIV`) |
| `ocrEnabled:false` | Scanned PDF untested live | Operational | Untested path |
| `P50_ENABLED=false`, P5.2 flag off | Review scheduling, recommendations unexercised | Operational | Untested |
| Frontend fetches **absolute** `NEXT_PUBLIC_API_URL`, no rewrite proxy | Deployment coupling | Architecture note | `INTENTIONAL_DIFFERENCE` candidate, not scored as a gap |

**None of the flag-gated rows is scored as `MISSING`.** A flag that is off is not a feature that is
absent — `05` marks them `UNKNOWN` and `06` charges them 0 toward the floor while excluding them from
Measured Parity's denominator. The distinction is the difference between "we could not see it" and
"it is not there", and this audit never conflates the two.

## 5. Decisions that would need owner approval before any implementation

The audit is read-only, so it took none of these. They are listed because the backlog in `07` cannot
be executed without them (mandate §10 Q10).

| Decision | Why the owner must make it | Blocks |
|---|---|---|
| Enable `TUTOR_ENABLED` in a non-production env and spend real-provider tokens | Costs money and is the only way to observe tutor parity | `07` `P0-TUTOR-FLAG`, all of area F |
| Choose a real LLM provider and budget | `mock` cannot be shipped; provider choice is a product/business decision | `07` `P1-CONTENT-TRUNC`, `P1-LANG`, `P1-LEVEL-FIT`, `08`'s unmeasured criteria |
| Enable `RAG_ENABLED` + pick an embedding backend (hashing-ngram is lexical, **not** semantic; `rag_bench` says `needPgvector: true`) | Cost + infra + correctness claim | `07` `M5-RAG` |
| Enable web/arXiv ingest | SSRF surface + legal/copyright posture | `07` `M5-WEB-ARXIV` |
| Authorise a fresh **owner-driven** reference capture with response bodies on | Requires the owner's PolySkill login; the agent cannot do it | Upgrading areas A/B from E1, raising Evidence Coverage above 53 % |
| Approve the `paywalled`/hearts/streak/billing semantics | Reference behaviour there is `UNKNOWN`; implementing from guesses would invent a contract | `07` `M8-BILLING` — explicitly "do not start" |
| Approve any DB migration | The backlog may need new columns (glossary, termKey, figures) | `07` `P1-GLOSSARY`, `P9-FIGURES` |
| Approve adding a browser UI test harness | Needed to make any UI claim at all | `03` §1.4's standing caveat removal |

## 6. Secret and PII handling

| Rule | Status |
|---|---|
| Mixpanel token + EAS projectId in `polyskill-analysis-report.md` must never be reproduced | **HONOURED** — not present in any audit artifact. Only the *existence* of client analytics is mentioned |
| No PII captured | All accounts are synthetic `audit_*@example.test`; all fixtures self-authored and fictional |
| No credentials in logs | Cookie names are logged (`access_token`, `csrf_token`); **values are not** |
| `captures/` must hold filtered metadata only | **Directory is empty** — see §8. Nothing was written, so nothing leaked. An empty directory is a truthful state, not a missing file |
| Response bodies in `logs/` | Bodies are from the **local** SopiSkill stack with synthetic data; no reference-product body, no third-party content |

## 7. Claim-labelling integrity

The mandate forbids unlabelled assertions. The audit's own internal audit of that rule:

| Requirement | Where enforced | Verdict |
|---|---|---|
| `FACT / INFERENCE / UNKNOWN / PROPOSAL` on every claim | `02` tiers, `05` cells, `03` result classes | **Held** |
| `STATIC / RUNTIME / SOPISKILL_CODE / SOPISKILL_TEST / REPORTED` source class | `04` evidence index, `02` session table | **Held** |
| E0 never promoted to runtime | `02` §1 rule 1; `05` prints the tier on every reference cell | **Held** |
| Owner transcript is not machine capture | `02` §1 rule 2; E2O tier; `06` §2.2 excludes F04 | **Held** |
| Absence of capture ≠ absence of feature | `02` §1 rule 3; all flag-gated rows are `UNKNOWN` | **Held** |
| No 99 % claim without all gates | `06` §7 | **Held — 1 of 5 gates passes** |
| Mock ≠ real provider | `08` §2 | **Held** |
| AI quality ≠ parity | `08` opening; `06` §9 | **Held** |
| No invented dates in backlog | `07` uses S/M/L only | **Held** |
| No claim a file exists if it does not | every Write returned "File created successfully"; this chapter only names files that exist | **Held** |

## 8. `captures/` — an explicit, reasoned empty state

`docs/audits/polyskill-parity-2026-11-04/captures/` **exists and is empty**. That is a deliberate and
truthful state, not an omission:

1. **Phase B was `BLOCKED`** (§2): no reference page target existed, so there is no fresh CDP capture
   to store.
2. **No raw body may be stored** under the mandate's redaction rule even if one existed — only
   filtered metadata could be filed.
3. **Fabricating a capture directory with placeholder files would violate §10/§11** of the mandate
   ("do not claim a file was created if it wasn't"). An empty directory is the only honest artifact.

All evidence that *does* exist is text and lives in `02` (reference tiers), `04` (evidence index),
`05` (matrix), and `logs/` (SopiSkill runs). If the owner later authorises a fresh capture, the
filtered metadata would be filed here with a capture ID, timestamp, and the same E0/E1/E2 labels.

## 9. Residual limitations that will not go away

These are not fixable by more work in this audit; they are structural.

| Limitation | Effect on conclusions |
|---|---|
| Reference backend is a black box (model, provider, prompt, retrieval all `UNKNOWN`) | Parity can only be judged at the *contract and behaviour* level; never at implementation level |
| No human expert rated AI quality | `08`'s 3.17/4 is an LLM signal, not ground truth |
| No browser UI assertion anywhere | **No visual/UX parity claim** is made in this audit; `tsc`+build prove compilation only |
| No a11y / keyboard harness | H01–H06 are `UNKNOWN`; 3 points of the score are unmeasurable |
| Single-machine, single-account tests | Multi-tenancy was probed (S1–S3 PASS) but not load-tested |
| Dirty working tree | Every SopiSkill test result is against the dirty tree, not clean HEAD `d747e78` |
| Backlog not implemented | `07` is entirely `PROPOSAL — CHƯA TRIỂN KHAI`; no fix was applied |

## 10. Gate and status summary

| Gate (mandate §1) | Result |
|---|---|
| Evidence Coverage ≥ 95 % | **FAIL — 53.0 %** |
| Measured Parity ≥ 99 % | **FAIL — 74.7 %** |
| Conservative Floor ≥ 95 % | **FAIL — 62.0 %** |
| No P0 gap in the core chain | **FAIL — tutor `503`, glossary/termKey absent** |
| E2E + security tests executed with logs/exit codes | **PASS — 8/8 probes, 18-step chain, `EXITCODE=0`** |

**Verdict: `CHƯA ĐỦ CĂN CỨ ĐỂ XÁC NHẬN 99%` — and the audit's own status is `PARTIAL AUDIT` per
mandate §11.** One gate of five passes. Even a perfect resolution of all 17 unknown points would cap
at 88.0 %, because the 12.0 weight of hard `MISSING` rows is implementation work, not evidence work
(`06` §6).
