# CLAUDE CODE — REA DEEP AUDIT & SOPISKILL FUNCTIONAL PARITY

> **Loại tài liệu:** Nhiệm vụ độc lập để giao trực tiếp cho Claude Code (không phải OpenCode).  
> **Ngày soạn:** 2026-11-04.  
> **Sản phẩm tham chiếu:** PolySkill (`https://web.polyskill.app`).  
> **Sản phẩm cần đánh giá:** **SopiSkill** / AI Learning Platform (`https://github.com/XuanHuu2906/SopiSkill` — chỉ là URL nhận diện, phải xác nhận repo local/HEAD thực tế).  
> **Chế độ thực thi:** **AUDIT-ONLY / READ-ONLY BY DEFAULT**. Chỉ thu thập bằng chứng hợp lệ, kiểm tra mã nguồn và thực hiện các bài test an toàn trong môi trường thử nghiệm; **không tự sửa mã nguồn sản phẩm**.

---

## 0. MỆNH LỆNH CHO CLAUDE CODE

Bạn là **Principal Product Reverse-Engineering Analyst + QA Lead + Software Architect** được giao tiến hành **một vòng kiểm chứng cực kỳ kỹ lưỡng** bằng REA và các công cụ kiểm thử hợp lệ, rồi **đối chiếu PolySkill với ứng dụng SopiSkill đang thực sự tồn tại trong repository**.

**Mục tiêu của người dùng:** đưa SopiSkill đến mức **tương đồng cao nhất có thể về tính năng, luồng trải nghiệm, trạng thái, hành vi và chất lượng sử dụng** so với PolySkill; mục tiêu tham vọng là **99% trong phạm vi hành vi có thể quan sát và được phép kiểm chứng**.

**99% không phải kết quả có sẵn để xác nhận.** Bạn phải đo đạc trung thực. Không đánh đồng:
- 99% **coverage tính năng được quan sát** với 99% **trùng backend, model, thuật toán, mã nguồn, prompt, UI hoặc tài sản**;
- có endpoint/schema trong bundle với tính năng đã chạy thành công ở runtime;
- có code SopiSkill với đã chạy test;
- **MockProvider** với AI provider thực;
- trạng thái chưa quan sát với trạng thái đạt yêu cầu.

**Đích đến:** một **gap analysis có bằng chứng tái lập**, bảng kiểm tính năng theo trọng số, tỷ lệ tương đồng được giới hạn chính xác, danh sách lỗi và backlog ưu tiên để Claude Code hoặc coding agent triển khai **ở một nhiệm vụ sau khi người dùng duyệt**.

**Yêu cầu cuối cùng:** KHÔNG được kết luận “giống 99%” nếu chưa đủ bằng chứng, dù người dùng mong muốn điều đó.

---

## 1. NGUỒN SỰ THẬT PHẢI ĐỌC TRƯỚC

Đọc theo thứ tự, **kiểm tra sự tồn tại thực tế** (ở repo, thư mục `docs/`, thư mục nghiên cứu hoặc đường dẫn người dùng đã cung cấp):

1. `AGENTS.md`, `CLAUDE.md` (nếu có), quy tắc kỹ thuật hiện hành trong repo SopiSkill.
2. `polyskill-analysis-report.md` — khảo sát **tĩnh**, REA 6.7.0.
3. `polyskill-dynamic-analysis.md` — khảo sát **runtime** bằng Chrome CDP / REA, ngày 2026-10-30.
4. `02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md` (nếu tài liệu nằm ngoài repo, tìm trong thư mục nghiên cứu được cấp phép).
5. `docs/development-progress.md` và/hoặc `development-progress.md` — **lịch sử nhóm báo cáo**, không tự coi là test mới.
6. `docs/architecture.md`, `docs/database-design.md`, `docs/implementation-plan.md`, `docs/llm-provider.md`, `docs/migration-runbook.md` nếu hiện có.
7. `SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md` hoặc `docs/MASTER_IMPLEMENTATION_PLAN.md` nếu hiện có.
8. Báo cáo `Bao_cao_PolySkill_Gia_su_AI_Tong_hop_Nguon.docx` nếu có; tài liệu này là tổng hợp nghiệp vụ, **không thay thế chứng cứ runtime**.
9. **Repository local thật**: frontend, backend, workers, migrations, test suite, Docker config, routes, schemas và provider adapters.

> **Nếu thiếu báo cáo REA cũ:** ghi `BLOCKED: missing historical evidence`, yêu cầu cung cấp file hoặc đường dẫn; vẫn có thể audit phần repo hiện hữu, nhưng không tự bịa lại báo cáo cũ. Không tự tải các file riêng tư từ GitHub/web hoặc giả định đã tồn tại.

### Thứ tự ưu tiên bằng chứng

| Loại bằng chứng | Có thể dùng để kết luận | Không thể tự suy ra |
|---|---|---|
| SopiSkill source tại `HEAD` + working tree | **IMPLEMENTED** khi kiểm tra mã nguồn thật | Đã chạy đúng, đã deploy |
| SopiSkill tests **vừa chạy** + logs/exit codes | **TESTED** với trường hợp cụ thể | Toàn bộ tính năng không có lỗi |
| PolySkill UI thao tác bằng tài khoản được phép + REA network metadata | **OBSERVED_RUNTIME** trong phạm vi capture | Thuật toán backend, mọi edge case |
| PolySkill public frontend bundle/call-sites | **OBSERVED_STATIC** về client/schema/call site | Tính năng đã chạy, server thực hiện đúng |
| Tài liệu thiết kế/nhật ký cũ | **REPORTED / DESIGN** | Hiện tại đã triển khai đầy đủ |
| Giả thuyết công nghệ server | **INFERENCE** | FACT hoặc đã xác minh |

