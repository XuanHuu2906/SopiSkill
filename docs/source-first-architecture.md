# Source-First Architecture (P3.0) & lộ trình RAG P4

> **Đánh số:** tài liệu này là **P3.0b** trong `SOPISKILL_MASTER_IMPLEMENTATION_PLAN.md`;
> plan gốc dành P3.0–P3.1 cho AI Tutor. Revision DB: `0005_p30_source_registry`.
>
> **Trạng thái:** P3.0b **IMPLEMENTED + TESTED** (Source Registry + Evidence Contract + minimal
> source-first integration). **P4.0 ingest PDF text + provenance: IMPLEMENTED + TESTED** (xem §10).
> Retrieval/embedding/citation đã kiểm chứng (P4.1) **CHƯA** triển khai.
> **Nhãn bằng chứng:** FACT (đọc từ code/migration), INFERENCE (suy luận có ghi rõ), UNKNOWN
> (chưa xác minh), PROPOSAL (thiết kế của dự án).
> **Nguồn tham khảo bên ngoài:** `polyskill-analysis-report.md`, `polyskill-dynamic-analysis.md`
> chỉ dùng để hiểu **hành vi client**. Báo cáo ghi rõ RAG/embedding/vector search phía server của
> sản phẩm đó là **UNKNOWN** ⇒ tài liệu này **không** khẳng định PolySkill dùng RAG/pgvector/
> embedding provider nào. Thiết kế dưới đây độc lập.

## 1. Vì sao "source-first"

Nội dung do LLM sinh có hai loại sai khác nhau: **sai kiến thức** (model bịa) và **không truy
vết được** (không biết dựa vào đâu). Source-first giải quyết loại thứ hai: mọi tuyên bố có nguồn
phải trỏ tới một **bản ghi nguồn có thật, có chủ, có phiên bản** — và trạng thái kiểm chứng phải
phản ánh **đúng mức đã kiểm tra**, không phải mức mong muốn.

Nguyên tắc bất biến của P3.0:

1. URL hợp lệ **không** làm nguồn đáng tin.
2. Model **không** được cấp `sourceId` ⇒ không thể bịa citation.
3. Có citation **không** đồng nghĩa nội dung đúng.
4. Không đủ bằng chứng ⇒ nói rõ "chưa xác minh", không tô hồng.

## 2. Bốn cấp kiểm chứng (phân biệt tuyệt đối)

| Cấp | Ý nghĩa | Ai/cái gì chứng minh | P3.0 |
|---|---|---|---|
| 1. Metadata verified | Title/publisher/version/ngày đã được review | Người review hoặc evaluator metadata (chỉ **đề xuất**) | Một phần: evaluator đề xuất, **không tự ghi** |
| 2. Locator verified | chunk/page/anchor được cite **có thật** trong nguồn | Đối chiếu với chunk store | **Chưa có** (chưa ingest) |
| 3. Evidence supports claim | Đoạn evidence thực sự chống lưng cho câu trong bài | So khớp ngữ nghĩa + review | **Không thể** ở P3.0 |
| 4. Claim corroborated | Claim được nguồn độc lập khác xác nhận | So sánh đa nguồn | **Không thể** ở P3.0 |

Enum tương ứng: `SourceVerificationStatus` (1) và `CitationValidationStatus` (2,3) với các giá
trị `unverified`, `locator_verified`, `evidence_supported`, `unavailable`, `source_changed`,
`rejected`. P3.0 chỉ có thể tạo ra `unverified`, `unavailable`, `source_changed`, `rejected` —
**không** bao giờ `evidence_supported`.

## 3. Schema (FACT — `backend/app/models/models.py`, migration `0005_p30_source_registry`)

