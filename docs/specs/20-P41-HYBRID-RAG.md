# 20 — P4.1 Hybrid RAG, Embeddings & Verified Citations (offline-first)

**Trạng thái:** IMPLEMENTED (working tree, chưa commit). Quyết định kiến trúc do người
dùng phê duyệt 2026-10-31: **phương án A — offline-first baseline**.

## 1. Phạm vi & quyết định

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| Embedding mặc định | `hashing` — deterministic, không network, không tải model | Chạy được pytest/CI offline, 0 chi phí |
| Embedding thật | adapter `openai_compatible`, **mặc định TẮT**, fail-fast khi thiếu cấu hình | Không tự gọi API trả phí |
| Vector store | JSON array + cosine exact trong Python, **không pgvector** | Không đổi Docker image; benchmark trước khi chuyển |
| Lexical | PostgreSQL `to_tsvector('simple', ...)` + `ts_rank_cd`; SQLite dùng token-overlap Python | FTS thật ở prod, test được offline |
| Fusion | RRF `Σ 1/(k + rank)`, k=60 mặc định | Không phụ thuộc scale điểm giữa 2 ranker |
| Ownership | Filter ở **SQL trước** khi tính similarity | Không thể lộ chunk người khác kể cả khi lỗi scoring |
| Citation | Chỉ `chk_<uuid>` do retrieval trả về + đối chiếu DB (owner/page/hash) | Không thể bịa nguồn/trang |
| Abstention | Không đủ bằng chứng ⇒ nói rõ, không tạo citation | RAG-010 |
| Bật/tắt | `RAG_ENABLED=false` mặc định | Không đổi hành vi P3.x hiện có |

**KHÔNG** coi hashing embedding là tương đương semantic embedding của model thật:
nó là baseline lexical/subword (word token + char n-gram + bỏ dấu tiếng Việt), có
collision hash, chỉ đo bằng benchmark trong `backend/evals/rag_eval.py`.

## 2. Interface embedding (ổn định để thay provider/pgvector)

```python
@dataclass(frozen=True)
class EmbeddingSpec:      # (provider, model, dimension, version)
    provider: str; model: str; dimension: int; version: str

class EmbeddingProvider(Protocol):
    spec: EmbeddingSpec
    async def embed_documents(self, texts: list[str]) -> list[list[float]]
    async def embed_query(self, text: str) -> list[float]
```

- `get_embedding_provider()` là **điểm thay duy nhất**. Đổi sang model multilingual
  hoặc pgvector chỉ cần thêm adapter/backend, không sửa `retrieval_service`.
- Vector luôn được gắn `provider+model+dimension+version`; retrieval **chỉ** dùng
  embedding khớp spec đang cấu hình ⇒ không trộn vector giữa model/version.
- Đổi dimension/model ⇒ spec khác ⇒ rows mới (không ghi đè); re-embed là thao tác
  idempotent riêng, dữ liệu cũ vẫn còn để rollback.

## 3. Truy vấn

```text
scope SQL (course + owner/public + document ready + [sourceIds])
   ├─ lexical: FTS/ts_rank_cd (PG) | token-overlap (SQLite)  → top L
   └─ vector : cosine(active spec)                            → top V
                ↓ RRF(k=60, bounded top-k)
        RetrievedChunk{chunkId, sourceId, documentId, page, charStart/End, anchor, textHash}
                ↓
   nếu rỗng hoặc điểm < ngưỡng ⇒ insufficientEvidence=true, không bịa
```

Giới hạn có chủ đích: candidate vector bị chặn (`RAG_CANDIDATE_LIMIT`) nên đây là
**exact search có trần**, không phải ANN. Chuyển pgvector/HNSW cần benchmark
latency/recall trên corpus lớn hơn — ghi ở mục 7.

## 4. Citation contract

Model được cấp danh sách chunk id trong prompt (khối untrusted). Trả lời phải
trích `[chk_...]`. Server:

1. Parse id từ **câu trả lời cuối** của model.
2. Bỏ mọi id không nằm trong allowlist của **chính request đó**.
3. Đối chiếu DB: chunk tồn tại, thuộc source ready + owner/public + course link,
   `text_hash` và `page_number` khớp ⇒ `locator_verified`.
4. Chỉ các citation đã verify mới được lưu (`tutor_messages.citations`) và hiển thị.
5. Không có citation hợp lệ ⇒ UI hiện nguồn đã truy xuất ở trạng thái chưa đối
   chiếu / thông báo chưa đủ căn cứ, **không** tô hồng thành đã kiểm chứng.

## 5. Feature flags

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `RAG_ENABLED` | `false` | Bật retrieval + citation trong tutor |
| `EMBEDDING_PROVIDER` | `hashing` | `hashing` \| `openai_compatible` |
| `EMBEDDING_MODEL` / `_DIMENSION` / `_VERSION` | `hashing-ngram-v1` / `256` / `v1` | Spec |
| `EMBEDDING_BASE_URL` / `_API_KEY` | rỗng | Chỉ cho `openai_compatible`; thiếu ⇒ `EMBEDDING_NOT_CONFIGURED` |
| `RAG_TOP_K` / `_CANDIDATE_LIMIT` / `_RRF_K` / `_MIN_SCORE` | 6 / 2000 / 60 / 0.0 | Truy vấn |
| `RAG_CONTEXT_MAX_CHARS` / `_MAX_CITATIONS` | 6000 / 5 | Trần prompt/response |

## 6. Giới hạn đã biết (không được che)

- Hashing embedding **không phải** semantic embedding; recall kém hơn model thật
  trên câu hỏi diễn đạt khác từ ngữ.
- PostgreSQL `simple` config giữ dấu tiếng Việt; truy vấn không dấu chỉ khớp qua
  nhánh vector (đã fold dấu), không qua FTS.
- Vector cosine quét có trần nên không phù hợp corpus rất lớn (chưa benchmark).
- Chưa có reranker; chưa có qrels do con người gán ngoài bộ eval nội bộ.
- `locator_verified` chứng minh **vị trí** tồn tại, không chứng minh claim đúng
  (`evidence_supported` vẫn cần đánh giá riêng).

## 7. Go/no-go cho pgvector

Chỉ chuyển khi benchmark trên corpus thật cho thấy: vector scan vượt
`RAG_CANDIDATE_LIMIT` hoặc p95 latency retrieval vượt ngưỡng chấp nhận, **và**
recall@k không giảm. Số đo hiện tại nằm trong `docs/development-progress.md`.
