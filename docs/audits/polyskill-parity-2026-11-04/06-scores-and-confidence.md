# 06 — Scores and Confidence

Audit: `polyskill-parity-2026-11-04`
Reference: PolySkill (`https://web.polyskill.app`, API `https://api.polyskill.app/v1`)
Target: SopiSkill, HEAD `d747e78` + dirty working tree

This chapter computes the three mandated figures from the 50 rows of `05`. No weight was adjusted
after a result was seen; the area weights are those fixed by mandate §7.1 (A=8, B=18, C=14, D=18,
E=12, F=18, G=9, H=3 → 100) and the scenario sub-weights were declared in `03` §1.3 before scoring.

## 1. The three figures

| # | Figure | Value | Denominator |
|---|---|---|---|
| 1 | **Evidence Coverage** | **53.0 %** | 100 (all weight) |
| 2 | **Measured Parity** | **74.7 %** | 83 (weight carrying a reference observation on both sides) |
| 3 | **Conservative Floor** | **62.0 %** | 100 (all weight) |
| — | Unknown / Blocked Weight | **17.0 %** | 100 |
| — | Optional upper bound (floor + unknown) | 79.0 % | **not a measured score** |

**Headline: the audit cannot confirm 99 % parity. Not one of the three gates is met.**

## 2. Evidence Coverage — 53.0 %

### 2.1 Definition applied

`Evidence Coverage` = weight of requirements that have **both** (a) strong PolySkill **runtime**
evidence and (b) a corresponding SopiSkill assessment, ÷ 100 × 100.

"Strong runtime" means **E2** (a response body was observed at runtime). By mandate and by `02` §1:

- **E1** (transport seen, body filtered/unparsed) is **not** strong — it proves volume, not contract.
- **E0** (client bundle declaration) is **not** runtime at all.
- **E2O** (owner-transcribed from DevTools) is *weaker than E2* and is **not** counted as strong
  here, even though it is strong enough to score a match value in `05`.
- `UNKNOWN_REFERENCE` has no observation.

### 2.2 The ledger (this is the whole computation — audit it row by row)

