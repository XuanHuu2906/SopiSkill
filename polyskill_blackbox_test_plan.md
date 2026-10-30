# PolySkill — Quy trình kiểm thử Black-box (Windows + Chrome DevTools + REA)

**Phiên bản tài liệu:** 1.0 — 30/10/2026  
**Trạng thái:** PROPOSAL / NOT TESTED — tài liệu hướng dẫn, không phải báo cáo kết quả mới.  
**Mục đích:** Thu bằng chứng về khả năng grounding/RAG, AI Tutor tool calling, adaptive learning bằng thao tác hợp lệ trên tài khoản do chủ tài khoản điều khiển. Không tìm cách biết bí mật backend bằng truy cập trái phép.

## 0. Cơ sở chứng cứ và phạm vi

Đọc trước `polyskill-analysis-report.md` mục 4–7, `polyskill-dynamic-analysis.md` mục 0, 2–7, `02_PROJECT_CONTEXT.md` mục B, `03_ROADMAP_AND_BACKLOG.md` phần P2–P4.

- FACT (đã có): client có Tutor SSE, enum sáu tool, `contextRef {lessonId, blockIndex}`, `contentVersion`, `citationSchema` và trạng thái ingest. Runtime có 4 POST Tutor 200 dạng SSE và `toolCalls[4]` trong history; 4 tool names chưa biết. Lesson test trước đó có `source: null`.
- FACT về giới hạn: lần tạo course ban đầu có 82 API requests bị REA lọc do whitelist origin sai. Nội dung SSE frames không được REA mặc định lưu; client enum không xác minh event thực sự đã phát.
- INFERENCE: có cơ chế RAG/retrieval phía server.
- UNKNOWN: LLM/provider, embeddings, vector DB/index, BM25/cosine/hybrid/reranking, prompts, thuật toán adaptation thực tế.

Chỉ dùng UI công khai trên tài khoản được phép và quan sát request do trình duyệt tự phát sinh. Không replay/forge API, không dùng session người khác, không vượt quota/paywall, không đọc hoặc trích xuất secret. Chủ tài khoản tự đăng nhập và bấm mọi thao tác có thay đổi dữ liệu/chi phí. Dừng khi có lỗi quyền, captcha, hạn mức hoặc điều khoản không cho phép.

## 1. Môi trường Windows — thiết lập có kiểm tra

1. Mở PowerShell trên máy Windows (không mặc định chạy trong WSL). Kiểm tra `node -v`, `npm -v`, `npx.cmd -y rea-agents@latest --version` hoặc `rea --version` nếu cài global. Giữ lại version/đường dẫn thực tế. Nếu chưa kết nối REA với OpenCode, đọc https://morluto.github.io/rea/get-started/ và chạy `npx.cmd rea-agents@latest setup`, kiểm tra kế hoạch setup rồi khởi động lại OpenCode.
2. Dùng Chrome riêng profile vì Chrome 136+ không chấp nhận remote-debugging-port cho profile mặc định. Lệnh PowerShell tham khảo:

```powershell
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path $chrome)) { throw 'Hãy xác định đúng đường dẫn Chrome trước khi chạy' }
$profile = Join-Path $env:LOCALAPPDATA 'REA-PolySkill-Profile'
Start-Process -FilePath $chrome -ArgumentList @(
  '--remote-debugging-port=9222',
  '--remote-debugging-address=127.0.0.1',
  ('--user-data-dir="' + $profile + '"'),
  'https://web.polyskill.app'
)
```

3. Chỉ mở tab cần nghiên cứu trong profile này; chủ tài khoản đăng nhập thủ công, không đưa mật khẩu/2FA/token vào OpenCode. Kiểm tra CDP đã sẵn sàng bằng `Invoke-RestMethod http://127.0.0.1:9222/json/version | Select-Object Browser` (chỉ hiện trường Browser; không công bố WebSocket debugger URL).
4. Với một số bản REA cần bật cấu hình trước khi chạy agent/server MCP; xác minh bằng `--help` và ghi nhận cấu hình thực tế. Ví dụ PowerShell trong terminal thực thi REA:

```powershell
$env:REA_BROWSER_OBSERVE_ENABLED = 'true'
$env:REA_BROWSER_CDP_ENDPOINTS_JSON = '["http://127.0.0.1:9222"]'
$env:REA_BROWSER_ALLOWED_ORIGINS_JSON = '["https://web.polyskill.app","https://api.polyskill.app"]'
npx.cmd -y rea-agents@latest list-browser-targets --help
npx.cmd -y rea-agents@latest inspect-web-page --help
```

5. **Quan trọng:** trong nghiên cứu trước, `--allowed-origins` cần được lặp lại cho từng origin chứ không nối bằng dấu phẩy. Lệnh dưới đây là mẫu để đối chiếu `--help` với version đang cài; chỉ chạy nếu version của bạn hỗ trợ những flag này.