Mọi nhận định quan trọng phải mang một trong các nhãn `FACT / INFERENCE / UNKNOWN / PROPOSAL` và có phân loại nguồn (`STATIC / RUNTIME / SOPISKILL_CODE / SOPISKILL_TEST / REPORTED`).

### Điểm xuất phát đã biết (chỉ để định hướng, phải xác nhận lại)

- PolySkill client được báo cáo: Expo SDK 57, React Native Web, React 19.2.3, Metro, TanStack Query; đây **không phải yêu cầu** đổi frontend SopiSkill sang Expo.
- Luồng tham chiếu: `topic/source → 5 interview questions → proposal → approve → generation → lesson blocks → quiz → tutor`; generation frontend poll khoảng 2 giây.
- 6 block types được nhắc tới: `teach`, `mc`, `blank`, `order`, `match`, `short`; có `contentVersion`, `glossary`, `figures`, prefetch.
- Tutor client có `contextRef(lessonId, blockIndex)`, SSE, `toolCalls`, `contextLabel`, allowance; tên tool xuất hiện trong client **không chứng minh** công cụ đã chạy ở server.
- PolySkill source types: arXiv/web/PDF; **source ingest chưa được thử ở báo cáo dynamic cũ**.
- **UNKNOWN**: PolySkill dùng LLM/provider/model nào; vector DB/embeddings/retrieval có thật không; backend prompts và thuật toán nội bộ; payload/thứ tự sự kiện SSE thực trong capture cũ.
- Báo cáo runtime trước có **lỗi `--allowed-origins`**: các lượt đầu lọc bỏ API requests. Lượt đã sửa dùng **cờ lặp riêng cho mỗi origin**, không phải một chuỗi gộp. Không coi 82 requests bị lọc là bằng chứng nội dung generation.
- Nhật ký SopiSkill ngày 2026-10-30 **báo cáo** đã làm P0–P2.0, 119 pytest passed / 6 skipped và 35/35 E2E trong một lần chạy trước; có 3 request smoke với LLM thật. Đó là **bằng chứng lịch sử được báo cáo**, không phải kết quả kiểm chứng hôm nay. P3 Tutor, P4 RAG, gamification nâng cao trong các tài liệu cũ có thể vẫn thiếu; **kiểm tra repo hiện tại trước khi phán quyết**.

---

## 2. GIỚI HẠN QUYỀN, AN TOÀN VÀ CÁC ĐIỂM DỪNG

### 2.1 Được phép trong nhiệm vụ này

- Đọc source và chạy các lệnh **chẩn đoán không phá hủy** trên repo SopiSkill do người dùng kiểm soát.
- Kiểm tra REA CLI/help/version, target browser được người dùng mở bằng tài khoản hợp lệ.
- Quan sát PolySkill bằng cách **đi qua giao diện bình thường**; lưu metadata/shape/screenshot đã che dữ liệu nhạy cảm nếu được phép.
- Chạy unit/integration tests trên **test database/fixture cô lập** và kiểm thử ứng dụng SopiSkill tại local/staging do người dùng kiểm soát, sau khi xác nhận không làm hỏng dữ liệu thật.
- Phân tích sự khác biệt về hành vi, lập đề xuất kiến trúc riêng và backlog.


---

## 3. PHẠM VI VÀ CÁC CÂU HỎI NGHIÊN CỨU

Trả lời **bằng chứng**, không bằng cảm giác:

1. PolySkill **hiện nay** có những hành trình/tính năng nào mà tài khoản test có thể dùng? Chứng cứ cũ nào còn đúng, chứng cứ nào đã thay đổi?
2. Đối với từng hành trình, UI làm gì, request/response **shape** thế nào, trạng thái, timing, lỗi, progress, persistence và recovery ra sao?
3. SopiSkill có code tương ứng không, code có được test chưa, UI có thực hiện được hành vi tương đương không?
4. Tính năng **thiếu hoàn toàn**, có nhưng **chưa nối end-to-end**, có nhưng **sai semantics**, và có nhưng **chưa được test** là những gì?
5. Các khía cạnh cá nhân hóa và AI Tutor/RAG có bằng chứng chất lượng hay chỉ có khả năng giao thức?
6. Những gap nào chặn trải nghiệm cốt lõi, những gap nào chỉ là polish, gamification, billing, khác biệt không cần thiết?
7. Có đủ căn cứ để đo mức tương đồng hay chỉ có thể đưa **ước lượng giới hạn theo phạm vi quan sát**?
8. Để tiến gần mục tiêu 99% **về chức năng và trải nghiệm hợp pháp**, cần thực hiện các phase nào, file nào, test nào, và tiêu chí nghiệm thu nào?

---

## 4. QUY TRÌNH BẮT BUỘC — LÀM THEO THỨ TỰ

### PHASE A — Repo audit + setup evidence

1. Xác định `pwd`, thư mục gốc repo SopiSkill, hệ điều hành/shell, phiên bản runtime và Docker. Không giả định Windows PowerShell tương đương Git Bash.
2. Chạy lệnh quan sát:

   ```bash
   git status --short
   git branch --show-current
   git rev-parse HEAD
   git remote -v
   rea --version
   rea --help
   rea list-browser-targets --help
   rea inspect-web-page --help
   rea analyze-web-bundle --help
   ```

   Nếu lệnh không tồn tại, ghi nguyên văn lỗi và kiểm tra vị trí cài REA bằng cách không phá hủy. `rea capture-browser-scenario --help` **chỉ chạy nếu `rea --help` liệt kê subcommand đó**. Không tự bịa option/flag; đọc CLI `--help` phiên bản thực tế trước khi xây command.
