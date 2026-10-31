# PolySkill Black-box Research — RAG / Agent / Adaptive Learning

**Session:** `ps-bbx-2026-10-31`
**Status:** EXECUTED — 10 of 12 cases produced usable evidence; R1–R5 and A1–A2 PASS.
**Verdict on the core question:** the product **does** ground answers in a user-owned PDF
(6/6 oracle correct, clean refusal on the unanswerable probe), and tool calls **do** execute at
runtime. The retrieval mechanism, embeddings, tool identities, LLM provider and any
progress-driven adaptation remain **UNKNOWN**.

This directory is research scaffolding. It never touches application code and never stores
credentials, cookies, tokens or user content.

---

## 1. What is in this directory

```
research/polyskill-blackbox/
├─ README.md                       <- you are here
├─ test-matrix.md                  12 planned cases with expected results + evidence bars
├─ fixtures/
│  ├─ make_fixture.py              generator for the synthetic PDF (Chrome headless print-to-pdf)
│  ├─ rag_synthetic_v1.pdf         LOCAL ONLY — fictional 3-page document (gitignored)
│  ├─ oracle.local.json            LOCAL ONLY — answer key (gitignored)
│  └─ .gitignore
├─ scripts/
│  └─ start-browser.ps1            owner-run launcher for the isolated CDP profile (does not log in)
├─ evidence/
│  ├─ observations-redacted.json   machine-readable redacted record (0 observations so far)
│  ├─ runs.csv                     one row per executed test (0 rows so far)
│  └─ .gitignore
└─ reports/
   ├─ blackbox-findings.md         FACT / INFERENCE / UNKNOWN, per capability
   └─ unknowns-and-next-tests.md   what is still unknown + how the next session closes it
```

## 2. Environment verified in this session

| Item | Value | How verified |
|---|---|---|
| Working dir / repo | `D:\Reverse Engineer`, branch `main`, HEAD `5e5f9cd`, clean tree | `git status --short`, `git branch --show-current`, `git log --oneline -3` |
| Node | `v24.11.1` | `node --version` |
| npm | `11.6.4` | `npm --version` |
| REA | `6.7.0` at `C:\nvm4w\nodejs\rea.cmd` | `rea --version` |
| Chrome | installed at `C:\Program Files\Google\Chrome\Application\chrome.exe` | path check; `--version` launches a window so it was not captured |
| REA flags | `--allowed-origins <array>`, `--observation-ms`, `--include-json-body-shapes`, `--format` | read from `rea inspect-web-page --help` on 6.7.0 |
| CDP `127.0.0.1:9222` | **closed** (`curl` exit 7, HTTP 000) | `curl http://127.0.0.1:9222/json/version` |
| `rea doctor` | `healthy:false` — only because Hopper/Ghidra/IDA/JADX native engines are absent; not a browser blocker | `rea doctor` |
| OpenCode MCP tools | **no REA MCP server is registered in `opencode.json`**; REA is used as a CLI | `opencode.json` inspection |

Because no REA MCP server is registered, the observation commands in this runbook are CLI
invocations. That is deliberate and does not change the evidence rules.

## 3. Documents read (and what was unavailable)

Read:
- `polyskill-analysis-report.md` — sections 4–7 (client-side tutor protocol, tool enum, citation schema, explicit "not provable from the client" list).
- `polyskill-dynamic-analysis.md` — sections 0, 2–7 (runtime request shapes, the 4 observed `toolCalls`, the `source: null` limitation, the origin-filter failure).
- `polyskill_blackbox_test_plan.md` — full playbook.
- `02_PROJECT_CONTEXT.md` — sections B, D, E.
- `03_ROADMAP_AND_BACKLOG.md` — P2–P4.

**Not in the workspace, but found elsewhere on the machine:** `02_PROJECT_CONTEXT.md` and
`03_ROADMAP_AND_BACKLOG.md` live at `D:\02_PROJECT_CONTEXT.md` and
`D:\03_ROADMAP_AND_BACKLOG.md`, *outside* the repo working directory. They were read from
there; nothing was copied into this repo and their content is not reproduced here.

## 4. Which claims are allowed today

Only the imported baseline is allowed, and it must carry its original label:

| Claim | Label | Because |
|---|---|---|
| Client handles `delta/tool/confirm/done/error/restarted` | FACT, E0 | Declared in client code (earlier static report) |
| Client declares 6 tutor tool names | FACT, E0 | Declared in client code (earlier static report) |
| Tutor POST returned 200 with `text/event-stream`-style streaming | FACT, E1 | Earlier runtime capture |
| 4 `toolCalls` existed in one thread's history | FACT, E2 | Earlier runtime capture; **names and summaries unknown** |
| `contextRef{lessonId, blockIndex}` was sent with tutor messages | FACT, E2 | Earlier runtime capture |
| The tested course had `source: null` | FACT, E2 | Earlier runtime capture |
| Server-side RAG/retrieval | INFERENCE | No direct evidence ever, in either report |
| Vector DB / embeddings / chunking / reranker | UNKNOWN | No evidence at any client-visible layer |
| LLM provider / model | UNKNOWN | Entirely server-side |
| `read_source` executed in any session | UNKNOWN | Enum only; never matched to a runtime call |
| Adaptive learning adapts to progress | UNKNOWN | Never tested; only a client→backend action mechanism is known |

