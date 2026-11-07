# SopiSkill — Nhiệm vụ tiếp theo cho Claude Code sau Parity Audit 2026-11-04

**Trạng thái:** PROPOSAL / NOT IMPLEMENTED / NOT TESTED.  
**Mục tiêu ngắn hạn:** có một E2E thật của AI Tutor **trong môi trường non-production, bằng mock provider**, sửa cách báo cáo test và bảo toàn trạng thái mã nguồn; không tự tuyên bố 99% parity.  
**Nguồn bắt buộc:** `docs/audits/polyskill-parity-2026-11-04/` nếu tồn tại trong repository, đặc biệt `00`, `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`. Nếu các tệp ở vị trí khác, tìm từ repo root và báo rõ đường dẫn. Đọc `AGENTS.md`, `docs/development-progress.md` và chỉ dẫn Claude Code hiện hữu. Tuyệt đối không giả định các tệp đã được commit.

## 1. Kết luận audit phải giữ nguyên

- Measured parity **74.7% = 62/83** và Evidence Coverage **53/100** là kết quả của *ma trận quan sát*, **không phải tỷ lệ hoàn thành sản phẩm**.
- SopiSkill có 6 lesson block types và luồng topic → 5 interview → proposal → approve → generation → lesson → quiz được E2E báo cáo. Runtime test dùng `LLM_PROVIDER=mock`, không phải AI thật.
- Tutor có code/unit tests nhưng runtime default trả `503 TUTOR_DISABLED`; RAG default trả `503 RAG_NOT_ENABLED`.
- Phần lesson có các khoảng trống rõ ràng: glossary, `termKey`, figures, prefetch; 4 loại khoảng cách được quan sát tại reference ở mức phù hợp.
- 699 tests passed, 29 skipped; `tsc` và build pass **chưa chứng minh giao diện browser hoạt động**.
- Audit có `18` bước nhưng các bước Tutor trả 503 và `me/stats`, `me/entitlement` trả 404; **exit 0 của driver chỉ nói quá trình audit chạy được**, không đồng nghĩa toàn bộ acceptance pass.
- Frontend container và frontend working tree có thể là hai phiên bản khác nhau. Audit chạy trên *dirty tree*: branch `feat/p6.0-ci-pipeline`, HEAD lịch sử `d747e78`, 15 modified + 8 untracked tại thời điểm audit. Đối chiếu trạng thái **hiện tại** trước mọi thay đổi.
- PolySkill mới được quan sát một phần qua những session cũ; trong lượt REA 6.8.0 gần nhất, CDP trả `targets: []`. Không tuyên bố đã capture mới khi chưa có bằng chứng.

## 2. Những điều cần hiệu chỉnh trong báo cáo / kế hoạch

1. **Phân tách ít nhất ba trục đánh giá:** (a) observed behaviour parity, (b) API/shape surface parity, (c) internal test readiness. Đừng cho điểm một feature `MATCHED(runtime)` chỉ vì code tồn tại / unit test pass khi feature đang bị tắt.
2. **Giữ riêng tầng bằng chứng:** E0 declaration, E1 transport, E2 body shape, E2O owner transcript. E1 có thể hỗ trợ kết luận mức *outcome*, nhưng không biến thành một bằng chứng API contract. Khi kết luận `1` cho E1, chú thích rõ vì sao và không đẩy vào Evidence Coverage.
3. **Chú thích đúng số học:** hiện tại floor 62, `floor + 17 unknown = 79` là upper bound nếu **không sửa code**; `88` chỉ là kịch bản **cộng thêm 9 điểm từ partial→full** rồi giả định 17 unknown thành full, nhưng **vẫn chưa sửa 12 điểm hard missing**. Không gọi bất cứ số nào là dự báo.
4. **Phân biệt audit-script success và full chain acceptance:** driver có thể exit 0 dù phát hiện các blocker 503/404. Bổ sung verdict riêng: `AUDIT_EXECUTION_PASS` và `PRODUCT_E2E_PARTIAL/FAIL` theo acceptance thật.
5. **Prefetch:** evidence chỉ xác nhận browser gọi `GET /lessons/{nextId}?prefetch=1`. Không có bằng chứng endpoint này trả kèm “next-lesson hint”. Triển khai **client prefetch** theo mục tiêu giảm thời gian chuyển bài và server tương thích nếu cần; không phát minh payload contract của PolySkill.
6. **Không tự bật LLM thật chỉ để gỡ Tutor 503:** kiểm tra `TUTOR_MESSAGES_PER_DAY=0`, `TUTOR_TOKENS_PER_DAY=0`, quota semantics và config thật trước; không giả định `0` nghĩa unlimited hay disabled.

