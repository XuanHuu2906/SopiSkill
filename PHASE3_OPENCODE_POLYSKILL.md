# PHASE 3 — PolySkill Black-box follow-up (U7/U13, U8, D2/U9)

**Đối tượng thực thi:** OpenCode trên Windows, với tài khoản và trình duyệt do chủ tài khoản điều khiển.  
**Trạng thái tại thời điểm giao:** Kế hoạch + prompt; **NOT TESTED** cho phiên mới.  
**Mục tiêu:** Thu thêm bằng chứng, không sao chép hệ thống hoặc đoán thuật toán backend.

## 0. Bối cảnh và ranh giới sự thật

Trước khi làm, đọc đầy đủ các file đã có trong workspace (nếu thiếu, báo BLOCKED, không tự dựng nội dung):

1. `polyskill-analysis-report.md`, mục 4–7.
2. `polyskill-dynamic-analysis.md`, mục 2–7.
3. `02_PROJECT_CONTEXT.md` và `03_ROADMAP_AND_BACKLOG.md`.
4. `research/polyskill-blackbox/README.md`, `test-matrix.md`.
5. `research/polyskill-blackbox/reports/blackbox-findings.md`.
6. `research/polyskill-blackbox/reports/unknowns-and-next-tests.md`.
7. `research/polyskill-blackbox/evidence/observations-redacted.json`, `runs.csv` (chỉ đọc dữ liệu đã ẩn nhạy cảm).

Baseline từ báo cáo 2026-10-31: PDF 3 trang hư cấu, 6/6 oracle đúng trên mẫu nhỏ; khóa học được tạo từ PDF có nguồn; sau một quick action, `toolCalls[]` tăng 3→4; tên tool chưa thấy; citation `cite{anchor,label}` có nhưng việc dẫn trang/đoạn bằng máy chưa được kiểm chứng; 4 difficulty quick actions chỉ hiện khi thread trống. Đây là bằng chứng của **hành vi**, không chứng minh RAG vector retrieval, model, chunker, reranker hoặc thuật toán thích nghi.

**Hiệu chỉnh phương pháp khi cập nhật báo cáo:**
- `toolCalls[]` tăng chỉ chứng minh có bản ghi tool call mới. Chỉ xác nhận thành công khi thấy được `ok=true` hoặc hiệu ứng thực thi đáng tin cậy.
- 6/6 đáp án đúng không phân biệt query-time retrieval với nội dung nguồn đã được nhúng vào lesson/context khi sinh khóa học.
- `brief` chuyển từ null sang có dữ liệu không đồng nghĩa đã quan sát trực tiếp chuỗi giá trị trạng thái ingest.

## 1. Ranh giới an toàn và phân quyền

- Làm việc **chỉ** trong `research/polyskill-blackbox/`, sau khi đã kiểm tra `pwd`, `git status --short`, nhánh, commit. Không đổi stack, không sửa mã ứng dụng AI Learning Platform, không commit/push trừ khi được yêu cầu.
- Chủ tài khoản tự mở Chrome, đăng nhập, gửi Tutor message, chọn quick action và quyết định mọi thao tác có khả năng thay đổi trạng thái/tiêu quota. OpenCode chỉ quan sát thụ động sau khi được phép truy cập đúng CDP endpoint và origins.
- Chỉ attach `http://127.0.0.1:9222`, đúng target của `https://web.polyskill.app` và chỉ mở rộng quan sát đến `https://api.polyskill.app` nếu được phê duyệt. Không gọi hoặc replay API PolySkill trực tiếp, không thử endpoints ngoài UI, không sửa JS runtime, không bypass auth/rate limit/guards.
- **Không thu** token, cookies, raw HAR, request body chứa nội dung cá nhân, raw SSE, private course IDs, email, session identifiers, storage values, secret headers; khi nhìn thấy ở local DevTools, chỉ ghi metadata tối thiểu (event names, số lượng, các boolean, tình trạng shape). Không gửi raw captures hoặc screenshots chứa dữ liệu riêng vào repo/chat.
- `--include-console-text` có nguy cơ thu nội dung nhạy cảm: không bật mặc định; chỉ thử nếu chủ tài khoản chấp thuận rõ phạm vi, và phải redact trước khi lưu. `include-json-body-shapes` không cung cấp giá trị trường `tool_name` hay `ok`.
- `Tiếp tục nghiên cứu` chỉ cho phép chuẩn bị và quan sát thụ động. **Trước mỗi** Tutor message và trước D2 (có thể tái sinh bài học), yêu cầu chủ tài khoản xác nhận riêng; nếu không có, ghi `BLOCKED_CONSENT` và bỏ qua.