| Row | w | Strong runtime ref? | Tier that would have qualified | Counted |
|---|---|---|---|---|
| A01 | 2 | No | E0 + E1 | — |
| A02 | 2 | No | E1 for `/home`; E2 only on the adjacent `/me/entitlement` | — |
| A03 | 2 | No | E1 (`/me/profile`, body unparsed) | — |
| A04 | 2 | No | E1 (5 × `/interview/answer`) | — |
| B01 | 3 | No | E1 (`/courses` 201) | — |
| B02 | 3 | No | E1 (5 × POST) | — |
| B03 | 3 | No | E1; payload never captured | — |
| B04 | 3 | No | `UNKNOWN_REFERENCE` | — |
| B05 | 3 | No | E1 | — |
| B06 | 3 | No | E1 for `/home`; E2 on `upNextLessonId` only | — |
| C01 | 3 | No | E1 + bundle static | — |
| C02 | 3 | **Yes** | E2 — grounded lesson body observed after generation | **3** |
| C03 | 3 | No | E0 | — |
| C04 | 3 | **Yes** | E2 — `units[]{…nodes[]}` | **3** |
| C05 | 2 | **Yes** | E2 — server-returned stage labels | **2** |
| D01 | 2 | **Yes** | E2 — `paywalled` + node fields | **2** |
| D02 | 2 | **Yes** | E2 — `upNextLessonId` | **2** |
| D03 | 2 | **Yes** | E2 — six block types | **2** |
| D04 | 2 | **Yes** | E2 — `figure{…}` | **2** |
| D05 | 2 | **Yes** | E2 — `terms[11]` | **2** |
| D06 | 2 | **Yes** | E2 — `paragraphs[].termKey` | **2** |
| D07 | 2 | **Yes** | E2 — ordered `blocks[]` | **2** |
| D08 | 2 | **Yes** | E2 — `?prefetch=1` observed in the request log | **2** |
| D09 | 2 | **Yes** | E2 — `contentVersion: int` | **2** |
| E01 | 3 | **Yes** | E2 — `score{correct,total}` | **3** |
| E02 | 3 | **Yes** | E2 — `clientAttemptId`, `contentVersion`, `duplicate` | **3** |
| E03 | 2 | **Yes** | E2 — `progress{…}` | **2** |
| E04 | 2 | **Yes** | E2 — full `rewards{…}` name set | **2** |
| E05 | 2 | **Yes** | E2 — the same name set (surface only) | **2** |
| F01 | 2 | **Yes** | E2 — thread envelope | **2** |
| F02 | 2 | **Yes** | E2 — `contextLabel` 8/8 and 16/16 | **2** |
| F03 | 2 | **Yes** | E2 — POST body incl. `entryPoint=teach_block` | **2** |
| F04 | 2 | No | **E2O** only — owner transcription; no machine capture | — |
| F05 | 2 | **Yes** | E2 — `toolCalls[4]` | **2** |
| F06 | 2 | No | E0; `action` null 14/14 and 16/16 | — |
| F07 | 2 | **Yes** | E2 — `allowance`/`limit`, 19→18 | **2** |
| F08 | 2 | No | E0 | — |
| F09 | 2 | No | E0 | — |
| G01 | 2 | **Yes** | E2 — upload + ingest to terminal state | **2** |
| G02 | 2 | **Yes** | E2 — 3-page fixture → 3 sections | **2** |
| G03 | 2 | No | E2 for **PDF only**; web/arXiv never exercised | — |
| G04 | 1 | No | `UNKNOWN_REFERENCE` (topic course, `source: null`) | — |
| G05 | 1 | **Yes** | E2 — `cite` on 3 of 7 blocks | **1** |
| G06 | 1 | No | `INFERENCE` only | — |
| H01 | 0.5 | No | no keyboard traversal | — |
| H02 | 0.5 | No | E2 but an incomplete a11y observation | — |
| H03 | 0.5 | No | E0 | — |
| H04 | 0.5 | No | nothing captured | — |
| H05 | 0.5 | No | E0 | — |
| H06 | 0.5 | No | E0 | — |
| **Total** | **100** | | | **53.0** |

`Evidence Coverage = 53.0 / 100 = 53.0 %`.

The gate is **≥ 95 %**. This audit is **42 points short**.

### 2.3 Why coverage is low, stated plainly

