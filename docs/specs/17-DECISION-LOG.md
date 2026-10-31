# 17 — Decision Log & Open Questions

**Trạng thái:** Chỉ các mục có bằng chứng đã được quyết định mới xem là accepted. Số còn lại là proposed/open.

| ID | Decision | Status | Evidence / what to decide |
|---|---|---|---|
| DEC-001 | SopiSkill xây độc lập, không clone PolySkill | ACCEPTED project principle | Project context + master plan |
| DEC-002 | Giữ stack hiện hữu Next.js 15/FastAPI/Postgres/Redis/Celery | Chọn cho kế hoạch | Master plan; check current repo before edits |
| DEC-003 | MockProvider là default, real provider fail-fast | REPORTED IMPLEMENTED | `llm-provider.md`, progress P2.0 |
| DEC-004 | Auth HttpOnly JWT cookie + CSRF + Argon2id | REPORTED IMPLEMENTED | progress P0.5; không dùng demo header production |
| DEC-005 | Quiz closed-form deterministic, answer key server-only | REPORTED IMPLEMENTED | progress P1.1 |
| DEC-006 | Generation job at-least-once + atomic claim/outbox | REPORTED IMPLEMENTED | progress P1.2 |
| DEC-007 | Course completed lesson threshold ≥80% | INCUMBENT / PRODUCT APPROVAL PENDING | Có code/report, chưa duyệt policy lâu dài |
| DEC-008 | XP cap theo user/lesson/contentVersion | INCUMBENT / PRODUCT APPROVAL PENDING | Có code/report, cần duyệt public policy |
| DEC-009 | Real smoke Deploy.com DeepSeek 3 requests | APPROVED FOR THAT SMOKE ONLY | Không là quyền chạy 10-topic real eval |
| DEC-010 | Curriculum prerequisite DAG, Bloom outcomes | DESIGN CHOICE, P2.1 NOT VERIFIED | Chọn cấu trúc và validation/migration |
| DEC-011 | Hybrid RAG FTS + pgvector + RRF | DESIGN CHOICE, P4 NOT VERIFIED | Benchmark retrieval/model/dimension trước code |
| DEC-012 | AI Tutor SSE + read-only tools | PROPOSED P3 | API/status/quota/replay chưa duyệt |
| DEC-013 | FSRS rồi BKT conditional | FUTURE P5 | Cần review history/eval before activation |
| DEC-014 | Production deployment, billing, paid plans | NOT APPROVED | P6/P7 manual gate |

## Câu hỏi cần chốt theo thời điểm (không chặn viết specs)

1. **P2.1:** Có cho phép tạo schema `curriculumGraph` trong payload proposal v2 không? Hay dùng bảng graph versioned riêng? Điều kiện: query patterns, migration/backfill & version compatibility.
2. **P2.1:** Ngôn ngữ course và thời lượng học được nhập explicit UI hay trích từ interview? Ngữ nghĩa `availableMinutesPerDay` khi user không trả lời là unknown.
3. **P2.1 real test:** Nhà cung cấp/model cụ thể, giới hạn USD hoặc số tokens, 1–2 topic được phép gửi, dữ liệu ngoài hay synthetic; không tự dùng quyền smoke cũ.
4. **P2.2:** Rubric và ngưỡng go/no-go về factuality, difficulty, cost/latency; ai là reviewer pedagogy.
5. **P3:** Quota tutor (messages/tokens/day), thread retention, timeout, `409 in-progress` behavior, event log/replay; stop billing semantics.
6. **P4:** PDF size/pages/time limits, private storage provider, retention/deletion, embedding model & dimension, quyền sử dụng tài liệu.
7. **P5:** Completion threshold 80%, XP formulas, version policy khi regenerate; có gamification công khai hay không.
8. **P6:** Host/deployment, legal/privacy policy, backups SLA, incident response, dữ liệu được đưa sang real AI provider.


## Accepted during P3.1 lát A (2026-10-31, agent implementation — user-approved scope)

```text
DEC-P31-A1: Tutor SSE replay semantics = explicit restart
Date / reviewer: 2026-10-31, user chose option when asked
Status: ACCEPTED
Context: P3.1.5 requires documenting replay/resume semantics; no durable event log exists.
Options: (a) explicit restart, no resume; (b) persist event log + Last-Event-ID.
Choice: (a). Keep `id = streamId:seq` for future extension, but do NOT accept Last-Event-ID.
Consequences: `replaySupported=false` stays; client reloads thread history after disconnect;
  changing this requires an event-log table + reconnect tests before any claim.
Evidence: docs/specs/10-AI-TUTOR-SSE.md §5, thread-detail response, E2E 12b.
```

```text
DEC-P31-A2: Stop semantics = best-effort server cancellation, no refund claim
Date / reviewer: 2026-10-31
Status: ACCEPTED
Context: pausing a provider stream cannot unsend tokens already generated/billed.
Options: (a) claim "cancelled ⇒ free"; (b) expose cancel_requested + providerStopGuaranteed=false.
Choice: (b). Endpoint writes `cancel_requested_at`; the stream task persists the terminal state.
Consequences: UI says the partial answer is kept; docs state tokens already produced may be billed.
Evidence: tests/test_p31_tutor_controls.py, PostgreSQL race test, development-progress P3.1 lát A.
```

```text
DEC-P31-A3: Tool allowlist split to P3.1 lát B
Date / reviewer: 2026-10-31, user chose split scope
Status: PENDING (implementation deferred)
Context: tools need a tool-call schema decision (server-side deterministic JSON vs native tool API).
Options: (a) server-side deterministic tools; (b) native OpenAI tool_calls; (c) no tools.
Choice: (a) recorded as preferred direction, not yet implemented.
Consequences: TUTOR-006 remains unimplemented; P3.1 cannot be called complete.
Evidence: docs/SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md §12.
```

## Format for new accepted decisions

```text
DEC-015: <short title>
Date / reviewer: <date, role>
Status: ACCEPTED | REJECTED | SUPERSEDED | PENDING
Context: <facts and constraints>
Options: <alternatives and risks>
Choice: <explicit user decision>
Consequences: <schema/api/rollout/tests>
Evidence: <issue/PR/commit/log>
```

Không suy diễn user đã chấp thuận một product policy chỉ vì code hiện thực hóa baseline đề xuất.