### `sources`
`id`, `source_type` (official_documentation | academic | user_document | webpage), `title`,
`canonical_url`, `author`, `publisher`, `publication_date`, `source_updated_at`, `retrieved_at`,
`language`, `version`, `owner_id` (NULL = public/không sở hữu riêng), `visibility`
(public | private), `license_info`, `content_hash`, `verification_status`, `dedupe_key`,
`created_at`, `updated_at`.

- `UNIQUE(dedupe_key)` chống duplicate vô hạn. `dedupe_key = sha256(scope | type | canonical_url
  hoặc title | content_hash)`; `scope = user:<id>` cho private, `public` cho public ⇒ hai người
  dùng có thể có nguồn private cùng tiêu đề mà không đụng nhau.
- `INDEX(visibility, owner_id)` phục vụ truy vấn "nguồn tôi thấy được".
- Nguồn **không** chứa nội dung tài liệu. `content_hash`/`version` là móc nối với ingestion P4.

### `course_sources`
`id`, `course_id`, `source_id`, `evaluation` (JSONB snapshot), `created_at`,
`UNIQUE(course_id, source_id)`.

### `lesson_citations`
`id`, `lesson_id`, `source_id`, `source_version`, `chunk_id`, `page_number`, `section_anchor`,
`evidence_text`, `validation_status`, `created_at`.

- `source_version` là **snapshot**; nếu `sources.version` đổi thì citation cũ được phát hiện là
  `source_changed` thay vì âm thầm trỏ sang bản mới.

### `lessons.grounding`
`source_grounded | general_ai_knowledge`, `server_default='general_ai_knowledge'` ⇒ mọi bài học
cũ đọc được và được hiểu là "kiến thức chung, chưa kiểm chứng" (không backfill dữ liệu giả).

## 4. Service layer (FACT)

| Module | Trách nhiệm |
|---|---|
| `services/source_service.py` | create (idempotent), get/list có ownership, link/unlink course, load cho worker |
| `services/source_evaluation.py` | evaluator deterministic metadata-only + công thức có giới hạn |
| `services/citation_service.py` | `validate_citation_locator`, `replace_lesson_citations`, `list_lesson_citations` |
| `services/source_discovery.py` | interface adapter: `curated` (catalog env), `mock` (deterministic, no network), `web` (placeholder từ chối) |
| `services/source_context.py` | dựng `SourceContextEntry`, quyết định `LessonGrounding`, câu thông báo |

### 4.1 Công thức đánh giá nguồn — và giới hạn của nó

Trọng số: authority 0.25, relevance 0.20, evidence 0.20, freshness 0.15, consistency 0.10,
licensing 0.10.

```
score(criterion) ∈ [0,1];  unknown ⇒ None (KHÔNG phải 0, không phải cao)
weightedScore = Σ(score_i × w_i) / Σ(w_i)      # chỉ i có score
coverage      = Σ(w_i có score) / Σ(w_i toàn bộ)
verdict       = insufficient_metadata nếu coverage < 0.5
                ngược lại: strong ≥ 0.7, moderate ≥ 0.45, else weak
```

- Thiếu dữ liệu ⇒ `unknown`, loại khỏi mẫu số. Không có chuyện "thiếu metadata ⇒ điểm cao".
- `license` hạn chế (`all rights reserved`, …) ⇒ `penalized`, chặn `metadata_verified`.
- `relevance` chỉ so khớp keyword bề mặt; `consistency` mặc định `unknown` vì chưa so sánh chéo.
- **Giới hạn cốt lõi:** evaluator này không đọc nội dung, không xác minh factual, không thay thế
  review. `suggestedVerificationStatus` chỉ là đề xuất; API không tự ghi vào DB.

## 5. API contract (FACT)

```
POST /v1/sources                      201 SourceOut          (CSRF bắt buộc)
GET  /v1/sources                      SourceListOut          (public + của mình)
GET  /v1/sources/discover?topic=…     SourceDiscoveryOut     (adapter=curated|mock; web ⇒ 503)
GET  /v1/sources/{id}                 SourceOut              (private người khác ⇒ 404)
GET  /v1/sources/{id}/evaluation      SourceEvaluationOut
POST /v1/courses/{id}/sources         CourseSourceOut 201    (CSRF; ownership cả course & nguồn)
GET  /v1/courses/{id}/sources         CourseSourceListOut
GET  /v1/lessons/{id}                 LessonOut + grounding + citations[] + evidenceNotice
```

