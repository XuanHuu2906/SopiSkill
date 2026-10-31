# SOPISKILL — MASTER IMPLEMENTATION PLAN & AGENT EXECUTION RUNBOOK

**Phiên bản:** 1.0 · **Ngày:** 2026-10-30  
**Repository:** https://github.com/XuanHuu2906/SopiSkill  
**Baseline được đối chiếu trên GitHub:** `main` — `464e5e19d978e0afee58960a73f44451c43fbdcf` (`464e5e1`)  
**Mục đích:** **Một kế hoạch duy nhất** để OpenCode triển khai tuần tự, không cần viết lại một prompt riêng cho mỗi phase.  
**Đích lưu trong repo (đề xuất):** `docs/MASTER_IMPLEMENTATION_PLAN.md`  
**Trạng thái:** **PROPOSAL / PLAN**, không phải khẳng định các phase tương lai đã triển khai hoặc kiểm thử.

> **Đọc trước:** Tài liệu này vừa là roadmap, vừa là specification giao việc. Agent phải bắt đầu bằng kiểm tra repository thực tế; **không được tự đánh dấu hoàn thành** dựa trên các dấu check có từ trước hoặc dựa trên tài liệu. Các mục P0/P0.5/P0.5.1/P1 dưới đây là **đã có mã và có kết quả kiểm thử do nhóm triển khai báo cáo**; lần lập plan này không chạy lại pytest, Docker hay ứng dụng trên máy Windows của người dùng.

---

## 0. Cách dùng ngay — chỉ cần một yêu cầu cho OpenCode

1. Chép file này vào **`docs/MASTER_IMPLEMENTATION_PLAN.md`** trong thư mục SopiSkill; giữ các file `AGENTS.md`, `.opencode/skills/`, `.agents/skills/`, `opencode.json` hiện có. Nếu chưa có `AGENTS.md`, sử dụng bản hướng dẫn được review, **không tự động ghi đè**.
2. Mở OpenCode **tại thư mục gốc repository**. Chạy lệnh kiểm tra trạng thái Git nếu cần.
3. Gửi **một prompt khởi động duy nhất**:

```text
Đọc AGENTS.md, docs/MASTER_IMPLEMENTATION_PLAN.md và docs/development-progress.md.
Thực hiện đúng cơ chế điều hành ở mục 2 của MASTER_IMPLEMENTATION_PLAN.
Kiểm tra branch/HEAD/git status và re-audit các file thực tế trước khi sửa.
Bắt đầu từ PHASE G0 rồi phase chưa hoàn thành đầu tiên theo dependency graph.
Tự chia từng phase thành task nhỏ, implement → test → review → report; chỉ sang
phase kế tiếp khi phase gate đạt và không chạm điểm dừng bắt buộc.
Không viết lại các phase đã có code; không chạy lệnh phá hủy dữ liệu;
không mua/dùng API trả phí, sửa secrets, deploy hay push main nếu chưa được duyệt.
Sau mỗi phase cập nhật docs/development-progress.md và báo cáo IMPLEMENTED /
TESTED / NOT TESTED / BLOCKED với lệnh, logs, files và commit SHA (nếu có).
Nếu gặp blocker, dừng đúng tại blocker, không báo PASS giả.
```

**Cách vận hành đề xuất:** Một phase = một nhánh/PR (hoặc một tập commit nhỏ trên nhánh riêng). Có thể tự làm tiếp **các bước nhỏ trong phase**; giữa các phase, lưu checkpoint và chỉ tự chuyển tiếp khi đủ mọi gate, không phát sinh quyết định về chi phí/bảo mật/migration phá hủy. **Không tự push thẳng `main`**.

---

## 1. Nguồn sự thật, phạm vi đã làm và quyết định kiến trúc

### 1.1 Nguồn phải đọc trước khi chỉnh code

| Nguồn | Vai trò | Mức độ tin cậy |
|---|---|---|
| Repository SopiSkill trên branch/commit được kiểm tra | **Source of truth cho IMPLEMENTED** | Code được kiểm tra trực tiếp |
| `docs/development-progress.md` | Nhật ký kết quả lệnh test & triển khai | **Reported evidence**, không thay thế lần chạy hiện tại |
| `docs/architecture.md`, `docs/database-design.md`, `docs/implementation-plan.md` | Thiết kế ban đầu, có thể lạc hậu | **DESIGN**, phải đối chiếu code |
| `docs/migration-runbook.md` | Quy trình nâng cấp DB hiện hữu | Runbook, kiểm tra trước khi sử dụng |
| `02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md` (trong ChatGPT Project) | Vision, ưu tiên, bảo mật | Tài liệu định hướng; phần “chưa có repo” nay **đã lỗi thời** |
| `AI_ALGORITHMS_DECISIONS_SOPISKILL.md` (file đã xuất, nếu đã copy vào repo) | Nhóm thuật toán được chọn và các đề xuất có điều kiện | **Kiến trúc chọn**, không đồng nghĩa đã code |
| `polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md` | Tham khảo hành vi client/runtime của sản phẩm khác | FACT có giới hạn; **không suy ra thuật toán backend** |

**Quy tắc nguồn:** `FACT` = có bằng chứng; `INFERENCE` = suy luận có ghi nhãn; `UNKNOWN` = không biết; `PROPOSAL` = quyết định thiết kế của SopiSkill. Không dùng lại endpoints, prompt, UI, code, assets, tên riêng, bí mật của PolySkill; không reverse-engineer trái phép.

### 1.2 Baseline tại commit `464e5e1`

| Hạng mục | Trạng thái ở baseline | Bằng chứng / giới hạn |
|---|---|---|
| Next.js 15 + TypeScript + TanStack Query; các trang học | IMPLEMENTED | Có source frontend |
| FastAPI + SQLAlchemy async + PostgreSQL + Redis + Celery | IMPLEMENTED | Có source backend, Docker Compose |
| Topic → 5 interview → proposal → approve → Celery → 4 lessons mock → quiz | IMPLEMENTED | Code; test Docker E2E **được báo cáo** |
| MockProvider deterministic; 6 block `teach/mc/blank/order/match/short` | IMPLEMENTED | Source provider, schemas |
| Auth register/login/logout/me, Argon2id, JWT cookie, CSRF | IMPLEMENTED | Commit `46a4fdd`, `464e5e1` |
| Alembic `0001_initial`, `0002_auth_columns` | IMPLEMENTED | Đã deploy; **không chỉnh sửa migration cũ** |
| Sửa HTTP 422, rate limiter, test regression | IMPLEMENTED | Commit `464e5e1` |
| `pytest -q` = 40/40, `e2e_acceptance.py` = 21/21, build OK | REPORTED TESTED | Theo `development-progress.md`, không test độc lập trong lần lập kế hoạch |
| Course progress, quiz key isolation, worker atomic claim | **CHƯA HOÀN THIỆN** | Có vấn đề cụ thể được review trong code |
| Real LLM adapter / AI Tutor SSE / RAG pgvector | NOT IMPLEMENTED | Chưa thấy module nghiệp vụ đầy đủ |
| Production deployment / distributed rate-limit / refresh token | NOT IMPLEMENTED | Chưa đạt production readiness |

### 1.3 Kiến trúc & thuật toán được chọn cho **dự án của chúng ta**

| Thành phần | Chọn / mức chắc chắn | Phase |
|---|---|---|
| Sinh ngôn ngữ, interview, proposal, lesson | **Transformer-based pretrained LLM** qua provider adapter; model/provider cụ thể **chưa chốt** | P2 |
| Tổ chức lộ trình | Prerequisite **Knowledge Graph dạng DAG**, topological sort; Bloom's Taxonomy để thiết kế mục tiêu | P2 |
| Chấm quiz đóng | **Deterministic grading server-side** | P1.1, giữ nguyên nguyên tắc |
| Tutor | **LLM grounded lesson + constrained tool calling + SSE** | P3 |
| Retrieval tài liệu | **Hybrid RAG**: PostgreSQL lexical search + embeddings (Transformer đa ngôn ngữ) + **RRF** + verified citation | P4 |
| PDF scan / image | **OCR dùng CNN/ViT pretrained** nếu có nhu cầu; không dùng CNN để xử lý PDF text sẵn | P4.3 tùy điều kiện |
| Năng lực người học | Rule-based baseline → **BKT** khi có dữ liệu; LSTM/DKT **có điều kiện** | P5 |
| Ôn tập | **FSRS** sau khi có review history phù hợp | P5 |
| Chọn bài / độ khó | Rules → contextual bandit (chỉ nghiên cứu nếu đo được lợi ích) | P5.2 tùy điều kiện |
| K-Means, RF/XGBoost, full RL | **Không chốt triển khai**; không thêm chỉ để liệt kê AI | Future |

**Quan trọng:** `opencode.json` cấu hình *coding agent* (DeepSeek/GLM qua Deploy.com) **khác** với `LLM_PROVIDER`/`LLM_MODEL` dùng bởi backend SopiSkill. Không tự lấy credentials của OpenCode đưa vào backend.

### 1.4 Các chính sách sản phẩm CHƯA được người dùng duyệt riêng

