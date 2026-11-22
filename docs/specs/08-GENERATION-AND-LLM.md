# 08 — Generation Jobs, LLM Provider & Curriculum DAG

**Trạng thái (`2026-11-22`):** **P1.2**, **P2.0**, **P2.1**, **P2.2**, **`P1-QUIZ-BLANK`** và **`RELIABILITY-CELERY-01/02`** đều đã **IMPLEMENTED · REPORTED TESTED**. Các vấn đề chất lượng ở provider thật (**`P1-CONTENT-TRUNC`**, **`P1-LANG`**, **`P1-LEVEL-FIT`**) là backlog ưu tiên tiếp theo.

## 1. Provider capabilities (IMPLEMENTED)

- `LLM_PROVIDER=mock` mặc định: deterministic, offline, **không gọi AI thật** (`MockProvider` không thay thế bằng chứng LLM thật).
- Registry `mock | openai | openai_compatible`: thiếu key/base URL/model hoặc provider lạ → `503 PROVIDER_NOT_CONFIGURED`, **không fallback mock**.
- Adapter OpenAI-compatible (`/chat/completions` + `response_format=json_object`): parse → Pydantic → semantic lint; timeout (`45s`), bounded retries (`LLM_MAX_RETRIES=2`, `LLM_MAX_SCHEMA_RETRIES=1`), input cap (`12_000` chars), output token budgets tách theo từng bước (`interview: 800`, `proposal: 4500`, `lesson: 3000`, `judge: 3000`, `tutor: 900`), redacted logs.
- **Real-LLM evaluation baseline (`2026-11-04`):** đã chạy 12 topics trên `deepseek-ai/deepseek-v4.1-flash-1017` (149 calls, `N=11` scored, 1 hit `PROVIDER_BUDGET_EXCEEDED`), mean **3.17/4**. Phát hiện 4 lỗi lặp lại:
  - `P1-QUIZ-BLANK` (multi-blank 5/11): **đã sửa trong code** (`validate_lesson` ở worker + `BLANK_SLOT_COUNT=1`).
  - `P1-CONTENT-TRUNC` (cắt cụt bài học 7/11 ở trần output token): **OPEN — chưa sửa**.
  - `P1-LANG` (6/6 topic tiếng Anh bị trả tiếng Việt): **OPEN — chưa sửa**.
  - `P1-LEVEL-FIT` (8/11 lệch trình độ): **OPEN — chưa sửa**.

## 2. Requirements

| ID | Yêu cầu | Trạng thái (2026-11-22) |
|---|---|---|
| GEN-001 | Mock output deterministic, offline tests không network | **IMPLEMENTED · TESTED** |
| GEN-002 | Real provider config fail-fast, key chỉ server | **IMPLEMENTED · TESTED** |
| GEN-003 | Validate interview/proposal/lesson schema + semantic rules (`validate_lesson` tại worker) | **IMPLEMENTED · TESTED** (`P1-QUIZ-BLANK`) |
| GEN-004 | Approve tạo job outbox; claim nguyên tử, lease, stale-dispatch recovery | **IMPLEMENTED · TESTED · DEPLOYED** (`RELIABILITY-CELERY-01/02`) |
| GEN-005 | Retry bounded, idempotent upsert; superseded job không overwrite | **IMPLEMENTED · TESTED** |
| GEN-006 | Learner profile từ 5 answers, Bloom outcomes, DAG acyclic | **IMPLEMENTED · TESTED** (`P1-PEDAGOGY` uncommitted) |
| GEN-007 | Hierarchical generation dùng snapshot approved proposal | **IMPLEMENTED · TESTED** |
| GEN-008 | Cost/token/latency/job metrics (`llm_usage_events`), per-job budget caps | **IMPLEMENTED · TESTED** (`0007_p22_eval_cost`) |
| GEN-009 | Eval ≥10 topics, cấu trúc/sư phạm/hallucination | **IMPLEMENTED · MEASURED** (`3.17/4` — cần sửa P1 & đo lại sau khi duyệt budget) |

## 3. Pipeline hiện hữu (P2.1–P2.2)

```text
answers[5] → deterministic LearnerProfile (pedagogy.py)
           → ProposalPayload (units + outcomes + Bloom skills + acyclic prerequisites DAG)
           → USER APPROVE (pin proposalVersion, create queued job in txn)
           → Celery worker atomic claim + lease
           → per-lesson generation (bounded output tokens + per-job token/cost budget)
           → validate_lesson() at worker boundary (incl. BLANK_SLOT_COUNT=1, unique options, teach+quiz)
           → persist private Lesson.content + llm_usage_events + backfill skills (if P5.0) → ready
```