```powershell
npx.cmd -y rea-agents@latest list-browser-targets http://127.0.0.1:9222 `
  --allowed-origins https://web.polyskill.app `
  --json

# Chỉ lấy TARGET_ID thực tế của tab PolySkill trong output trên
npx.cmd -y rea-agents@latest inspect-web-page http://127.0.0.1:9222 TARGET_ID `
  --allowed-origins https://web.polyskill.app `
  --allowed-origins https://api.polyskill.app `
  --observation-ms 30000 `
  --include-json-body-shapes `
  --json
```

Nếu version yêu cầu `--approved`, có flag khác hoặc bị từ chối bởi scope policy: tham chiếu `--help` và điều chỉnh tối thiểu, không đoán tên flag và không nới whitelist. Mở quan sát **trước khi** thao tác; output chỉ phản ánh cửa sổ sau attach. REA là công cụ quan sát thụ động, không phải công cụ click UI.

## 2. Quan sát DevTools đi kèm

- Mở Chrome DevTools `F12` → `Network`, bật `Preserve log`, chọn `Fetch/XHR` khi lọc; không xuất HAR thô. Clear log ngay trước mỗi thử nghiệm, bắt đầu quay trước khi bấm.
- Với `POST /v1/courses/{id}/tutor/messages`: chọn request → `Headers` để kiểm tra `200`, `content-type: text/event-stream`; chọn `EventStream` (hoặc `Response` nếu tab không có) để kiểm tra loại sự kiện `delta`, `tool`, `confirm`, `done`, `error`, `restarted` nếu hiện ra. Chrome DevTools hỗ trợ EventStream cho Fetch/EventSource/XHR, nhưng việc tab/frames hiển thị còn phụ thuộc cách ứng dụng streaming. **Không kết luận event không tồn tại chỉ vì tab trống.**
- Chỉ ghi tên event, số lượng, trình tự, tổng thời gian, công cụ/nhãn nếu có và không nhạy cảm. Không chép tin nhắn riêng tư, access token, cookie, full URL chứa query nhạy cảm, headers authorization hay raw response.
- Với phần lịch sử tutor: xem request `GET /v1/courses/{id}/tutor`, ghi `toolCalls.length`, `contextLabel` hiện diện, tên tool chỉ nếu nhận được hợp lệ. Đối chiếu UI, request, response. Chọn một hành động ở UI rồi ghi event được tạo sau hành động đó; không tự gọi endpoint.
- Cách soát lỗi capture: số request thực sự bắt được, `disallowed_origin`, `attach_limited`, `policy_filtered`, `truncated`, `window_elapsed` và `target_changed` nếu có. Một capture bị lọc hoặc mất request không thể là bằng chứng phủ định.

## 3. Bộ tài liệu thử RAG (thuộc sở hữu của bạn)

Tạo `research/polyskill-blackbox/fixtures/rag_synthetic_v1.pdf` với ít nhất 3 trang, hoàn toàn là thông tin giả lập do bạn tự viết. Ghi rõ “Tài liệu thử nghiệm hư cấu; không phải kiến thức thực tế”. Không đưa thông tin cá nhân hoặc bài báo có bản quyền mà bạn không được quyền dùng.

- Trang 1: định nghĩa hư cấu về quy trình **LUMORA-731** có 3 giai đoạn: Chuẩn bị → Khớp mẫu → Xác thực.
- Trang 2: chính sách hư cấu, điểm kích hoạt **ORBIT-294** và ngưỡng **17 đơn vị**, mô tả số lượng rõ ràng.
- Trang 3: mục ngoại lệ: trong điều kiện **MƯA TÍM**, quy trình bỏ qua Khớp mẫu và đi thẳng Xác thực; thêm một mục dễ nhầm là **ORBIT-249** có ngưỡng 71 đơn vị để kiểm tra nhầm lẫn.

Lưu bản PDF nguồn làm oracle; ghi trang và câu trích nguyên gốc trong file **riêng ở máy bạn**, không tải oracle ra nơi công cộng. PDF tạo bằng thư viện local có sẵn; nếu thiếu, ghi BLOCKED thay vì cài lung tung hoặc dùng tài liệu bên thứ ba.

### RAG — các ca thử

| ID | Thao tác trên UI | Điều kiện đạt về hành vi | Không được kết luận |
|---|---|---|---|
| R1 | Tạo khóa từ PDF, hỏi “Theo tài liệu, LUMORA-731 có những giai đoạn nào?” | Trả lời đủ 3, không bổ sung sai | Chưa chứng minh vector RAG |
| R2 | Hỏi lại bằng cách diễn đạt khác, không lặp nhãn tiêu đề | Truy xuất đúng ý nghĩa từ tài liệu | Không biết embedding model |
| R3 | Hỏi “ORBIT-294 ngưỡng bao nhiêu?” rồi hỏi “ORBIT-249 ngưỡng bao nhiêu?” | Không trộn 17 và 71 | Không biết retriever/reranker |
| R4 | Hỏi “MƯA TÍM là ngoại lệ gì? dẫn nguồn cụ thể.” | Trả lời đúng và citation dẫn đúng trang/đoạn khi hệ thống hỗ trợ | Citation có thể được tạo mà không dùng vector search |
| R5 | Hỏi câu hỏi không có trong PDF: “Ai sáng chế LUMORA-731 vào năm nào?” | Nhận biết thiếu bằng chứng, không bịa tên/năm; nếu trả lời, ghi nhận lỗi grounding | Không khẳng định RAG không tồn tại chỉ bởi một lỗi |

Đối chứng (nếu quota cho phép): tạo course chỉ từ topic “LUMORA-731” *không* tải PDF và hỏi cùng câu. Nếu câu trả lời khác, tăng sức nặng bằng chứng hệ thống sử dụng nguồn, nhưng chưa tách biệt được prompt injection-free context injection so với retrieval. Test lặp tối thiểu 2 lần cho một số câu nếu budget cho phép; `n=1` chỉ là pilot.

**Outcome RAG:** `SOURCE_GROUNDING_OBSERVED` nếu có câu trả lời đúng thông tin độc nhất từ PDF; `CITATION_GROUNDED` nếu citation thực sự trỏ đúng vị trí; `RAG_MECHANISM_UNKNOWN` luôn giữ nguyên trừ khi có bằng chứng trực tiếp khác.

## 4. AI Agent / Tool Calling

| ID | Thao tác | Cần lưu bằng chứng | Kết luận giới hạn |
|---|---|---|---|
| A1 | Mở lesson, hỏi “Giải thích khái niệm đang học” | `contextRef` đúng lesson/block, `contextLabel`, SSE response | Tutor có context passing |
| A2 | Bấm quick action `explain_deeper` hoặc action tương đương thực sự thấy trên UI | `event: tool` nếu thấy, GET history `toolCalls` tăng, tool name nếu thấy | Có tool call tại runtime, không suy luận toàn bộ agent loop |
| A3 | Trên lesson từ PDF, yêu cầu tham khảo nguồn theo UI | `read_source` nếu có bằng chứng thực từ event/history và citation có thể mở | Không kết luận `read_source` chỉ từ enum |
| A4 | Nếu hiện UI `confirm`, chỉ thực hiện hành động an toàn được chủ tài khoản chấp thuận | Có bước xác nhận, outcome và trạng thái trước/sau | Không suy đoán quyền backend của tool |

Ghi rõ **UI function ≠ tool call**: không thấy `event: tool`/history thì không tuyên bố đã thực thi tool, dù câu trả lời có chất lượng tốt. Không sử dụng prompt để ép lộ system prompt hoặc gọi tool bị cấm.

## 5. Adaptive Learning

### Thiết kế A/B giới hạn

Tạo tối đa hai course trên **cùng tài khoản được phép**, cùng topic “Python: vòng lặp và danh sách”, dùng cùng ngôn ngữ, nhưng khác câu trả lời phỏng vấn:
- `NOVICE`: chưa biết lập trình, cần ví dụ trực quan, mục tiêu nhập môn, thời lượng giới hạn.
- `ADVANCED`: biết cú pháp Python và list, muốn bài nâng cao, cùng điều kiện thời lượng nếu UI cho phép.

Lưu snapshot đề cương, số bài, mục tiêu, mức độ phức tạp, khái niệm và quiz. Mã hóa nhãn A/B khi chấm để giảm thiên lệch; so rubric cụ thể: số khái niệm tiên quyết, ví dụ, độ sâu bài, câu hỏi suy luận, prerequisite.

| ID | Thao tác | Dấu hiệu quan sát | Giới hạn |
|---|---|---|---|
| D1 | So proposal/lesson của NOVICE vs ADVANCED | Có khác biệt nhất quán với input | Có personalization; không xác định thuật toán |
| D2 | Trong một lesson dùng quick action `harder/easier/more_practical` | Có thay đổi block/quiz/difficulty; ghi `contentVersion` nếu đổi | Điều chỉnh theo lệnh chưa phải adaptive tự động |
| D3 | Làm quiz sai có chủ đích ở lượt thử được phép rồi theo dõi bài gợi ý/feedback | Ghi điểm, `progress`, `upNextLessonId`, thay đổi độ khó nếu có | Một lần chưa đủ chứng minh Knowledge Tracing |

Nếu có quota/chỉ số học tập hạn chế, ưu tiên D1 rồi D2, chỉ chạy D3 khi được chủ tài khoản đồng ý vì có thể làm thay đổi hồ sơ học tập.

## 6. Evidence log an toàn

Lưu trong workspace của bạn, mặc định chỉ chia sẻ dữ liệu đã ẩn nhạy cảm:

```text
research/polyskill-blackbox/
  README.md
  test-matrix.md
  fixtures/                    # PDF tự tạo, không đẩy lên Git mặc định
  evidence/
    runs.csv                    # timestamp, test ID, thao tác, verdict, capture quality
    observations-redacted.json # HTTP method, path template, status, event types, counts
  reports/
    blackbox-findings.md
    unknowns-and-next-tests.md
