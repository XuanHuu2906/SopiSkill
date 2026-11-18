# 11 — PDF Source Ingestion, Hybrid RAG & Verified Citations

**Trạng thái:** P4.0 **IMPLEMENTED + TESTED**; P4.1 **IMPLEMENTED + TESTED (offline baseline)** — chi tiết
`docs/specs/20-P41-HYBRID-RAG.md`. P4.2 **IMPLEMENTED + TESTED (offline; chưa gọi mạng thật trong
test)** — chi tiết mục 7. P4.3 OCR có điều kiện. Không có chứng cứ nào về pipeline RAG/backend của
PolySkill; toàn bộ ở đây là thiết kế của SopiSkill.

## 1. Requirements

| ID | Yêu cầu | Phase |
|---|---|---|
| RAG-001 | Upload PDF private có kiểm tra type, bytes, pages, owner | P4.0 |
| RAG-002 | Extract text theo page với provenance và status rõ | P4.0 |
| RAG-003 | Chunks có sourceId/page/offset/textHash/pipelineVersion, retry idempotent | P4.0 |
| RAG-004 | PDF corrupt/oversize/scan-no-text được xử lý an toàn | P4.0 |
| RAG-005 | Text PDF là untrusted, ngăn prompt injection vào hệ thống | P4.0 |
| RAG-006 | Embedding model/dimension/version được chốt sau benchmark | P4.1 |
| RAG-007 | Lexical PostgreSQL FTS + vector pgvector, filter owner trước hợp nhất | P4.1 |
| RAG-008 | Reciprocal Rank Fusion (RRF), bounded top-k/context | P4.1 |
| RAG-009 | Citation server validator: chỉ IDs đã retrieve và tồn tại, user có quyền | P4.1 |
| RAG-010 | Không có evidence → trả lời không đủ thông tin, không bịa citation | P4.1 |
| RAG-011 | URL/arXiv ingest chống SSRF, licensing, redirects | P4.2 **IMPL+TESTED offline** |
| RAG-012 | OCR pretrained chỉ bật khi corpus scan và eval cho thấy cần | P4.3 **IMPL+TESTED (opt-in)** |

## 2. P4.0 ingestion sequence (proposed)

```text
Browser PDF upload → API stream+validate MIME magic/limits
    → private object storage (random key), source status queued
    → ingest worker atomic claim
    → extract text with page identifiers → normalize layout
    → chunk text with stable anchor/offset and checksum
    → source ready | failed (structured reason)
```

- Không public storage object keys, local file paths hoặc raw chunks trong API cho user khác.
- Pipeline idempotent per `(sourceId, checksum, pipelineVersion)`; hard limit bytes/page count/extraction time/rate configurable.
- PDF scan không có text: `NO_EXTRACTABLE_TEXT`, **không giả vờ đã OCR**.
- Ownership delete semantics, storage retention, source version regeneration cần được quyết định trước production.

## 3. P4.1 retrieval algorithm (proposed)

```text
User question (course/source scope)
    |-- PostgreSQL Full Text Search (lexical, owner-filtered)
    `-- Transformer multilingual embedding + pgvector cosine (owner-filtered)
            ↓
        RRF rank fusion
            ↓
    top-k bounded chunks + provenance validation
            ↓
    Tutor answer generation (untrusted chunks separated)
            ↓
    Server validates all citations against retrieved chunk allowlist
            ↓
    Answer + sourceId/chunkId/page/anchor returned to UI