Thêm field vào `LessonOut` là **backward-compatible** (field có default). Client cũ bỏ qua field
mới vẫn hoạt động.

## 6. Luồng generation sau tích hợp (FACT)

```
topic → interview → proposal → approve → [source resolution] → generation → lessons
```

1. `approve` giữ nguyên (không thêm bước bắt buộc).
2. Worker `_generate_lessons` load `course_sources` **scoped theo `course.user_id`** (worker
   không có identity request; ownership suy từ course đã xác thực ở approve/claim).
3. `build_source_context` dựng metadata (title/publisher/url/version). P3.0 **không** có excerpt.
4. Provider nhận `source_context` (metadata + ranh giới chống prompt injection) và bị cấm tự tạo
   URL/số trang/sourceId.
5. Sau mỗi lesson: `grounding` do **server** quyết định; `replace_lesson_citations` ghi citation
   từ registry; snapshot đánh giá nguồn vào `course_sources.evaluation` nếu chưa có.
6. Citation P3.0 luôn `unverified` (không locator) hoặc `unavailable` (có locator nhưng chưa
   ingest). Bài học **luôn** `general_ai_knowledge` vì chưa có đoạn bằng chứng thật.

### 6.1 Chống prompt injection từ nguồn
Nội dung nguồn (khi có ở P4) phải được đặt trong delimiter `<<<NGUON_BAT_DAU>>> … <<<NGUON_KET_THUC>>>`
và prompt tuyên bố rõ đó **không phải chỉ thị**. P3.0 chưa ingest nên rủi ro này chưa mở.

### 6.2 Retry/idempotency
Không đổi. `replace_lesson_citations` xóa-rồi-tạo theo `lesson_id` khi ghi bài ⇒ retry không
nhân bản citation. `dedupe_key` + `UNIQUE(course_id, source_id)` chống nhân bản nguồn/liên kết.

## 7. Bảo mật (FACT + lý do thiết kế)

| Rủi ro | Cách xử lý |
|---|---|
| Đọc nguồn private người khác | Query lọc `visibility='public' OR owner_id=me`; sai ⇒ 404 (không xác nhận tồn tại) |
| Link nguồn người khác vào course | `get_owned_course` + `get_accessible_source` |
| Bịa citation | Model không nhận/không trả `sourceId`; citation chỉ sinh server-side từ registry |
| Nguồn giả "verified" | Tạo nguồn luôn `unverified`; evaluator chỉ đề xuất |
| SSRF qua discovery | P3.0 **không** fetch URL; adapter `web` từ chối 503 |
| Prompt injection | Ranh giới delimiter + chỉ thị không tin nội dung nguồn |
| Lộ PII/key trong log | Log chỉ `source_id/type/visibility`; key nằm env server-side |
| Cross-tenant retrieval (P4) | Filter `owner_id` **tại query**, không lọc sau khi lấy |

## 8. Chuẩn bị P4 — interface & điểm tích hợp (PROPOSAL)

Mục tiêu P4: biến metadata-only thành **evidence thật** mà không đổi contract API P3.0.

### 8.1 Model bổ sung (P4.0) — **ĐÃ TRIỂN KHAI** (revision `0011_p40_source_ingest`)

```
source_documents  (source_id, content_hash, mime, byte_size, page_count, pipeline_version,
                   status, storage_key, original_filename, attempts_count, max_attempts,
                   lease_expires_at, heartbeat_at, dispatched_at, dispatch_attempts,
                   error_code, error, ingested_at)
source_chunks     (source_id, document_id, chunk_index, page_number, char_start, char_end,
                   section_anchor, text, text_hash)
```

