# 18 — Requirements → Phase → Acceptance Traceability

**Trạng thái:** Planned trace matrix. `T-*` là test scenario trong `15-TEST-PLAN.md`, không ngụ ý đã chạy.

| Requirement IDs | Specification | Phase | Acceptance/Test IDs |
|---|---|---|---|
| PRD-001; AUTH-001..005 | 01, 06 | Regression + P3/P4 | T-001, T-002, T-013, T-015 |
| PRD-002; COURSE-001..005 | 01, 07 | Core + P2.1 | T-003 |
| PRD-003; COURSE-006..010 | 01, 07 | Core + P2.1 | T-003, T-004, T-010 |
| PRD-004; GEN-001..005 | 01, 08 | P1.2/P2.0 regression | T-004, T-005, T-006 |
| PRD-006; GEN-006..009 | 01, 08, 19 | P2.1/P2.2 | T-010, T-011, T-006 |
| PRD-005; LESSON-001..010 | 01, 09 | P1.1 regression | T-007, T-008, T-009 |
| PRD-007; TUTOR-001..010 | 01, 10 | P3.0/P3.1 | T-012, T-013, T-014 |
| PRD-008; RAG-001..012 | 01, 11 | P4.0–P4.3 | T-015, T-016, T-017, T-018 |
| PRD-009; ADAPT-001..007 | 01, 12 | P5 | T-019 |
| UX-001..010 | 13 | Cross-phase | T-001, T-003, T-009, T-012, T-015 |
| PRD-010; OPS-001..009 | 01, 14 | P6 and continuously | T-020 + CI migration/security tests |

## Acceptance evidence checklist per requirement

- Requirement ID + contract source (file/section), test file/path, command/exit code and logs.
- Preconditions: user identity, provider mode mock/real, PostgreSQL/Redis/worker state, feature flag.
- Expected status and response schema/error; security negative case including user B.
- Migration revision, data preservation and rollback/restore plan when schema changed.
- `IMPLEMENTED` and `TESTED` recorded separately; unfinished requirements keep `NOT TESTED` or `BLOCKED`.

## Phase dependencies

```text
P2.1 → P2.2 → P3.0 → P3.1 → P4.0 → P4.1 → P5 → P6
P4.2/P4.3 conditional; P7 only after product approval.
```

Một số P6 hạng mục (CI, secret scanning, backups planning) có thể chạy sớm, nhưng production gate vẫn phải hoàn thành trước public launch.
