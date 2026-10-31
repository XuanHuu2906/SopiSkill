# Source Research Agent (P2.SR)

> **Trạng thái:** IMPLEMENTED + TESTED (unit/integration/PostgreSQL race/Docker E2E).
> **Revision DB:** `0006_p2sr_source_research` (upgrade/downgrade/legacy-row đã kiểm chứng trên PostgreSQL throwaway).
> **Giới hạn cốt lõi:** chưa có ingestion nội dung, chưa có RAG, chưa tìm kiếm internet.
> Nguồn chỉ được **xác minh metadata** — không có bằng chứng nội dung.

## 1. Vị trí trong kiến trúc

```
User request → Course Orchestrator (API + course_service)
                    ↓
              Interview (5 câu, P2.1)
                    ↓
         Source Research Agent  ← (P2.SR, tuỳ chọn, default OFF)
                    ↓
              Source Registry (sources / course_sources, P3.0)
                    ↓
       Course Proposal → Approve → Generation Worker → Lessons
```

Course Orchestrator **giữ quyền điều phối**. Agent không đổi course, không sửa
progress, không gọi tool ngoài allowlist, không truy cập DB (chỉ nhận `saver` do
tầng service tiêm vào).

## 2. Vì sao module độc lập chứ không nhét vào `course_service`

| Lý do | Hệ quả |
|---|---|
| Nghiên cứu nguồn có vòng đời/cấu hình riêng (adapter, timeout, feature flag) | Bật/tắt không ảnh hưởng flow interview/proposal/generation |
| Cần test offline deterministic | Adapter mock chạy không network, không cần key |
| Dễ mở rộng P4 (ingest/RAG) | Chỉ cần thêm adapter + tool, không sửa contract API |
| Trung thực về giới hạn | Agent không có tool đọc nội dung ⇒ không thể "tự nhận" grounded |

## 3. Cấu trúc

```
backend/app/agents/source_research/
    __init__.py        # export công khai
    agent.py           # SourceResearchAgent.run() — bounded, deterministic
    schemas.py         # ResearchRequest, TopicAnalysis, SourceCandidate,
                       # CandidateScores, RankedSourceOut, ResearchResult
    policies.py        # domain trust policy (programming/medicine/general)
    ranking.py         # dedupe + scoring + verification status
    topic.py           # topic analysis rule-based (không LLM)
    tools.py           # allowlisted toolbox + budget/timeout/validation
    adapters/
        base.py        # protocol + bridge tới SourceDiscoveryAdapter có sẵn
        mock.py        # deterministic, KHÔNG network
backend/app/services/source_research_service.py   # identity, idempotency, persistence
backend/app/api/v1/research.py                    # endpoints
backend/alembic/versions/0006_p2sr_source_research.py
```

**Tái sử dụng, không nhân bản:** adapter discovery thật đã có từ P3.0
(`app/services/source_discovery.py`). `agent/adapters/base.py` chỉ định nghĩa
protocol tối thiểu + `ServiceDiscoveryBridge` chuyển `SourceCandidateOut` →
`SourceCandidate`. Thêm provider thật (Crossref/OpenAlex/arXiv) = implement adapter
trong `source_discovery.py` rồi cấu hình `SOURCE_RESEARCH_PROVIDER`.

## 4. Workflow agent (không có vòng lặp tự do)

1. `analyze_topic(request)` — hàm thuần, deterministic:
   domain (programming/medicine/general), chủ đề con, tiên quyết, trình độ, ngôn
   ngữ, truy vấn tìm kiếm.
2. `search_source_adapter(query, max_results)` cho tối đa **2 query** — mỗi call
   bị chặn bởi `max_tool_calls` và `tool_timeout_seconds`.
3. `dedupe_candidates` — chuẩn hoá URL (bỏ fragment, bỏ trailing slash, casefold
   host) hoặc `adapter+candidateId`; giữ ứng viên đầu tiên.
4. `rank_sources` — chấm điểm theo **domain policy**, trả kèm `selectionReason`.
5. `save_research_result` — chỉ khi service tiêm `saver`.

Không có suy luận nhiều bước tự do, không có LLM call trong agent. Muốn thêm
LLM ở P sau: giữ nguyên contract `ResearchResult`, chỉ thay bước 1/4.