3. Đọc `CLAUDE.md`, `AGENTS.md`, tài liệu hiện có; phát hiện actual `frontend/` hay `apps/web/`, `backend/` hay `services/api/` từ filesystem.
4. Lập **manifest hiện trạng**: branch + HEAD + dirty state, các thành phần, migration head, config provider (chỉ tên biến, không giá trị secret), test files, route map. KHÔNG thực thi thay đổi DB.
5. Thiết lập `docs/audits/polyskill-parity-YYYY-MM-DD/` **chỉ để ghi báo cáo audit**; nếu repo không cho phép tạo file, xuất ra một thư mục audit ngoài repo được cho phép. Không sửa code sản phẩm.
6. Sao lưu các báo cáo REA cũ theo cách **giữ nguyên nội dung** (hoặc chỉ lập tham chiếu/file hash); ghi rõ thời điểm và những giới hạn của chúng.

**Gate A:** có manifest repo và version REA thật, không có thay đổi source/config/DB.

### PHASE B — Kiểm chứng PolySkill bằng REA và browser (read-only observation)

1. Yêu cầu người dùng **tự đăng nhập** tài khoản PolySkill hợp lệ nếu chưa sẵn sàng. Không đọc/copy token/cookie.
2. Kiểm tra browser target thực bằng `rea list-browser-targets`; không dùng target ID của báo cáo 2026-10-30 vì có thể đã đổi.
3. Attach capture **trước khi người dùng bắt đầu luồng thao tác**; kiểm tra 2 origins đúng (`web.polyskill.app`, `api.polyskill.app`), cờ `--allowed-origins` **lặp theo đúng help**. Kiểm tra số request bị `disallowed_origin`. Nếu vẫn lọc API, sửa cấu hình rồi **quan sát lại** (khi còn quyền/quota); không tự kết luận từ capture lỗi.
4. Chỉ quan sát requests/response metadata và cấu trúc đã redact bằng REA. Bật các lựa chọn bao gồm accessibility/network/timing **nếu CLI thật hỗ trợ**. Nếu dùng DevTools để xác minh SSE: chỉ ghi event type/count/order và hành vi UI, **không sao chép nội dung người dùng/response bí mật**.
5. Với mỗi kịch bản trong §5, thực hiện qua **giao diện sản phẩm** khi người dùng cho phép; ghi timestamp, thao tác, state trước/sau, network status/shape, UI evidence, hạn chế tài khoản. Khi quota không đủ hoặc thao tác làm phát sinh chi phí không được duyệt: `BLOCKED`.
6. So lại REA static **chỉ nếu bundle công khai hợp lệ và tool cho phép**. Lưu hash/version để đối chiếu delta, không lưu, chuyển giao hoặc chép lại source bundle vào sản phẩm.
7. Kiểm tra các trường hợp failure **chỉ trong UI bình thường** (back, reload, đóng/mở trang, retry bằng nút có sẵn). **Không chủ động gây lỗi network/server, giả mạo request, stress test, hay kiểm thử authorization đối với PolySkill.**
8. Tách bằng chứng **client call-site** và **runtime traffic** ở mọi dòng; REA có thể không giữ payload SSE — không gắn nhãn runtime verified cho event không bắt được.

**Gate B:** evidence index đầy đủ, provenance rõ, không có yêu cầu vượt quyền/chi phí, có bảng coverage các kịch bản `OBSERVED / PARTIAL / NOT OBSERVABLE / BLOCKED`.

### PHASE C — Audit độc lập SopiSkill

1. Đi từ **code thực tế** (không coi progress docs là source of truth):
   - Frontend routes/pages/components/hooks, auth/session, quiz player, tutor panel, source upload UI, profile, i18n, error/loading states.
   - Backend routes/schemas/services, state machine, auth/CSRF/ownership, job lifecycle, grading, tutor SSE/tools, citations, progress/gamification, quotas.
   - Worker/Celery, provider adapter, mock-vs-real mode, migration history, storage adapter, tests, feature flags.
2. Với từng tính năng, ghi **path + symbol + dòng (nếu có)**, trạng thái `IMPLEMENTED / NOT IMPLEMENTED / PARTIAL`, phụ thuộc và known limitations.
3. Lấy `docs/development-progress.md` làm **thông tin lịch sử cần xác minh lại**, không nhận kết quả test trước đây là kết quả lần này.
4. Chạy trên **test DB** hoặc stack local an toàn đã xác minh dữ liệu, nếu environment cho phép:

   ```bash
   # Từ backend, nếu đúng layout/venv hiện có
   python -m pytest -q

   # Từ frontend, nếu npm scripts có tồn tại
   npm run build
   # npx tsc --noEmit   # chỉ nếu dự án thực tế hỗ trợ

   # Quan sát trước khi khởi động thêm bất kỳ service nào
   docker compose config
   docker compose ps
   ```

   **Không được tự chạy `docker compose up` trên DB chính có dữ liệu cần bảo vệ hoặc migration auto-upgrade chưa kiểm tra.** Nếu có stack sandbox hợp lệ và quyền chạy, thực hiện E2E baseline theo script thật (ví dụ `backend/e2e_acceptance.py`) rồi ghi command + exit code + log. Nếu thiếu môi trường: `NOT TESTED` cùng blocker, không giả định PASS.
5. Với các kịch bản trên PolySkill được quan sát, chạy **kịch bản tương đương trên SopiSkill** bằng người dùng/test data thuộc quyền sở hữu, ghi screenshot (nếu có), network metadata, persistence sau reload, lỗi, độ trễ.
6. Với SopiSkill, có thể test negative security trên **tài khoản thử nghiệm A/B do nhóm kiểm soát**: cross-user ownership, CSRF, answer key leak, duplicate attempts/XP, idempotency, tutor context authorization; chỉ dùng môi trường test/sandbox.
7. Kiểm tra API compatibility nội bộ SopiSkill, **không yêu cầu** trùng URL/method/field name với API PolySkill nếu semantics đúng.

