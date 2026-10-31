# 11 — PDF Source Ingestion, Hybrid RAG & Verified Citations

**Trạng thái:** **PROPOSAL / P4.0–P4.1**; web/arXiv P4.2 tùy chọn; OCR P4.3 có điều kiện. Chưa có chứng cứ pipeline RAG của SopiSkill hoặc PolySkill thực sự chạy.

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
| RAG-011 | URL/arXiv ingest chống SSRF, licensing, redirects | P4.2 optional |
| RAG-012 | OCR pretrained chỉ bật khi corpus scan và eval cho thấy cần | P4.3 conditional |

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

## 7. P4.2 URL/arXiv controls (optional)

- Chỉ fetch HTTPS/host cho phép; chặn internal/private/link-local/metadata addresses qua DNS và redirects; validate after each hop; bảo vệ DNS rebinding.
- Hard caps trên redirects/bytes/requests/time, loại file, robots/copyright/rights; không vượt captcha/paywall/auth.
- Store canonical URL, retrieved-at, page title/source version, extraction anchors; citation phải mở được nguồn thực trong giới hạn quyền.

## 8. P4.3 OCR conditional

- Chỉ nghiên cứu OCR CNN/ViT pretrained nếu PDF scan là use case thực; lưu page bbox/confidence và flag `origin=ocr`.
- Eval CER/WER và độ chính xác bảng/công thức/citation page; nếu không đạt threshold so với baseline thì không bật.

## 9. Acceptance & không làm

- Từ PDF fixture hợp lệ: source ready → retrieved chunks đúng user → tutor trả lời có citation trỏ đúng page/chunk; không có nguồn thì abstain.
- Không triển khai arbitrary web scraping, không bịa nguồn, không sử dụng tài liệu riêng tư qua connector khi user chưa cho phép.