## 2. Phase 0 — Preflight môi trường (không tác động PolySkill)

- Kiểm tra repo, file đang tồn tại, phiên bản REA và CLI help trên Windows; sử dụng `rea --help`, `rea inspect-web-page --help`, hoặc tương đương `npx.cmd -y rea-agents@... --help` theo cài đặt đang có. Không tự cập nhật phiên bản.
- Kiểm tra biến môi trường khi REA chạy: `REA_BROWSER_OBSERVE_ENABLED=true`; `REA_BROWSER_CDP_ENDPOINTS_JSON=["http://127.0.0.1:9222"]`; `REA_BROWSER_ALLOWED_ORIGINS_JSON=["https://web.polyskill.app","https://api.polyskill.app"]`. Các tham số CLI phải phù hợp **phiên bản thực tế** và phải được xác minh bằng `--help`.
- Dùng `list-browser-targets` để lấy TARGET_ID mới trước từng cửa sổ. Không dùng ID đã lưu từ phiên cũ.
- REA chỉ capture sự kiện sau khi attach. Phải bắt đầu cửa sổ REA và bật `Network` / `Preserve log` trên Chrome DevTools **trước** khi chủ tài khoản thao tác.
- Kiểm tra kết quả capture: `disallowed_origin=0`; mã lỗi `target_changed` / `target_unavailable` / attach-limited; request có thật không; coverage hợp lệ. Không diễn giải `0 requests` trong cửa sổ lỗi là không có hoạt động.
- Không lưu raw JSON capture vào repo. Chỉ ghi báo cáo và data metadata đã redact.

## 3. Phase 1 — U7 và U13: xác minh SSE events + tool identity (P0)

**Mục tiêu:** Tìm ra tên event runtime được phát ra; nếu có, xác định tool chính xác bằng quan sát đáng tin cậy, không suy từ UI badge.

### Thao tác của chủ tài khoản

1. Mở **một lesson thuộc khóa học PDF test**, ưu tiên lesson có khả năng truy cập nguồn. Thao tác trong cửa sổ có thể làm tốn Tutor quota.
2. Mở Chrome DevTools (`F12`) → `Network` → `Preserve log`; chưa gửi câu hỏi.
3. OpenCode bắt đầu capture thụ động của đúng tab, trong cửa sổ đã xác minh có hai origin hợp lệ.
4. Sau khi được phê duyệt riêng, chủ tài khoản gửi đúng **một** câu hỏi không nhạy cảm, ví dụ: `Trong tài liệu LUMORA-731, điều kiện MƯA TÍM áp dụng ở giai đoạn nào? Nếu không tìm thấy, hãy nói rõ.`
5. Chọn request `POST .../tutor/messages` → tab `EventStream` trong DevTools, chỉ đếm event name và kiểm tra những field tên tool thực tế nếu có. Không copy toàn bộ EventStream/raw payload.
6. Nếu DevTools không hiện event name, chỉ ghi `EVENTSTREAM_NOT_VISIBLE`; không khai báo sự kiện thực tế từ enum client.
7. Kiểm tra lịch sử Tutor trước/sau. Nếu truy cập được `toolCalls[].ok` từ view trong DevTools mà không xuất dữ liệu nhạy cảm, chỉ ghi giá trị boolean và số lượng; không ghi ID, content, args.

### Evidence tối thiểu

```
test_id: U7_U13
timestamp_local: <time>
lesson_context: synthetic-fixture-only
capture_ok: true|false
disallowed_origin: <number>
request_seen: true|false
sse_http_200: true|false
event_counts: {delta: N, tool: N, confirm: N, done: N, error: N, restarted: N, other: N}
event_names_actual: [only observed names]
tool_names_actual: [only if explicitly observed]
tool_calls_before: N
tool_calls_after: N
new_tool_ok: true|false|unknown
limitations: [...]
```