**Gate C:** mỗi hạng mục có `IMPLEMENTED`, `TESTED`, `NOT TESTED` hoặc `BLOCKED` với chứng cứ code và logs riêng; test không gây phá dữ liệu.

### PHASE D — Đối chiếu, lượng hóa, kết luận và backlog

1. Dựng **ma trận parity một dòng / một observable requirement** từ §5 và §6.
2. Với mỗi requirement đối chiếu **ít nhất một evidence PolySkill** (static/runtime) với **một evidence SopiSkill** (source/test/UI), hoặc ghi rõ nguyên nhân thiếu.
3. Chấm điểm theo quy tắc §7, công bố phạm vi đo và evidence coverage trước khi nói phần trăm.
4. Tạo backlog ưu tiên cho **mỗi gap thực sự có ý nghĩa**: root cause khả dĩ, module/file, API/data contract riêng, thứ tự thực hiện, tiêu chí nghiệm thu, test, security, migration/rollback, estimate mức độ `S/M/L` (**không bịa ngày/giờ làm xong**).
5. Report phải phân biệt rõ: **PARITY GAP**, **BUG**, **UNTESTED**, **UNKNOWN REFERENCE**, **INTENTIONAL DIFFERENCE**, **FUTURE/NON-MVP**.
6. **Chỉ đề xuất** phương án sửa; nếu người dùng sau đó chấp thuận triển khai thì tạo nhiệm vụ/PR riêng theo master plan. Không sửa code trong vòng audit này.

**Gate D:** báo cáo có thể audit lại, không có chứng cứ bịa, điểm số có denominator và giới hạn rõ.

---

## 5. BỘ KỊCH BẢN KIỂM TRA CHI TIẾT (KHÔNG BỎ QUA ÂM THẦM)

**Quy ước cột cho mỗi scenario:** `ID`, `precondition`, `steps` qua UI hợp lệ, `expected behavior observed`, `reference evidence`, `SopiSkill evidence`, `result`, `risk`, `notes`. Mỗi tình huống cần đối chiếu **happy path, state/persistence, error/recovery** khi được phép; không tự tạo lỗi ở PolySkill.

### Nhóm A — Trang đầu, tài khoản, onboarding, hồ sơ

- **A01** Landing/dashboard: trạng thái chưa đăng nhập / đã đăng nhập, danh sách khóa học, resume, empty/error/loading.
- **A02** Onboarding: ngôn ngữ, vai trò, mục tiêu, trải nghiệm lần đầu; ngôn ngữ chọn có ảnh hưởng nội dung thực không.
- **A03** Login/logout/profile: điều hướng, refresh/reload; không so sánh giao thức token nội bộ bằng cách lấy secret.
- **A04** Danh sách khóa học, profile/stats, tiến độ, đổi thiết bị/trình duyệt nếu người dùng kiểm soát; cache/session isolation chỉ test phá quyền trên SopiSkill.

### Nhóm B — Tạo khóa học, interview, proposal (cực kỳ quan trọng)

- **B01** Nhập topic ngắn, dài hợp lệ; validation và thông báo lỗi UI.
- **B02** Interview: số câu, kiểu trả lời, thứ tự, câu hỏi có thay đổi theo topic/proficiency hay chỉ theo template (muốn kết luận personalization phải có ≥2 case hợp lệ được duyệt).
- **B03** Đi từng câu, quay lại/chỉnh sửa, reload giữa interview, resume, nút Continue/Back, xử lý bỏ trống.
- **B04** Proposal: `units`, `lessons`, objectives/outcomes, checkpoints/project nếu UI có; khả năng xem trước/chỉnh sửa/yêu cầu tutor revise.
- **B05** Approve: xác nhận, chống submit hai lần, trạng thái đề cương đã duyệt.
- **B06** So sánh 2 learner profiles trên cùng topic **chỉ khi quota/chi phí được duyệt**; đo thay đổi về mục tiêu, độ khó, ví dụ, cấu trúc course. Nếu không đủ mẫu: `NOT VERIFIED`, không tuyên bố personalized như nhau.

### Nhóm C — Generation và độ tin cậy

- **C01** Các stage/status UI, progress theo thời gian, polling (không khẳng định chính xác timing nếu không bắt được).
- **C02** Course ready: số unit/lesson, thứ tự, liên kết học; nội dung có thực sự khác theo input không.
- **C03** Back/reload trong generation; trạng thái dữ liệu bền vững; retry khi UI cho phép.
- **C04** Generation fail/timeout/partial ready: chỉ quan sát khi xảy ra tự nhiên trên PolySkill, không cố gây lỗi; trên SopiSkill kiểm thử failure injection an toàn trong sandbox.
- **C05** Không nhân đôi courses/lessons/jobs khi retry ở SopiSkill; worker claim, recovery, outbox, `contentVersion`, chi phí LLM. Không suy backend PolySkill sử dụng Celery/Redis.

### Nhóm D — Lesson Engine, knowledge path và nội dung

- **D01** Course path/unit graph: khóa/mở bài, `upNextLessonId`, trạng thái, paywall indicators; không vượt paywall.
- **D02** `teach`: paragraphs, formatting, terms/glossary, code/math, media/figure, khả năng đọc.
- **D03** `mc`: lựa chọn, feedback, retry, trạng thái sau submit.
- **D04** `blank`: nhập đáp án/chỗ trống, validation/case handling; có bị lộ key không (kiểm tra SopiSkill server).
- **D05** `order`: drag/tap để sắp xếp, shuffle, chấm điểm.
- **D06** `match`: ghép cặp, shuffle, feedback.
- **D07** `short`: cách gửi/hiển thị chấm tự luận; **không tuyên bố LLM grading nếu chưa chứng minh**.
- **D08** Figure types được hỗ trợ trong client/schema (formula/visual/diagram), render và accessibility trên SopiSkill; có trạng thái không hỗ trợ không.
- **D09** Bước lesson, next/previous, progress trong bài, prefetch lesson tiếp theo, restore sau reload.
- **D10** Content versioning: quiz attempt cũ, regenerate, cache invalidation; làm ở SopiSkill sandbox, không cố sửa khóa PolySkill.
- **D11** Glossary, math/notation, multilingual text, mobile responsive, keyboard, states (loading/empty/error).

