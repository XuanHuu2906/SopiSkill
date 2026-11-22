# 11 — PDF/Web/arXiv Source Ingestion, Hybrid RAG & Verified Citations

**Trạng thái (`2026-11-22`):**
- **P4.0 (PDF ingest + MinIO/S3):** **IMPLEMENTED · REPORTED TESTED** (`SOURCE_INGEST_ENABLED=true`).
- **P4.1 (Embeddings + Hybrid RAG + Verified Citations):** **IMPLEMENTED · REPORTED TESTED (offline hashing baseline)** — chi tiết `20-P41-HYBRID-RAG.md`, **DEFAULT-OFF** (`RAG_ENABLED=false`).
- **P4.2 (Web/arXiv ingest + SSRF/robots/rights):** **IMPLEMENTED · REPORTED TESTED (offline + live probe `example.com` & arXiv `1706.03762`)**, **DEFAULT-OFF** (`WEB_INGEST_ENABLED=false`, allowlist rỗng).
- **P4.3 (OCR opt-in `rapidocr` / `vietocr`):** **IMPLEMENTED · REPORTED TESTED (corpus synthetic)** — chi tiết `21-P43-OCR.md`, **DEFAULT-OFF** (`OCR_ENABLED=false`).

## 1. Requirements

| ID | Yêu cầu | Trạng thái (2026-11-22) |
|---|---|---|
| RAG-001 | Upload PDF private kiểm tra magic `%PDF-`, bytes (`20 MB`), pages (`300`), owner | **IMPLEMENTED · TESTED** |
| RAG-002 | Extract text theo page với provenance và status rõ (`queued/extracting/ready/no_text/failed`) | **IMPLEMENTED · TESTED** |
| RAG-003 | Chunks có `sourceId`/`documentId`/`pageNumber`/`charStart`/`charEnd`/`textHash`/`pipelineVersion`, idempotent | **IMPLEMENTED · TESTED** |
| RAG-004 | PDF corrupt/oversize/scan-no-text xử lý an toàn (không bịa text) | **IMPLEMENTED · TESTED** |
| RAG-005 | Text tài liệu là untrusted, ngăn prompt injection | **IMPLEMENTED · TESTED** |
| RAG-006 | Embedding model/dimension/version tách theo spec, không trộn chéo | **IMPLEMENTED** (`hashing` 256-dim baseline; semantic model thật chờ benchmark/duyệt) |
| RAG-007 | Lexical PostgreSQL FTS + vector cosine exact, **filter owner trong SQL trước** | **IMPLEMENTED · TESTED** (`pgvector` DEFERRED) |
| RAG-008 | Reciprocal Rank Fusion (`RRF`, `k=60`), bounded top-k & context chars | **IMPLEMENTED · TESTED** |
| RAG-009 | Citation server validator: chỉ `chk_*` trong retrieval allowlist của request & user có quyền | **IMPLEMENTED · TESTED** |
| RAG-010 | Không đủ bằng chứng ⇒ `insufficientEvidence=true`, abstain, không bịa citation | **IMPLEMENTED · TESTED** |
| RAG-011 | URL/arXiv ingest chống SSRF/DNS rebinding, `robots.txt`, `userConfirmedRights=true` | **IMPLEMENTED · TESTED** (`DEFAULT-OFF`) |
| RAG-012 | OCR pretrained cục bộ (`rapidocr` / `vietocr`), opt-in theo env & `OCR_MODEL_VERSION` | **IMPLEMENTED · TESTED** (`DEFAULT-OFF`) |

## 2. P4.0 PDF ingestion sequence (IMPLEMENTED)

```text
Browser PDF upload (POST /v1/sources/{id}/document)
  → API stream + validate magic `%PDF-` / byte limit (20 MB) / owner + CSRF
  → Private MinIO/S3 object storage (random key), `source_documents.status = queued`
  → Celery ingest worker atomic claim + lease (300s, max 3 attempts)
  → Extract text theo page (max 300 pages, timeout 120s); trang thiếu text → OCR nếu OCR_ENABLED=true
  → Chunk text (target 1000 chars, min 200, no overlap) với offset + textHash
  → `ready` | `no_text` | `failed` (structured error code)
```
- Idempotent theo `(source_id, checksum, pipeline_version)`. Không lộ `storage_key` hay raw text qua `SourceDocumentOut`.

## 3. P4.1 Hybrid Retrieval & Verified Citations (IMPLEMENTED — `RAG_ENABLED=false`)