## 5. Hard rules this directory follows

1. The agent never clicks, types, uploads or navigates inside the owner's PolySkill session.
2. The agent never replays, forges or re-sends a PolySkill request.
3. No secret, token, cookie, raw HAR, raw SSE frame or user-authored text is written here.
4. A missing request is never a negative result unless capture quality is provably complete.
5. A client enum is never promoted to runtime behaviour. E0 never becomes E2 by inference.
6. `PASS` is only written after an executed, evidenced test. This session has zero.
7. The PDF fixture and its oracle stay local (gitignored). The PDF is fictional and contains no personal data.

## 6. How to run a real session (owner-gated)

Nothing below is executed automatically. Each step needs the owner's explicit "yes".

### 6.1 Owner starts the isolated browser

Easiest: run the prepared launcher (it does not log you in and does not touch data).

```powershell
powershell -ExecutionPolicy Bypass -File research/polyskill-blackbox/scripts/start-browser.ps1
```

Equivalent manual form:
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$profile = Join-Path $env:LOCALAPPDATA 'REA-PolySkill-Profile'
Start-Process -FilePath $chrome -ArgumentList @(
  '--remote-debugging-port=9222',
  '--remote-debugging-address=127.0.0.1',
  ('--user-data-dir="' + $profile + '"'),
  'https://web.polyskill.app'
)
```

Then the owner logs in manually. Credentials never enter this repo or the chat.

### 6.2 Agent confirms the port and the correct tab

```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version | Select-Object Browser
rea list-browser-targets http://127.0.0.1:9222 `
  --allowed-origins https://web.polyskill.app --format json
```

Select the target whose URL is `https://web.polyskill.app/...`. Do not guess.

### 6.3 Arm observation *before* the owner acts

Origin filter must be repeated per origin (this was the failure in the earlier session):

```powershell
rea inspect-web-page http://127.0.0.1:9222 TARGET_ID `
  --allowed-origins https://web.polyskill.app `
  --allowed-origins https://api.polyskill.app `
  --observation-ms 180000 `
  --include-json-body-shapes `
  --format json > evidence/raw/run-<test-id>.json
```

`evidence/raw/` is gitignored. Only a hand-redacted summary is promoted into
`observations-redacted.json`; the raw file is deleted (or kept strictly local, never committed).

### 6.4 Owner performs exactly one test action, then stops

One test per window keeps the attribution clean. Afterwards the agent records:
`requests_captured`, `disallowed_origin`, `attach_limited`, `policy_filtered`, `truncated`,
`window_elapsed`, `target_changed`.

### 6.5 Verdict rules

| Situation | Verdict |
|---|---|
| Action done, relevant request captured, quality complete | `OBSERVED` (or `NOT_OBSERVED` if the feature is genuinely absent with good coverage) |
| Action done, `disallowed_origin > 0` | `INCONCLUSIVE` — fix the flags, re-run |
| Action done, 0 requests captured | `INCONCLUSIVE` — never "feature absent" |
| Action not done (no consent / no session) | `BLOCKED` |
| Prepared but never attempted | `NOT_TESTED` |

## 7. Session status board

| Item | Status |
|---|---|
| Repo audit + git cleanliness | IMPLEMENTED (verified) |
| Environment inventory | IMPLEMENTED (verified: Chrome/156.0.8078.76, REA 6.7.0) |
| Baseline FACT/INFERENCE/UNKNOWN extraction | IMPLEMENTED |
| 12-case test matrix with expected results | IMPLEMENTED + UPDATED with results |
| 3-page fictional PDF fixture + local oracle | IMPLEMENTED + TESTED (text layer verified, Unicode OK) |
| Redacted evidence store | IMPLEMENTED (7 observation records) |
| Findings + unknowns reports | IMPLEMENTED (v2, post-execution) |
| Source upload + ingest | **TESTED — PASS** (20 requests, brief with 3 sections) |
| Source-backed course generation | **TESTED — PASS** (grounded lesson content) |
| R1–R5 (RAG grounding) | **PASS** 6/6 oracle sub-probes |
| A1 (context passing) | **PASS** transport-level |
| A2 (tool execution) | **PASS** execution-level; tool name UNKNOWN |
| A3 (`read_source` attribution) | **NOT_OBSERVED_WITH_GOOD_COVERAGE** — tool names never visible |
| A4 (confirm flow) | **NOT TESTED** — no confirm surfaced, not manufactured |
| D1 (novice vs advanced) | **NOT TESTED** — needs 2 more courses + consent |
| D2 (harder/easier) | **INCONCLUSIVE** — actions only exist on an empty thread; window hit `target_changed` |
| D3 (post-quiz adaptation) | **NOT TESTED** — mutates the learning record |

See `reports/blackbox-findings.md` for the full status table and
`reports/unknowns-and-next-tests.md` for the ordered next actions.
