# LLM Provider — cấu hình & vận hành (P2.0)

SopiSkill dùng **provider adapter trung lập**. Mặc định là `mock` (deterministic,
không tốn phí, **không phải AI thật**). Muốn dùng LLM thật cần cấu hình server-side
và được duyệt về ngân sách/dữ liệu.

## Bật provider thật

```dotenv
LLM_PROVIDER=openai            # hoặc openai_compatible (endpoint tương thích)
LLM_API_KEY=...                # CHỈ server-side, không commit, không NEXT_PUBLIC_*
LLM_BASE_URL=https://api.openai.com/v1   # KHÔNG kèm /chat/completions
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
LLM_MAX_OUTPUT_TOKENS=2000
LLM_MAX_INPUT_CHARS=12000
```

Adapter gọi `POST {LLM_BASE_URL}/chat/completions` với `response_format=json_object`,
parse JSON → Pydantic → semantic lint (`app/providers/validation.py`).

## Fail-fast (không có fallback ngầm)

| Tình huống | Kết quả |
|---|---|
| `LLM_PROVIDER` không có trong registry | API trả **503 `PROVIDER_NOT_CONFIGURED`** |
| Provider thật thiếu key/base URL/model | **503 `PROVIDER_NOT_CONFIGURED`** |
| `LLM_PROVIDER=mock` | MockProvider (tường minh) |

Không có nhánh nào biến provider lỗi thành "mock chạy thành công".

## Error taxonomy → retry

| Exception | `code` | Retry? |
|---|---|---|
| `ProviderTimeoutError` | `PROVIDER_TIMEOUT` | có (bounded) |
| `ProviderRateLimitError` | `PROVIDER_RATE_LIMITED` | có (tôn trọng `retry-after`) |
| `ProviderTransientError` | `PROVIDER_TRANSIENT` | có |
| `ProviderAuthError` | `PROVIDER_AUTH_FAILED` | không |
| `ProviderBudgetError` | `PROVIDER_BUDGET_EXCEEDED` | không |
| `ProviderConfigError` | `PROVIDER_NOT_CONFIGURED` | không |
| `SchemaInvalidError` | `PROVIDER_SCHEMA_INVALID` | không (sửa prompt) |

Worker dùng `job_service.classify_error` để quyết định requeue (bounded bởi
`GENERATION_MAX_ATTEMPTS`) hay fail.

## Semantic validation

Ngoài Pydantic:

- Interview: đúng **5** câu, không rỗng, không trùng, ≤400 ký tự.
- Proposal: 2–6 unit, tiêu đề unit/bài không trùng, ít nhất 1 bài, có outcomes.
- Lesson: có ≥1 `teach` + ≥1 câu hỏi; `answerIndex` trong `[0, len(options))`;
  option order không trùng; đáp án `blank` **không** nằm trong câu và câu phải có
  chỗ trống (`____`, `...`); match/order không trùng khóa.

Vi phạm ⇒ `SchemaInvalidError` ⇒ job failed với mã rõ ràng (không đốt tiền retry).

## Quan sát & riêng tư

- Log mỗi lần gọi: `provider`, `model`, `prompt_version`, `prompt_tokens`,
  `completion_tokens`. **Không** log API key, prompt, hay nội dung người học.
- Input người dùng bị cắt theo `LLM_MAX_INPUT_CHARS`.
- Output bị cắt được phát hiện qua `finish_reason` (`length`), **không** chỉ dựa
  vào tổng `completion_tokens`. Lý do: model reasoning tính cả `reasoning_tokens`
  vào `completion_tokens`, nên một response **hoàn chỉnh** vẫn có thể chạm trần —
  báo lỗi khi đó là false positive (đã gặp thật ở P2.1 real eval).
- Khi bị cắt: **một** lần leo thang ngân sách (×2, trần ×1.6, bounded bởi
  `LLM_MAX_RETRIES`) rồi mới báo `ProviderBudgetError`.
- Sai schema/semantic: thử lại **bounded** bởi `LLM_MAX_SCHEMA_RETRIES` (mặc định
  1 → tối đa 2 request) kèm mô tả lỗi ngắn trong prompt sửa. Không retry mù.

## Token budget theo loại call (P2.1)

| Biến | Mặc định | Dùng cho |
|---|---|---|
| `LLM_MAX_OUTPUT_TOKENS_INTERVIEW` | 800 | 5 câu hỏi phỏng vấn |
| `LLM_MAX_OUTPUT_TOKENS_PROPOSAL` | 4500 | proposal + skills + prerequisites |
| `LLM_MAX_OUTPUT_TOKENS_LESSON` | 3000 | một bài học blocks |
| `LLM_MAX_OUTPUT_TOKENS_JUDGE` | 3000 | LLM-as-judge (chỉ eval, không trên đường học) |
| `LLM_MAX_SCHEMA_RETRIES` | 1 | số lần sửa schema tối đa (áp dụng cả proposal/lesson từ P2.2) |

`LLM_MAX_OUTPUT_TOKENS` cũ vẫn giữ làm fallback chung. Compose truyền đủ các
biến này cho `backend`, `worker`, `beat` (sửa P2.1: trước đây thiếu nên container
dùng default, gây `PROVIDER_BUDGET_EXCEEDED` khi chạy thật).

## Curriculum & hồ sơ người học (P2.1)

- `LearnerProfile` được **server** suy ra deterministic từ câu trả lời
  (`services/pedagogy.py`), không phải model tự khai; không suy diễn thuộc tính
  nhạy cảm.