```text
Query (course/source scope)
  |-- SQL owner + linked-course filter (bắt buộc trước mọi bước tính điểm)
  |-- Lexical: PostgreSQL `to_tsvector('simple')` + `ts_rank_cd` (SQLite token-overlap trong test)
  `-- Vector: exact cosine trên `source_chunk_embeddings` (JSON vector; `hashing-ngram-v1` 256-dim mặc định hoặc `openai_compatible`)
        ↓
      RRF fusion (k=60) + ngưỡng `rag_min_lexical_score=0.40`, `rag_min_similarity=0.10`, `rag_vector_only_min_similarity=0.40`
        ↓
      Top-k bounded chunks → Tutor prompt (untrusted delimiter) hoặc `POST /v1/courses/{id}/sources/search`
        ↓
      Server validate toàn bộ `chk_*` citations theo allowlist của request (`validationStatus="locator_verified"`, `evidenceSupported=false`)
```
- **Giới hạn đã biết:** `hashing-ngram-v1` là lexical/subword baseline, **không phải** semantic embedding thật. Trước khi bật `RAG_ENABLED=true` cho người dùng cuối cần chốt provider embedding thật và hiệu chỉnh lại các ngưỡng trên tập eval ≥30 câu.

## 4. Citation contract thực tế (`TutorCitationOut` / `RagChunkOut`)

Mỗi citation trả ra gồm: `chunkId`, `sourceId`, `documentId`, `pageNumber`, `charStart`, `charEnd`, `sectionAnchor`, `textHash`, `sourceTitle`, `sourceVersion`, `sourceUrl` (`null` với PDF upload), `textSource` (`native | ocr`), `ocrConfidence?`, `ocrBbox?`, `validationStatus`, `evidenceSupported` (luôn `false` vì mới xác minh vị trí `locator_verified`, chưa chạy NLI kiểm chứng claim).

## 5. P4.2 Web / arXiv controls (IMPLEMENTED — `WEB_INGEST_ENABLED=false`)

- Cổng 7 lớp trong `services/url_fetcher.py`: (1) `WEB_INGEST_ENABLED` + allowlist host không rỗng, (2) HTTPS port 443 không userinfo, (3) DNS global-unicast check, (4) `PinnedNetworkBackend` re-resolve trong `connect_tcp` chống DNS rebinding, (5) `follow_redirects=False` kiểm lại mọi hop (max 3), (6) byte/time/char caps, (7) `robots.txt` conservative.
- Bắt buộc `userConfirmedRights=true` (lưu `rights_confirmed_at`).
- arXiv mặc định đọc `/abs` (Highwire `citation_*`), tôn trọng `robots.txt` (`export.arxiv.org` chỉ bật khi đặt `ARXIV_METADATA_SOURCE=atom`).
- Đã kiểm chứng mạng thật (`2026-11-01`): `example.com` và arXiv `1706.03762` (15 trang, 45 chunk).

## 6. P4.3 OCR opt-in (IMPLEMENTED — `OCR_ENABLED=false`)

- Hỗ trợ 2 engine cục bộ không gọi mạng:
  - `rapidocr` (ONNX PP-OCR, nhẹ; CER EN ≈ `0.000`, CER VI ≈ `0.094` do rơi dấu tiếng Việt).
  - `vietocr` (VGG-Transformer VI + detector rapidocr; CER VI ≈ `0.004`, cần torch ~250 MB, chậm hơn ~1.5×).
- Chỉ OCR trang thiếu text layer; đổi `pipelineVersion` để không ghi đè citation lịch sử; gắn `textSource="ocr"` rõ ràng.

## 7. Khoảng trống so với tham chiếu PolySkill (`PROPOSAL — NOT IMPLEMENTED`)

- **Structured `source.brief` (`P2-BRIEF`):** PolySkill nén nguồn sau ingest thành `brief {what, claims[1..10], notation[≤20], assumes[≤10], sections[≤40]{anchor, heading, gist}}` để các agent tạo khóa và tutor đọc theo mục lục nhẹ. SopiSkill hiện mới có `preview` ngắn ở `SourceDocumentOut` và tìm kiếm theo chunks — cân nhắc bổ sung `source.brief` ở phase sau.
- **Citation link behavior:** đối chiếu ngày `2026-11-22` xác nhận PDF có `canonicalUrl=null` được render dạng pill tĩnh không click được là chủ đích hợp lý; web/arXiv gắn `sourceUrl` + anchor mở link ngoài an toàn.
