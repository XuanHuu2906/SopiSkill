# 00 — Hiện trạng, evidence và quy tắc quản lý specification

**Trạng thái:** DRAFT nguồn từ 2026-10-30; **đã cập nhật lại theo Git HEAD 2026-10-31** cho P2.1–P3.1 lát A
(xem `docs/development-progress.md` để lấy bằng chứng lệnh/kết quả). Các mục không nêu trong bảng dưới vẫn
giữ nguyên nhãn PLANNED/NOT IMPLEMENTED.

## 1. Source-of-truth hierarchy

1. **Repository được checkout tại thời điểm triển khai**: code, migrations, route definitions, test output, Git diff.
2. **`development-progress.md`**: lịch sử test được báo cáo, có ngày, tên module, lệnh, kết quả; không tương đương test chạy trong phiên hiện tại.
3. **`llm-provider.md`, `migration-runbook.md`**: các hành vi và vận hành đã được nhóm ghi nhận.
4. **`SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`**, `architecture.md`, `database-design.md`: hướng dẫn/thiết kế, nhiều mốc được viết trước khi P1.1–P2.0 hoàn thành.
5. **`02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md`**: vision và ưu tiên ban đầu; tuyên bố “chưa có repo” đã lỗi thời so với progress sau này.
6. Nghiên cứu PolySkill: chỉ bối cảnh/hình thái hành vi, **không là chứng cứ để xác định backend SopiSkill**.

## 2. Baseline được báo cáo mới nhất

| Hạng mục | Trạng thái theo hồ sơ | Bằng chứng lịch sử |
|---|---|---|
| Repo SopiSkill | Có, `https://github.com/XuanHuu2906/SopiSkill`; baseline cũ `464e5e1` | Master plan; HEAD hiện tại **UNKNOWN** |
| Next.js 15 + TS, FastAPI + PostgreSQL 16 + Redis 7 + Celery | REPORTED IMPLEMENTED | `development-progress.md` |
| Đăng ký/đăng nhập; JWT HttpOnly cookie, Argon2id, CSRF; owner scope | REPORTED IMPLEMENTED + TESTED | P0.5/P0.5.1 |
| Topic → 5 interview → proposal → approve → jobs → lessons → quiz | REPORTED IMPLEMENTED + TESTED với mock | Slice 0/1 |
| Quiz key isolation, progress, XP an toàn, content version | REPORTED IMPLEMENTED + TESTED | P1.1 |
| Atomic job claim, outbox/reconciler, retry/backoff | REPORTED IMPLEMENTED + TESTED | P1.2, migration `0004_p12_job_reliability` |
| Dashboard course list, session cache isolation, route guard | REPORTED IMPLEMENTED + TESTED | P1.3 |
| Provider-neutral OpenAI-compatible adapter, fail-fast, semantic lint | REPORTED IMPLEMENTED + TESTED | P2.0; pytest **119 passed, 6 skipped**, E2E mock **35/35** |
| Real LLM smoke Deploy.com / DeepSeek | **3 request thực** đã được phê duyệt/ghi nhận, không phải full E2E | P2.0: interview/proposal/lesson HTTP 200 |
| P2.1 curriculum DAG/hierarchical generation | REPORTED IMPLEMENTED + TESTED | P2.1 |
| P2.2 eval rubric, usage/cost, job budget | REPORTED IMPLEMENTED + TESTED | P2.2, migration `0007_p22_eval_cost` |
| P3.0b source registry, P2.SR research agent | REPORTED IMPLEMENTED + TESTED (agent offline) | `0005_p30_source_registry`, `0006_p2sr_source_research` |
| P3.0 AI Tutor SSE + lesson grounding | REPORTED IMPLEMENTED + TESTED (mock streaming) | `0008_p30_tutor_core`; real provider streaming NOT TESTED |
| P3.1 lát A tutor stop/allowance/stale/replay semantics | REPORTED IMPLEMENTED + TESTED (mock) | `0009_p31_tutor_controls` |
| P3.1 lát B tool allowlist + audit | REPORTED IMPLEMENTED + TESTED (mock planner) | `0010_p31_tutor_tools`; tool quality với model thật NOT TESTED |
| PDF/RAG (P4), adaptive learning (P5) | PLANNED / NOT IMPLEMENTED | Master plan P4/P5 |
| Production deployment, distributed limit/backup restore drill | PLANNED / NOT VERIFIED | P6 |

**Lưu ý:** Kết quả 119/6 và 35/35 là output trong nhật ký ngày 2026-10-30; **không phải kết quả kiểm thử mới của bộ specs**.

## 3. Những mâu thuẫn đã giải quyết khi viết spec

- Cấu trúc repo: đề xuất ban đầu `apps/web` / `services/api`; tài liệu tiến độ chỉ ra **`frontend/` và `backend/`**. Giữ cấu trúc hiện tại, không tự monorepo rewrite.
- Auth: kiến trúc cũ nhắc bearer/demo `X-User-Id`; P0.5 mới hơn xác nhận **JWT HttpOnly cookie + CSRF**, `ALLOW_DEMO_HEADER=false` mặc định. Không hồi quy sang demo header.
- Master plan ở baseline đánh dấu P1.1–P2.0 TODO; **nhật ký tiến độ có các mục mới hơn báo hoàn thành**. Bắt đầu audit P2.1, không làm lại nguyên phase cũ.
- Policy “lesson completed ≥80%” và reward XP hiện **đã được áp dụng theo báo cáo**, nhưng tài liệu vẫn ghi chưa được phê duyệt riêng như business policy dài hạn. Đánh dấu `INCUMBENT / PRODUCT APPROVAL PENDING`.
- `database-design.md` gợi ý embedding vector(1536); model và dimension **chưa chốt**. Không hardcode dimension trước benchmark.
- `architecture.md` mô tả worker có thể sinh proposal; luồng mới được giữ: proposal phải có để user approve, worker sinh lessons theo snapshot approved proposal.

## 4. Quy tắc thay đổi spec

- Mỗi requirement có ID ổn định như `COURSE-001`, `TUTOR-004`, `RAG-006`.
- Khi contract **đang chạy** khác proposal, viết **compatibility/migration plan**, không overwrite API client đang dùng.
- Chấp nhận một thiết kế chỉ sau khi có quyết định product/engineering được ghi trong `17-DECISION-LOG.md`.
- Các specs của Tutor/RAG là **contract đề xuất**; test trong `15-TEST-PLAN.md` là điều kiện tương lai, không phải evidence đã pass.
- Khi OpenCode làm phase: cập nhật trạng thái, commit, migration, lệnh test và fail cases trong `docs/development-progress.md`.