Almost the entire onboarding/auth/course-creation journey (area A, all of area B, area C's polling)
was observed on the reference at **E1 only** — requests and status codes were recorded but bodies
were filtered or not parsed. Under this audit's own tier rules those cannot support a contract
claim. They are scored in `05` on *business outcome*, which is defensible; they cannot be counted
toward coverage, which would not be.

Consequence: the parity figure that matters most to a stakeholder — "does onboarding match?" — is
the **least** evidenced part of the reference. Closing that requires a fresh capture session with
response bodies enabled, not more code reading.

## 3. Measured Parity — 74.7 %

### 3.1 Formula

`Measured Parity = Σ w_i · match_i / Σ w_i eligible × 100`, where `eligible` excludes `UNKNOWN`.

`Σ w_i · match_i = 62.0` (computed in `05` §10.1, per-area subtotals summing to 62.0).
`Σ w_i eligible = 100 − 17 = 83`.

**62.0 / 83 = 74.70 %**.

`UNKNOWN` is excluded from **both** numerator and denominator. It is never counted as `MATCHED`,
and it is never counted as a failure either — the two errors §7.2 of the mandate forbids.

### 3.2 Per-area parity

| Area | Weight | Weighted match | Eligible | Parity within area |
|---|---|---|---|---|
| A — onboarding/auth/dashboard/profile | 8 | 5.0 | 8 | 62.5 % |
| B — topic→interview→proposal→approve | 18 | 15.0 | 15 | **100.0 %** |
| C — generation/status/retry | 14 | 11.0 | 11 | **100.0 %** |
| D — lesson/path/figures/glossary | 18 | 9.0 | 18 | **50.0 %** |
| E — quiz/grading/rewards | 12 | 9.0 | 12 | 75.0 % |
| F — tutor | 18 | 9.0 | 12 | 75.0 % |
| G — sources/citations | 9 | 4.0 | 7 | 57.1 % |
| H — UX/a11y/robustness | 3 | 0.0 | 0 | not measurable |
| **Total** | **100** | **62.0** | **83** | **74.7 %** |

The shape of this table is the audit's most actionable output:

- **B and C are at 100 %** on everything that could be scored — the topic→interview→proposal→
  approve→generate spine is genuinely at parity. That is a real, defensible strength.
- **D is at 50 %** and is the single largest weight pool (18). Glossary, `termKey`, figures,
  prefetch are hard absences. This is where parity is actually being lost.
- **A is at 62.5 %** but rests on thin reference evidence, so its true value is unknown in both
  directions.
- **H contributes 0 / 0** — three points of the score are simply not measurable today.

## 4. Conservative Floor — 62.0 %

`Conservative Floor = Σ w_i · match_i / 100 × 100 = 62.0 %`.

This is the **mathematical lower bound**. Every `UNKNOWN` row contributes **0**, regardless of
whether SopiSkill implements it, because no reference fact establishes the requirement. Per mandate
§7.2, these rows **give only a lower bound** and must **not** be described as broken, missing or
defective features. Several may well be present and good — G04's source-evaluation surface and F08's
server-side stop plausibly exceed the reference. They score 0 because the reference never
demonstrated the behaviour, not because SopiSkill failed.

## 5. Unknown / Blocked Weight — 17.0 %

| Row | w | Why unmeasured | BLOCKED or NOT OBSERVABLE |
|---|---|---|---|
| B04 revise proposal | 3 | `revise_proposal` is E0; never exercised | NOT OBSERVABLE |
| C03 retry | 3 | declared E0; never exercised | NOT OBSERVABLE |
| F06 confirm gate | 2 | `action` null 14/14, 16/16 | NOT OBSERVABLE |
| F08 stop | 2 | declared E0; never exercised | NOT OBSERVABLE |
| F09 Last-Event-ID | 2 | declared E0; never exercised | NOT OBSERVABLE |
| G04 source↔course + evaluation | 1 | reference used a topic-based course | NOT OBSERVABLE |
| G06 query-time RAG | 1 | `INFERENCE`; no client signal | **BLOCKED** |
| H01–H06 (6 × 0.5) | 3 | no a11y/keyboard/viewport harness on either side | NOT OBSERVABLE / PARTIAL |
| **Total** | **17.0** | | |

`Unknown/Blocked Weight = 17.0 %`.

### 5.1 The optional upper bound — explicitly not a measured score

`Floor + Unknown = 62.0 + 17.0 = 79.0 %`.

This figure assumes **every single unmeasured row would score 1** — that the reference has all six
of those capabilities *and* that SopiSkill implements them *and* that its implementation matches on
the first try. It is reported only so a reader can see the ceiling of the current evidence. **It is
not a measured score and must never be quoted as one.**

## 6. The hard ceiling: even perfect execution cannot reach 99 % on this evidence set

This is the audit's most important arithmetic result, and it is independent of any future
implementation work:

| Scenario | Weighted match |
|---|---|
| Current measured | 62.0 |
| + every `0.5` row upgraded to `1` | +9.0 → 71.0 |
| + every `UNKNOWN` row resolved as a perfect `1` | +17.0 → **88.0** |
| + the 12.0 of hard `MISSING` rows scoring `1` | +12.0 → 100.0 |

**The 12.0 weight of `MISSING` rows cannot be recovered by resolving unknowns.** They are provable
absences on the SopiSkill side against runtime-established reference facts: glossary (D05, 2),
inline `termKey` (D06, 2), figures (D04, 2), prefetch (D08, 2), gamification surface (E05, 2), ingest
brief (G02, 2). Filling them is implementation work, not evidence work.

So:

- **With today's evidence**: `Measured Parity` 74.7 %, `Conservative Floor` 62.0 %.
- **Best case after a perfect evidence campaign** (every unknown resolves favourably): 88.0 %.
- **99 % requires** closing the 12 points of hard gaps *and* upgrading 9 points of partials *and*
  resolving all 17 unknown points favourably — and then re-observing the whole matrix, because the
  reference evidence for area A and B is still E1.

## 7. Gate evaluation (mandate §1)

| Gate | Threshold | Measured | Verdict |
|---|---|---|---|
| Evidence Coverage | ≥ 95 % | **53.0 %** | **FAIL** |
| Measured Parity | ≥ 99 % | **74.7 %** | **FAIL** |
| Conservative Floor | ≥ 95 % | **62.0 %** | **FAIL** |
| No P0 gap in topic→interview→proposal→generation→lesson/quiz→tutor | zero | Tutor runtime `503 TUTOR_DISABLED`; D05/D06 glossary absent | **FAIL** |
| E2E + security tests actually executed, with logs and exit codes | required | `logs/e2e-chain.log` (18 steps), `logs/security-probes.log` (S1–S8 PASS), `EXITCODE=0` | **PASS** |

One of five gates passes. The mandated verdict is therefore:

> ### `CHƯA ĐỦ CĂN CỨ ĐỂ XÁC NHẬN 99%`
>
> Evidence Coverage 53.0 % (gate 95 %), Measured Parity 74.7 % (gate 99 %), Conservative Floor
> 62.0 % (gate 95 %), and a P0 chain gap in the tutor. Even a perfect resolution of all unknown
> rows would cap at 88.0 %.

## 8. Confidence in the individual scores

Not all 62 points of weighted match deserve the same trust. Three bands:

| Band | Rows | Weight | Why |
|---|---|---|---|
| **High confidence** | All `E2`-backed rows: C02, C04, C05, D01–D09, E01–E05, F01–F03, F05, F07, G01, G02, G05 | 53.0 | Contract observed at runtime on the reference; behaviour observed or test-verified on SopiSkill |
| **Medium confidence** | B01–B03, B05, B06, C01, E03's threshold, plus every `E2O`/`E1`-scored `1` | 24.0 | Outcome-level match on E1 reference evidence. The *business outcome* is solid; the *contract* is not established |
| **Low confidence** | A01–A04, F04, G03 | 6.0 | E1/E0/E2O reference evidence; A04 additionally scores a SopiSkill-internal defect with no reference baseline |

The single most fragile scored row is **A04** (0.5). It rests on 5 unparsed POSTs on the reference
side and on a SopiSkill-side extraction defect whose *reference* counterpart was never measured. It
is scored `PARTIAL` for honesty, but on this evidence the true value could plausibly be `1` (the
reference is equally bad) or `0` (the reference is good and SopiSkill is not). It is reported as
`PROPOSAL`-grade evidence, not as a finding about parity.

The single most robust row is **D03** (six block types, `1`). Both sides were observed running
with an identical taxonomy, independently derived. It would take a direct contradiction to overturn.

## 9. What these numbers do not mean

- `74.7 %` is **not** "the product is 74.7 % done". It is the parity of the 83 points this audit
  could score, against a reference whose own behaviour is only partly observed.
- `62.0 %` floor is **not** a quality judgement. It is a lower bound that charges zero for every
  unmeasured row.
- `79.0 %` upper bound is **not** a forecast. It assumes every unmeasured capability exists on both
  sides and matches.
- None of these figures is an AI quality score. Model output quality is a **separate** 5-criterion
  rubric in `08` and is never folded into parity (`07` §7.3 of the mandate).
- Nothing here establishes that the reference grades attempts server-side, consumes `contextRef`,
  or runs retrieval. Those remain `UNKNOWN`/`INFERENCE`.