## 5. Trạng thái kiểm chứng (4 cấp, tách biệt)

| Cấp | Ai/cái gì tạo | P2.SR |
|---|---|---|
| `discovered` | Agent thấy ứng viên từ adapter | **Có** (mặc định của agent) |
| `metadata_verified` | Kiểm tra **cấu trúc** metadata: URL http(s), có publisher/author, ngôn ngữ, ngày hoặc version | **Có** (nhưng ghi DB vẫn `unverified`) |
| `content_available` | Có nội dung đã ingest được phép truy xuất | **Không** — agent không có tool đọc nội dung |
| `evidence_verified` | Đoạn bằng chứng thật đã đối chiếu với claim | **Không** — thuộc P4 |

`ResearchResult` validator **từ chối** `content_available`/`evidence_verified`:
đó là bảo đảm ở tầng dữ liệu, không chỉ là quy ước.

Mock adapter luôn bị ép `discovered`, kể cả khi metadata trông đầy đủ — vì
metadata đó không có thật.

## 6. Domain policies (không dùng một trust score cho mọi lĩnh vực)

| Domain | Ưu tiên cao | Trọng số nhấn |
|---|---|---|
| `programming` | official documentation, standard/specification | authority + freshness |
| `medicine` | clinical guideline, systematic review, government health | authority (0.4) |
| `general` | chương trình chính thức, university course, textbook | metadata completeness |

Điểm `total` chỉ so sánh trong một lần nghiên cứu, **không phải xác suất nguồn
đúng**. Tiêu chí thiếu dữ liệu ⇒ `None` và bị loại khỏi mẫu số (không bị tính 0).

## 7. API contract

```
POST /v1/courses/{id}/research-runs          201 ResearchRunOut   (CSRF, rate limit 10/phút)
GET  /v1/courses/{id}/research-runs          ResearchRunListOut
GET  /v1/courses/{id}/research-runs/{runId}  ResearchRunOut       (cross-user ⇒ 404)
POST /v1/courses/{id}/research-runs/{runId}/accept
                                             200 ResearchRunOut    (409 nếu không linkable)
```

Request body (`extra=forbid`):

```json
{ "maxSources": 8, "learningGoals": ["..."], "learnerLevel": "beginner" }
```

Không có `courseId`/`ownerId` trong body: server lấy từ path + identity đã xác thực.

Response (rút gọn):

```json
{
  "researchRunId": "rr_<uuid>",
  "courseId": "crs_<uuid>",
  "status": "completed",
  "domain": "programming",
  "sources": [
    {
      "candidateId": "py-docs",
      "title": "Python official documentation",
      "sourceType": "official_documentation",
      "canonicalUrl": "https://docs.python.org/3/",
      "verificationStatus": "metadata_verified",
      "relevanceScore": 0.87,
      "selectionReason": "Loại nguồn 'official_documentation' thuộc nhóm chính thức ...",
      "isMock": false,
      "scores": { "authority": 1.0, "relevance": 0.87, "total": 0.88 }
    }
  ],
  "warnings": [],
  "insufficientEvidence": false,
  "adapter": "curated",
  "isMock": false,
  "toolCalls": 2,
  "notice": "Metadata do danh mục curated cung cấp; chưa đối chiếu nội dung gốc."
}
```

Nguồn **không** có `sourceId` trong output: id registry chỉ tồn tại sau khi vào
bảng `sources` (accept), ngăn agent tự nhận là nguồn đã đăng ký.

## 8. Feature flag

```env
SOURCE_RESEARCH_ENABLED=false        # mặc định TẮT ⇒ hành vi cũ giữ nguyên
SOURCE_RESEARCH_PROVIDER=mock        # mock | curated (cả hai offline)
SOURCE_RESEARCH_MAX_SOURCES=8
SOURCE_RESEARCH_TIMEOUT_SECONDS=15
SOURCE_RESEARCH_MAX_TOOL_CALLS=12
SOURCE_RESEARCH_TOOL_TIMEOUT_SECONDS=5
SOURCE_RESEARCH_AUTO_LINK=false      # tự research + link khi generation bắt đầu
```

- Flag tắt: endpoint trả `503 SOURCE_RESEARCH_DISABLED`; worker **không** gọi
  `maybe_auto_link_for_generation` (hàm tự kiểm tra flag) ⇒ flow cũ y hệt.
