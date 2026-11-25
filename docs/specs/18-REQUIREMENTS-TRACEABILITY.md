# 18 — Requirements → Phase → Acceptance Traceability

**Trạng thái (`2026-11-22`):** Đồng bộ với `15-TEST-PLAN.md` (T-IDs đã chuẩn hóa `T-001`..`T-023`) và trạng thái triển khai thực tế của repo (`d747e78` + working tree).

| Requirement IDs | Specification | Phase | Test IDs (`15-TEST-PLAN.md`) | Trạng thái hiện tại (2026-11-22) |
|---|---|---|---|---|
| PRD-001; AUTH-001..005 | 01, 06 | P0.5 + Cross-phase | T-001, T-002, T-013, T-016 | **IMPLEMENTED · REPORTED TESTED** (rate-limit Redis còn mở) |
| PRD-002; COURSE-001..005 | 01, 07 | Core + P2.1 + `P1-PEDAGOGY` | T-003 | **IMPLEMENTED · REPORTED TESTED** (`P1-PEDAGOGY` chưa deploy container) |
| PRD-003; COURSE-006..009 | 01, 07 | Core + P2.1 | T-003, T-004, T-010 | **IMPLEMENTED · REPORTED TESTED** |
| COURSE-010 (proposal revision) | 07 | Backlog (`GAP-08`) | — | **PROPOSAL / NOT IMPLEMENTED** |
| PRD-004; GEN-001..005 | 01, 08 | P1.2 / P2.0 / Celery-01-02 | T-004, T-005, T-006 | **IMPLEMENTED · TESTED · DEPLOYED** |
| PRD-006; GEN-006..009 | 01, 08, 19 | P2.1 / P2.2 | T-006, T-010, T-011 | **PARTIAL** (hạ tầng xong; real eval `3.17/4`, còn `TRUNC`/`LANG`/`LEVEL-FIT`) |
| PRD-005; LESSON-001..010 | 01, 09 | P1.1 / P6.1 / `P1-QUIZ-BLANK` | T-007, T-008, T-009 | **IMPLEMENTED · REPORTED TESTED** |
| PRD-007; TUTOR-001..010 | 01, 10 | P3.0 / P3.1 / P4.1 | T-012, T-013, T-014, T-015 | **IMPLEMENTED · DEFAULT-OFF** (mock PASS; real streaming NOT TESTED) |
| PRD-008; RAG-001..012 | 01, 11, 20, 21 | P4.0–P4.3 | T-016, T-017, T-018, T-019 | **IMPLEMENTED · ĐA SỐ DEFAULT-OFF** (hashing baseline) |
| PRD-009; ADAPT-001..007 | 01, 12, 22, 23, 24 | P5.0–P5.2 | T-020 | **IMPLEMENTED · DEFAULT-OFF** (BKT/DKT deploy BLOCKED) |
| UX-001..010 | 13 | P1.3 / FR-1..FR-5 | T-001, T-009, T-022 | **IMPLEMENTED (uncommitted)**; Playwright E2E & screen-reader **NOT TESTED** |
| PRD-010; OPS-001..009 | 01, 14, 25 | P6.1 / P6.2+ | T-021, T-023 | **PARTIAL** (P6.1 CI PASS; P6.2+ prod hardening & backup drill OPEN) |

## Acceptance evidence checklist per requirement

- Requirement ID + contract source (file/section), test file/path, command/exit code và logs.
- Preconditions: user identity, provider mode (`mock` hay real), PostgreSQL/Redis/worker state, feature flags.
- Expected status, response schema/error và negative security cases (bao gồm user B cross-owner).
- Migration revision (nếu có), data preservation và rollback/restore plan.
- Tách bạch `IMPLEMENTED`, `TESTED`, `DEFAULT-OFF`, `NOT TESTED`, `BLOCKED`.

## Phase dependency map (cập nhật)

```text
[DONE in code] P0.5–P1.3 → P2.0–P2.2 → P2.SR → P3.0–P3.1 → P4.0–P4.3 → P5.0–P5.2 → P6.1 + FR-1..FR-5
                                                                                      │
                                                                                      ▼
[NEXT] Wave 1 (Commit + Container Sync + Playwright E2E)
     → Wave 2 (P1-CONTENT-TRUNC + P1-LANG + P1-LEVEL-FIT + Real Eval)
     → Wave 3 (Flag activation: Tutor/P5.0/Semantic RAG + P6.2 Redis rate-limit / TLS / Backup drill)
     → Wave 4 (Prioritized Product Gaps: Glossary, Proposal revision, Per-block/AI short grading, Figures, Stats)
     → P7+ Deferred (Reel Engine, Practice Formats, Offline SQLite, Leagues, Billing)
```