Để không chặn mọi task, agent có thể dùng **baseline đề xuất** trong môi trường local rồi ghi vào Decision Log; **phải hỏi khi lựa chọn tạo chi phí thật hoặc thay đổi dữ liệu hiện có**:

- **Progress:** lesson completed khi có attempt đạt **≥80%** trên `contentVersion` hiện hành; chỉ là **PROPOSAL**, cần đánh giá tác động đến sản phẩm trước khi chốt làm policy lâu dài.
- **XP:** không thưởng lặp vô hạn cho cùng một lesson vì submit lại; định nghĩa rõ theo user + lesson + version và quy tắc reattempt, có transaction/constraint.
- **Quiz:** ẩn answer key trước khi nộp; có thể trả lời giải thích sau nộp theo policy do backend quyết định.
- **LLM:** provider/model/budget/dữ liệu gửi ra ngoài do người dùng phê duyệt; mặc định `mock`, không tốn phí.
- **Công khai:** không có tính năng billing, newsletter, scraping web tùy tiện hoặc production deploy tự động.

---

## 2. Quy chế thực thi bắt buộc của Agent (áp dụng mọi phase)

### 2.1 Quy trình 9 bước

**B1 Audit:** `git status`, `git branch --show-current`, `git rev-parse HEAD`, inspect file liên quan; đọc `AGENTS.md`, progress và các skill có liên quan. Nếu HEAD khác baseline, **dùng source hiện tại** và diff trước khi triển khai.

**B2 Plan:** Tạo plan ngắn ngay trong báo cáo/issue: mục tiêu, dependency, file chạm, thay đổi API/schema, rủi ro, rollback, tests. Không đổi stack hoặc tự rewrite.

**B3 Contract:** Định nghĩa/điều chỉnh input-output, status codes, state machine, auth/owner scope; đảm bảo backward compatibility nếu có client/data cũ.

**B4 Test trước:** Viết failing tests cho lỗi đã biết hoặc contract mới (trong khả năng môi trường); không tự sửa test chỉ để qua.

**B5 Implement tối thiểu:** Áp dụng thay đổi nhỏ, tách module, tận dụng interface/infra sẵn có; không trộn nhiều phase trong một commit.

**B6 Security:** Kiểm tra quyền sở hữu ở server, validate input, CSRF với cookie mutation, idempotency, secret isolation, timeout, log redaction; external content không được biến thành system instruction.

**B7 Verify:** Chạy unit → integration → frontend build → Docker/worker E2E nếu môi trường hỗ trợ. Test concurrency, error path và negative authorization khi phase đụng các thành phần đó.

**B8 Review:** Đọc diff, đánh giá backward compatibility, query/migration, kiểm tra không lộ token/PII/answer key, update docs.

**B9 Report:** Nêu đúng `IMPLEMENTED` / `TESTED` / `NOT TESTED` / `BLOCKED`, lệnh và output, số tests, commit SHA, known issues, phase gate. Không viết **PASS** nếu chưa chạy.

### 2.2 Quy tắc chuyển phase

- `GATE-PASS`: *tất cả* criteria bắt buộc được xác minh bằng kết quả thực; không có regression nghiêm trọng; docs và test có thể tái lập.
- `GATE-PARTIAL`: có code nhưng còn test/infra pending; **không coi phase hoàn tất**.
- `BLOCKED`: thiếu key, quyền, service, schema data, chi phí, quyết định quan trọng — ghi lý do, cách gỡ và **dừng** nhánh phụ thuộc.
- `NOT TESTED`: thiếu Docker/Python/Node/DB không có nghĩa code pass; ghi lệnh có thể chạy trên Windows.
- Dừng **bắt buộc** trước destructive migration/rollback, xóa volume, gửi dữ liệu riêng ra API ngoài, trả phí, thay secrets thật, production deploy, bật billing, hoặc push trực tiếp `main`.
- **Không** làm một đợt code toàn bộ roadmap rồi báo xong; mỗi phase có commit/checkpoint và review riêng. Có thể tự động thực hiện bước con của phase khi đủ điều kiện.

### 2.3 Bộ lệnh baseline (PowerShell / Windows)

```powershell
# Từ thư mục gốc SopiSkill
git status --short
git branch --show-current
git rev-parse HEAD

docker compose config
docker compose ps

# Backend (venv đã cài dependencies)
cd backend
python -m pytest -q
cd ..

# Frontend
cd frontend
npm run build
cd ..

# Docker smoke + E2E (chỉ trên stack local an toàn)
docker compose up -d --build
docker compose ps
$env:E2E_BASE = "http://127.0.0.1:8001"
python .\backend\e2e_acceptance.py
docker compose logs --tail=120 backend worker
```

Nếu `python -m pytest` hoặc Docker chưa sẵn sàng, ghi `BLOCKED/NOT TESTED` cùng môi trường; không sửa nội dung acceptance chỉ để bỏ kiểm tra. `docker compose up` có thể thay đổi dữ liệu local qua migrations; **kiểm tra migration và backup trước** nếu database chứa dữ liệu cần giữ.

### 2.4 Skills cần nạp theo nhiệm vụ

| Công việc | Skills nên dùng |
|---|---|
| Mọi phase | `sopi-repo-audit`, `sopi-verification-report`; Superpowers TDD/debug/review nếu đã kiểm tra hoạt động |
| Auth, policy, API | `sopi-fastapi-auth`, `sopi-quiz-progress` khi liên quan |
| Migration | `sopi-alembic-migrations` |
| Worker | `sopi-celery-reliability` |
| Frontend | `vercel-react-best-practices`, `web-design-guidelines` |
| Provider/LLM | `sopi-llm-structured-output`, `sopi-ai-evaluation` |
| Tutor | `sopi-tutor-sse`, `sopi-ai-evaluation` |
| PDF/RAG | `sopi-rag-provenance`, `sopi-ai-evaluation` |

Skill được phát hiện hoặc validate frontmatter **khác** việc đã runtime-load. Agent phải thông báo nếu skill cần dùng chưa nạp được, sau đó thực hiện bằng spec trong file này; không tự nhận nó hoạt động.

### 2.5 Bộ tiêu chí hoàn thành chung (Global DoD)

- Có code thật trên branch được kiểm tra; không có secret, token, passwords, user private data trong diff/log.
- Schema/API được validate; migration forward và rollback/restore plan nếu thay DB; dữ liệu cũ không mất.
- Tests *mới* kiểm tra cả positive, negative, repeated requests, cross-user access; regression tests cũ không bị làm giả.
- Mock được ghi nhãn mock, real provider phải có proof-of-request/usage trong môi trường cho phép.
- Feature flags mặc định an toàn; không vô tình mở dịch vụ trả phí, route nội bộ hoặc public file.
- Có README/architecture/progress được cập nhật và `phase gate` có bằng chứng.

---

## 3. Thứ tự phase và dependency graph

```text
BASELINE 464e5e1 (P0 + P0.5 + P0.5.1 + P1 đã có code)
    │
    ▼
G0    Audit/Quality Gate & migration consistency check
    │
    ▼
P1.1  Quiz Integrity + Progress + XP + Content Version
    │
    ▼
P1.2  Celery Job Reliability + Retry/Outbox
    │
    ▼
P1.3  Frontend UX / Session Isolation / Course Navigation
    │
    ▼
P2.0  LLM Provider Infrastructure (vẫn chạy mock được)
    │
    ▼
P2.1  Real AI Course Generator + Pedagogy DAG
    │
    ▼
P2.2  AI Evaluation + Cost/Quality Controls
    │
    ▼
P3.0  Tutor Core: Threads + SSE + Lesson Context
    │
    ▼
P3.1  Tutor Tools + Limits + Cancel/Resume
    │
    ▼
P4.0  PDF Text Ingestion + Provenance
    │
    ▼
P4.1  Hybrid RAG + Verified Citations
    │
    ├──► P4.2 Web/arXiv Ingestion [OPTIONAL, nguồn được phép]
    ├──► P4.3 OCR CNN/ViT [OPTIONAL, PDF scan thật]
    │
    ▼
P5.0  Learner Profile + Mastery Baseline + FSRS
    │
    ├──► P5.1 BKT [CONDITIONAL]
    └──► P5.2 DKT/LSTM, Bandits [RESEARCH ONLY until dataset adequate]
    │
    ▼
P6    Production Hardening, CI/CD, Privacy, Operations
    │
    ▼
P7    Gamification/Billing/Analytics nâng cao [FUTURE, approval required]
```

**Mốc ra MVP AI thực dụng:** sau **P2.2** đã có course generation thật; sau **P3.1** có Tutor; sau **P4.1** có học từ PDF kèm citation. P5–P7 là nâng cao; không bắt toàn bộ P7 để ra bản đầu tiên.

