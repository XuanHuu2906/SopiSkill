# KẾ HOẠCH HỌC THUẬT TOÁN — DỰ ÁN SOPISKILL (AI LEARNING PLATFORM)

> **Phiên bản:** 1.0  
> **Ngày lập:** 2026-11-02  
> **Thời lượng:** 12 tuần × 4 buổi/tuần × 90 phút = **48 buổi / 72 giờ**  
> **Người học:** Python mức cơ bản; nền toán mới bắt đầu; mong muốn **hiểu sâu, tự lập trình và kiểm chứng**.  
> **Trạng thái tài liệu:** **LEARNING PLAN / PROPOSAL**, không phải báo cáo triển khai tính năng.  
> **Tên file khuyến nghị trong repo (nếu muốn lưu):** `docs/AI_ALGORITHMS_LEARNING_PLAN.md` (không tự ghi vào repo).

## 1. Mục tiêu đầu ra

Sau 12 tuần, học viên cần có khả năng:

1. Giải thích bằng lời và code các ý tưởng Big O, hash table, graph/DAG, topological sort, deterministic grading, retry/backoff và idempotency.
2. Trình bày Transformer/LLM inference, token/embedding, dot product, softmax, self-attention và giới hạn của LLM; **không cần tự train LLM**.
3. Xây dựng mô hình offline của `lesson -> quiz -> progress`, `topic -> proposal DAG`, `document -> chunks -> retrieval -> citation`, `attempts -> mastery -> ôn tập`.
4. Phân biệt **thuật toán**, **kỹ thuật hệ thống**, **giao thức** và **khung sư phạm** (Bloom's Taxonomy).
5. Đọc code/bản thiết kế SopiSkill, đặt test và đánh giá một lựa chọn kỹ thuật; không chỉ dựa vào OpenCode.
6. Trình bày được bằng chứng **IMPLEMENTED / TESTED / NOT TESTED / BLOCKED** khi liên hệ sản phẩm thật.

## 2. Căn cứ và phạm vi xác nhận

**Nguồn có sẵn trong ChatGPT Project:**

- `SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`: mục **1.3** (bảng thuật toán được chọn), **8–10** (P2, LLM/DAG/evaluation), **11–12** (Tutor), **13–16** (PDF/RAG/OCR), **17–18** (BKT/FSRS và advanced adaptive).
- `development-progress.md`: lịch sử G0, P1.1, P1.2, P1.3, P2.0 và test log **được tác giả báo cáo**, đặc biệt mục **2026-10-30 — P2.0**.
- `architecture.md`, `database-design.md`, `implementation-plan.md`, `llm-provider.md`, `02_PROJECT_CONTEXT.md`, `03_ROADMAP_AND_BACKLOG.md`.

**Phân loại theo tài liệu ngày 30/10/2026 (không phải audit repo HEAD ngày hôm nay):**

| Nhóm | Được báo cáo đã làm / kiểm thử | Mức độ chắc chắn trong kế hoạch học |
|---|---|---|
| Quiz | Grading deterministic, server-side answer key, shuffle ổn định, version/progress/XP | **REPORTED IMPLEMENTED + TESTED** ở P1.1 |
| Generation reliability | Atomic claim, outbox/reconciler, bounded retry, lease/heartbeat | **REPORTED IMPLEMENTED + TESTED** ở P1.2 |
| Real LLM | Provider adapter, Pydantic/semantic lint; 3 real smoke requests được chấp thuận | **REPORTED PARTIAL**, không coi là đã hoàn tất P2.1 |
| Curriculum DAG | Prerequisite DAG, topological sort và Bloom | **PROPOSAL** P2.1 |
| Tutor | Lesson-grounded LLM + tool allowlist + SSE | **PROPOSAL** P3 |
| PDF / RAG | Chunking, embeddings, pgvector, lexical + vector search, RRF, citation validator | **PROPOSAL** P4 |
| Cá nhân hóa | Rule-based mastery + FSRS; BKT có điều kiện; DKT/bandit nghiên cứu | **PROPOSAL / CONDITIONAL** P5 |
| OCR | CNN/ViT nếu có PDF scan thực tế | **OPTIONAL**, không tự nhận là module hiện có |

**Không suy ra thuật toán backend PolySkill từ các quan sát REA.** Báo cáo tham khảo sản phẩm bên ngoài không chứng minh họ dùng các kỹ thuật trên. Tên module trong các tuần P3–P5 chỉ là **đường dẫn đề xuất**, phải audit repo trước khi sử dụng.

## 3. Cách dạy và điều kiện qua bài

**Một buổi 90 phút:** 15 phút trực giác → 20 phút lý thuyết/toán → 25 phút Python → 20 phút liên hệ SopiSkill → 10 phút kiểm tra. Có thể kéo dài khi chưa nắm chắc, không chạy theo lịch cứng.

**Nguyên tắc:**

- Công thức luôn bắt đầu bằng ví dụ số nhỏ, giải thích ký hiệu rồi mới viết code.
- Người học **tự giải trước**; chỉ sau đó mới nhận gợi ý và lời giải tham khảo. Dùng OpenCode để đối chiếu/review, không giao agent làm bài thay.
- Mỗi buổi có 4 câu trắc nghiệm/giải thích + 1 bài code (hoặc bài tính tay khi phù hợp).
- **Qua buổi:** tối thiểu **3/4 câu lý thuyết đúng**, bài thực hành đạt đủ test bắt buộc và trình bày được trực giác; thiếu tiêu chí nào thì học bù và làm lại.
- **Qua tuần:** hoàn thành mini-deliverable, giải thích các trường hợp lỗi/edge case, ghi lại những điều chưa hiểu.
- **Không dùng API có phí, không upload tài liệu riêng, không sửa DB/code production** nếu chưa được chấp thuận rõ ràng. Mọi thực hành dùng fixtures giả lập hoặc nội dung được phép.

**Toán bổ trợ theo nhu cầu:**

| Khi học | Ôn toán nào | Yêu cầu tối thiểu |
|---|---|---|
| Tuần 1–2 | Tỷ lệ %, lũy thừa, biến, tổng | Tự tính 2/5 = 40%; hiểu n, n² |
| Tuần 4 | Vector, ma trận, dot product, căn bậc hai, softmax | Tính tay vector 2D và attention 2 token |
| Tuần 9–10 | Norm và cosine, thứ hạng, trung bình | Viết cosine và tự tính RRF 2 bảng |
| Tuần 11 | Xác suất có điều kiện, Bayes | Tính posterior từ ví dụ đơn giản |
| Tuần 12 | Thời gian, dữ liệu chuỗi ôn tập | Hiểu input/output của review scheduler |

## 4. Bản đồ phụ thuộc kiến thức

```text
Python cơ bản + Toán nhập môn
    ├── Big O → Hash/Set → Deterministic grading → Idempotency/Retry
    ├── Graph → DAG → Topological sort → Course curriculum
    ├── Vector/Matrix → Dot product → Softmax → Transformer/LLM
    │                      └── Embeddings → Cosine → Hybrid RAG → RRF/Citations
    └── Xác suất → Bayes → Mastery baseline → BKT
                                           └── Review history → FSRS
LLM + context → Tutor grounding → tool calling → SSE + safety
```

## 5. Lịch học chi tiết — 48 buổi

### Tuần 01 — Nền tảng tư duy thuật toán và toán nhập môn

**Liên hệ roadmap:** Nền tảng  
**Kết quả học tập:** Hiểu input/output, Big O, lựa chọn cấu trúc dữ liệu; dùng phép tỷ lệ, lũy thừa, vector cơ bản mà không cần nền tảng toán cao.  
**Module liên hệ:** Liên hệ `backend/app/services/course_service.py` (progress), `backend/app/services/lesson_content.py` (logic bài học).

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 01 | **Thuật toán là gì? Đếm bước và Big O** | Input/output, O(1), O(n), O(n²), thời gian vs bộ nhớ | Tự viết `calculate_progress(lesson_ids, completed_ids)`; test dữ liệu rỗng/ID không hợp lệ |
| 02 | **List, Dict, Set và Hash Table** | Tra cứu tuyến tính, hash, độ phức tạp trung bình và trường hợp xấu | Đo và giải thích khác biệt `id in list` so với `id in set` |
| 03 | **Duyệt đồ thị và ý tưởng prerequisite** | Node, edge, DFS/BFS trực giác, phát hiện phụ thuộc | Biểu diễn 5 kỹ năng Python bằng adjacency list và duyệt danh sách |
| 04 | **Toán nền: phân số, lũy thừa, vector** | Tỷ lệ phần trăm, tổng, chỉ số, vector và tích vô hướng mức nhập môn | Tự tính progress, bình phương độ dài vector và dot product 2D |

**Sản phẩm cuối tuần:** 01 script Python tính progress và tra cứu lessons; 01 sơ đồ prerequisite 5 kỹ năng; test cơ bản.  
**Điều kiện qua tuần:** Giải thích được sự khác nhau giữa O(1)/O(n)/O(n²), chọn đúng list hoặc set cho bài toán tra cứu; tính được 1 tích vô hướng nhỏ.

### Tuần 02 — Thuật toán chấm quiz xác định và bảo vệ đáp án

**Liên hệ roadmap:** P1.1 (đã được báo cáo implemented/tested)  
**Kết quả học tập:** Hiểu vì sao quiz đóng nên chấm bằng logic xác định và answer key phải ở server.  
**Module liên hệ:** `backend/app/services/lesson_content.py`, `backend/app/services/lesson_service.py`, `backend/tests/test_grading.py` (kiểm tra đường dẫn tại HEAD).

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 05 | **Chuẩn hóa dữ liệu đáp án** | Trim, casefold, exact-match, ràng buộc kiểu và sai số | Viết `normalize_answer` + test chữ hoa/dấu cách |
| 06 | **Chấm MC/blank/order/match** | So sánh index, chuỗi, thứ tự và cặp ghép; tính điểm | Viết 4 hàm chấm bằng key riêng không nằm trong public input |
| 07 | **Deterministic shuffle và SHA-256** | Hash như fingerprint/seed ổn định; khác mã hóa; chống lộ khóa | Xáo trộn thứ tự ổn định theo lesson/version, kiểm tra chạy lại ra kết quả giống |
| 08 | **Content versioning, attempts và tiến độ** | Version cũ/mới, ngưỡng hoàn thành, kiểm soát XP | Xây bộ chấm 5 loại quiz; test submit sai version và nộp lặp |

**Sản phẩm cuối tuần:** `quiz_engine.py` và test cases cho 5 block quiz, không lộ answer key; mô tả chính sách hoàn thành >=80% là lựa chọn hiện có cần duyệt riêng.  
**Điều kiện qua tuần:** Tất cả unit test pass trong sandbox; giải thích vì sao không tin client tự gửi `correct=True`.

### Tuần 03 — Job reliability: giao dịch, race condition, retry

**Liên hệ roadmap:** P1.2 (đã được báo cáo implemented/tested)  
**Kết quả học tập:** Hiểu cách bảo đảm một generation job không làm trùng course/lesson khi worker lỗi hoặc request bị gửi lại.  
**Module liên hệ:** `backend/app/services/job_service.py`, `backend/app/worker/generation.py`, `backend/app/worker/reconcile.py`.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 09 | **State machine và idempotency** | States, transitions, idempotency key, invariant | Vẽ trạng thái queued/running/ready/failed và test chuyển trạng thái sai |
| 10 | **Race condition và atomic claim** | Critical section, khóa và cập nhật nguyên tử | Mô phỏng 10 worker claim một job; so sánh trước/sau khóa |
| 11 | **Exponential backoff và jitter** | Retry giới hạn, lỗi transient/fatal; `retry-after` | Viết hàm tính lịch thử lại 2/4/8... và không retry 401 |
| 12 | **Outbox, lease và recovery** | Ghi DB rồi dispatch broker, heartbeat, lease hết hạn | Mô phỏng broker tắt/mở; giải thích vì sao at-least-once không phải exactly-once |

**Sản phẩm cuối tuần:** Mini job runner giả lập bằng Python có idempotency, tối đa 3 attempts và test race cơ bản.  
**Điều kiện qua tuần:** Mô tả được ba tình huống retry an toàn, khi nào fail-fast và cách kiểm tra không tạo trùng lessons.

### Tuần 04 — Transformer và cơ sở toán cho LLM

**Liên hệ roadmap:** P2 — nền tảng lý thuyết; không huấn luyện model từ đầu  
**Kết quả học tập:** Hiểu Transformer và inference đến mức giải thích được token, vector, attention và tại sao model sinh text.  
**Module liên hệ:** `backend/app/providers/base.py`, `backend/app/providers/openai_compatible_provider.py`.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 13 | **Tokenization, vocabulary và embedding** | Token khác từ; biến token thành vector; độ dài context | Tự xây bảng token nhỏ và biểu diễn câu thành chỉ số + vector |
| 14 | **Vector, ma trận và tích vô hướng** | Phép nhân vector/matrix, transpose, sqrt, ý nghĩa score | Tính tay điểm tương đồng của 2 token với vector 2 chiều |
| 15 | **Softmax và Self-Attention** | Q/K/V, scaled dot-product, softmax; làm việc với ma trận nhỏ | Tính bảng attention 2 token bằng Python/NumPy và đối chiếu tay |
| 16 | **Autoregressive inference và giới hạn** | Dự đoán token kế tiếp, sampling, temperature, hallucination | So sánh hai cấu hình decoding bằng mock/simulation, không gọi API trả phí |

**Sản phẩm cuối tuần:** Notebook mini mô phỏng attention với 2–3 token, giải thích từng phép tính và kích thước tensor.  
**Điều kiện qua tuần:** Giải thích được công thức attention bằng lời; tự tính 1 ví dụ softmax/dot product có hướng dẫn.

### Tuần 05 — LLM provider, structured output và AI evaluation

**Liên hệ roadmap:** P2.0 (đã smoke test thật theo log) + P2.2 (kế hoạch)  
**Kết quả học tập:** Phân biệt JSON hợp lệ với nội dung đúng; hiểu timeout, token budget và cách kiểm tra độ tin cậy của AI.  
**Module liên hệ:** `backend/app/providers/validation.py`, `backend/app/providers/openai_compatible_provider.py`, `backend/app/core/config.py`, `docs/llm-provider.md`.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 17 | **Adapter và hợp đồng input/output** | Provider abstraction, mock vs real, prompt versioning | Đọc flow input->provider->schema; mock trả JSON cố định |
| 18 | **Pydantic và semantic validation** | Schema, discriminated union, ràng buộc logic liên trường | Validator 5 câu phỏng vấn, không lặp, answerIndex đúng bounds |
| 19 | **Retry, timeout, quota và cost** | Mã lỗi, fail-fast, bounded retry, token accounting | Viết test 429/401/timeout/schema-invalid với HTTP mock |
| 20 | **Đánh giá chất lượng bài học** | Evaluation dataset, rubric, deterministic vs human judgement | Chấm 3 bài mẫu bằng rubric: đúng chủ đề, logic, quiz bám nội dung |

**Sản phẩm cuối tuần:** `provider_mock_eval.py` + bộ test schema/semantic + bảng rubric tối thiểu 3 topic.  
**Điều kiện qua tuần:** Chỉ ra được 3 lỗi mà JSON Schema không bắt được; không dùng mock test để tuyên bố chất lượng LLM thật.

### Tuần 06 — DAG và Topological Sort để xây lộ trình

**Liên hệ roadmap:** P2.1 — dự kiến, chưa xác minh triển khai  
**Kết quả học tập:** Biết định nghĩa prerequisite, phát hiện vòng lặp và sắp thứ tự học hợp lệ.  
**Module liên hệ:** Đề xuất module `backend/app/services/curriculum_service.py` hoặc `backend/app/pedagogy/` nếu được triển khai; không mặc định đã tồn tại.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 21 | **Directed Graph và prerequisite** | Node/edge/degree, điều kiện tiên quyết, biểu diễn dữ liệu | Tạo graph cho Python: biến → điều kiện → vòng lặp → hàm |
| 22 | **Topological Sort bằng Kahn** | In-degree, queue, thứ tự topo | Viết thuật toán Kahn từ đầu không dùng thư viện graph |
| 23 | **DFS và phát hiện cycle** | DFS states, back edge, graph không hợp lệ | Test graph A→B→C→A báo lỗi thay vì tạo course |
| 24 | **Ghép Bloom + DAG vào proposal** | Bloom là taxonomy giáo dục, không phải ML; validate lesson objectives | Sinh proposal mock với units/lessons có thứ tự và điều kiện prerequisite |

**Sản phẩm cuối tuần:** `curriculum_dag.py` + test graph rỗng/nhiều nhánh/cycle; mock proposal theo schema riêng.  
**Điều kiện qua tuần:** Sắp xếp được 6 skill thành thứ tự học hợp lệ và phát hiện được cycle trước approve.

### Tuần 07 — AI Tutor, grounding và streaming

**Liên hệ roadmap:** P3 — dự kiến  
**Kết quả học tập:** Hiểu cách làm Tutor bám ngữ cảnh bài học, tool allowlist và stream phản hồi an toàn.  
**Module liên hệ:** Đề xuất `backend/app/api/v1/tutor.py`, `backend/app/services/tutor_service.py`, `backend/app/services/tutor_tools.py`.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 25 | **Conversation context và grounding** | Context window, chọn nội dung lesson/block, chống ảo giác | Lắp context theo `lessonId` + `blockIndex` từ server-side test data |
| 26 | **Tool calling có giới hạn** | Tool schemas, allowlist, owner check, max iterations | Tạo mock tool `read_lesson` và từ chối tool ngoài allowlist |
| 27 | **SSE và event ordering** | delta/done/error, event ID, disconnect và cancellation | Tạo generator phát từng chunk và test ghép lại câu trả lời |
| 28 | **Idempotent Tutor messages** | clientMessageId, lưu hội thoại, quota và tránh trùng | Mô phỏng gửi cùng message hai lần nhưng chỉ lưu một bản |

**Sản phẩm cuối tuần:** Mock Tutor chạy cục bộ, có stream đơn giản, owner check và tests duplicate messages.  
**Điều kiện qua tuần:** Mô tả đúng sự khác nhau giữa streaming và retry/replay; không claim resume nếu không có event log.

### Tuần 08 — PDF ingestion, chunking và provenance

**Liên hệ roadmap:** P4.0 — dự kiến  
**Kết quả học tập:** Biến PDF text thành nguồn dữ liệu có thể tìm kiếm, giữ nguyên dấu vết trang/chunk.  
**Module liên hệ:** Đề xuất `backend/app/services/ingest_service.py`, `backend/app/worker/ingest.py`, `backend/app/services/storage.py`.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 29 | **Text extraction từ PDF** | Text native, trang, metadata; phân biệt scanned PDF | Đọc PDF fixture do mình tạo, ghi text/page và kiểm tra số trang |
| 30 | **Chunking và overlap** | Kích thước chunk, overlap, tradeoff, token budget | Viết chunker theo đoạn; thử overlap 0 vs overlap vừa phải |
| 31 | **Provenance và source IDs** | sourceId/chunkId/page/offset/contentHash, phiên bản nguồn | Tạo metadata chuẩn cho 5 chunks và kiểm tra page không rỗng |
| 32 | **File safety và prompt injection** | MIME/size validation, sandbox, untrusted text, upload safety | Test PDF sai loại/rỗng và text chứa chỉ dẫn giả trong tài liệu |

**Sản phẩm cuối tuần:** Pipeline trên PDF fixture do bản thân sở hữu: extract → chunks có page + hash; chưa cần OCR.  
**Điều kiện qua tuần:** Mỗi chunk truy ngược đúng trang; không coi text nguồn là system instructions; biết khi nào OCR cần thiết.

### Tuần 09 — Embedding và tìm kiếm ngữ nghĩa

**Liên hệ roadmap:** P4.1 — dự kiến  
**Kết quả học tập:** Hiểu cách ánh xạ văn bản sang vector, cosine similarity và giới hạn của lexical/vector retrieval.  
**Module liên hệ:** Đề xuất `backend/app/services/embedding_service.py`, `backend/app/services/retrieval_service.py`, schema pgvector sau khi chọn embedding model.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 33 | **Embedding vectors và semantic search** | Nội dung gần nghĩa trong không gian vector, model/dimension | Vẽ 3 vectors 2D do mình tự đặt, chọn nearest neighbor |
| 34 | **Cosine similarity và chuẩn vector** | Dot product, norm, cosine; giá trị âm/0/dương | Viết `cosine_similarity(a,b)` từ đầu, test vector 0 |
| 35 | **Lexical Full Text Search** | Tokenization, match từ khóa, PostgreSQL FTS vs BM25 | Mô phỏng keyword scorer và phân tích hạn chế tiếng Việt |
| 36 | **pgvector và ownership filters** | Exact vector search trước, index HNSW khi benchmark, kiểm soát tenant | Thiết kế query pseudo-SQL có `owner_id` + course/source filter |

**Sản phẩm cuối tuần:** `vector_search_demo.py` dùng vectors nhỏ + checklist quyền truy cập source.  
**Điều kiện qua tuần:** Tính cosine của hai vector nhỏ; giải thích tại sao không phải cứ vector cao điểm là citation đúng.

### Tuần 10 — Hybrid RAG, RRF và verified citations

**Liên hệ roadmap:** P4.1 — dự kiến  
**Kết quả học tập:** Kết hợp lexical/vector rank, build context và chỉ hiển thị citations thật sự kiểm chứng được.  
**Module liên hệ:** `retrieval_service.py`, `citation_service.py` là module đề xuất; đối chiếu khi có source thực.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 37 | **Ranking và Reciprocal Rank Fusion** | Thứ hạng, tham số k, cộng điểm theo rank | Tự tính RRF cho top-3 từ 2 bảng kết quả |
| 38 | **Context assembly và token budget** | Top-k, giới hạn chunks, metadata, untrusted delimiters | Viết hàm chọn chunk dưới giới hạn token giả lập |
| 39 | **Citation validator phía server** | Chunk IDs, page verification, ownership, câu trả lời thiếu nguồn | Từ chối citation tới chunk không được retrieval trả về |
| 40 | **RAG evaluation** | Recall@k, MRR, groundedness, citation precision | Tạo 10 query fixture; tính Recall@3 và kiểm tra link citation |

**Sản phẩm cuối tuần:** Mini hybrid RAG offline trên 1 bộ tài liệu test có quyền, câu trả lời giả lập nhưng citation phải truy được nguồn.  
**Điều kiện qua tuần:** 100% citations trong fixture resolve được source/chunk/page và không vượt quyền; biết khi nào trả “không đủ thông tin”.

### Tuần 11 — Ước lượng năng lực người học và BKT

**Liên hệ roadmap:** P5.0/P5.1 — baseline rule-based dự kiến, BKT có điều kiện  
**Kết quả học tập:** Ôn xác suất, Bayes và biết cách ước lượng mastery mà không ngụy nhận heuristic là ML.  
**Module liên hệ:** Đề xuất `backend/app/services/progress_service.py`, `backend/app/services/recommendation_service.py`; chưa ghi nhận BKT chạy thực tế.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 41 | **Xác suất cơ bản và Bayes** | Biến cố, xác suất có điều kiện, prior/posterior | Tính xác suất điển hình từ bảng 2×2; giải thích Bayes bằng lời |
| 42 | **Rule-based mastery baseline** | Score theo skill, threshold, lịch sử attempt, bias dữ liệu | Viết baseline mastery từ các attempt có skill tag |
| 43 | **Bayesian Knowledge Tracing** | P(L0), learn, guess, slip; update theo correct/incorrect | Tự viết hàm cập nhật BKT một bước và thử chuỗi 5 attempts |
| 44 | **Đánh giá và sai lệch** | Train/test split theo learner/time, calibration, Brier score | So sánh BKT vs baseline bằng dữ liệu mô phỏng; không claim hơn khi không đo |

**Sản phẩm cuối tuần:** `mastery.py` với rule-based + BKT mô phỏng và unit tests kết quả xác suất [0,1].  
**Điều kiện qua tuần:** Giải thích Bayes bằng ví dụ đơn giản; phân biệt mastery estimate với điểm số thực tế và không khẳng định AI adaptive đã deploy.

### Tuần 12 — FSRS, tổng hợp và đánh giá cuối khóa

**Liên hệ roadmap:** P5.0 dự kiến; các mô hình nâng cao chỉ nghiên cứu  
**Kết quả học tập:** Biết mục đích spaced repetition, cơ chế đầu vào/đầu ra của scheduler và tích hợp tất cả thành demo học tập.  
**Module liên hệ:** Đề xuất learner review events, recommendation service và scheduler; không sửa DB thật trong khóa học.

| Buổi | Chủ đề | Kiến thức trọng tâm | Bài thực hành / kiểm chứng |
|---:|---|---|---|
| 45 | **Forgetting curve và spaced repetition** | Nhớ/quên theo thời gian, độ khó, lịch sử ôn; không đồng nhất FSRS với công thức minh họa | Tạo lịch ôn baseline theo ngày và so sánh cách chọn ngày |
| 46 | **FSRS ở mức thực hành** | Review grades, stability/difficulty, scheduling version; dùng thư viện kiểm chứng khi cần | Mô phỏng input review events→due date, test cùng history cho kết quả ổn định |
| 47 | **Tổng hợp Mini AI Learning Engine** | DAG + quiz + PDF chunks + retrieval + citation + mastery + review | Gắn các module tuần trước thành một CLI demo có test regression |
| 48 | **Demo, giải thích và phản biện** | Tradeoffs, limitations, mô hình thật vs mock, chi phí/an toàn | Trình bày 10 phút + trả lời 10 câu hỏi phản biện có rubric |

**Sản phẩm cuối tuần:** Mini AI Learning Engine trên local, README, test logs, sơ đồ dữ liệu, bảng hạn chế và demo 10 phút.  
**Điều kiện qua tuần:** Chạy được bộ test offline; giải thích ít nhất 8/10 câu hỏi phản biện; không tuyên bố Tutor/RAG/BKT/FSRS đã triển khai trong repo thật.

## 6. Các checkpoint bắt buộc

| Checkpoint | Thời điểm | Phải trình bày / nộp | Trạng thái ban đầu |
|---|---|---|---|
| CP-1 | Cuối tuần 1 | Big O, list/set, progress và vector nền | ☐ Chưa học |
| CP-2 | Cuối tuần 3 | Bộ chấm quiz + mô hình job idempotent | ☐ Chưa học |
| CP-3 | Cuối tuần 6 | Attention mini, validated mock LLM output, DAG curriculum | ☐ Chưa học |
| CP-4 | Cuối tuần 10 | Mock Tutor + PDF chunk metadata + hybrid retrieval có verified citations | ☐ Chưa học |
| CP-5 | Cuối tuần 12 | Mastery/BKT/FSRS demo + bài kiểm tra cuối khóa | ☐ Chưa học |

**Rubric đánh giá bài code (100 điểm):** đúng chức năng 40, tests/edge cases 25, giải thích đúng độ phức tạp/cơ chế 20, rõ ràng và an toàn 15. Điểm tổng từ **80 trở lên** và không bỏ sót test bắt buộc mới được qua checkpoint. Đây là **quy tắc của kế hoạch dạy học**, không phải chính sách hoàn thành course trong sản phẩm SopiSkill.

## 7. Project thực hành cuối khóa

Tên: **Mini AI Learning Engine — offline educational prototype**.

**Input:** chủ đề học + profile giả lập + PDF fixture (do người học có quyền sử dụng).  
**Luồng:** prerequisite graph (DAG) → proposal mock → lesson/quiz deterministic → progress → chunk tài liệu → retrieval → verified citation → mastery baseline/BKT → review scheduler.  
**Output:** CLI đơn giản, README, mô tả data contracts, unit tests, báo cáo kết quả và giới hạn.

**Phân biệt:** ở bài tập, mô phỏng retrieval/AI là mock phải ghi là mock; muốn thử LLM thật chỉ khi duyệt ngân sách/dữ liệu. Nếu FSRS dùng thư viện có phiên bản thì ghi lại version; nếu chỉ viết lịch ôn đơn giản thì gọi **baseline scheduler**, không gắn nhãn FSRS đầy đủ.

**Definition of Done:**

- CLI chạy trên Windows; không phụ thuộc tài khoản API trả phí.
- Có tối thiểu 15 unit tests (positive, negative, empty input, duplicate, wrong version, owner scope mock).
- Tất cả citation hiển thị trong demo trỏ tới sourceId/chunkId/page thực có ở fixture.
- Không công khai answer key trước khi chấm quiz.
- Có README: chạy, kiến trúc, lý do chọn thuật toán, Big O phù hợp, giới hạn, phần mới chỉ là prototype học tập.
- Có bảng **IMPLEMENTED / TESTED / NOT TESTED / BLOCKED**, không tuyên bố PASS nếu chưa chạy.

## 8. Nhật ký tiến độ học (điền sau mỗi buổi)

> **Trạng thái ban đầu:** 0/48 buổi được đánh dấu hoàn thành. Buổi 1 đã bắt đầu trong chat nhưng **chưa có bằng chứng bài kiểm tra và bài code được nộp/chấm**, nên vẫn là `IN PROGRESS`.

| Buổi | Trạng thái | Ngày học | Điểm quiz | Bài code & test | Ghi chú |
|---:|---|---|---|---|---|
| 01 | IN PROGRESS | — | — | — | — |
| 02 | NOT STARTED | — | — | — | — |
| 03 | NOT STARTED | — | — | — | — |
| 04 | NOT STARTED | — | — | — | — |
| 05 | NOT STARTED | — | — | — | — |
| 06 | NOT STARTED | — | — | — | — |
| 07 | NOT STARTED | — | — | — | — |
| 08 | NOT STARTED | — | — | — | — |
| 09 | NOT STARTED | — | — | — | — |
| 10 | NOT STARTED | — | — | — | — |
| 11 | NOT STARTED | — | — | — | — |
| 12 | NOT STARTED | — | — | — | — |
| 13 | NOT STARTED | — | — | — | — |
| 14 | NOT STARTED | — | — | — | — |
| 15 | NOT STARTED | — | — | — | — |
| 16 | NOT STARTED | — | — | — | — |
| 17 | NOT STARTED | — | — | — | — |
| 18 | NOT STARTED | — | — | — | — |
| 19 | NOT STARTED | — | — | — | — |
| 20 | NOT STARTED | — | — | — | — |
| 21 | NOT STARTED | — | — | — | — |
| 22 | NOT STARTED | — | — | — | — |
| 23 | NOT STARTED | — | — | — | — |
| 24 | NOT STARTED | — | — | — | — |
| 25 | NOT STARTED | — | — | — | — |
| 26 | NOT STARTED | — | — | — | — |
| 27 | NOT STARTED | — | — | — | — |
| 28 | NOT STARTED | — | — | — | — |
| 29 | NOT STARTED | — | — | — | — |
| 30 | NOT STARTED | — | — | — | — |
| 31 | NOT STARTED | — | — | — | — |
| 32 | NOT STARTED | — | — | — | — |
| 33 | NOT STARTED | — | — | — | — |
| 34 | NOT STARTED | — | — | — | — |
| 35 | NOT STARTED | — | — | — | — |
| 36 | NOT STARTED | — | — | — | — |
| 37 | NOT STARTED | — | — | — | — |
| 38 | NOT STARTED | — | — | — | — |
| 39 | NOT STARTED | — | — | — | — |
| 40 | NOT STARTED | — | — | — | — |
| 41 | NOT STARTED | — | — | — | — |
| 42 | NOT STARTED | — | — | — | — |
| 43 | NOT STARTED | — | — | — | — |
| 44 | NOT STARTED | — | — | — | — |
| 45 | NOT STARTED | — | — | — | — |
| 46 | NOT STARTED | — | — | — | — |
| 47 | NOT STARTED | — | — | — | — |
| 48 | NOT STARTED | — | — | — | — |

## 9. Cách phối hợp khi học bằng ChatGPT + OpenCode

**ChatGPT đóng vai gia sư:** giải thích lý thuyết, đặt câu hỏi, chấm bài, review giải thuật/tư duy; không tự đánh dấu hoàn thành khi chưa thấy đáp án/test.

**OpenCode đóng vai công cụ kiểm chứng code (tùy chọn):** chỉ đọc source trên repo và chạy test trong local sandbox, không tự sửa những module thật khi mục tiêu là học; nếu muốn triển khai một phần lên SopiSkill, phải mở task riêng có scope, acceptance, tests và không làm ngoài phạm vi.

**Mẫu yêu cầu để tiếp tục bài học:**

```text
Tiếp tục kế hoạch trong SOPISKILL_AI_ALGORITHMS_LEARNING_PLAN_12_WEEKS.md.
Tôi đang ở Buổi <số>. Hãy dạy theo 5 phần:
trực giác → lý thuyết/toán → code Python → liên hệ SopiSkill → quiz/bài tập.
Đừng đưa ngay lời giải bài tập; hãy chấm và review khi tôi nộp.
Không chuyển buổi nếu chưa đạt điều kiện qua bài.
```

**Mẫu nhờ OpenCode kiểm chứng (chỉ đọc):**

```text
Mục tiêu: học và đối chiếu module <tên> trong SopiSkill, KHÔNG triển khai chức năng.
1. Kiểm tra repo, HEAD, git status và file thực tế.
2. Đọc module liên quan và tóm tắt input/output, thuật toán, độ phức tạp, test.
3. Chạy unit tests phù hợp nếu an toàn và sẵn môi trường; báo lệnh + output.
4. Không sửa code/DB, không gọi API có phí, không push/deploy.
5. Báo rõ FACT CODE / REPORTED TESTED / NOT TESTED / UNKNOWN.
```

## 10. Phần mở rộng sau 12 tuần (tùy dữ liệu/thời gian)

1. **LSTM / Deep Knowledge Tracing**: chỉ nghiên cứu khi có đủ lịch sử bài làm và baseline BKT; cần so sánh held-out, calibration, leakage.
2. **Contextual Bandit**: chỉ nghiên cứu khi có reward/propensity logging, phương án đánh giá offline và giới hạn thử nghiệm trên người học.
3. **OCR bằng CNN/ViT pretrained**: chỉ nếu có PDF scan cần xử lý và bộ kiểm thử CER/WER + page provenance.
4. **Reranking, ANN/HNSW**: cần benchmark retrieval/cost/latency trước khi chọn; không mặc định tốt hơn baseline.
5. **K-Means / Random Forest / XGBoost / full RL**: không nằm trong kiến trúc đã chốt; chỉ học khi có bài toán và dữ liệu cụ thể.

---

**Ghi chú về nguồn:** Kế hoạch học là **đề xuất sư phạm của ChatGPT** xây trên tài liệu dự án được người dùng cung cấp. Lịch 12 tuần, bài tập, checkpoint và rubric không phải phần đã triển khai/được xác minh trong SopiSkill. Tài liệu có thể cần cập nhật khi audit repository ở HEAD mới.