## 3. Phạm vi triển khai lần này — GATE TUTOR-MOCK-01

### 3.1. Preflight, không sửa code

- Chạy `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git diff --stat`; kiểm tra mọi untracked/modified file. **Không stash/reset/checkout/clean/commit/push** nếu chưa được chủ repo duyệt.
- Kiểm tra `docker compose config`, `docker compose ps`, backend/worker configs, `/health` và chạy test trên working tree hiện tại. Ghi rõ image/container nào đang chạy từ commit/bản build nào. Không giả định frontend đang mở ở :3000 phản ánh source chưa commit.
- Đọc: `backend/app/core/config.py`, `backend/app/api/v1/tutor.py`, `backend/app/services/tutor_service.py`, `backend/app/providers/`, `backend/app/core/limits.py`, `frontend/src/app/lesson/[lessonId]/TutorPanel.tsx`, `backend/tests/test_p30_tutor.py` (nếu có) và E2E harness.
- Xác định lý do cụ thể `TUTOR_DISABLED`, điều kiện bật tools/limits, phụ thuộc provider, khả năng mock streaming và cách hủy. Nếu cần API phí thật thì ghi `BLOCKED real provider`, **vẫn tiếp tục mock testing** nếu có thể.

### 3.2. Thay đổi được phép khi đã xác minh an toàn

- Chỉ thay đổi tối thiểu phục vụ **test/runtime Tutor bằng mock trên môi trường non-prod cô lập**; ưu tiên *ephemeral compose override/environment* hoặc test fixture thay vì sửa `.env` lâu dài.
- Mặc định **không bật** tool có tác dụng ghi dữ liệu, RAG, web ingest hay API trả phí; giữ `TUTOR_TOOLS_ENABLED=false`, `RAG_ENABLED=false` trừ khi có kiểm thử riêng với allowlist bảo mật đã được duyệt.
- Bảo toàn server-side authorization: course/lesson/contextRef/`blockIndex` phải resolve từ DB theo owner; không nhận đoạn lesson client gửi để đi vòng auth.
- Bảo toàn session cookie + CSRF, idempotency `clientMessageId`, timeout/cancel, quota, log không chứa token/PII. Không bỏ `_require_enabled()` hoặc quota guard để làm E2E green.
- Nếu cần viết test mới hoặc sửa bug tối thiểu, thay đổi module nhỏ và giải thích rõ nguyên nhân. Không tự viết lại toàn bộ Tutor vì code đã có.

### 3.3. Acceptance criteria bắt buộc

1. **OFF:** Với `TUTOR_ENABLED=false`, route trả 503 `TUTOR_DISABLED` rõ ràng; frontend không treo.
2. **ON + MOCK:** User đã đăng nhập, có lesson thuộc course của mình, request Tutor trả HTTP 200 `text/event-stream` với ít nhất một `delta` và terminal `done`, được assert từ bytes/frames thực trên test backend (không chỉ gọi hàm giả lập).
3. **History:** Reload/re-fetch thread vẫn có user/assistant messages đúng, không lộ dữ liệu user khác.
4. **Authorization:** user B không đọc/nhắn trong course của A (404); `lessonId` khác course, `blockIndex` invalid, thiếu CSRF hoặc session phải bị từ chối đúng contract.
5. **Idempotency:** Retry cùng `clientMessageId` không ghi trùng, không double-charge quota; GET usage không tiêu quota.
6. **Negative stream:** provider lỗi giữa stream, disconnect/cancel hoặc timeout có hành vi đã ghi rõ; nếu mock không mô phỏng đủ, ghi `NOT TESTED`, không báo PASS.
7. **UI:** chạy browser-driven smoke test nếu browser harness có sẵn; nếu không, `NOT TESTED browser UI` dù `tsc`/build đã pass.
8. **No paid calls:** xác minh cấu hình `mock`, key không xuất hiện trong logs, không tiêu token API ngoài.
9. **Regression:** unit/integration liên quan, `pytest` (ghi pass/skip), `npx tsc --noEmit`, `npm run build`, Docker E2E trên test stack; không gọi test pass khi chỉ có exit 0 của audit driver.
10. **Clean report:** phân biệt `IMPLEMENTED`, `TESTED`, `NOT TESTED`, `BLOCKED`, `REPORTED`, biết rõ artifact/log/hash/commit/tree.