### Nhóm E — Quiz, attempts, progress, phần thưởng

- **E01** Submit quiz: request schema đã redact, score và feedback, khả năng xem giải thích kết quả.
- **E02** `durationMs`, attempt timing, nộp nhiều lần, idempotency. Chỉ chứng minh **server idempotency** khi test được hành vi, không suy từ trường `clientAttemptId`.
- **E03** Progress completed/total/percent, resume sau reload/logout/login.
- **E04** XP/streak/hearts/goal/levels/milestones: cái nào thực sự render và thay đổi sau lesson; việc schema có field không đồng nghĩa UI có tính năng hoàn chỉnh.
- **E05** SopiSkill chống answer key leak trước submit; không nhận kết quả `correct=true` do client tự khai; XP không farm qua requests đồng thời; version mismatch lỗi rõ.

### Nhóm F — AI Tutor & agent behavior (**ưu tiên cao**)

- **F01** Tutor mở ở các entrypoint: trong lesson, `teach_block`, `wrong_answer`, `term`, `proposal`, `path_harder` nếu UI có; phân biệt client enum với trạng thái runtime.
- **F02** ContextRef: lesson/block cụ thể; so sánh phản hồi trong ngữ cảnh và contextLabel/history; check permission trên **SopiSkill**.
- **F03** Streaming: loading → deltas → done/error; tốc độ tương đối, scrolling, cancel; sự kiện SSE chỉ ghi **được quan sát nếu thực sự capture**.
- **F04** Thread/history: reply tiếp, reload, thread grouping, sealed status, context retention, isolation giữa hai người dùng SopiSkill.
- **F05** Quick actions: explain deeper, easier/harder/more practical, sửa đề cương; map UI action → observable result, **không tự khẳng định một tool backend cụ thể chạy**.
- **F06** Tool calling: `toolCalls`/summary/confirmation; tool names trong frontend PolySkill có thể không thực thi. SopiSkill phải có allowlist/authorization/safe tool audit.
- **F07** Quota/allowance/usage-limit UI: chỉ xem trạng thái hiện có; **không cố cạn quota của PolySkill**. SopiSkill có thể test local vượt quota.
- **F08** Stop/cancel, interrupted stream, retry/replay và `Last-Event-ID`: chỉ thực nghiệm hợp lệ và có quyền; không gọi resumable nếu không có event-log/replay proof.
- **F09** Tutor pedagogy: có hướng dẫn/gợi mở theo bước, sửa hiểu nhầm, đưa đáp án khi phù hợp, không bịa kiến thức. Dùng rubric review chứ không đoán thuật toán/prompt.

### Nhóm G — Source ingest và citations (**ưu tiên cao, hiện thiếu evidence cũ**)

- **G01** Các entrypoint arXiv/web/PDF, loại input, file size/status/error UI; **chỉ** kiểm tra upload khi người dùng duyệt tài liệu hợp pháp và mức sử dụng.
- **G02** Ingest status `awaiting_upload/pending/extracting/ready/failed` nếu thấy; không suy nội bộ extract/embedding từ tên status.
- **G03** Course được tạo từ nguồn; source attribution, document references, citations dẫn tới đoạn/trang thật; kiểm tra nguồn bản quyền/permissions.
- **G04** Tutor read_source/citation: chỉ phân loại `runtime verified` khi thấy nguồn thật và citation resolve. `citationSchema` ở bundle là **STATIC**, không đủ chứng minh RAG server-side.
- **G05** Kiểm tra riêng SopiSkill: PDF ingest safety, provenance page/chunk, retrieval/embedding version, citation validator, SSRF, prompt injection, owner scope, không bịa citation.
- **G06** Trường hợp không có bằng chứng: hệ thống phải từ chối trích dẫn giả; SopiSkill kiểm thử bằng fixture, không gây hại đến sản phẩm tham chiếu.

### Nhóm H — Phi chức năng và khác biệt có chủ đích

- **H01** Lỗi mạng và phục hồi/điều hướng (PolySkill chỉ quan sát tự nhiên; SopiSkill được test sandbox).
- **H02** Accessibility, mobile viewport, keyboard, giảm chuyển động, screen readers (chỉ claim khi test).
- **H03** i18n Vietnamese/English, course language, UX rõ ràng; **không chép thiết kế pixel-perfect**.
- **H04** Security SopiSkill: auth, CSRF, object ownership, rate limit, safe retries, secret redaction, output/answer-key isolation.
- **H05** Performance: ghi sample size, network và thời gian nếu đo được; **không so sánh latency AI từ một request đơn lẻ như benchmark đáng tin cậy**.
- **H06** Billing, plans, paywall, social/notifications: ghi feature coverage/blocked/intentional differences; không tự mua gói hoặc ưu tiên billing khi core flow còn thiếu.

---

## 6. MẪU RECORD BẰNG CHỨNG VÀ MA TRẬN PARITY

### 6.1 Mỗi evidence phải trace được

Mẫu trong `evidence-index.md`:

| Evidence ID | System | Source type | Scenario | Timestamp (timezone) | File/path/hash hoặc CLI log | Finding | Caveat |
|---|---|---|---|---|---|---|---|
| PS-R-001 | PolySkill | RUNTIME | F02 | YYYY-MM-DD HH:mm +07 | `captures/...` | `contextRef` shape xuất hiện | không lưu value |
| PS-S-001 | PolySkill | STATIC | F06 | YYYY-MM-DD | hash bundle + section | Tool enum tồn tại trong client | chưa chứng minh tool đã chạy |
| SS-C-001 | SopiSkill | CODE | F02 | YYYY-MM-DD | `backend/...:symbol` | Handler hiện diện | chưa được test |
| SS-T-001 | SopiSkill | TEST | F02 | YYYY-MM-DD | `logs/pytest-...txt` | Test case + exit 0 | chỉ covers test fixtures |

Các hàng trên **chỉ là template minh họa**, tuyệt đối không giữ như evidence thật nếu chưa chạy.

### 6.2 Mẫu ma trận cho `parity-matrix.md` hoặc `.csv`

| ID | Requirement/hành vi tham chiếu | PolySkill evidence + level | SopiSkill file + test evidence | Ref observable? | Match `0/0.5/1/UNKNOWN` | Severity | Gap type | Next test/fix |
|---|---|---|---|---|---|---|---|---|
| F02 | Tutor hiểu context block đang học | `PS-R-...` | `SS-C-...`, `SS-T-...` | Yes | 0.5 | P0 | PARTIAL | ... |

**Chỉ là dòng minh họa**; thay tất cả bằng kết quả kiểm chứng. Dùng đủ chi tiết để người khác tự kiểm tra đường dẫn, scenario, kết luận.

### 6.3 Quy tắc phân loại nghiêm ngặt

- `MATCHED`: hai ứng dụng **được quan sát chạy** với cùng kết quả nghiệp vụ cốt lõi; không yêu cầu giống implementation/API URL.
- `PARTIAL`: kết quả khác đáng kể, hoặc chạy được một phần end-to-end.
- `MISSING`: tham chiếu có bằng chứng rõ, SopiSkill không có code/hành vi tương ứng.
- `UNTESTED`: có code nhưng không chạy được test tương ứng.
- `UNKNOWN_REFERENCE`: PolySkill chỉ có client declaration/không đủ quyền quan sát hành vi cần kiểm tra.
- `INTENTIONAL_DIFFERENCE`: lựa chọn kiến trúc/branding/UX độc lập không làm mất hành vi nghiệp vụ.
- `BLOCKED`: thiếu quyền, quota, môi trường, dữ liệu mẫu hoặc budget.

Không cho điểm tối đa chỉ vì tên endpoint, component hoặc schema giống nhau. Không cho 0 điểm vì dùng framework/backend khác.

---

## 7. CHẤM ĐIỂM GẦN 99% — **CÓ DENOMINATOR VÀ ĐỘ TIN CẬY**

### 7.1 Trọng số đề xuất theo trải nghiệm người học (tổng 100)

| Miền | Trọng số |
|---|---:|
| A. Onboarding, auth, dashboard và hồ sơ | 8 |
| B. Topic → 5 interview → proposal/edit/approve | 18 |
| C. Generation/status/retry/reliability | 14 |
| D. Lesson blocks, path, figures, glossary, navigation | 18 |
| E. Quiz/grading/progress/attempts/rewards | 12 |
| F. Tutor ngữ cảnh, streaming, history, tools, allowance | 18 |
| G. Sources PDF/web/arXiv, provenance, citations | 9 |
| H. Khả dụng UX, accessibility, robustness | 3 |
| **Tổng** | **100** |

**Đây là `PROPOSAL` cách đo functional parity**, không phải trọng số do PolySkill công bố. Chia các mục trong từng miền thành các requirements nhỏ có tổng trọng số khớp. Ghi đầy đủ rubric / scoring sheet, đừng tự điều chỉnh trọng số sau khi thấy kết quả.

### 7.2 Phân biệt 3 con số

1. **Evidence Coverage (%)** = `(tổng trọng số của requirements có cả PolySkill runtime-evidence đủ mạnh và SopiSkill được đánh giá/test tương ứng) / 100 × 100`.
2. **Measured Parity (%)** = `(tổng w_i × match_i) / (tổng w_i eligible) × 100`, với `match_i = 1, 0.5, 0`; mẫu số **chỉ gồm requirements đủ điều kiện đánh giá**. Không tính UNKNOWN vào MATCHED.
3. **Conservative Floor (%)** = `tổng w_i × match_i / 100 × 100` (đối với các mục chưa đo, điểm đóng góp = 0 **chỉ cho lower bound toán học**, **không** gọi chúng là tính năng lỗi/thiếu).

Ngoài ra báo `Unknown/Blocked Weight (%)`. Nếu cần upper bound: `Conservative Floor + Unknown/Blocked Weight` (giả định tất cả unknown đều match — **không phải điểm đo**).

**Không được viết 'SopiSkill đạt 99% so với PolySkill' trừ khi:**

- `Evidence Coverage ≥95%` theo bộ rubric đã công bố;
- `Measured Parity ≥99%` **và** `Conservative Floor ≥95%`;
- **không có gap P0** trong topic → interview → proposal → generation → lesson/quiz → tutor trên phạm vi được duyệt;
- các bài test E2E và security cần thiết đã chạy có log/exit code, không phải chỉ code review;
- ghi rõ tuyên bố là **'99% functional parity trên phạm vi quan sát được trong audit [ngày]'**, **không** phải bản sao tổng thể hay backend giống hệt.

Nếu không đạt ngưỡng hoặc không có đủ coverage, báo: `CHƯA ĐỦ CĂN CỨ ĐỂ XÁC NHẬN 99%` kèm các con số đo được và lý do. Không dùng điểm cảm tính dựa vào số route/endpoint hoặc số dòng code.

