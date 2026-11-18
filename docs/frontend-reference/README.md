# SopiSkill frontend reference pack

Evidence-based record of the PolySkill reference survey and the SopiSkill frontend
reconstruction built from it. Everything here is labelled by confidence; nothing is
presented as measured unless a command or artefact backs it.

**Survey date:** 2026-11-03 · **Branch:** `feat/p6.0-ci-pipeline` · **Base commit:** `d747e78`
**Work log:** [`../frontend-reconstruction-log.md`](../frontend-reconstruction-log.md)
**Plan of record:** [`../SOPISKILL_FRONTEND_REA_MASTER_PLAN.md`](../SOPISKILL_FRONTEND_REA_MASTER_PLAN.md)

## Contents

| File | Answers |
|---|---|
| [`reference-audit.md`](reference-audit.md) | How the reference was observed, with what tooling, and what it does **not** prove |
| [`screen-inventory.md`](screen-inventory.md) | Per-screen measured layout, states, and which screens were not observable |
| [`evidence-register.md`](evidence-register.md) | Every artefact: what it shows and what it does not |
| [`interaction-map.md`](interaction-map.md) | Which flows were driven for real vs. inferred |
| [`design-tokens.md`](design-tokens.md) | Colour, type, spacing, radius, elevation, motion, layout constants |
| [`component-mapping.md`](component-mapping.md) | Reference pattern → SopiSkill component, plus "not mapped" |
| [`api-gap-register.md`](api-gap-register.md) | Reference features SopiSkill cannot render without a backend change |
| [`visual-comparison.md`](visual-comparison.md) | Reference vs. local measurements, viewport by viewport |
| [`accessibility-review.md`](accessibility-review.md) | Keyboard, naming, focus, contrast and reduced-motion checks |
| [`decisions.md`](decisions.md) | PROPOSAL decisions and their rationale |
| [`implementation-checklist.md`](implementation-checklist.md) | Phase-by-phase tick list with the verifying command |
| [`phase-reports/`](phase-reports/) | Phase reports in the §11 template |

`evidence/` holds raw DOM/computed-style JSON; `screenshots/` holds reference and local
PNGs at 1440×900, 768×1024 and 390×844 (DPR 1).

## Confidence labels

- **FACT** — directly measured (computed style, bounding box, screenshot, bundle string).
- **INFERENCE** — consistent conclusion from several facts, not itself measured.
- **UNKNOWN** — not observable without acting on the account or reading the server.
- **PROPOSAL** — a SopiSkill design decision; it does not exist in the reference.

## Privacy

Screenshots and DOM dumps were captured from an owner session, then redacted before
storage: the account's display name was replaced with the neutral token **"Người học"**
in JSON/Markdown and painted out in the PNGs. No credentials, cookies, tokens, email
addresses or private page bodies were stored. See [`evidence-register.md`](evidence-register.md#privacy-redaction).

## What this pack is not

It is not a copy of the reference product. No PolySkill logo, mascot, illustration,
copy string or font file is reproduced in SopiSkill. Palette, type scale, spacing,
radius, shadow and breakpoints are re-implemented because they are observable layout
properties; brand identity belongs to SopiSkill.