| ID | Trạng thái khởi tạo | Độ ưu tiên | Gate bắt buộc |
|---|---|---|---|
| P0/P0.5/P0.5.1/P1 | **Đã code, reported tested** | Bảo toàn | Re-run regression khi môi trường cho phép |
| G0 | NEXT | Critical | Baseline + schema audit rõ |
| P1.1 | TODO | Critical | Quiz không lộ đáp án; progress/XP bền vững |
| P1.2 | TODO | High | Không double job/lesson/cost trong retry/race |
| P1.3 | TODO | High | Auth session/UI & navigation đúng |
| P2.0 | TODO | High | Adapter real configured fail-fast; offline tests |
| P2.1 | TODO | High | Generation bằng LLM thật có kiểm chứng nếu có credentials |
| P2.2 | **DONE 2026-10-31** | High | `0007_p22_eval_cost`; dataset 12 topic + rubric deterministic + LLM-as-judge + cost/budget guard; 270 pytest, 51/51 E2E, real eval 12/12 |
| P3.0 (Tutor Core) | **DONE 2026-10-31** | High | `0008_p30_tutor_core`; 306 pytest + 2 race + 58/58 E2E (tutor on) / 52/52 (off) |
| P3.1 (Tools/cancel/quota) | TODO | High | Cần P3.0 làm nền |
| P3.0b (Source Registry + Evidence Contract) | **DONE 2026-10-31** | High | `0005_p30_source_registry`; 190 pytest + 3 race + 47/47 E2E |
| P2.SR (Source Research Agent) | **DONE 2026-10-31** | High | `0006_p2sr_source_research`; agent độc lập + registry/idempotency + flag off/on; offline adapter (mock/curated) |
| P4.0–P4.1 | TODO (nền P3.0b + P2.SR đã sẵn) | High | PDF → hybrid RAG → citations xác thực |
| P4.2–P4.3 | OPTIONAL | Medium | Chỉ khi có use case/test corpus |
| P5.0 | TODO sau RAG | Medium | Mastery/FSRS có data model và QA |
| P5.1–P5.2 | CONDITIONAL | Low | Phải hơn baseline trên held-out evaluation |
| P6 | TODO (hạng mục có thể làm song song sớm) | High trước public launch | Operational / privacy / security checks |
| P7 | FUTURE | Low | Chỉ làm khi có quyết định sản phẩm |

---

## 4. PHASE G0 — Audit, quality gate, migration consistency

**Mục tiêu:** Bắt đầu từ đúng mã đang chạy và khép lại rủi ro migration còn nghi vấn **mà không sửa lại migration 0001/0002 đã được deploy**.

**Modules/files:** `backend/alembic/versions/0001_initial.py`, `0002_auth_columns.py`, `backend/alembic/env.py`, `backend/app/models/models.py`, `docs/migration-runbook.md`, `docs/development-progress.md`, `backend/tests/`.

**Thứ tự thực hiện:**

- [ ] G0.1 Audit HEAD, git status, file tree, `AGENTS.md`, skills, dependencies và bản báo cáo mới nhất. Nếu HEAD > baseline, lập diff và cập nhật bảng trạng thái thực tế, **không làm lại task đã xong**.
- [ ] G0.2 Chạy baseline tests/build/smoke nếu môi trường có sẵn; ghi rõ mốc 40/40, 21/21 chỉ là lịch sử được báo cáo.
- [ ] G0.3 Trên **database tạm biệt lập**, kiểm tra `upgrade head → downgrade -1 → introspection schema → upgrade head`, so sánh cấu trúc mỗi revision với các file migration; kiểm tra chính xác số cột `email/password_hash` và unique constraint tương ứng.
- [ ] G0.4 Nếu revision semantics không nhất quán: tạo **đề xuất sửa forward-only** hoặc ghi rõ hạn chế downgrade trong runbook; **không sửa file revision đã áp dụng trên DB thật**, không auto downgrade database chính.
- [ ] G0.5 Đối chiếu `backend/app/services/course_service.py`, `lesson_service.py`, `worker/generation.py`, `providers/__init__.py` để ghi nhận chỗ cần P1.1/P1.2.
- [ ] G0.6 Cập nhật `docs/development-progress.md` phần evidence và technical debt; không ghi status TESTED cho thứ chưa chạy.

**Acceptance / Gate:** Có audit report HEAD, baseline logs (hoặc NOT TESTED), kết quả revision-level schema check trên DB test, không có tác động dữ liệu chính; các nguy cơ migration được phân loại BLOCKED/known limitation. Nếu có dữ liệu production, dừng trước bất kỳ thao tác rollback nào.

**Tests:** pytest, frontend build, Docker E2E nếu khả dụng; Alembic `current/history` và kiểm tra schema trên **temp DB**.  
**Không làm:** Refactor auth lớn, đổi tên revision, overwrite database, `stamp` mù quáng, đổi stack.

---

## 5. PHASE P1.1 — Quiz Integrity, Progress & Content Versioning

**Mục tiêu:** Sửa những sai lệch dữ liệu hiện tại; chuẩn bị đầu ra bài học cho LLM thật mà không để lộ đáp án trước khi nộp.

**Đề xuất chính sách:** lesson completed khi attempt có score ≥80% trên `contentVersion` hiện tại; XP không cộng lại vô hạn. Nếu người dùng chưa chốt, ghi đây là PROPOSAL trong contract và giữ option cấu hình.

**Modules/files:**

- Backend: `backend/app/api/v1/routes.py`, `backend/app/schemas/schemas.py`, `backend/app/services/course_service.py`, `lesson_service.py`, `grading_service.py`, `backend/app/models/models.py`.
- Frontend: `frontend/src/app/lesson/[lessonId]/page.tsx`, `frontend/src/app/course/[courseId]/page.tsx`, `frontend/src/lib/api.ts`.
- Tests: `backend/tests/test_grading.py`, `test_api_flow.py`, `backend/e2e_acceptance.py`, thêm file tests mới đúng domain.
- Migration: **revision mới** nếu cần answer key storage/progress indexes/XP unique events; không sửa `0001/0002`.

**Công việc chi tiết theo thứ tự:**

- [ ] P1.1.1 **Contract audit:** phân biệt `Lesson.content` lưu nội bộ, `LessonPublicOut.blocks` trả người học, `GradingKey` chỉ có server; version contract.
- [ ] P1.1.2 **Hide keys:** loại `answerIndex` (`mc`), `answer` (`blank`), `acceptedAnswers` (`short`) trước submission. Với `order` và `match`, **không dùng thứ tự mảng/cặp làm lời giải ẩn**; tạo public options được shuffle ổn định với attempt/seed không lộ answer mapping. UI phải tự cho người học sắp xếp/ghép cặp.
- [ ] P1.1.3 **Server grading:** answer key nằm ở DB server hoặc representation nội bộ; không nhận `correct`/answer key từ client; mapping câu hỏi bằng stable block ID hoặc version + index. Reject index ngoài bounds và duplicate answer index theo contract.
- [ ] P1.1.4 **Post-submit response:** trả score và feedback theo chính sách, không vô tình lộ đáp án của câu khác qua error. Bảo đảm mock E2E thay đổi sang fixture/answer key chỉ test backend biết, **không tự lấy đáp án từ public lesson** để tự động chứng minh 100%.
- [ ] P1.1.5 **Progress policy:** tính `completed/total/percent` từ attempts đã lưu, không nhầm `LessonStatus.ready` = học xong. Trả progress đúng qua `/v1/courses/{id}`; test nhiều bài, nộp đúng/sai, reload và cross-user.
- [ ] P1.1.6 **Idempotency + XP:** unique key `(user, lesson, clientAttemptId)` được DB đảm bảo; retry same ID trả same attempt/reward; xử lý double-submit/concurrency không nhân XP. Quy tắc earn XP lại sau lesson/version mới cần document + test.
- [ ] P1.1.7 **Version:** regeneration tăng `contentVersion` khi nội dung thực thay đổi; attempts cũ giữ làm lịch sử, không bị reset/xóa; stale submission → 409; progress hiện hành áp dụng đúng version policy.
- [ ] P1.1.8 **Approval state:** cập nhật `CourseProposal.approved_at` đúng lúc approve nếu chưa có; GET proposal `approved` phản ánh thực tế.
- [ ] P1.1.9 **Frontend:** quiz player dùng public blocks, disable double submit, idempotent `clientAttemptId` ổn định khi retry mạng cùng một lần nộp, update/invalidate progress và XP.
- [ ] P1.1.10 **Docs:** schema public/private, scoring & completion policy, migration/rollback, cập nhật acceptance script.

**Acceptance / Gate:**

1. GET lesson **không tiết lộ đáp án xác định** trước submission, kể cả order/match; test riêng cả 5 quiz blocks.
2. Client gửi `correct=true` giả hay thay index không làm thay điểm; server tự grade từ private key.
3. Sau một lesson đạt ngưỡng, course progress tăng và vẫn chính xác sau fresh GET/login; user khác không truy cập được.
4. 20 request lặp/đồng thời theo cùng id không nhân attempt/XP (test DB concurrency phù hợp PostgreSQL, không chỉ SQLite).
5. Regenerate/retry không phá attempts cũ; stale version → 409; proposal approved flag đúng.
6. Mock E2E full flow và `npm run build` không regression.

**Tests bắt buộc:** backend unit/integration; matrix quiz types; test public payload không có key; attempt race trên PostgreSQL; E2E login → course → lesson → quiz → progress/reload.  
**Không làm:** LLM grading tự luận, OCR/RAG, thay đổi UX không liên quan, xóa attempts cũ.

---

## 6. PHASE P1.2 — Reliable Generation Jobs & Safe Retries

**Mục tiêu:** Tạo đúng một kết quả cho mỗi job, hạn chế double charge khi LLM thật xuất hiện; khôi phục được khi broker/worker chết.