### 7.3 Chất lượng AI cần đánh giá riêng, không suy từ schema

Dùng **ít nhất** một bộ test case có quyền sử dụng (một phần chạy offline/mock, phần LLM thật chỉ khi có phê duyệt), đánh giá theo rubric:

- Mục tiêu học sát profile và topic (0–4).
- Sự mạch lạc của đề cương/bài học, độ khó, ví dụ và hoạt động học (0–4).
- Tính đúng đắn và nhất quán đáp án quiz (0–4).
- Tutor ưu tiên gợi mở, sửa hiểu nhầm, grounding đúng lesson (0–4).
- Không bịa citation, xử lý thiếu nguồn đúng cách (0–4).

Cung cấp N, mô tả dữ liệu, reviewer/rubric, score distribution, disagreement. **Không suy chất lượng cao chỉ vì LLM trả JSON hợp lệ hoặc 3 smoke requests HTTP 200.** Không cần bắt chước model/provider PolySkill vốn chưa xác định.

---

## 8. CÁC GAP ĐÃ BIẾT CẦN KIỂM TRA TRƯỚC (KHÔNG COI LÀ KẾT LUẬN MỚI)

Dựa trên báo cáo lịch sử, ưu tiên xác minh những phần sau từ **repo hiện tại**:

1. **AI Tutor:** streaming SSE, thread/history, contextRef owner check, allowlist tools, stop/replay, allowance — tài liệu 2026-10-30 chưa chứng minh đã triển khai P3.
2. **Source Ingest + RAG:** PDF, web/arXiv, chunk/page provenance, retrieval, verified citations — tài liệu 2026-10-30 chưa chứng minh đã triển khai P4.
3. **Chất lượng generation thật:** adapter P2.0 và 3 smoke requests đã được báo cáo, nhưng 10-topic eval, pedagogical DAG/hierarchical real E2E có thể chưa hoàn thiện.
4. **Lesson UX & structured figures:** 6 block types và glossary/figures là các requirement khác nhau; có schema không đồng nghĩa UI render đủ.
5. **Proposal edit/revise** qua UI/Tutor và state/versioning.
6. **Gamification, profile, i18n, paywall**: phân biệt core gap và optional/deferred, không ưu tiên thanh toán trước việc học.
7. **Security & reliability:** CSRF, auth/session isolation, answer key protection, idempotent XP, worker recovery; các test 2026-10-30 cần tái chạy khi hợp lệ.

Đây là **CHECKLIST CẦN XÁC MINH**, không phải lời khẳng định những tính năng này chắc chắn còn thiếu vào ngày audit.

---

## 9. BACKLOG SAU AUDIT — HỢP ĐỒNG GIAO VIỆC

Với mỗi gap P0/P1 tạo task dạng:

```markdown
### GAP-<ID> — <Tên tính năng/hành vi>
- **Tình trạng:** MISSING | PARTIAL | BUG | UNTESTED | BLOCKED | UNKNOWN_REFERENCE
- **Mức ưu tiên:** P0 (blocking user journey/security) | P1 (major parity) | P2 (polish/future)
- **PolySkill evidence:** PS-R-... hoặc PS-S-... + giới hạn
- **SopiSkill evidence:** file:symbol, test/log, hành vi quan sát
- **Current vs expected:** ...
- **Phạm vi sửa đề xuất:** module/file/contract/migration nếu có
- **Dependency / thứ tự:** ...
- **Acceptance criteria:** Gherkin hoặc checklist đo được, có positive/negative
- **Test bắt buộc:** unit, integration, E2E, security, concurrency, performance tùy tính năng
- **Rủi ro:** data migration, idempotency, privacy, budget, compatibility
- **Rollback/feature flag:** ...
- **Ước lượng:** S / M / L (không tự hứa thời hạn)
- **Không làm:** copy code/UI/assets/secret, rewrite stack, bypass external access
- **Trạng thái:** PROPOSAL — CHƯA TRIỂN KHAI
```

Thứ tự thực hiện backlog nên theo **critical path** (không máy móc chạy theo phase cũ nếu repo hiện tại đã tiến xa hơn):

`Functional blockers / security → course generation & content quality → lesson/quiz coverage → Tutor SSE/context → source ingestion/citations → personalization → UX/i18n/gamification → billing`.

Nếu phát hiện nhiều gap, đưa **Top 10 có ảnh hưởng lớn nhất**, sau đó đầy đủ backlog theo milestone. Ưu tiên tận dụng code hiện có, không thay đổi stack SopiSkill chỉ vì PolySkill dùng Expo.

---

## 10. CẤU TRÚC ARTIFACT BẮT BUỘC

Xuất trong thư mục audit (đường dẫn cuối cùng phải có trong báo cáo):

```text
docs/audits/polyskill-parity-YYYY-MM-DD/
  00-executive-summary.md          # Kết luận, 3 chỉ số, chưa đạt gì
  01-repo-and-tool-baseline.md     # branch/HEAD/status/REA/version/config được redact
  02-reference-evidence.md        # PolySkill static vs runtime, so với báo cáo cũ
  03-scenarios.md                 # A01..H06, preconditions/results/blocked
  04-evidence-index.md            # PS-R, PS-S, SS-C, SS-T và trỏ file nguồn
  05-parity-matrix.md             # Mỗi requirement có đối chiếu 2 phía
  06-scores-and-confidence.md     # trọng số, coverage, denominator, unknowns
  07-gap-backlog.md               # Task spec có thứ tự, tests, dependencies
  08-ai-quality-evaluation.md     # chỉ khi có data test; nếu không ghi NOT TESTED
  09-command-and-test-log.md      # lệnh thực chạy, timestamps, exit code
  10-security-and-limitations.md  # các điểm không thể kiểm chứng và ranh giới
  captures/                       # CHỈ metadata đã lọc; không secrets/PII/code
  logs/                           # CHỈ logs an toàn của SopiSkill/test
```