- `SOURCE_RESEARCH_AUTO_LINK=true` + provider curated: worker chạy agent **trước**
  khi resolve source context; lỗi nghiên cứu không làm job thất bại.
- Mock **không bao giờ** auto-link (URL `example.invalid` không tồn tại).

## 9. Idempotency & hạn chế retry

- `request_fingerprint = sha256(courseId, topic, level, goals, language, maxSources, adapter)`.
- `UNIQUE(course_id, request_fingerprint)` ⇒ request đồng thời tạo đúng **1 row**
  (đã kiểm chứng trên PostgreSQL thật với 6 request song song).
- Run `failed` hoặc `running` quá hạn (`> max(60s, 4×timeout)`) được **chạy lại
  trên cùng row**, không sinh row mới. Run đã completed ⇒ trả `reused=true`.
- Toàn bộ agent bị chặn bởi `asyncio.wait_for(source_research_timeout_seconds)`;
  timeout ⇒ row `failed` + `error.code=SOURCE_RESEARCH_TIMEOUT` (retryable), không
  treo job generation.

## 10. Bảo mật

| Rủi ro | Xử lý |
|---|---|
| Cross-tenant đọc kết quả nghiên cứu | `get_owned_course` + query thêm `user_id` ⇒ 404 |
| Agent ghi DB trực tiếp | Agent không import DB; chỉ gọi `saver` do service tiêm |
| Prompt injection từ nguồn | Chưa ingest nội dung ⇒ chưa có nội dung nào vào prompt |
| SSRF / crawl ngoài ý muốn | Adapter `web` từ chối; mock/curated không network (test chặn `socket.socket`) |
| Nguồn giả được đánh dấu verified | Mock bị ép `discovered`; DB ghi `unverified`; `accept` từ chối run mock |
| PII người học bị gửi ra ngoài | Query chỉ chứa topic + chủ đề con; goals/level **không** được gửi vào adapter |
| Đốt chi phí | Không LLM, không network; bounded tool calls + timeout + rate limit |

## 11. Nâng cấp thành Source-First Hybrid RAG (P4)

Agent đã chuẩn bị sẵn các điểm nối; **không cần đổi contract P2.SR**:

| Điểm nối hiện tại | P4 |
|---|---|
| `ResearchResult.sources[].verificationStatus` (agent-verifiable) | Thêm bước ingest ⇒ ghi `sources.content_hash`, `source_documents` |
| `source_research_service.link_verified_sources` (chỉ `metadata_verified`) | Sau ingest, link kèm document id |
| `source_context.build_source_context(excerpt_provider=…)` | Trả chunk text đã retrieve ⇒ `lesson_grounding` chuyển `source_grounded` |
| `citation_service.validate_citation_locator(has_ingested_content=…)` | `True` + so chunk/page ⇒ `locator_verified` |
| `SourceDiscoveryAdapter` (curated/mock/web-placeholder) | `ArxivAdapter`/`WebAdapter` + allowlist + SSRF guard |
| `rank_candidates` (metadata-only) | Thêm tín hiệu retrieval (chunk coverage) — **không** thay thế policy domain |

Checklist P4 (không làm ở P2.SR):

1. Migration `source_documents`, `source_chunks`, bật `pgvector` **trong migration**.
2. Ingest worker idempotent theo `source_id + content_hash + pipeline_version`.
3. Retrieval có filter `owner_id`/`course_id` **trong query**.
4. Eval Recall@k/MRR/citation precision trước khi bật cho người dùng.
5. **Không** đặt `evidence_verified` chỉ vì có locator.

## 12. Giới hạn đã biết (trung thực)

- Agent **không truy cập internet**; `mock`/`curated` chỉ đọc dữ liệu cấu hình.
- Agent **không kiểm chứng được nội dung** nguồn (chưa ingest ⇒ không đọc được).
- `metadata_verified` = kiểm tra cấu trúc metadata, không phải "nguồn đáng tin".
- Topic analysis rule-based: chủ đề lạ có thể không tách được chủ đề con.
- Relevance là so khớp từ khoá bề mặt.
- `SOURCE_RESEARCH_PROVIDER=web` chưa triển khai (bị từ chối có chủ đích).
- UI chưa có màn hình research; API sẵn sàng.