- `source_chunks.text` là nguồn duy nhất được phép làm `evidence_text` (P4.1).
- `embedding`/`embedding_model`/`dimension` **chưa** có: thuộc P4.1 sau benchmark model.
- pgvector **chỉ** thêm khi chốt dimension (P4.1), không thêm trước.
- `UNIQUE(source_id, content_hash, pipeline_version)` chống nhân bản document khi retry.

### 8.1b Trạng thái P4.0 (FACT)

| Hạng mục | Trạng thái |
|---|---|
| Upload streaming + trần byte/page + magic `%PDF-` | **Có** (`services/ingest.check_limits`) |
| Private storage MinIO/S3, key ngẫu nhiên, không lộ path | **Có** (`services/storage.py`) |
| Trích text theo trang; PDF scan ⇒ `no_text` (không OCR) | **Có** (`services/ingest.extract_pages`) |
| Chunking page provenance, offset/hash, không overlap | **Có** (`services/ingest.chunk_pages`) |
| Worker idempotent + claim/lease + outbox reconciler | **Có** (`worker/ingest.py`) |
| Untrusted delimiter | **Có** (`ingest.wrap_untrusted`), chưa nối prompt (chưa retrieval) |
| `locator_verified` / `evidence_supported` | **KHÔNG** tạo ra — cần đối chiếu locator (P4.1) |

### 8.2 Điểm nối đã chuẩn bị sẵn trong P3.0

| Điểm nối | Hiện tại (P4.0) | P4.1 |
|---|---|---|
| `source_context.build_source_context(excerpt_provider=…)` | vẫn `None` | Trả chunk text đã retrieve |
| `source_context.lesson_grounding` | Cần excerpt thật | Không đổi |
| `citation_service.validate_citation_locator(has_ingested_content=…)` | `True` khi có document `ready` | So locator với chunk store ⇒ `locator_verified` |
| `citation_service.replace_lesson_citations(evidence_by_source=…)` | `None` | Map `source_id → evidence text` |
| `sources.content_hash` | Cập nhật từ SHA-256 file thật khi ingest | Phát hiện nguồn đổi (`source_changed`) |
| `SourceDiscoveryAdapter` | curated/mock | `ArxivAdapter`, `WebAdapter` có SSRF guard |

### 8.3 Ingestion (P4.0) — yêu cầu an toàn bắt buộc

- Upload streaming, giới hạn size/type, xác minh MIME **magic**, giới hạn page count; không tin
  extension.
- Storage server-side path non-public, object key random, download chỉ sau auth.
- Trích text PDF **trước** (không OCR ở P4.0); PDF scan ⇒ `NO_EXTRACTABLE_TEXT`.
- Chunking giữ `page_number`/offset/heading; tránh overlap gây trích dẫn mơ hồ.
- Worker idempotent theo `source_id + content_hash + pipeline_version`.
- Lọc/delimiter nội dung nguồn như **untrusted input**.

### 8.4 Retrieval (P4.1)

- Baseline: PostgreSQL FTS (lexical) + pgvector exact search; **chỉ** thêm hybrid RRF/reranker
  khi benchmark cho thấy lợi ích (không mặc định gọi là BM25).
- Filter `owner_id`/`course_id`/`source_id` **trong query**.
- Retrieval trả `chunkId` + `page` + `contentHash`; citation validator đối chiếu **thật**.
- Không đủ evidence ⇒ trả "chưa đủ thông tin từ tài liệu", không bịa.
- Eval: Recall@k, MRR, citation precision, groundedness; case âm (no-source, chunk xung đột,
  chunk chứa prompt injection, chunk của user khác).

### 8.5 Web/arXiv (P4.2) — chưa triển khai

Bắt buộc: HTTPS allowlist/policy outbound, chặn localhost/private/link-local/metadata IP,
chống DNS rebinding, giới hạn redirect/size/time, tôn trọng robots/license/paywall.