```

Mẫu mỗi record:

```json
{
  "test_id": "A2",
  "observed_at": "2026-10-30T21:00:00+07:00",
  "mode": "USER_UI_PLUS_PASSIVE_CAPTURE",
  "evidence": ["POST /v1/courses/{courseId}/tutor/messages → 200 SSE", "GET /tutor history toolCalls count=4"],
  "capture_quality": "COMPLETE_WITHIN_WINDOW",
  "verdict": "OBSERVED",
  "claim_level": "FACT",
  "limits": ["toolCall names hidden", "no SSE body retained"],
  "source": "local:redacted-note-A2"
}
```

Dùng các nhãn `OBSERVED`, `NOT_OBSERVED_WITH_GOOD_COVERAGE`, `INCONCLUSIVE`, `BLOCKED`, `NOT_TESTED`. `NOT_OBSERVED` không có nghĩa là tính năng chắc chắn không tồn tại. Phân loại nhận định `FACT`, `INFERENCE`, `UNKNOWN`, `PROPOSAL`. Có thể dùng thang bằng chứng: E0=tên/enum trên client; E1=Network metadata; E2=runtime event/history; E3=thí nghiệm đối chứng lặp lại. E3 vẫn không xác định được thuật toán backend nếu có nhiều cách triển khai tương đương.

**Đánh giá:** Mỗi ca cần: action mô tả rõ; oracle/expected result; thời điểm; minh chứng từ UI và/hoặc request; outcome; hạn chế; không dùng PASS nếu chưa thao tác thật. Ghi `TESTED` chỉ với ca đã thực chạy. Nếu chưa có quyền/chi phí/thiết lập, ghi `BLOCKED` và lý do.

## 7. Tiêu chí hoàn thành đợt nghiên cứu

- RAG: ít nhất 4/5 test R1–R5 có bằng chứng hợp lệ, ghi rõ độ chính xác citation riêng biệt; nêu kết luận tối đa là source grounding/citation, không võ đoán vector DB.
- AGENT: ít nhất A1 và A2 có logs runtime đủ scope; nếu không thấy event nhưng có history, ghi sự khác biệt và hạn chế.
- ADAPT: D1 và D2 được so sánh với rubric; D3 tùy approval; nói rõ personalization theo input, user-triggered adjustment hay tự động thích nghi.
- Evidence: có version Chrome/REA, phạm vi origin, số request lọc, time window, dữ liệu được che, summary FACT/INFERENCE/UNKNOWN.
- Báo cáo cuối có riêng bảng `IMPLEMENTED` (script/file cục bộ), `TESTED`, `NOT TESTED`, `BLOCKED`. Không báo một tính năng PolySkill “PASS” dựa vào static frontend hay suy đoán.

**Mốc dừng:** Chủ tài khoản không phê duyệt thao tác; thiếu tài liệu nguồn; đụng quota/chi phí; yêu cầu captcha/bypass; tool capture thiếu quyền; có khả năng lộ PII/secret.

## 8. Tham khảo kỹ thuật

- `polyskill-analysis-report.md` — mục 4–7 (nghiên cứu đã có)
- `polyskill-dynamic-analysis.md` — mục 0, 2–7 (nghiên cứu đã có)
- https://github.com/morluto/rea/blob/main/docs/browser-observation.md — kiểm tra phạm vi và CLI phiên bản hiện cài
- https://morluto.github.io/rea/guides/browser/ — workflow list targets / inspect page
- https://github.com/morluto/rea/blob/main/docs/browser-scenario-contract.md — scenario riêng, không mặc định dùng để thao tác vào tài khoản
- https://developer.chrome.com/docs/devtools/network/reference/#analyze-events-in-a-stream — EventStream
- https://developer.chrome.com/blog/remote-debugging-port — Chrome 136+ yêu cầu user-data-dir không mặc định

**Không chép tài liệu này thành khẳng định đã chạy:** trên ChatGPT hiện chưa có quyền điều khiển browser Windows của bạn, và chưa có capture mới của phiên này.