**Modules/files:** `backend/app/worker/generation.py`, `celery_app.py`, `backend/app/services/course_service.py`, `backend/app/models/models.py`, `backend/app/api/v1/routes.py`, `backend/tests/`, `docker-compose.yml`; migration bổ sung nếu lưu dispatch/outbox/lease.

**Công việc:**

- [ ] P1.2.1 Mô tả state machine course/job và chỉ ra transaction boundary approve → dispatch. Chốt statuses `queued/running/ready/failed` và transitions hợp lệ.
- [ ] P1.2.2 **Atomic claim** job trong PostgreSQL (`UPDATE ... WHERE status='queued' RETURNING ...` hoặc lock row phù hợp); redelivery/concurrent worker không chạy hai lần. Không dựa duy nhất vào cờ `_use_celery` hay khóa Redis không bền.
- [ ] P1.2.3 Xử lý **commit thành công nhưng `send_task` lỗi**: outbox/recovery dispatcher hoặc job reconciler có bằng chứng; không bỏ job vĩnh viễn ở `queued`.
- [ ] P1.2.4 Idempotent generation/upsert; job stale không ghi đè kết quả của job mới hơn; proposal version được snapshot/pin cho job trước khi sinh.
- [ ] P1.2.5 Timeout, cancellation, heartbeat/stale jobs, bounded retry/backoff; phân biệt lỗi tạm thời/lỗi schema/lỗi user. Mỗi retry có `attempts_count`, log không chứa prompt/secret.
- [ ] P1.2.6 Bảo toàn `contentVersion`/attempt policy từ P1.1; transaction/unique constraints xử lý race khi tạo unit/lesson.
- [ ] P1.2.7 Tách module provider call khỏi DB transaction dài; worker engine/session phù hợp Celery asyncpg event loop (đừng làm tái phát cross-loop bug).
- [ ] P1.2.8 Kịch bản fail injection: Redis unavailable, worker crash, duplicate delivery, task exception, LLM timeout mocked, retry same job/another job.
- [ ] P1.2.9 Frontend hiển thị progress có nguồn DB, thông báo lỗi dễ hiểu, thao tác retry không tự spam.

**Acceptance / Gate:** concurrent duplicate claim không tạo hai dòng lesson/job hoặc gọi provider hai lần cho một job; có recoverable pending dispatch; retry không phá bài đã hoàn thành; lỗi được hiển thị và trace được bằng request/job ID.  
**Tests:** DB PostgreSQL concurrency + Celery Docker full stack; crash/restart simulation trên test stack; unit mocks dispatch/provider.  
**Không làm:** Đổi Redis/Celery sang stack khác, đưa Kafka vào MVP, chạy thao tác phá dữ liệu live.

---

## 7. PHASE P1.3 — Frontend UX, Navigation & Session Isolation

**Mục tiêu:** Biến vertical slice đang chạy thành trải nghiệm học trọn vẹn và bền với reload, switching account, lỗi mạng.

**Modules/files:** `frontend/src/app/**`, `frontend/src/lib/api.ts`, `frontend/src/app/providers.tsx`, các hooks/components mới theo convention repo; backend list endpoints nếu thiếu; tests frontend/E2E.

**Công việc:**

- [ ] P1.3.1 Sau login/register/logout: invalidate/clear TanStack Query cache; không hiển thị course/XP/user A khi user B đăng nhập trên cùng browser.
- [ ] P1.3.2 Route guard UX `/new`, `/course/[id]`, `/lesson/[id]` cho session hết hạn; quyền sở hữu vẫn enforce ở backend.
- [ ] P1.3.3 Dashboard “Khóa học của tôi”: paginated list scoped theo user; trạng thái, tiến độ, bài đang học, resume link. Nếu thêm API, version và test ownership.
- [ ] P1.3.4 Interview reload đúng vị trí, không dùng placeholder trống khiến câu trước bị xem như đã trả lời mà không có dữ liệu; thiết kế masked/readonly nếu nhạy cảm.
- [ ] P1.3.5 Proposal UI có loading/error/approved rõ ràng; **chỉnh sửa proposal** chỉ bổ sung nếu contract/versioning được duyệt, không tự thay API thầm lặng.
- [ ] P1.3.6 Loading/empty/error/retry/failed state trên mọi route; stop polling ở terminal states; accessibility keyboard và label/form validation.
- [ ] P1.3.7 Client submit quiz ổn định idempotency key khi retry; cache invalidation cập nhật progress/XP.
- [ ] P1.3.8 Smoke test đa user, reload, expired cookie, CSRF 403, API 5xx/timeout; đo lỗi UX phát hiện và sửa.

**Acceptance / Gate:** A→logout→B không lộ cached data; course list chỉ của B; refresh giữ vị trí & tiến độ; `npm run build` pass; E2E mock user journey pass.  
**Không làm:** UI clone PolySkill, native app, gamification nâng cao, billing.

---

## 8. PHASE P2.0 — Real LLM Adapter Infrastructure (Provider-Neutral)

**Mục tiêu:** Sẵn sàng kết nối **Transformer LLM pretrained** nhưng không khóa nhà cung cấp; giữ MockProvider cho offline tests.

**Modules/files:** `backend/app/providers/base.py`, `mock_provider.py`, `providers/__init__.py`, các adapter mới (ví dụ `openai_compatible_provider.py` nếu được duyệt), `backend/app/core/config.py`, `backend/app/schemas/`, worker, tests, `.env.example`, docs.

**Công việc:**

- [ ] P2.0.1 Audit contract `LLMProvider`: interview questions, proposal, lesson; xác định structured response schema, error taxonomy, timeout, cancellation.
- [ ] P2.0.2 **Fail-fast:** config provider lạ → error rõ (`PROVIDER_NOT_CONFIGURED`), **không fallback về MockProvider**. Giữ `mock` làm default chỉ khi cấu hình là `mock`.
- [ ] P2.0.3 Viết một adapter theo lựa chọn người dùng, dùng server-only key, model/base URL qua env; **không đồng nhất provider của OpenCode với provider của sản phẩm**.
- [ ] P2.0.4 Validate Pydantic/discriminated union và semantic rules: đúng 5 câu interview; units/lessons trong giới hạn; `MC.answerIndex < len(options)`; unique options; no empty teach; đáp án phù hợp nội dung.
- [ ] P2.0.5 API call timeout, retry có backoff/jitter, circuit breaker/429 handling theo provider, budget per-request, no unbounded loops; phân biệt recoverable/fatal.
- [ ] P2.0.6 Log metadata `provider/model/prompt_version/tokens/latency/cost_estimate/job_id` nhưng **không log API key, raw user profile hay nội dung nhạy cảm**.
- [ ] P2.0.7 Mocked HTTP integration tests: valid output, malformed JSON, schema invalid, 429, 5xx, timeout, cancel, budget exceeded, wrong provider config.
- [ ] P2.0.8 Viết hướng dẫn bật/tắt real provider, rollback sang `mock`, phân biệt rõ nội dung mock với AI thật ở UI/log.

**Gate về quyền/chi phí:** Nếu **chưa được chọn provider/model/API key/budget**, **chỉ hoàn thành infrastructure + mocked tests** và đánh dấu **BLOCKED real-provider E2E**. Không dùng tài khoản/API trả phí của người dùng khi chưa cho phép.

**Acceptance / Gate:** adapter không lộ key; provider lạ fail-fast; schema invalid fail có lỗi hữu ích; offline suite pass; real request chỉ PASS khi có log đã redacted + output thực.  
**Không làm:** Huấn luyện Transformer từ đầu, fine-tune, RAG, OCR, giả mạo kết quả LLM.

---

## 9. PHASE P2.1 — AI Course Generator + Pedagogy DAG

**Mục tiêu:** Sinh course từ interview bằng LLM thật, có khả năng kiểm soát cấu trúc và giá trị học tập.

**Modules/files:** `backend/app/services/course_service.py`, `providers/`, `worker/generation.py`, `schemas/`, mới `services/curriculum_service.py`/`pedagogy/` nếu cần, frontend proposal screens, eval fixtures.

**Công việc:**

- [ ] P2.1.1 **Interview:** prompt/version 5 câu bám topic, mục tiêu, trình độ, thời lượng; có test minh chứng 5 câu đúng schema. Có thể dùng baseline cố định nếu LLM lỗi, nhưng **phải ghi rõ fallback mode**, không trình bày là LLM thành công.
- [ ] P2.1.2 **Learner profile:** trích mục tiêu/level/time/preferences từ 5 answers với schema riêng, check inconsistency; không suy diễn thuộc tính nhạy cảm.
- [ ] P2.1.3 **Curriculum:** tạo outcomes theo Bloom (khung pedagogy, không phải thuật toán ML) và prerequisite skill nodes/edges; xác thực DAG không chu trình bằng topological sort.
- [ ] P2.1.4 **Structured proposal:** LLM output `ProposalPayload` đã validate + semantic lint: đơn vị/bài có thứ tự, không lặp vô nghĩa, đủ mục tiêu, tổng lessons trong budget. UI review trước approve.
- [ ] P2.1.5 **Hierarchical generation:** job snapshot profile/proposal→ unit→lesson→typed blocks; chỉ truyền ngữ cảnh cần thiết; tránh hallucination/đáp án mâu thuẫn, kiểm tra pedagogical coherence.
- [ ] P2.1.6 **Quiz answer keys:** phải tuân thủ private/public contract của P1.1; LLM tạo đáp án nhưng server validate và không phát tán keys; chấm bài đóng vẫn deterministic.
- [ ] P2.1.7 **Retry/job cost:** tận dụng P1.2; khi lỗi từng lesson không nhân đôi provider request vô hạn; partial failure rõ status và rollback/continuation policy.
- [ ] P2.1.8 **Real AI e2e** trên sandbox tài khoản đã được phép: 1–2 topic mẫu, API request có usage thực, lesson có teach+quiz đúng contract; đo chi phí/latency; không log raw secrets.