### 8.6 Transition checklist từ P3.0 → P4

1. [ ] Migration P4.0: `source_documents`, `source_chunks`, `vector` extension (bật trong migration,
       không bật bằng tay).
2. [ ] Ingest worker + idempotency + test PDF text/scan/oversize/corrupt.
3. [ ] Cập nhật `source_evaluation.evaluate_source(has_content=…)` — đã có tham số.
4. [ ] Cập nhật `citation_service` để set `locator_verified` **chỉ khi** chunk/page tồn tại.
5. [ ] Bật `source_context.excerpt_provider` ⇒ grounding chuyển `source_grounded` **chỉ** khi có
       excerpt thật.
6. [ ] Eval retrieval + citation trước khi bật cho người dùng (`RAG_ENABLED`).
7. [ ] Frontend: mở citation tới đúng page/chunk; hiển thị `locator_verified` khác
       `evidence_supported`.

> **Cảnh báo:** không đánh dấu `evidence_supported` chỉ vì locator tồn tại. Đó là hai cấp khác nhau.

## 9. Giới hạn đã biết của P3.0 (trung thực)

- Không có nội dung nguồn ⇒ **không thể** grounding thật; mọi bài học là `general_ai_knowledge`.
- `locator_verified` chưa từng được tạo ra (chưa có chunk store).
- `consistency` luôn `unknown` (chưa so sánh chéo nguồn).
- `relevance` chỉ keyword bề mặt.
- Chưa có UI tạo/duyệt nguồn (chỉ hiển thị nguồn đã liên kết + citation); tạo nguồn hiện qua API.
- Discovery chỉ `curated`/`mock`; không tìm kiếm thật.
- P4.0 đã có job ingest PDF text: `content_hash` được cập nhật từ file thật và chunk có provenance,
  nhưng **chưa** có retrieval/citation verified (P4.1).

## 10. P4.0 — PDF text ingestion (FACT, đã triển khai)

### 10.1 API bổ sung

```
GET    /v1/sources/ingest-config                     SourceIngestConfigOut (giới hạn, không lộ secret)
POST   /v1/sources/{sourceId}/document              202 SourceDocumentOut  (multipart, CSRF)
GET    /v1/sources/{sourceId}/documents              SourceDocumentListOut
GET    /v1/sources/{sourceId}/documents/{docId}      SourceDocumentOut
DELETE /v1/sources/{sourceId}/documents/{docId}      204
DELETE /v1/sources/{sourceId}                        204 (chỉ nguồn private của chính user)
```

Upload chỉ áp dụng cho **nguồn private thuộc user hiện tại** (`source_service.get_owned_source`);
nguồn public dùng chung và nguồn private của người khác trả 404 (không xác nhận tồn tại).

### 10.2 Trạng thái document

`queued → extracting → ready | no_text | failed`.

- `no_text` là trạng thái thật của PDF scan (không có text layer), **không** phải lỗi và **không**
  được đọc là "đã OCR". Chỉ `ready` mới có chunk dùng được.
- Lease + `max_attempts` chặn retry vô hạn; reconciler chạy qua Celery beat
  (`app.worker.ingest.reconcile_ingest`).
- Upload trùng bytes + cùng pipeline trả document cũ (không chạy lại ingest, không nhân bản chunk).

### 10.3 Giới hạn/không làm ở P4.0

- Không OCR (P4.3), không web/arXiv (P4.2), không embedding/retrieval (P4.1).
- Không malware scanner thật: chỉ giới hạn parser/size/page + private storage. Không được mô tả
  hệ thống là đã quét virus/malware.
- Chưa có UI mở đúng page/chunk và chưa hiển thị citation đã kiểm chứng — cần P4.1.
- `groundingAvailable` vẫn `false`: có chunk **không** làm bài học `source_grounded`.