**Verdict:**
- `EVENTS_OBSERVED` chỉ khi tab EventStream hiển thị event names thực tế.
- `TOOL_NAME_CONFIRMED` chỉ khi có tool name từ một payload runtime có thể kiểm tra.
- `TOOL_RECORD_OBSERVED` khi lịch sử toolCalls tăng; `TOOL_EXECUTION_SUCCESS` chỉ nếu `ok=true` hoặc hành vi thành công được chứng minh.
- Nếu chỉ thấy SSE 200, vẫn giữ `EVENT_NAMES_UNKNOWN`; nếu có UI badge “đã đọc tài liệu nguồn” vẫn giữ `read_source=UNKNOWN`.

## 4. Phase 2 — U8: đánh giá citation theo PDF fixture (P0, không đổi dữ liệu)

1. Dùng PDF fixture của nhóm trong `fixtures/rag_synthetic_v1.pdf` (gitignored, không gửi lên nơi khác). Kiểm tra hash nếu có oracle để đảm bảo đang dùng đúng bản. Không đổi fixture/đáp án trong lúc đánh giá.
2. Mở lesson có `cite{anchor,label}`. Ghi số lượng citation, nhãn trang, có/không có thao tác điều hướng ở view hiện tại.
3. Đối chiếu thủ công câu trích và trang được nêu với `oracle.local.json` và nội dung PDF. Nếu có thư viện PDF text extraction hiện hữu, có thể chạy **offline** script để kiểm tra locator/quote; phải ghi thư viện, phiên bản, cách chuẩn hóa Unicode, trang 1-indexed, kết quả hash/substring. Không tự cài thêm package nếu chưa phê duyệt.
4. Phân loại `anchor`: văn bản nguyên văn, định danh/slug, hay chưa rõ. **Không bắt buộc `anchor` match literal text nếu format chưa xác minh**; chỉ chấm được nếu hiểu được quy tắc ánh xạ.
5. Không nhầm `label` “Trang 3” với citation machine-checkable. Không kết luận cả app không hỗ trợ click chỉ vì một view hiển thị StaticText.

### Verdict

- `CITATION_CONTENT_MATCH`: trích dẫn đúng nội dung PDF.
- `CITATION_PAGE_MATCH`: đúng trang theo fixture.
- `CITATION_LOCATOR_VALIDATED`: `anchor`/locator chỉ đến một span tồn tại, kiểm chứng được bằng chương trình hoặc một cách đối chiếu độc lập rõ ràng.
- `CITATION_NAVIGABLE_IN_THIS_VIEW`: thao tác click/chuyển vị trí thực sự xảy ra trong view này.
- Không thể chứng minh → `PARTIAL` / `UNKNOWN`, ghi rõ vì sao.

## 5. Phase 3 — D2/U9: difficulty quick action (P1, thay đổi trạng thái)

**Điều kiện:** Chủ tài khoản đồng ý riêng rằng nút này có thể thay đổi nội dung lesson hoặc tiêu quota.

1. Chủ tài khoản tự mở một **lesson chưa từng nhắn Tutor**, để 4 quick actions đang hiển thị. Nếu không có thread trống, dừng `BLOCKED`, không tạo course/lesson mới khi chưa được phê duyệt.
2. **Trước khi click**, ghi snapshot đã redact: `contentVersion`, số block, tên block types, bài học có nội dung gì (chỉ hash text đã chuẩn hóa hoặc một mô tả từ PDF fixture), `upNextLessonId` nếu hiện hữu, và ảnh UI đã redacted nếu thực sự cần.
3. Nếu quan sát được, ghi cả `thread` lúc đầu có bao nhiêu tin nhắn và vị trí của 4 quick actions.
4. OpenCode bắt đầu capture **trước** hành động. Chủ tài khoản tự chọn duy nhất một quick action, ưu tiên `Đi sâu hơn vào phần toán`.
5. Khi Tutor hoàn tất, chỉ đọc dữ liệu UI/API trả về một cách thụ động; so sánh text/structure và `contentVersion`. Nếu cần reload để kiểm tra persistence, chủ tài khoản tự thực hiện.
6. Đừng dùng một request hậu kiểm có nội dung nhạy cảm để suy về thay đổi lesson. Nếu window lỗi `target_changed`, đánh dấu capture lỗi và xin mở lại target ở lần thử khác; không coi là test fail của sản phẩm.

