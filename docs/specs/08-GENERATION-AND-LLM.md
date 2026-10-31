# 08 — Generation Jobs, LLM Provider & Curriculum DAG

**Trạng thái:** P1.2 job reliability và P2.0 adapter được **báo cáo đã triển khai/test**. P2.1/P2.2 ở đây là **đề xuất triển khai mới**.

## 1. Current provider capabilities (reported)

- `LLM_PROVIDER=mock` mặc định, deterministic và **không gọi API AI thật**.
- Registry `mock | openai | openai_compatible`; thiếu cấu hình provider thật hoặc provider lạ → `503 PROVIDER_NOT_CONFIGURED`, **không fallback mock**.
- Adapter OpenAI-compatible `/chat/completions` với `response_format=json_object`, parse → Pydantic → semantic lint; timeout, retries bounded, backoff+jitter/`retry-after`, cắt input, output token budget và redacted metadata logs.
- Real smoke **3 requests được duyệt** qua Deploy.com với `deepseek-ai/deepseek-v4.1-flash-1017` và HTTP 200; **không** chứng minh hierarchical generation, tutor streaming, chi phí đầy đủ hoặc second provider.

## 2. Requirements

| ID | Yêu cầu | Phase |
|---|---|---|
| GEN-001 | Mock output deterministic, offline tests không network | P0 / regression |
| GEN-002 | Real provider config fail-fast, key chỉ server | P2.0 / regression |
| GEN-003 | Validate interview/proposal/lesson schema + semantic rules | P2.0 |
| GEN-004 | Approve tạo job outbox; claim nguyên tử, lease, recovery | P1.2 / regression |
| GEN-005 | Retry bounded, idempotent upsert; superseded job không overwrite | P1.2 / regression |
| GEN-006 | Learner profile từ 5 answers, objective dựa Bloom, DAG acyclic | P2.1 |
| GEN-007 | Hierarchical generation dùng snapshot approved proposal | P2.1 |
| GEN-008 | Cost/token/latency/job metrics, per-user budget controls | P2.2 |
| GEN-009 | Eval ≥10 topics, cấu trúc/giá trị sư phạm/hallucination | P2.2 |

## 3. Hierarchical pipeline P2.1 — PROPOSAL

```text
answers[5] → validated learner_profile snapshot
            → curriculum plan (learning outcomes + prerequisite DAG)
            → validated proposal vN → USER APPROVE
            → generate job pins (courseId, profileVersion, proposalVersion, model/promptVersion)
            → per-unit outline → per-lesson typed blocks
            → semantic checks & server-only answer keys
            → persist versions + progress → ready
```

Các bước có thể gộp network calls nếu tiết kiệm chi phí, nhưng **không** bỏ validation hoặc snapshot/pinning. Không tự ý gọi model trong DB transaction dài.

## 4. Semantic validation (ít nhất theo P2.0)

- Interview: đúng 5 câu, ≤400 ký tự/câu, không rỗng/trùng.
- Proposal: 2–6 units, không trùng title/lesson vô nghĩa, có outcomes; limits chi tiết theo current schema.
- Lesson: có ≥1 `teach` và ≥1 quiz; `mc.answerIndex` nằm trong options; options unique; `blank` che đáp án bằng `____` (repair được nếu an toàn), order/match không duplicate keys.
- P2.1: prerequisite DAG no cycle/missing nodes, lesson-outcome alignment, difficulty consistency, progression hợp lý; test theo file `19-PEDAGOGY-AND-EVALUATION.md`.

**Phân loại lỗi:**

| Code | Retry? | Ý nghĩa |
|---|---|---|
| `PROVIDER_TIMEOUT`, `PROVIDER_RATE_LIMITED`, `PROVIDER_TRANSIENT` | Có, bounded | Lỗi tạm thời |
| `PROVIDER_AUTH_FAILED`, `PROVIDER_NOT_CONFIGURED` | Không | Cấu hình/quyền |
| `PROVIDER_BUDGET_EXCEEDED` | Không | Budget guard |
| `PROVIDER_SCHEMA_INVALID` | Không (theo policy hiện hành) | Output không hợp contract; chỉnh prompt/offline trước |

## 5. Job state and recovery

- `queued`: DB commit, chưa chắc broker đã nhận; `dispatched=false` hiển thị trung thực.
- `running`: worker atomic claim, có lease timeout/heartbeat; tăng `attempts_count` theo số worker claims, **không** bằng lượt user bấm retry.
- `ready`: lessons đã được ghi hợp lệ; `failed`: error code an toàn.
- `running → queued`: với recoverable failures còn retry budget; backoff có giới hạn.
- Reconciler tìm outbox chưa dispatch / lease hết hạn, không tạo double effect; duplicate Celery delivery là no-op nếu job đã done.
- Retry explicit tạo **job mới**, giữ lịch sử cũ; contentVersion chỉ tăng nếu nội dung thực thay đổi; attempts cũ không bị xóa.

## 6. Token/cost policy

- Global và per-job max output/input budget; max lessons per course; max request count; hard stop trước request vượt quota.
- Log usage nếu provider cung cấp: `provider`, `model`, `prompt_version`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `job_id`; giá chính xác có thể **UNKNOWN** nếu provider không trả fee.
- Đề xuất thêm `provider_usage`/`generation_usage` theo job và stage ở P2.2; idempotency keys tránh đếm chi phí hai lần do retry persistence, nhưng **không thể hứa** external provider không charge lại nếu network timeout sau khi request đã xử lý.
- `LLM_PROVIDER=mock` khi chạy tests/local mặc định. Chỉ real E2E khi có budget cụ thể được duyệt.

## 7. Acceptance for P2.1

1. 10 topics offline fixtures; mỗi generated proposal hợp schema, DAG acyclic, IDs unique, mapping lessons/outcomes đúng.
2. Mock end-to-end và existing E2E regression còn pass; backend not leak answer keys.
3. Concurrency: duplicate approve/retry/worker không nhân đôi lessons; stale worker không overwrite content mới.
4. Controlled errors: invalid JSON, schema invalid, 429, timeout, budget exceeded, fail-fast config có test.
5. Real provider: chỉ đánh dấu **TESTED REAL** nếu được phép, có proof request/usage redacted, nội dung quan sát; nếu chưa phép → **BLOCKED**, không thay bằng mock để báo PASS.

## 8. Không làm

Không tự tạo key, sử dụng credential của coding agent, auto mua API, fine-tune, gọi API backend của PolySkill hay tuyên bố thuật toán backend của PolySkill.