Có thể xuất thêm `parity-matrix.csv` để lọc/sort nếu thuận tiện, nhưng **file `.md` vẫn là bắt buộc**. Nếu không có quyền ghi vào repo, dùng thư mục khác, ghi rõ lý do; **không claim file đã được tạo nếu chưa tạo**.

### Báo cáo cuối phải trả lời rõ 10 câu

1. Repo SopiSkill audit ở branch/HEAD nào, dirty không?
2. REA CLI version/commands đã sử dụng? Capture có bị origin-filter/drop requests không?
3. Những phần nào của PolySkill thực sự đã quan sát runtime? Những gì chỉ thấy từ client bundle?
4. Tính năng nào của SopiSkill đã code, đã chạy E2E, mới mocked, hoặc vẫn chưa test?
5. Có bao nhiêu scenarios `OBSERVED`, `PARTIAL`, `BLOCKED`, `NOT OBSERVABLE`?
6. `Evidence Coverage`, `Measured Parity`, `Conservative Floor` là bao nhiêu và mẫu số chính xác?
7. Có thể xác nhận mục tiêu 99% không? Nếu không, **tại sao**, thiếu gì?
8. Top 10 functional gaps và thứ tự fix nào mang lại hiệu quả lớn nhất?
9. Tests đã chạy, lệnh, exit code/log, số pass/fail/skip và các test cần chạy tiếp?
10. Những quyết định nào cần chủ dự án duyệt trước khi triển khai, dùng tiền, mở quyền, upload source hoặc cập nhật DB?

---

## 11. DEFINITION OF DONE CHO NHIỆM VỤ AUDIT

**Chỉ kết luận AUDIT COMPLETE khi:**

- [ ] Đọc hai báo cáo REA cũ, context, master plan và repository thực tế (hoặc nêu rõ tài liệu thiếu).
- [ ] Có branch/HEAD/git status, REA version và command help chứng minh tool có thật.
- [ ] REA quan sát PolySkill hợp lệ; có kiểm tra origin filter, giới hạn CDP, permissions và coverage; phần bị chặn được ghi chính xác.
- [ ] Ma trận nhiều-kịch-bản **có evidence cả 2 bên** hoặc được đánh dấu UNKNOWN/BLOCKED, không bịa các bước đã test.
- [ ] Đã phân loại `FACT / INFERENCE / UNKNOWN / PROPOSAL`, static ≠ runtime, code ≠ tested.
- [ ] Có điểm số với trọng số/denominator/coverage/unknown, không báo 99% khi chưa đủ căn cứ.
- [ ] Backlog cụ thể: module, nhiệm vụ, dependency, acceptance tests, giới hạn, security, migration/rollback.
- [ ] Không sao chép tài sản/mã nguồn/bí mật của PolySkill; không gọi endpoint ngoài giao diện; không vượt quyền.
- [ ] Không sửa production code, DB chính, secrets, Docker volumes, chưa deploy/push, không phát sinh chi phí không duyệt.
- [ ] Có báo cáo `IMPLEMENTED / TESTED / NOT TESTED / BLOCKED` và đường dẫn artifact thực đã tạo.

**Nếu một gate không đạt:** xuất **PARTIAL AUDIT** với phát hiện đã xác minh và danh sách blocker, thay vì chờ mãi hoặc tự khai PASS.

---

## 12. LỜI NHẮN KHỞI ĐỘNG NGẮN ĐỂ DÁN VÀO CLAUDE CODE

Dán nguyên nội dung dưới đây vào Claude Code **sau khi đặt file này tại đường dẫn mà Claude có thể đọc** (ví dụ `docs/CLAUDE_CODE_REA_POLYSKILL_PARITY_AUDIT.md` trong SopiSkill):

```text
Đọc toàn bộ docs/CLAUDE_CODE_REA_POLYSKILL_PARITY_AUDIT.md,
CLAUDE.md/AGENTS.md (nếu có), hai báo cáo REA PolySkill cũ,
docs/development-progress.md và tài liệu kiến trúc hiện hành.

Thực hiện PHASE A → B → C → D để AUDIT thật kỹ mức tương đồng
chức năng/trải nghiệm giữa PolySkill và SopiSkill bằng REA + kiểm tra
repository + các bài test an toàn được phép. Tôi muốn hướng tới 99%
functional parity, nhưng cấm xác nhận 99% khi bằng chứng không đủ.

Xác nhận repo/HEAD/working tree và phiên bản/lệnh REA trước khi dùng;
khắc phục lỗi origin-filter của capture cũ; tách STATIC và RUNTIME;
đánh dấu UNKNOWN/BLOCKED, không suy đoán backend PolySkill.

Chỉ dùng tài khoản và thao tác UI được phép, không vượt quyền/copy
code/assets/prompts/secrets, không tự mua gói, tiêu quota, upload
source riêng, hay gửi request trực tiếp ngoài UI. Không sửa source,
DB, migration, .env, không deploy/push. Nếu một phần bị chặn, tiếp
tục các phần độc lập và báo cáo PARTIAL chính xác.

Tạo đầy đủ audit artifacts theo mục 10, parity matrix, điểm số có
confidence/coverage, top gaps, backlog có file/module, acceptance
criteria và tests. Báo cáo lệnh + exit code thật, IMPLEMENTED/TESTED/
NOT TESTED/BLOCKED. Kết thúc bằng nhận định có/không đủ bằng chứng
để nói đã đạt 99% và đề xuất 3 bước triển khai ưu tiên tiếp theo.
```