### 3.4. Không làm ở gate này

- Không sửa glossary/figures/prefetch/RAG/billing đồng thời với Tutor.
- Không dùng tài khoản PolySkill để gọi API trực tiếp ngoài UI; không tự động đăng nhập, quét hàng loạt hoặc tiêu quota.
- Không tăng cap token/ngân sách không giới hạn, không dùng LLM real khi chưa được duyệt cụ thể.
- Không đổi stack, xóa/reset volume, destructive migration, đẩy `main`, tạo commit nếu chưa được yêu cầu.

## 4. Sau khi Tutor mock gate đạt — backlog đề xuất (không tự thực hiện)

1. **P1-QUIZ-BLANK** (nhỏ, deterministic): schema/lint bắt `blank` có số placeholder khớp số đáp án; giữ backward compatibility với một blank, unit+E2E negative tests.
2. **P1-PEDAGOGY + P1-LEVEL-FIT** (nhỏ): sửa parser `gio/phut/tieng`, “hiểu sâu”, “đồ thị”; ≥20 Vietnamese fixtures, tránh false positives; không tự ép model thành advanced khi người học chưa yêu cầu.
3. **P1-LANG** (vừa): truyền language qua course → profile → proposal → lessons/quiz → tutor; giữ default `vi`; test `en`/`vi` và unsupported locale. Migration nếu cần phải xin duyệt.
4. **P1-CONTENT-TRUNC** (vừa): chặn lưu lesson không hoàn chỉnh; bắt finish_reason/truncation, ưu tiên generation per-lesson/bounded retry hoặc thiết kế budget có đo trước; cần duyệt chi phí khi chạy 12-topic real-provider eval.
5. **P1-GLOSSARY + inline terms**, rồi **figures/diagram renderer**, rồi **client prefetch**; đây là khoảng cách lesson quan trọng. Mọi migration mới phải có thiết kế expand/rollback, dữ liệu cũ vẫn còn.
6. **Reference capture parallel track:** chủ tài khoản tự điều khiển Chrome/tab đã đăng nhập, REA ghi **metadata/field shape đã lọc**, không xuất cookie/token, full response hay nội dung riêng tư. Phải có target CDP thật và verify origin filters. Khi chưa có thì `BLOCKED` và giữ coverage 53%; không bịa bằng chứng, không gọi UNKNOWN là MISSING.

## 5. Mẫu báo cáo Claude Code cần xuất cuối gate

```markdown
# TUTOR-MOCK-01 Result
- Timestamp / branch / HEAD / working tree (before/after):
- Source documents and audit versions read:
- Root cause of 503:
- Environment / provider (prove MOCK):
- Changes (paths + rationale):
- IMPLEMENTED:
- TESTED: [command, environment, exit, pass, fail, skip, log]
- NOT TESTED:
- BLOCKED:
- Security probes: auth, owner, CSRF, idempotency, quota, no secrets
- E2E verdict: PRODUCT_E2E_PASS / PARTIAL / FAIL (not audit-script exit)
- Regression verdict:
- Rollback:
- No paid calls / no destructive operation proof:
- Next task proposed (do NOT self-start):
```

**Điểm dừng:** Sau khi đạt hoặc thất bại Gate TUTOR-MOCK-01, báo cáo và dừng. Chỉ tiến sang gate tiếp theo khi chủ repo chọn. Mục tiêu 99% là mục tiêu **behaviour parity đo được**, không phải lý do sao chép mã nguồn, assets, prompt, UI hay bí mật của PolySkill.