### Phân loại

- `TUTOR_RESPONSE_ONLY`: chỉ lời đáp Tutor đổi, bài học không thấy thay đổi.
- `LESSON_CONTENT_CHANGED`: block/text lesson thay đổi được ghi nhận và kiểm chứng sau refresh; `contentVersion` có hoặc không tăng phải ghi riêng.
- `COURSE_PATH_CHANGED`: nodes/upNext thay đổi (ghi chép; chưa suy ra mastery algorithm).
- `NO_OBSERVABLE_EFFECT`: có window hợp lệ nhưng không phát hiện khác biệt theo các chỉ số đã xét.
- `INCONCLUSIVE`: thiếu baseline, thread không trống, hết hạn mức, target_changed, hoặc không có after-state.

**Không được gọi D2 là progress-driven adaptive learning.** Đây mới là user-triggered adjustment. D1, D3 và A4 chưa nằm trong scope phiên này.

## 6. File đầu ra (không ghi đè bằng chứng cũ)

Đọc báo cáo cũ, tạo hoặc cập nhật tối thiểu:

- `research/polyskill-blackbox/reports/phase3-sse-citation-difficulty.md`
- `research/polyskill-blackbox/evidence/phase3-observations-redacted.json` (metadata tối thiểu; không raw payload)
- `research/polyskill-blackbox/test-matrix.md` (ghi kết quả mới kèm session/case reference, giữ kết quả lịch sử)
- `research/polyskill-blackbox/reports/unknowns-and-next-tests.md` (chỉ đóng UNKNOWN đã có bằng chứng mới)

Không tự ý đưa raw captures, PDF test, oracle nội bộ hoặc real identifiers vào Git.

## 7. Acceptance criteria / tests

- [ ] Repo/branch/commit, `git status` được ghi lại trước thay đổi.
- [ ] Đọc được baseline, không giả định đã cấp quyền CDP nếu chưa xác minh.
- [ ] Mỗi phase có `PRECONDITION`, `OBSERVATION_WINDOW`, `EVIDENCE`, `VERDICT`, `LIMITATION`.
- [ ] Không có `disallowed_origin` hoặc nếu có phải nêu giới hạn coverage. `target_changed` phải đánh dấu invalid capture.
- [ ] Không kết luận tool identity chỉ từ UI badge; không kết luận thành công chỉ từ count.
- [ ] Không kết luận RAG thuật toán, vector DB, embeddings hoặc model chỉ từ source grounding.
- [ ] Không kết luận difficulty adaptation từ một câu trả lời dài hơn.
- [ ] Scan nội dung mới để tránh token/cookie/email/private IDs; nêu chính xác cách và kết quả scan, không báo `0 hit` khi chưa chạy.
- [ ] Chỉ báo `TESTED` / `PASS` nếu có bằng chứng hành động thật; nếu chưa chạy dùng `NOT TESTED` hoặc `BLOCKED`.
- [ ] Không sửa chức năng sản phẩm, không commit/push.

## 8. Báo cáo cuối cần có

1. `EXECUTION`: đã làm thực tế đến đâu; repo/status/lệnh và phiên bản công cụ.
2. `CASES`: U7, U13, U8, D2 — từng case `OBSERVED / NOT_OBSERVED / INCONCLUSIVE / BLOCKED / NOT_TESTED`.
3. `EVIDENCE`: ID cửa sổ, metadata và diff phù hợp; không chứa dữ liệu nhạy cảm.
4. `CLAIM REGISTER`: FACT / INFERENCE / UNKNOWN / PROPOSAL, mỗi claim có nguồn và giới hạn.
5. `ARCHITECTURE IMPACT`: đề xuất cụ thể cho `AI Learning Platform` nhưng không tự triển khai khi chưa được giao.
6. `NEXT`: tối đa 3 việc tiếp theo, nêu consent/quota cần thiết.

### Lưu ý đóng phiên

**Được phép:** Cập nhật báo cáo dựa trên quan sát trực tiếp, nêu unknown còn lại.
**Không được phép:** Tuyên bố đã khám phá thuật toán private backend, hoặc tự thực hiện thêm các hành động PolySkill ngoài giao diện do chủ tài khoản điều khiển.