**Acceptance / Gate:** ít nhất 10 topic eval (unit/offline + subset real được phép); proposal đúng schema & prerequisites DAG acyclic; bài học không rỗng/không trùng cực đoan; course ready nếu job hoàn thành; mock suite vẫn pass; real test có bằng chứng hoặc được ghi BLOCKED rõ ràng.  
**Không làm:** Tuyên bố bài học luôn chính xác, web retrieval trá hình, dùng endpoint PolySkill, train/fine-tune.

---

## 10. PHASE P2.2 — AI Evaluation, Safety, Quality & Cost Control

**Mục tiêu:** Chuyển từ “LLM trả JSON hợp lệ” sang “nội dung phù hợp người học, có tiêu chí đánh giá và ngân sách”.

**Modules/files:** tests/evals mới (`backend/evals/`, `backend/tests/`), provider adapter, job metadata, docs metrics.

**Công việc:**

- [ ] P2.2.1 Tạo eval dataset **tối thiểu 10 topic** (kỹ thuật, xã hội, tiếng Việt/tiếng Anh, beginner/advanced, ambiguous topic), không chứa tài liệu riêng chưa được phép.
- [ ] P2.2.2 Rubric kiểm tra: mục tiêu rõ, đúng mức học viên, cấu trúc có logic, ví dụ đúng, quiz bám lesson, tính nhất quán đáp án, lặp nội dung, ngôn ngữ, toxicity.
- [ ] P2.2.3 Tách metrics: **deterministic** (schema/duplicate/keys/DAG), **human or reviewed rubric** (pedagogy/factual accuracy), **LLM-as-judge** nếu sử dụng phải lưu metadata và sample kiểm tra, không coi là ground truth.
- [ ] P2.2.4 Quan sát token/latency/cost per job và per model; guard ngân sách/giới hạn bài; không giữ prompt cá nhân trong logs public.
- [ ] P2.2.5 Thiết lập regression evaluation giữa mock/real provider và giữa prompt versions; fail khi thụt lùi nghiêm trọng.
- [ ] P2.2.6 Report số lượng eval, lỗi, baseline, mục tiêu và chi phí; ngưỡng go/no-go là **PROPOSAL** cần hiệu chỉnh theo kết quả đo thật.

**Acceptance / Gate:** có báo cáo eval tái lập, không claim “AI chính xác” chỉ từ JSON; schema/ownership/budget tests pass; biết tỷ lệ lỗi + chi phí thực hoặc BLOCKED khi chưa có API.  
**Không làm:** Benchmark giả, rating sao không có nguồn, full production analytics.

---

## 11. PHASE P3.0 — AI Tutor Core (SSE + Lesson Grounding)

**Mục tiêu:** Người học hỏi AI trong đúng bài đang học, câu trả lời được stream và lưu theo thread.

**Modules/files:** backend `api/v1/tutor.py`, `services/tutor_service.py`, `models/models.py`, `schemas/`, `providers/` stream interface, Alembic revision mới; frontend lesson UI/tutor components/hook; tests.

**Contract đề xuất (API riêng của SopiSkill, không sao chép một sản phẩm khác):**

```text
POST /v1/courses/{courseId}/tutor/messages
  body: { clientMessageId, threadId?, text, contextRef:{lessonId, blockIndex} }
  accept: text/event-stream
  events: delta | done | error  (mở rộng tool/confirm ở P3.1)
GET  /v1/courses/{courseId}/tutor/threads/{threadId}
POST /v1/courses/{courseId}/tutor/messages/{messageId}/stop  (P3.1)
```

**Công việc:**

- [x] P3.0.1 DB: `tutor_threads`, `tutor_messages`, user/course owner, message state, clientMessageId unique, timestamps; migration backward compatible. — `0008_p30_tutor_core`, expand-only, rollback + legacy-row đã kiểm chứng.
- [x] P3.0.2 Server resolve course + lesson **cùng owner**; blockIndex in bounds; không tin nội dung `lesson`/`contextRef` tự cung cấp để bypass DB.
- [x] P3.0.3 Tutor prompt với lesson + selected block + conversation history bounded; có guidance khi không đủ context, không bịa citation. (chỉ public blocks — không answer key)
- [x] P3.0.4 SSE response heartbeat/`delta/done/error`, buffering/broken connection và persisted final message; chọn event IDs/ordering rõ ràng. (`id = streamId:seq`, seq đơn điệu từ 0)
- [x] P3.0.5 Idempotency: double-click/reconnect cùng `clientMessageId` không tạo hai user messages hoặc double billing; xác định replay behavior. (đã xong ⇒ replay; đang chạy ⇒ 409)
- [x] P3.0.6 UI: tutor panel trong lesson, loading/stream/stop state, auto scroll có accessibility, error/retry; CSRF + cookie đúng contract.
- [x] P3.0.7 Test output giữa 2 user, invalid block, expired session, malformed stream, disconnect; mock streaming provider cố định, không cần tiền.

**Acceptance / Gate:** stream 1 câu trả lời hoàn chỉnh trong đúng lesson, history sau reload có data đúng, 404 cross-owner, blocked unauthorized context, no duplicate messages, test real streaming chỉ khi provider được phép.  
**Không làm:** Tutor tool có quyền ghi/cập nhật course chưa được duyệt, RAG citation chưa có source.

---

## 12. PHASE P3.1 — Tutor Tools, Allowance, Cancel & Replay

**Mục tiêu:** Biến tutor thành trợ giảng có kiểm soát thay vì agent tự do.

**Modules/files:** `services/tutor_tools.py`, `tutor_service.py`, `api/v1/tutor.py`, `core/limits.py`, provider stream, frontend; models/migrations khi cần.

**Công việc:**

- [ ] P3.1.1 Tool allowlist **read-only** lúc đầu: `read_lesson`, `explain_deeper`; validate JSON arguments và authorization trước mỗi tool call.
- [ ] P3.1.2 Tool max-iterations/time budget, audit `tool_calls` (name, safe summary, ok, duration); model không được gọi tool ngoài allowlist.
- [ ] P3.1.3 `read_source` **chỉ bật sau P4.1** khi source/chunk ownership & provenance hoạt động; không có source thì từ chối hữu ích.
- [ ] P3.1.4 Cancel/stop: server cancellation flag và provider request timeout; không cam kết xóa chi phí đã phát sinh; test stop giữa stream.
- [ ] P3.1.5 SSE replay/resume: **chọn và document** semantics (`Last-Event-ID` với persisted event log hoặc explicit restart). Không tuyên bố hỗ trợ resume nếu chưa lưu event IDs replayable.
- [ ] P3.1.6 Usage allowance: giới hạn lượt/tokens theo user, lưu bền vững; trả quota state/error có cấu trúc; rate limit distributed đưa vào P6 nếu dùng nhiều instances.
- [ ] P3.1.7 Safety: prompt injection qua user text/tool output, runaway loops, data exfiltration, concurrent requests, redacted logs.
- [ ] P3.1.8 UI “giải thích sâu hơn” hoặc gợi mở từ block đang học; không cần sao chép interaction/design từ PolySkill.

**Acceptance / Gate:** 0 cross-user leakage trong negative test; tool gọi đúng allowlist; cancel behavior trung thực; quota vượt trả response rõ và không gọi provider; no duplicate messages on retry.  
**Không làm:** Tool cho model tùy ý thực thi code, truy cập web nội bộ hay cập nhật lesson không có xác nhận người dùng.

---

## 12.1 PHASE P3.0b — Source Registry & Evidence Contract (đã làm trước P4)

> Thực hiện trước P4 để có nền truy vết nguồn, không phải RAG.

- [x] `sources` / `course_sources` / `lesson_citations` + `lessons.grounding` (migration
      `0005_p30_source_registry`, expand-only, rollback đã kiểm chứng).
- [x] Ownership server-side: public hoặc owner; cross-user ⇒ 404.
- [x] Dedupe `sources(dedupe_key)` + `course_sources(course_id, source_id)` — chống duplicate
      (đã test race trên PostgreSQL thật).
- [x] Evaluator deterministic metadata-only; thiếu dữ liệu ⇒ `unknown`, loại khỏi mẫu số.
- [x] Evidence contract 4 cấp; P3.0 **không thể** tạo `evidence_supported`.
- [x] Discovery adapter `curated`/`mock` (không network); `web` ⇒ 503.
- [x] Tích hợp generation: source resolution → prompt metadata → ghi grounding + citation.
- [x] Frontend: danh sách nguồn ở course, citation + notice chưa xác minh ở lesson.
- [ ] UI tạo nguồn / discover / review trạng thái (chỉ API; ghi nhận là việc còn lại).

