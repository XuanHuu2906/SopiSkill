# API gap register

Reference features that SopiSkill **cannot** render faithfully with its current backend
contract. None of these were faked, mocked, or worked around with invented endpoints.
Every entry names the missing field or endpoint, the evidence for its absence, and the
decision taken.

Contract untouched by this work: `frontend/src/lib/api.ts` was not modified, no route,
schema, migration or environment variable was added.

## Gaps

| ID | Reference element | Evidence it exists | SopiSkill contract | Decision | Unblock by |
|---|---|---|---|---|---|
| GAP-01 | Per-lesson duration (`· 9 phút`, `· 4 phút`) | `course-768x1024.png`, `dom-course-1440x900.json` | `CourseDetailOut` has no duration field | **Not rendered.** No placeholder minutes. | Additive field `estimatedMinutes` on lesson payload + migration |
| GAP-02 | Unit tone / `Pro` paywall chip | `course-768x1024.png` (Trang 2 carries `Pro`) | No paywall concept in the data model | **Not rendered.** | Product decision + backend entitlement model |
| GAP-03 | Weekly XP bar chart, 46 milestones, league | `profile-1440x900.png`, `dom-profile-1440x900.json` | Only `xp` and streak counters on `/v1/auth/me` | **Not rendered** beyond a compact XP/streak readout | New endpoint(s) for activity history and milestones |
| GAP-04 | Quick-answer chips in the interview | Reference returns suggested answers per question | SopiSkill returns question text only | **Textarea instead of chips.** Chips remain for topic suggestions on `/new` only. | Backend must return answer options per question |
| GAP-05 | `?prefetch=1` next-lesson prefetch | Reference route behaviour | No prefetch contract | **Omitted.** Optional optimisation, not required. | Backend/route support |
| GAP-06 | Glossary `terms[]` pill row | Reference lesson shows term pills | `LessonOut` has no `terms` | **Rendered only when present; currently absent**, so the row does not appear | Additive `terms[]` on lesson payload |
| GAP-07 | Named tutor tools (`read_source`, `explain_deeper`) | Reference tutor shows tool chips by name | Tutor stream emits a generic `tool` event | **Generic badge only.** Tool names are never invented. | Backend must emit a tool identifier |
| GAP-08 | Proposal editing / AI revision | Not observed in reference | No edit/revision endpoint | **Not rendered.** Approve only; no fake edit affordance. | Explicit API + product approval |
| GAP-09 | Source ingest with citation validation | Reference has source/CAG surfaces | SopiSkill has `/sources` with its own ingest contract | **Uses SopiSkill's own contract**, not the reference's | — (already covered by existing API) |
| GAP-10 | Dark-mode toggle placement | Reference has a single toggle in side nav | n/a (UI decision) | **Segmented Sáng/Hệ thống/Tối control** — equivalent behaviour, different form (**PROPOSAL**) | — |
| GAP-11 | Per-question feedback band + explanation after each answer | Reference reveals a correctness band and an explanation per question | `grade_attempt` grades the **whole lesson in one batch**; `public_block()` never emits answers | **One submit at the end.** Per-question feedback is contractually impossible without changing grading. | Backend would need a per-block grading endpoint |
| GAP-12 | Lesson duration, type tag, lock state, unit ordering | Reference lesson rows carry `· 9 phút`, a type chip, `Đã khóa`, and ordered units | Not in `LessonOut` | **Not rendered.** The counter reflects the real block count instead. | Additive fields on the lesson payload |
| GAP-13 | Offline save / download lesson | Reference exposes an offline affordance | No offline or export contract | **Not rendered.** No fake download button. | Backend export endpoint + storage |
| GAP-14 | Vocabulary list + lesson summary sheet | Reference ends a lesson with a summary sheet and a vocabulary list | `LessonOut` has no such collections | **Not rendered.** The outline sheet covers navigation only. | Additive `terms[]` / `summary` on the lesson payload |
| GAP-15 | Seven-step lesson structure (`1/7`…`7/7`) | Reference lessons run seven steps | SopiSkill lessons ship six blocks | **Counter shows the true count** (`1/6`…`6/6`); structure is not padded to seven. | Content-generation change, not frontend |

## Rules applied

- A missing endpoint never becomes a mocked fetch, a hard-coded array, or a `TODO` that
  renders plausible data.
- Where a reference element is purely visual and costs nothing to imitate (spacing,
  radius, type), it was implemented; where it implies data SopiSkill does not have, it
  was omitted and recorded here.
- Any future unblock must be an **additive** backend change reviewed separately; this
  frontend work does not carry migrations.