## 4. Semantic validation & error taxonomy

- **Interview:** đúng 5 câu, ≤400 ký tự/câu, không rỗng/trùng.
- **Proposal:** 2–6 units, 2–8 outcomes, DAG acyclic, không duplicate title vô nghĩa.
- **Lesson (`backend/app/providers/validation.py` + `worker/generation.py`):**
  - Ít nhất 1 `teach` và 1 quiz block.
  - `mc.answerIndex` trong biên, options không trùng.
  - `blank`: **đúng 1 chỗ trống** (`BLANK_SLOT_COUNT = 1`, kiểm bằng `_count_blank_slots()`), không tạo thêm chỗ trống khi câu đã có marker; `order`/`match` không trùng key; `short` bắt buộc có `acceptedAnswers` (`1..10`).
  - Worker gọi `validate_lesson(content)` trước khi ghi `ready` — nội dung sai schema không bao giờ được lưu `ready`.

| Code | Retry? | Ý nghĩa |
|---|---|---|
| `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_TRANSIENT` | Có, bounded | Lỗi tạm thời |
| `PROVIDER_AUTH_FAILED`, `PROVIDER_NOT_CONFIGURED` | Không | Cấu hình/quyền |
| `PROVIDER_BUDGET_EXCEEDED` / `BUDGET_EXCEEDED` | Không | Vượt trần token/chi phí job |
| `PROVIDER_SCHEMA_INVALID` | Bounded schema retry (`LLM_MAX_SCHEMA_RETRIES=1`) rồi fail | Output không hợp contract |
| `DISPATCH_EXHAUSTED` | Không | Quá `GENERATION_MAX_DISPATCH_ATTEMPTS=5` mà không worker claim |

## 5. Job state, Celery config & recovery (`RELIABILITY-CELERY-01/02`)

- **3 nhánh thu hồi của beat reconciler (`30s`):**
  1. `queued` với `dispatched_at IS NULL` quá `GENERATION_DISPATCH_GRACE_SECONDS=10` → dispatch lại.
  2. `running` hết `lease_expires_at` (`GENERATION_LEASE_SECONDS=180`) → reclaim/retry có giới hạn (`GENERATION_MAX_ATTEMPTS=3`).
  3. `queued` có `dispatched_at` cũ hơn `GENERATION_STALE_DISPATCH_SECONDS=300` (message thất lạc / worker chết trước khi claim) → re-dispatch tới `GENERATION_MAX_DISPATCH_ATTEMPTS=5`, quá ngưỡng đánh `failed` / `DISPATCH_EXHAUSTED`.
- **Celery Redis config đã sửa và xác minh live:** `broker_transport_options={"visibility_timeout": 3600}` (thay key sai `worker_visibility_timeout`), `task_time_limit=2400`, `task_acks_late=True`, `worker_prefetch_multiplier=1`.

## 6. Token/cost policy (IMPLEMENTED)

- Trần per-job cấu hình trong `config.py`: `GENERATION_MAX_TOKENS_PER_JOB=400000`, `GENERATION_MAX_COST_USD_PER_JOB=0` (0 = không giới hạn USD).
- `LLM_PRICING_JSON` rỗng ⇒ `costEstimateUsd = null` và `costKnown = false` (tuyệt đối không báo `$0` giả).
- Mọi lời gọi real LLM ngoài mock chỉ thực hiện khi owner duyệt rõ provider, model, tập topic và ngân sách.

## 7. Hướng mở rộng tiếp theo (PROPOSAL)

- **`P1-CONTENT-TRUNC`:** bắt `finish_reason == "length"` rõ ràng thay vì để JSON cắt cụt/bài cụt, đo & tinh chỉnh token budget hoặc chiến lược chia nhỏ sinh bài.
- **Automated Validator / QA Agent (`OBSERVED_STATIC` từ PolySkill `fnd_`):** có thể cân nhắc thêm bước kiểm định chất lượng sau sinh (flag `ambiguous`, `weak_distractors`, `wrong_answer`) ở phase sau.
- **Lazy / on-demand lesson generation:** sinh bài 1 trước cho người học vào học sớm, các bài sau chạy nền (`preparing`) — hiện chưa triển khai.
