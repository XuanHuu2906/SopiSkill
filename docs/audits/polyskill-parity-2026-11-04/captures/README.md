# captures/ — intentionally empty

This directory holds **no capture files** for audit `polyskill-parity-2026-11-04`. That is a
deliberate and truthful state, not an omission.

## Why

1. **Phase B was `BLOCKED`.** `mcp__rea__list_browser_targets(cdp_endpoint="http://127.0.0.1:9222",
   allowed_origins=["https://web.polyskill.app"])` returned `targets: []` with all exclusion counters
   zero — no page target existed at all. The endpoint was a bare headless Chrome with no tab on the
   reference product. A logged-in reference session requires the account owner's interactive login,
   which this audit could not perform. Evidence id `ev_f7404a13cb326b015f9476383274536434b44305b7aea600b280ed8b4004da14`.

2. **No raw body may be stored anyway.** The mandate permits only filtered metadata in `captures/`;
   response bodies are not filed.

3. **No fabricated artifacts.** Mandate §10/§11 forbid claiming a file exists when it does not. An
   empty directory with this notice is the only honest artifact.

## Where the evidence actually is

- Reference tiers and contracts → `../02-reference-evidence.md`
- Evidence IDs → `../04-evidence-index.md`
- Parity rows → `../05-parity-matrix.md`
- SopiSkill run logs → `../logs/`

If the owner authorises a fresh owner-driven capture later, filtered metadata is filed here with a
capture ID, timestamp, and the same `E0 / E1 / E2 / E2O` labels used throughout the audit.