Chi tiết + checklist chuyển P4: `docs/source-first-architecture.md`.

## 12.2 PHASE P2.SR — Source Research Agent Foundation

**Mục tiêu:** Agent nghiên cứu nguồn độc lập, testable offline, sẵn sàng nối P4.
**Không phải RAG.** Không crawl internet, không ingest nội dung, không citation thật.

- [x] Package `app/agents/source_research/`: agent + schemas + policies + ranking + tools + adapters.
- [x] Topic analysis deterministic (domain, chủ đề con, tiên quyết, level, language, queries).
- [x] `SourceDiscoveryAdapter` protocol + bridge tới adapter P3.0 (`curated`/`mock`); `web` từ chối.
- [x] Mock discovery deterministic, không network (test chặn socket).
- [x] Policy riêng theo domain (programming/medicine/general) thay vì một trust score.
- [x] Dedupe canonical URL; max sources; bounded tool calls + timeout; structured error codes.
- [x] Chỉ kết luận `discovered`/`metadata_verified`; validator từ chối `content_available`/`evidence_verified`.
- [x] `source_research_runs` (migration `0006_p2sr_source_research`) với UNIQUE(course_id, fingerprint).
- [x] API `/v1/courses/{id}/research-runs` (create/list/get/accept) + CSRF + rate limit + ownership 404.
- [x] Feature flag `SOURCE_RESEARCH_ENABLED` (default false) ⇒ flow cũ không đổi; `AUTO_LINK` default false.
- [x] Worker hook `maybe_auto_link_for_generation`: lỗi research không làm job failed; mock không auto-link.
- [ ] UI research run + review/accept nguồn (API sẵn sàng).
- [ ] Adapter nguồn thật (Crossref/OpenAlex/arXiv/web) — cần allowlist + SSRF guard (P4.2).

Chi tiết: `docs/source-research-agent.md`.

## 13. PHASE P4.0 — PDF Text Ingestion & Source Provenance

**Mục tiêu:** Cho người học tải **PDF do họ có quyền sử dụng** và tạo nguồn tri thức có thể kiểm chứng.

**Modules/files:** `api/v1/sources.py`, `services/ingest_service.py`, `services/storage.py`, `worker/ingest.py`, `models/models.py`, Alembic revision mới, `core/config.py`, Docker object storage adapter nếu cần, frontend upload/source status, tests.

**Công việc:**

- [ ] P4.0.1 Source ownership: `sources` (owner, course relation nếu có, mime, original name safe, checksum, status), `source_pages`/`source_chunks` (page, offsets, text hash, provenance). Xóa theo quyền sở hữu; cascade rõ.
- [ ] P4.0.2 Upload PDF qua streaming giới hạn size/type; xác minh MIME magic, page count, malware/sandbox limits, không tin extension. Đặt hard limits cấu hình rõ và có test.
- [ ] P4.0.3 Storage adapter server-side, path non-public, random object keys, no direct arbitrary local path; signed retrieval chỉ sau auth.
- [ ] P4.0.4 Async extract **PDF text trước**; giữ page numbers, heading/span/anchors. Với PDF scan chưa OCR ở phase này, báo `NO_EXTRACTABLE_TEXT`/status thích hợp.
- [ ] P4.0.5 Chunking có page provenance, heading, source/version checksum; tránh overlap gây trích dẫn mơ hồ; log không chứa raw tài liệu cá nhân.
- [ ] P4.0.6 Worker idempotent per `source_id + content_hash + pipeline_version`; retry không tạo trùng chunks, trạng thái extracting/ready/failed bền vững.
- [ ] P4.0.7 Lọc/đánh dấu untrusted source text; document prompt-injection boundaries; không cho parser chạy process nguy hiểm.
- [ ] P4.0.8 Frontend: upload, progress, source list, error, file validation; owner A/B isolation.

**Acceptance / Gate:** PDF text fixture có page/chunk đúng nguồn, PDF rỗng/scan/oversize/corrupt bị xử lý an toàn; 2 user không đọc được source nhau; reload tồn tại; không gọi RAG nếu ingest chưa ready.  
**Không làm:** Tự crawl website, tự OCR mọi PDF, dùng Google Drive/files người dùng không được cho phép, giả citation.

---

## 14. PHASE P4.1 — Hybrid RAG + Embeddings + Verified Citations

**Mục tiêu:** Từ các chunks đã ingest, AI Tutor trả lời có căn cứ và citation đúng nguồn.

**Thuật toán chọn:** lexical retrieval (PostgreSQL Full Text Search baseline; **không gọi nó là BM25 mặc định**) + vector embedding Transformer đa ngôn ngữ (cosine / pgvector exact search baseline) → Reciprocal Rank Fusion (RRF) → [optional reranker khi benchmark có lợi] → answer synthesis.

**Modules/files:** `services/embedding_service.py`, `services/retrieval_service.py`, `services/citation_service.py`, `api/v1/search.py` nếu cần, models/migrations `source_chunks.embedding`, worker embed jobs, Tutor tool `read_source`, frontend citations UI, eval fixtures.

**Công việc:**

- [ ] P4.1.1 **Embedding model/provider selection gate:** benchmark tiếng Việt/Anh trên 30+ query/answer examples; model, dimension, privacy, cost **chưa chốt** — lưu cấu hình model + dimension + version để tránh trộn vectors.
- [ ] P4.1.2 Migrations pgvector + indexes phù hợp **dimension của model đã chọn**, dữ liệu cũ không mất; exact vector search trước, HNSW **chỉ nếu đo được scale/latency**.
- [ ] P4.1.3 Lexical retrieval có metadata filters bắt buộc `owner_id`, `source_id/course_id`; xử lý tiếng Việt rõ giới hạn tokenizer; không trộn chunk của người khác.
- [ ] P4.1.4 Vector retrieval có cùng ownership filter, no cross-tenant rows; RRF hợp nhất thứ hạng; giới hạn top-k, chunk/token budget.
- [ ] P4.1.5 Context assembly mang `sourceId/chunkId/page/offset/contentHash` và untrusted delimiter; chống prompt injection trong source.
- [ ] P4.1.6 Citation validator phía server: LLM chỉ được chọn từ IDs được retrieval trả về; kiểm tra source tồn tại, owner hợp lệ, page/chunk/anchor hợp lệ. Không bịa URL, số trang hoặc nội dung trích dẫn.
- [ ] P4.1.7 Nếu không có đủ evidence: model trả **“chưa đủ thông tin từ tài liệu”**, không bịa câu trả lời tự tin. Câu hỏi ngoài nguồn phải minh bạch.
- [ ] P4.1.8 Integrate vào tutor dưới feature flag `RAG_ENABLED`, `read_source` mở khi source ready, citations UI mở đúng PDF/page.
- [ ] P4.1.9 Evals: retrieval Recall@k, MRR (nếu có qrels), citation precision/coverage, answer groundedness, cost/latency; có ít nhất test negative no-source, conflicting chunks, injected chunks.

**Acceptance / Gate:** Bộ PDF test sở hữu hợp pháp, tối thiểu 30 queries có ground truth page/chunk; **100% citation hiển thị phải resolve được chunk nguồn có quyền**; đo recall/groundedness, không khẳng định chất lượng cao khi chưa đo.  
**Không làm:** Claim vector search của PolySkill, giả citations, truy cập nguồn người khác, dùng reranker/HNSW không benchmark.

---

## 15. PHASE P4.2 — Web/arXiv Sources [OPTIONAL]

**Điều kiện khởi động:** PDF text + retrieval/citations đã hoạt động; người dùng muốn học từ URL/arXiv và đồng ý chính sách ingest.

**Modules:** `services/url_fetcher.py`, `services/arxiv_service.py`, ingest worker, schemas, tests.

- [ ] P4.2.1 HTTPS URL allowlist hoặc policy outbound rõ; chặn SSRF (localhost, private/link-local/metadata IP, DNS rebinding, redirects, port bất thường).
- [ ] P4.2.2 Download giới hạn size/time/redirect, MIME, robots/licensing & rights; không vượt paywall, auth, website access controls.
- [ ] P4.2.3 arXiv định danh hợp lệ, metadata/version/page provenance khi xuất PDF/HTML; cache hợp lệ.
- [ ] P4.2.4 HTML sanitation, text extraction, anchor provenance, chunk/embedding đồng bộ với P4.1.
- [ ] P4.2.5 Tests redirect SSRF, DNS rebind mock, unknown MIME, 404/429, hostile HTML, link citations.

**Gate:** không thể fetch IP nội bộ qua redirects/DNS; citation trỏ nguồn thực; source không có quyền truy cập được từ chối.  
**Không làm:** Scrape trái phép, bypass robots/captcha/paywall, thu thập dữ liệu cá nhân hàng loạt.

---

## 16. PHASE P4.3 — Scanned PDF OCR (CNN/ViT) [CONDITIONAL]

**Điều kiện khởi động:** Có corpus PDF scan thật, text extraction không đủ và chi phí OCR chấp nhận được.