```

- PostgreSQL FTS baseline **không tự gọi là BM25**; multilingual tokenizer tiếng Việt có hạn chế, cần benchmark.
- Không hardcode `vector(1536)` trước khi chọn model; lưu embedding model, dimension, version và reindex/re-embed plan khi đổi.
- Ưu tiên exact search trước; HNSW/reranker chỉ bật nếu có benchmark scale/latency và retrieval quality.
- RRF là strategy proposed, **không phải thuật toán được xác minh của sản phẩm tham chiếu**.

## 4. Citation contract

**Proposed citation pointer:**

```json
{
  "sourceId":"src_...",
  "chunkId":"chk_...",
  "page":7,
  "anchor":{"start":132,"end":208},
  "title":"Tài liệu bài học"
}
```

Validation bên server trước trả về:

1. `chunkId` thuộc retrieval allowlist của **request cụ thể**, không chỉ là ID model tự bịa.
2. Chunk tồn tại, thuộc source có quyền với user/course; source status ready và không bị deleted.
3. `page`/offset hợp lệ và khớp metadata lưu; không tạo URL/page không có thật.
4. Không cite tài liệu ngoài phạm vi. Nếu cite không hợp lệ → drop/retry constrained synthesis theo budget; tuyệt đối không hiển thị citation giả.
5. Content answer và citation coverage có thể khác nhau; báo rõ câu nào không được hỗ trợ từ source khi thích hợp.

## 5. PDF test fixtures

- PDF text 3–5 pages có heading, bảng đơn giản, page boundaries và expected chunks/anchors.
- File scan only, corrupt, encrypted, oversize, malicious filename, MIME mismatch, empty file, duplicate upload.
- Two users cùng tên file nhưng IDs khác; API/chunks/search không leak.
- Payload chèn “ignore previous instructions” nằm trong PDF phải được coi là **dữ liệu được trích**, không phải system instruction.

## 6. Retrieval and citation evaluation

- Trước P4.1 go-live: ít nhất **30 question/answer examples** có ground truth source/page/chunk.
- Đo Recall@k, MRR nếu qrels, citation validity (100% displayed pointer phải resolve và authorized), citation precision/coverage, groundedness, latency/cost.
- Negative cases: no source, conflicting chunks, wrong page, inaccessible source, prompt injection trong chunk, empty retrieval.
- Không claim hallucination-free chỉ vì citation pointer hợp lệ; cần kiểm tra claim hỗ trợ đúng đoạn nguồn.

## 7. P4.2 URL/arXiv controls (IMPLEMENTED 2026-11-01)

**Cổng outbound (theo thứ tự, mọi hop redirect phải qua lại từ đầu)** — `services/url_fetcher.py`:

1. `WEB_INGEST_ENABLED` + `WEB_INGEST_ALLOWED_HOSTS` (allowlist rỗng ⇒ từ chối **tất cả**).
   Khớp chính xác host hoặc subdomain: `example.com` cho `docs.example.com`, **không** cho
   `evil-example.com` / `example.com.attacker.net`.
2. Chỉ HTTPS (mặc định), port 443, không userinfo; scheme/port lạ bị từ chối.
3. Resolve DNS và yêu cầu **mọi** IP là global-unicast (`ipaddress.is_global`, chặn thêm
   multicast/IPv4-mapped). Một IP xấu ⇒ chặn cả hostname.
4. `PinnedNetworkBackend` bọc httpcore: resolve lại **ngay trong `connect_tcp`** và chỉ mở
   socket tới IP đã kiểm tra ⇒ chặn DNS rebinding. TLS/SNI vẫn dùng hostname gốc.
5. `follow_redirects=False`; mỗi `Location` được resolve lại và chạy lại cổng 1–4.
6. Trần byte (content-length + stream), redirects, thời gian, ký tự trích; lỗi mã ổn định.
7. `robots.txt`: 4xx ⇒ allow, 5xx/lỗi mạng/redirect ⇒ **từ chối** (conservative), cache theo
   origin. Tắt `WEB_INGEST_RESPECT_ROBOTS` là quyết định vận hành, không phải mặc định.

**Rights audit:** API yêu cầu `userConfirmedRights=true` (schema chặn ⇒ 422 **trước** khi có
request outbound) và lưu `source_documents.rights_confirmed_at`.

**Provenance:** `source_documents.origin` (`web|arxiv`), `origin_url` (canonical URL đã fetch),
`origin_meta` (HTTP status/redirect chain/title/arXiv id-version-authors). Chunk web giữ
`section_anchor` = breadcrumb heading (`H1 › H2`), `page_number=1`, offset ký tự tuyệt đối
trong text đã trích; chunk arXiv dùng provenance page thật của PDF. Citation trả `sourceUrl`.

**arXiv:** chỉ nhận **ID** (`2401.12345`, `2401.12345v2`, `hep-th/9901001`); URL dựng từ ID với
host cấu hình, và host vẫn phải nằm trong allowlist. Metadata mặc định đọc trang `/abs` qua thẻ
Highwire `citation_*` vì robots của `export.arxiv.org` (Atom API) là `Disallow: /` — Atom chỉ dùng
khi đặt `ARXIV_METADATA_SOURCE=atom` và parse bằng `defusedxml`. PDF phải có magic `%PDF-`.

**Đã kiểm chứng mạng thật (2026-11-01):** `example.com` và arXiv `1706.03762` (15 trang, 45 chunk)
qua API thật; citation trả `sourceUrl` thật. **Giới hạn đã biết:** chưa có malware scanner cho file
tải về; robots.txt chỉ hỗ trợ luật path-prefix (không wildcard `*`/`$` hay `Crawl-delay`); chưa cache
nội dung theo TTL (fetch lại cùng nội dung idempotent ở DB nhưng vẫn gọi mạng); chưa xử lý trang
render bằng JavaScript.

## 8. P4.3 OCR conditional — chi tiết `docs/specs/21-P43-OCR.md`

Đã triển khai (opt-in, mặc định TẮT) và đo trên corpus synthetic:

- Engine pretrained `rapidocr` (ONNX PP-OCR, cục bộ, không train/fine-tune, không gọi API ngoài).
- Chỉ OCR trang THIẾU text layer; trang native giữ nguyên. Chunk mang `textSource`,
  `ocrConfidence` (điểm engine, **không** phải xác suất đúng), `ocrBbox` chuẩn hoá theo trang.
- Bật OCR đổi `pipelineVersion` ⇒ document mới; citation cũ không bị ghi đè.
- Trần `OCR_MAX_PAGES`/`OCR_DPI`/`OCR_TIMEOUT_SECONDS`; mã lỗi `OCR_NOT_CONFIGURED`,
  `OCR_PAGE_LIMIT`, `OCR_NO_TEXT`, `OCR_TIMEOUT`, `OCR_FAILED`.
- Đo thật: CER EN = 0.000; CER VI = 0.094 (model **rơi dấu tiếng Việt**); ~2.8 s/trang @200 DPI.
- Chưa đo bảng/công thức; corpus synthetic không đại diện scan thật ⇒ không suy rộng.

## 9. Acceptance & không làm

- Từ PDF fixture hợp lệ: source ready → retrieved chunks đúng user → tutor trả lời có citation trỏ đúng page/chunk; không có nguồn thì abstain.
- Không triển khai arbitrary web scraping, không bịa nguồn, không sử dụng tài liệu riêng tư qua connector khi user chưa cho phép.