- `skills` + `prerequisites` là DAG; chuẩn hoá bỏ self-loop/cạnh ngược thứ tự
  bài; **chu trình thật ⇒ 502** `PROPOSAL_SCHEMA_INVALID`. Proposals legacy thiếu
  curriculum được `fill_skills` lấp để mỗi bài có đúng 1 skill.
- Prompt version: `p2.1-v1` (thay `p2.0-v1`).

## Usage / cost / budget (P2.2)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LLM_PRICING_JSON` | rỗng | Giá USD / 1 triệu token theo model. Rỗng ⇒ `costEstimateUsd=null` + `costKnown=false` (**không phải 0**) |
| `GENERATION_MAX_TOKENS_PER_JOB` | 400000 | Trần token (prompt+completion) cho một job; 0 = không giới hạn |
| `GENERATION_MAX_COST_USD_PER_JOB` | 0 | Trần chi phí ước tính cho một job; 0 = không giới hạn |

- Adapter ghi usage vào collector của task (`app/providers/usage.py`). Worker flush vào
  `llm_usage_events` và cộng dồn cột usage trên `generation_jobs`; `GET /v1/courses/{id}/generation`
  trả `llmCalls/promptTokens/completionTokens/costEstimateUsd/costKnown`.
- Interview/proposal trong request cũng ghi usage bằng session riêng (best-effort) vì chi phí phát
  sinh kể cả khi request rollback.
- Vượt trần ⇒ job `failed` với `BUDGET_EXCEEDED` (fatal, không retry — retry chỉ đốt thêm tiền).
- Không lưu prompt/nội dung người học trong bảng usage.

## Eval chất lượng (P2.2)

```powershell
cd backend
# Offline, không tốn tiền
python -m evals.runner --provider mock --all

# Real provider (cần --yes). Judge = LLM-as-judge, chỉ là tín hiệu tham khảo.
$env:LLM_PROVIDER="openai"
python -m evals.runner --all --judge --yes

# So sánh 2 report (regression theo ngưỡng, bỏ qua khi khác provider/prompt/dataset)
python -m evals.runner --compare evals/reports/a.json evals/reports/b.json
```

- Dataset 12 topic (`evals/dataset.py`): vi/en, beginner→advanced, có chủ đề mơ hồ; kỳ vọng là
  **thuộc tính cấu trúc**, không so khớp chuỗi.
- Rubric deterministic (`evals/rubric.py`) là **cổng pass/fail**: schema/lint/DAG/quiz-per-lesson/
  độ dài teach/trùng lặp/số bài/ngôn ngữ. Ngưỡng trong `THRESHOLDS` là PROPOSAL.
- `HUMAN_RUBRIC` (9 tiêu chí 0–4) dành cho **người chấm**; chưa có điểm người chấm trong repo.
- LLM-as-judge lưu `status/usedLlm/judgeModel/promptVersion/scores/notes/disclaimer`; provider
  không hỗ trợ (mock) ⇒ `status=not_run`, không tạo điểm giả.
- `real_provider_eval.py` (P2.1) vẫn tồn tại cho smoke nhanh; `runner.py` là công cụ P2.2 đầy đủ.

## Trạng thái P2.0

- **IMPLEMENTED + TESTED (mocked)**: registry fail-fast, adapter OpenAI-compatible,
  taxonomy lỗi, semantic validation, timeout/retry/backoff, redaction log,
  **28 mocked HTTP tests** + 4 test fail-fast ở API.
- **TESTED (real, 3 request, có duyệt)**: Deploy.com
  `https://api-cdn.deploy.com/api/v1` + `deepseek-ai/deepseek-v4.1-flash-1017`.
  Kết quả: interview 5 câu 4.79s; proposal 3 unit/12 bài 13.89s; lesson 5 block
  12.05s — tất cả HTTP 200 và qua semantic lint.
- **P2.1 TESTED (real)**: eval 3 topic (`vi-beginner-tech`, `vi-advanced-social`,
  `en-advanced-eng`) → **3/3 pass**, 31 request, 18.365 prompt / 63.163 completion
  tokens; real E2E qua Docker + Celery worker **37/37 PASS** (9 bài học thật).
- **P2.2 TESTED (real, có duyệt ngân sách)**: `evals.runner --all --judge --yes` trên
  Deploy.com `deepseek-ai/deepseek-v4.1-flash-1017` → **12/12 topic pass** rubric deterministic,
  149 request (không tính judge), 103.984 prompt / 339.926 completion tokens. Judge chấm được
  **11/12** topic (1 topic `en-beginner-excel` bị cắt output ở trần judge 4800 token ⇒
  `status=error`, **không** bịa điểm); điểm trung bình các topic chấm được = **3.17/4**.
  Real Docker E2E (mock→provider thật) **51/51 PASS**, job usage thật
  `llm_calls=10, 7551 prompt / 23146 completion, cost≈$0.0275` khi cấu hình giá.
- **BLOCKED**: real-provider E2E tự động trong CI (không đưa key vào CI); điểm rubric **người
  chấm** cho 12 topic (chưa có người chấm thật; judge không thay thế).

Sau smoke test, `LLM_PROVIDER` đã đặt lại `mock` trong `.env` để tránh chi phí
ngoài ý muốn. Muốn chạy thật lại: đổi `LLM_PROVIDER=openai` rồi restart
backend + worker.

## Rollback

Đặt `LLM_PROVIDER=mock` và restart backend/worker. Không cần migration; job đang
chạy dở sẽ dùng provider mới ở lần claim/retry kế tiếp (proposal version đã pin).