- [ ] P4.3.1 So sánh OCR pretrained CNN-based/ViT-based + layout-aware parser trên sample PDF scan có phép; không train mô hình từ đầu.
- [ ] P4.3.2 Phân biệt text OCR và text native, giữ page bbox/confidence, bảng/công thức theo bản nguồn.
- [ ] P4.3.3 Đánh giá CER/WER, bảng/công thức, page provenance, latency/cost; công bố limitation.
- [ ] P4.3.4 Chỉ bật OCR nếu chất lượng vượt text-only baseline trên corpus; có fallback rõ.

**Gate:** OCR không làm citation sai trang; metric được ghi lại.  
**Không làm:** Bật OCR cho mọi file khi chưa có nhu cầu, giới thiệu CNN như thành phần đã có trong MVP.

---

## 17. PHASE P5.0 — Learner Profile, Mastery Baseline & FSRS

**Mục tiêu:** Cá nhân hóa dựa trên **lịch sử học thực**, không chỉ 5 câu interview.

**Modules:** `models` (skills, lesson-skill links, review events), `services/progress_service.py`, `services/recommendation_service.py`, FSRS scheduler adapter, frontend profile/review queue.

- [ ] P5.0.1 Gắn stable skill IDs, prerequisite graph, learning objectives cho lesson; migration mới, backfill có chiến lược không giả dữ liệu.
- [ ] P5.0.2 Mastery baseline **rule-based** từ các attempts tagged theo skill, difficulty/time; không gọi thang điểm heuristic là xác suất ML hiệu chuẩn.
- [ ] P5.0.3 Next lesson policy: chỉ đề xuất bài mà prerequisites đã đạt; không vượt quyền/course entitlement.
- [ ] P5.0.4 FSRS spaced repetition dựa trên review event có rating/response; lưu schedule, due dates theo timezone được chọn; thuật toán/library versioned để tái lập.
- [ ] P5.0.5 UI “học tiếp/ôn tập”, mô tả vì sao được đề xuất, cho user bỏ qua hoặc điều chỉnh.
- [ ] P5.0.6 Tests deterministic progression, timezone, missed reviews, content version update, missing skill tags, cross-user data.

**Gate:** mọi gợi ý có lý do có thể kiểm tra; dữ liệu progress không xung đột P1.1; không có dự đoán bí ẩn thiếu dataset.  
**Không làm:** Tự tuyên bố có RL/Deep Learning adaptive khi chỉ dùng rules.

---

## 18. PHASE P5.1/P5.2 — Advanced Adaptive AI [CONDITIONAL]

### P5.1 — Bayesian Knowledge Tracing (BKT)

- [ ] Chuẩn bị dataset chuỗi attempt theo `(user, skill, timestamp, correct)` có đủ độ dài, split train/test theo user/time tránh leakage.
- [ ] So sánh BKT với heuristic baseline, kiểm tra calibration, Brier/log loss, drift, fairness; không deploy nếu không vượt baseline đáng kể.
- [ ] Khi deploy, feature flag và shadow evaluation trước; có rollback và fallback rule-based.

### P5.2 — LSTM/DKT và Contextual Bandit (chỉ nghiên cứu)

- [ ] LSTM/DKT chỉ khi dataset tuần tự đủ lớn và BKT không đạt mục tiêu; không huấn luyện mô hình đắt đỏ vì trào lưu.
- [ ] Contextual bandit cho gợi ý độ khó/hoạt động nếu có reward rõ ràng và logging policy đúng; đánh giá offline, tránh gây hại cho người học bằng thí nghiệm không kiểm soát.
- [ ] K-Means/Random Forest/XGBoost chỉ mở backlog khi có câu hỏi nghiệp vụ cụ thể, nhãn/dữ liệu và tiêu chí hơn baseline.

**Gate chung:** quality gains có số liệu held-out, privacy review, rollback; nếu chưa đủ dữ liệu → `NOT STARTED`, **không cố triển khai**.  
**Không làm:** Full RL tự động trên người học, dùng dữ liệu cá nhân không có quyền/chính sách.

---

## 19. PHASE P6 — Production Hardening, QA, CI/CD & Operations

**Mục tiêu:** Đạt điều kiện release an toàn; có thể bắt đầu các việc độc lập như CI/checks sớm hơn, nhưng **chỉ đóng gate trước khi public**.

**Modules:** `.github/workflows/`, Dockerfiles, Compose/prod config, migration/runbooks, `core/config.py`, `core/limits.py`, security headers, logging, monitoring, tests.

- [ ] P6.1 CI pipeline: Python tests, frontend build/lint/typecheck, migration upgrade on empty PostgreSQL, static security scanning & dependency checks (có baseline, avoid noisy auto-fix).
- [ ] P6.2 API security review: JWT/cookie/CSRF/issuer/audience/secret rotation, login abuse limits, scope checks, uploads/SSRF, redacted logs, session cache isolation.
- [ ] P6.3 HTTPS/TLS, `COOKIE_SECURE=true`, trusted proxy, CSP, HSTS/cookie domain policy phù hợp deployment, CORS chính xác. Không bật `SameSite=None` bừa bãi.
- [ ] P6.4 Redis distributed rate limiting và quotas nếu nhiều replicas; network/proxy IP trust; không coi in-memory limiter là production protection.
- [ ] P6.5 Database backup **và restore test** trên môi trường test; migration forward compatibility, no destructive auto-upgrade, outbox worker recovery, job queue monitoring.
- [ ] P6.6 Observability: trace/request/job IDs, metrics latency/error/cost, alerts lỗi Celery/LLM, không log raw prompts/PII/keys.
- [ ] P6.7 Privacy & retention: user/source delete, data export, secret scanning, provenance, permission audits, policy third-party AI data transfer.
- [ ] P6.8 Accessibility/i18n UX, end-to-end test trên browser thật (Playwright nếu chọn), Windows Docker runbook, staging smoke/load tests.
- [ ] P6.9 Release checklist: staging deploy, security findings triage, performance budgets, rollback plan, owner approval; production deploy là **manual gate**.

**Acceptance / Gate:** CI green có logs, backup restore drill thành công, HTTPS/cookie secure kiểm chứng, test authorization/CSRF/RAG SSRF, migration và worker recovery; không lộ secret; người dùng phê duyệt launch.  
**Không làm:** Public launch, domain changes, data migration live hoặc tự xoay JWT secret khi chưa phê duyệt.

---

## 20. PHASE P7 — Gamification, Analytics & Billing [FUTURE]

**Chỉ triển khai sau khi MVP có dữ liệu sử dụng thực và người dùng chọn tính năng:**

- **P7.1 Gamification:** XP economy, streak, hearts/goal/levels/leaderboard tùy chọn; chống farm, quyền riêng tư và accessibility.
- **P7.2 Product analytics:** funnels course create→finish, quiz quality, Tutor usefulness, RAG source coverage; aggregate/minimize PII.
- **P7.3 Billing/subscriptions:** payment provider riêng, webhook signature, idempotency, entitlement, refunds, audit log; yêu cầu phê duyệt pháp lý/vận hành, không làm ngầm.
- **P7.4 Mobile/i18n enhancements:** chỉ khi nhu cầu/độ ưu tiên được xác nhận; không thay kiến trúc Next.js vì bắt chước ứng dụng khác.

**Gate:** có PRD/metrics/cost/risk/owner approval riêng cho từng nhóm.  
**Không làm:** Monetization hoặc khai thác dữ liệu người học khi chưa được chấp thuận.

---

## 21. Ma trận test xuyên phase (tối thiểu)

| Test scenario | P1.1 | P1.2 | P2 | P3 | P4 | P5/P6 |
|---|---:|---:|---:|---:|---:|---:|
| Register/login/logout + cookie/CSRF/ownership | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Topic→5 interview→proposal→approve→lessons→quiz | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| No answer key leak before submit | ✓ | ✓ | ✓ | — | — | ✓ |
| Attempts/XP/progress persist after reload | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| ContentVersion stale/regen + historical attempts | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Generation duplicate request/worker race | — | ✓ | ✓ | — | — | ✓ |
| Provider fail/timeout/schema invalid/cost gate | — | ✓ mock | ✓ | ✓ | ✓ | ✓ |
| SSE context ownership/reconnect/stop | — | — | — | ✓ | ✓ | ✓ |
| PDF security/SSRF/citation page & chunk | — | — | — | — | ✓ | ✓ |
| User A/B data isolation | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Migration upgrade & rollback on temporary DB | ✓ nếu đổi DB | ✓ nếu đổi DB | ✓ nếu đổi DB | ✓ | ✓ | ✓ |
| Real provider cost/quality eval | — | — | ✓ khi có permission | ✓ khi có permission | ✓ khi có permission | ✓ |

**Điều kiện chung:** “✓” là **test bắt buộc ở phase đó**, không phải bằng chứng test đã được chạy. Tạo test fixture phù hợp; tránh E2E test chỉ biết đáp án vì GET lesson vô tình tiết lộ answer key.

---

## 22. Quy chuẩn migration, compatibility & rollback

