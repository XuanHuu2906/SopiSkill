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
- Input người dùng bị cắt theo `LLM_MAX_INPUT_CHARS`; output chạm trần
  `LLM_MAX_OUTPUT_TOKENS` ⇒ `ProviderBudgetError`.
- Trước khi bật provider thật, cần xác nhận: dữ liệu nào được gửi ra ngoài, ngân
  sách, và nhà cung cấp (xem Decision Log trong master plan).

## Trạng thái P2.0

- **IMPLEMENTED + TESTED (mocked)**: registry fail-fast, adapter OpenAI-compatible,
  taxonomy lỗi, semantic validation, timeout/retry/backoff, redaction log,
  **28 mocked HTTP tests** + 4 test fail-fast ở API.
- **TESTED (real, 3 request, có duyệt)**: Deploy.com
  `https://api-cdn.deploy.com/api/v1` + `deepseek-ai/deepseek-v4.1-flash-1017`.
  Kết quả: interview 5 câu 4.79s; proposal 3 unit/12 bài 13.89s; lesson 5 block
  12.05s — tất cả HTTP 200 và qua semantic lint.
- **BLOCKED**: real-provider E2E tự động trong CI (không đưa key vào CI) và
  P2.1 real eval 10 topic (cần duyệt thêm ngân sách).

Sau smoke test, `LLM_PROVIDER` đã đặt lại `mock` trong `.env` để tránh chi phí
ngoài ý muốn. Muốn chạy thật lại: đổi `LLM_PROVIDER=openai` rồi restart
backend + worker.

## Rollback

Đặt `LLM_PROVIDER=mock` và restart backend/worker. Không cần migration; job đang
chạy dở sẽ dùng provider mới ở lần claim/retry kế tiếp (proposal version đã pin).