1. **Tuyệt đối không sửa nội dung migration 0001/0002 đã triển khai**; migration mới có revision riêng và dependency rõ.
2. Chọn cách **expand → backfill → switch → contract** khi tách dữ liệu (ví dụ quiz public/private). Không drop cột cũ khi client/worker cũ còn phụ thuộc.
3. Tạo backup DB và kiểm chứng restore trên test DB trước migration rủi ro; không đụng volume `pgdata`/volume hiện tại mà không cần thiết.
4. `alembic upgrade head` trên database tạm; kiểm tra `downgrade -1` + schema, unique keys và indexes; nếu downgrade nguy hiểm thì **ghi rõ chỉ hỗ trợ restore từ backup**, không fake “reversible”.
5. Race/idempotency phải được test trên PostgreSQL; SQLite in-memory chỉ đủ cho logic test cơ bản.
6. Khi chuyển schema lesson public/private, giữ API backward compatible hoặc version endpoint; test UI cũ trong thời gian migration.
7. Nếu có provider/RAG index dimension thay đổi, version embedding, backfill/re-embed có migration plan; không âm thầm phá embeddings cũ.
8. Frontend/Backend contract thay đổi phải cập nhật OpenAPI/examples, Pydantic schemas, TS types và E2E cùng phase.

---

## 23. Template phase report mà Agent **bắt buộc xuất**

Agent lưu nhật ký vào `docs/development-progress.md` theo format sau sau **mỗi phase**:

```markdown
## YYYY-MM-DD — <PHASE_ID> <TÊN>
- Base commit: <sha>
- New commit/branch: <sha/branch hoặc NOT COMMITTED>
- Scope & decisions: ...
- IMPLEMENTED: [file/module, thay đổi]
- TESTED: [command, output, số test, môi trường, log path/link nếu có]
- NOT TESTED: [điều chưa chạy, lý do]
- BLOCKED: [vướng mắc, action cần từ người dùng]
- Database: [migration rev, backup/checksum/rollback hoặc N/A]
- Security: [auth/owner/CSRF/secrets/idempotency review]
- Regressions: [cũ/mới, kết quả]
- Known limitations: ...
- PHASE GATE: PASS / PARTIAL / BLOCKED
- NEXT: <phase/task kế tiếp>
```

**Định nghĩa trạng thái:**

- `IMPLEMENTED`: file code có thật ở HEAD/working tree, không đồng nghĩa chạy được.
- `TESTED`: lệnh thực sự được thực thi trong phiên làm việc liên quan, output/exit code có thật; tests pass không chứng minh hết bug.
- `NOT TESTED`: chưa chạy, chưa có môi trường, hoặc chỉ review tĩnh.
- `BLOCKED`: điều kiện tiên quyết thiếu; dừng tính năng phụ thuộc và ghi yêu cầu giải quyết.

---

## 24. Danh sách kiểm tra của người review trước mỗi PR/merge

- [ ] File thay đổi đúng phạm vi phase; code không clone/copy từ PolySkill.
- [ ] Lưu được baseline git SHA, tests logs và diff; không có thay đổi không liên quan.
- [ ] API contract backward compatible hoặc có migration path được duyệt.
- [ ] Ownership, authorization và rate limit không bị vô hiệu hóa; tránh demo auth trên môi trường khác local.
- [ ] Không lộ `JWT_SECRET`, LLM key, raw source PDF, answer key, cookie, token trong repo/response/log.
- [ ] Không có insecure fallback: unknown provider ≠ mock success; missing citation ≠ fake citation.
- [ ] Worker retries và DB writes idempotent trong concurrency case liên quan.
- [ ] `pytest`, `npm run build`, E2E Docker đã chạy hoặc ghi NOT TESTED/BLOCKED rõ; review test mới có ý nghĩa.
- [ ] Database migration và restore/rollback được giải thích; dữ liệu cũ còn nguyên.
- [ ] Docs/progress updated, gate được xác nhận; **không push main/production deploy khi chưa duyệt**.

---

## 25. Backlog ưu tiên ngay sau baseline `464e5e1`

**Phải làm trước khi bật LLM thật:**

1. `G0`: re-audit và kiểm tra revision Alembic `downgrade -1` trên temp DB — **không sửa hai revision cũ**.
2. `P1.1`: tách answer key khỏi public lesson; progress hiện hành; XP idempotency/concurrency; content version/history; proposal approval flag.
3. `P1.2`: atomic job claim, dispatch/reconciliation, Celery retry/race; không để model request tính tiền bị nhân đôi.
4. `P1.3`: auth cache isolation, resume/dashboard và lỗi UX.
5. `P2.0`: provider real adapter config fail-fast + mocked tests; chốt provider/model/budget trước integration có chi phí.

**Điểm hoàn thành đầu tiên đáng demo:** người dùng đăng nhập, tạo course bằng mock, hoàn thành bài, thấy progress đúng, không thể đọc answer key qua API, worker retry an toàn. Sau đó mới demo course sinh bằng Transformer/LLM thật.

---

## 26. Decision log (bổ sung theo quá trình, không thay lịch sử)

| Ngày | Quyết định | Trạng thái | Bằng chứng/điều kiện |
|---|---|---|---|
| 2026-10-30 | Giữ stack hiện hữu FastAPI/Next.js/PostgreSQL/Redis/Celery, không rewrite | **CHỌN cho kế hoạch** | GitHub baseline |
| 2026-10-30 | Transformer/LLM + DAG + Hybrid RAG; grading deterministic | **CHỌN cấp thuật toán** | `AI_ALGORITHMS_DECISIONS_SOPISKILL.md` |
| 2026-10-30 | Auth và Alembic đã có, không triển khai lại P0.5 | **FACT code**, TESTED theo log được báo cáo | Commits `46a4fdd`, `464e5e1` |
| 2026-10-30 | Threshold lesson completed ≥80%, XP award policy, public-answer reveal policy | **PROPOSAL, chưa duyệt riêng** | Cần ghi quyết định khi làm P1.1 |
| 2026-10-30 | LLM provider/model/key/budget | **UNKNOWN/CHƯA CHỐT** | Chỉ chọn khi người dùng cho phép |
| 2026-10-30 | Embedding model/dimension/index và OCR | **CHƯA CHỐT** | P4 benchmark / use case |
| 2026-10-30 | BKT/LSTM/Bandit và billing | **CONDITIONAL/FUTURE** | Dữ liệu/metrics/approval |
| 2026-10-31 | **P3.0 tách khỏi P3 Tutor**: làm Source Registry + Evidence Contract trước, không nhảy sang RAG | **HOÀN THÀNH (IMPLEMENTED+TESTED)** | `docs/development-progress.md` 2026-10-31 P3.0; migration `0005_p30_source_registry` |
| 2026-10-31 | **P3.0 AI Tutor Core**: SSE + grounding từ public blocks + idempotency theo DB, chưa có tool/cancel/quota đầy đủ | **HOÀN THÀNH (IMPLEMENTED+TESTED MOCK; real streaming NOT TESTED)** | `docs/development-progress.md` 2026-10-31 P3.0 Tutor; migration `0008_p30_tutor_core` |
| 2026-10-31 | Nguồn mới **luôn** `unverified`; evaluator chỉ **đề xuất** trạng thái, không tự ghi | **CHỌN (bảo mật/trung thực)** | `services/source_service.create_source`, `services/source_evaluation` |
| 2026-10-31 | Bài học chưa có nguồn ingest ⇒ luôn `general_ai_knowledge`; không tạo `evidence_supported` giả | **CHỌN (trung thực với bằng chứng)** | `services/source_context.lesson_grounding`, `tests/test_p30_source_first.py` |
| 2026-10-31 | Citation do **server** sinh từ registry; LLM không nhận/không trả `sourceId` | **CHỌN (chống citation giả)** | `services/citation_service`, prompt `p3.0-v1` |
| 2026-10-31 | Discovery mặc định `curated`/`mock`, **không network**; `web` trả 503 tới khi có SSRF guard P4.2 | **CHỌN (an toàn)** | `services/source_discovery` |
| 2026-10-31 | P2.2 tách 3 tầng: rubric deterministic = cổng pass/fail; human rubric cho người chấm; LLM-as-judge chỉ tham khảo | **CHỌN (trung thực đánh giá)** | `evals/rubric.py`, `evals/judges.py` |
| 2026-10-31 | `cost_estimate_usd = NULL` khi chưa cấu hình giá model — NULL = chưa biết, không phải miễn phí | **CHỌN (trung thực chi phí)** | `services/llm_usage_service.py`, `GenerationOut.costKnown` |
| 2026-10-31 | Budget job vượt trần ⇒ `BUDGET_EXCEEDED` fatal, không retry | **CHỌN (kiểm soát chi phí)** | `worker/generation.py`, `job_service.classify_error` |

---

### Lời nhắc cuối cho OpenCode

> **Không hỏi người dùng viết prompt mới cho từng phase.** Hãy dùng chính file này làm backlog triển khai tuần tự. Tự kiểm tra code thực tế, chia việc thành các commit nhỏ, dùng skills đúng nhiệm vụ, test và báo cáo sau mỗi checkpoint. **Dừng khi thiếu một quyết định có tác động tài chính, dữ liệu thật, bảo mật hoặc production; đừng tự chọn phương án có rủi ro và đừng khai báo hoàn thành nếu không có bằng chứng.**
