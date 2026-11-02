from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"

    database_url: str = "sqlite+aiosqlite:///./ailp.db"

    redis_url: str = ""

    llm_provider: str = "mock"
    # Provider thật dùng chung namespace này; key CHỈ tồn tại server-side.
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    # Trần token output mặc định (giữ tương thích). Có thể override theo từng
    # loại call — proposal cần nhiều token hơn interview rất nhiều.
    llm_max_output_tokens: int = 2000
    llm_max_output_tokens_interview: int = 800
    llm_max_output_tokens_proposal: int = 4500
    llm_max_output_tokens_lesson: int = 3000
    # P2.2 — LLM-as-judge (rubric chấm chất lượng). Chỉ dùng khi eval, không
    # nằm trên đường đi của người học.
    llm_max_output_tokens_judge: int = 3000
    llm_max_input_chars: int = 12_000
    # Số lần thử lại khi LLM trả JSON đúng cú pháp nhưng sai schema/semantic
    # (1 = tối đa 2 request cho một bước). Bounded để không đốt tiền.
    llm_max_schema_retries: int = 1
    # P2.2 — cost control. Giá để trống ⇒ `costEstimateUsd = None` (chưa biết),
    # KHÔNG báo 0. Định dạng: {"model": {"inputPerMTok": 0.27, "outputPerMTok": 1.1}}.
    llm_pricing_json: str = ""
    # Trần token (prompt+completion) cho MỘT generation job. 0 = không giới hạn.
    # Job vượt trần ⇒ dừng giữa chừng với lỗi `BUDGET_EXCEEDED` (không retry).
    generation_max_tokens_per_job: int = 400_000
    # Trần chi phí ước tính cho một job (USD). 0 = không giới hạn.
    generation_max_cost_usd_per_job: float = 0.0
    # Giữ lại cho tương thích .env cũ (không dùng trực tiếp trong adapter).
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    @property
    def llm_api_key_resolved(self) -> str:
        """Ưu tiên LLM_API_KEY, fallback OPENAI_API_KEY (không lộ ra response/log)."""
        return self.llm_api_key or self.openai_api_key

    cors_origins: str = "http://localhost:3000"

    generation_max_schema_retries: int = 2

    # P1.2 reliability
    generation_lease_seconds: int = 180
    generation_max_attempts: int = 3
    generation_retry_backoff_seconds: int = 2
    generation_dispatch_timeout_seconds: float = 5.0
    generation_dispatch_grace_seconds: int = 10
    generation_max_dispatch_attempts: int = 5
    generation_lesson_timeout_seconds: float = 60.0
    generation_reconcile_interval_seconds: int = 30
    generation_allow_inline_fallback: bool = True
    # Chỉ dùng cho dev/test: chạy generation NGAY trong request (await) thay vì
    # fire-and-forget. Tránh chia sẻ connection SQLite :memory: giữa 2 session.
    generation_inline_blocking: bool = False

    # P3.0 Source-First — registry/discovery/evaluation
    # Adapter discovery mặc định. `mock` và `curated` đều KHÔNG gọi network.
    source_discovery_adapter: str = "curated"
    # Danh mục nguồn chọn tay (JSON array). Rỗng = danh mục trống.
    source_curated_catalog: str = ""
    # Bật đưa danh sách nguồn đã liên kết vào prompt sinh bài học.
    source_context_enabled: bool = True
    # Trần ký tự excerpt gửi kèm mỗi nguồn (P3.0 chưa ingest nội dung nên thường None).
    source_context_max_chars: int = 0

    # P2.SR Source Research Agent — MẶC ĐỊNH TẮT để giữ nguyên hành vi cũ.
    source_research_enabled: bool = False
    # mock | curated. Cả hai KHÔNG gọi network; `web` bị từ chối ở adapter discovery.
    source_research_provider: str = "mock"
    source_research_max_sources: int = 8
    # Trần thời gian toàn bộ một lần nghiên cứu (giây) — chặn job treo vô hạn.
    source_research_timeout_seconds: float = 15.0
    # Trần số tool call của agent (mỗi call có timeout riêng).
    source_research_max_tool_calls: int = 12
    source_research_tool_timeout_seconds: float = 5.0
    # Tự động nghiên cứu + link nguồn khi generation bắt đầu. Chỉ có hiệu lực khi
    # source_research_enabled=True. Mặc định tắt: flow cũ không đổi.
    source_research_auto_link: bool = False

    # P3.0 AI Tutor — mặc định TẮT để không đổi hành vi hiện tại.
    tutor_enabled: bool = False
    # Số message history (user+assistant) gửi kèm trong một lời gọi.
    tutor_history_max_messages: int = 12
    # Trần ký tự cho một câu hỏi của người học.
    tutor_max_question_chars: int = 2000
    # Trần ký tự nội dung lesson đưa vào prompt (public blocks, không answer key).
    tutor_context_max_chars: int = 6000
    # Trần token output cho một câu trả lời tutor.
    llm_max_output_tokens_tutor: int = 900
    # Timeout toàn bộ một stream (giây) — chặn stream treo vô hạn.
    tutor_stream_timeout_seconds: float = 60.0
    # Khoảng nghỉ giữa hai heartbeat khi provider chưa trả token (giây).
    tutor_heartbeat_seconds: float = 15.0
    # Số lượt hỏi tối đa/24h/user. 0 = không giới hạn lượt.
    tutor_messages_per_day: int = 0
    # P3.1 — allowance token: trần token (prompt+completion) cộng dồn trong 24h.
    # 0 = không giới hạn. Token chưa biết (provider không báo) được tính là 0,
    # nghĩa là trần này KHÔNG bảo đảm chặn chi phí khi provider không trả usage.
    tutor_tokens_per_day: int = 0
    # P3.1 — số stream đồng thời tối đa trên MỖI user (0 = không giới hạn).
    tutor_max_concurrent_streams: int = 2
    # P3.1 — một message `running`/`pending` quá tuổi này bị coi là mồ côi khi
    # user mở thread mới; không có tiến trình nào còn ghi nó (server restart).
    tutor_stale_stream_seconds: float = 180.0
    # P3.1 — nhịp kiểm tra cờ stop server-side trong lúc stream (giây).
    tutor_cancel_poll_seconds: float = 1.0
    # P3.1 lát B — tool allowlist (read-only). TẮT mặc định để không đổi hành vi:
    # bật mới cho phép model yêu cầu read_lesson/explain_deeper.
    tutor_tools_enabled: bool = False
    # Số tool call tối đa cho MỘT lượt hỏi (chặn vòng lặp vô hạn).
    tutor_tool_max_calls: int = 2
    # Timeout một lần chạy tool (giây) — tool hiện tại là CPU-local, trần này chặn
    # mọi executor tương lai vô tình block.
    tutor_tool_timeout_seconds: float = 3.0
    # Trần ký tự kết quả tool đưa vào prompt.
    tutor_tool_max_result_chars: int = 3000

    # P4.0 — PDF ingestion. Upload/ingest TẮT ngầm nếu kho lưu trữ chưa cấu hình:
    # API trả 503 `STORAGE_NOT_CONFIGURED` thay vì ghi file vào chỗ không kiểm soát.
    source_ingest_enabled: bool = True
    # Trần byte của MỘT file PDF (streaming; vượt ⇒ 413, không đọc hết vào RAM).
    source_max_pdf_bytes: int = 20 * 1024 * 1024
    # Trần số trang đọc được. Vượt ⇒ `TOO_MANY_PAGES`.
    source_max_pdf_pages: int = 300
    # Trần thời gian trích text toàn bộ một tài liệu (giây).
    source_extract_timeout_seconds: float = 120.0
    # Kích thước chunk theo ký tự (không overlap giữa chunk ⇒ citation rõ ràng).
    source_chunk_target_chars: int = 1000
    source_chunk_min_chars: int = 200
    # Phiên bản pipeline trích xuất/chunking. Đổi giá trị ⇒ document mới được
    # ingest lại (không ghi đè chunk của pipeline cũ).
    source_pipeline_version: str = "p4.0-v1"
    # Số document ingest xử lý mỗi vòng reconciler.
    source_ingest_reconcile_limit: int = 10
    # Lease của một lượt ingest (giây) — hết hạn ⇒ reconciler cho worker khác claim.
    source_ingest_lease_seconds: int = 300
    source_ingest_max_attempts: int = 3

    # ---------- P4.3 OCR cho PDF scan ----------
    # MẶC ĐỊNH TẮT: PDF scan vẫn `no_text` như P4.0. Bật chỉ khi có corpus scan
    # thật và đã đo CER/WER (`evals/ocr_eval.py`).
    ocr_enabled: bool = False
    # Engine pretrained (chạy cục bộ, không network):
    #   `rapidocr` — ONNX PP-OCR, nhẹ; charset THIẾU dấu tiếng Việt ⇒ CER VI ≈ 9,4%.
    #   `vietocr`  — VGG-Transformer pretrained VI + detector rapidocr; CER VI ≈ 0,4%,
    #                cần torch (~250MB) và chậm hơn ~1,5×.
    # Giá trị khác ⇒ `OCR_NOT_CONFIGURED`, KHÔNG quay về text-only.
    ocr_engine: str = "rapidocr"
    # Ngôn ngữ nhận dạng của engine. `vi` cần model Latin của PP-OCR; model mặc
    # định (Trung/Anh) làm RƠI DẤU tiếng Việt ⇒ phải khai báo và đo lại CER.
    ocr_lang: str = "vi"
    # Phiên bản model/pipeline OCR. Đổi ⇒ `pipeline_version` đổi ⇒ document mới,
    # chunk cũ không bị ghi đè.
    ocr_model_version: str = ""
    # VietOCR (engine `vietocr`): weight pretrained CỤC BỘ. Để trống ⇒ Predictor
    # dùng cache của VietOCR; ingest KHÔNG tự tải từ mạng.
    ocr_vietocr_weights: str = ""
    # File config VietOCR tuỳ biến (rỗng = dùng cấu hình có sẵn `vgg_transformer`).
    ocr_vietocr_config: str = ""
    # Trần số trang OCR cho MỘT tài liệu (0 = không giới hạn — KHÔNG khuyến nghị:
    # OCR là CPU-bound, vài giây/trang).
    ocr_max_pages: int = 20
    # DPI render trang trước khi OCR. 200 là mức cân bằng chất lượng/thời gian;
    # dưới 150 mất dấu tiếng Việt, trên 300 chậm mà ít cải thiện.
    ocr_dpi: int = 200
    # Trần thời gian OCR toàn bộ một tài liệu (giây) ⇒ `OCR_TIMEOUT`.
    ocr_timeout_seconds: float = 300.0
    # Ngưỡng confidence tối thiểu để giữ một dòng OCR (0–1). Dòng dưới ngưỡng bị
    # BỎ chứ không bịa; đây là lọc nhiễu, KHÔNG phải bảo đảm độ chính xác.
    ocr_min_confidence: float = 0.0

    # Kho lưu trữ: `s3` (MinIO/S3-compatible) cho mọi môi trường thật;
    # `memory` chỉ là backend test/dev (mất khi restart, KHÔNG dùng production).
    # Rỗng = chưa cấu hình ⇒ upload bị từ chối 503, không ghi file cục bộ ngầm.
    source_storage_backend: str = ""
    source_storage_bucket: str = "sopiskill-sources"
    source_storage_endpoint: str = ""
    source_storage_access_key: str = ""
    source_storage_secret_key: str = ""
    source_storage_region: str = "us-east-1"
    # secure=False cho MinIO local HTTP; bật True khi endpoint dùng HTTPS thật.
    source_storage_secure: bool = False
    # Tạo bucket nếu chưa có (dev/MinIO). Production nên tạo trước và tắt cờ này.
    source_storage_auto_create_bucket: bool = True

    # ---------- P4.2 Web/arXiv ingestion ----------
    # MẶC ĐỊNH TẮT + allowlist RỖNG ⇒ không có request outbound nào cho tới khi
    # người vận hành bật cờ VÀ khai báo host được phép. Đây là cổng duy nhất.
    web_ingest_enabled: bool = False
    # Danh sách host (DNS hostname) được phép fetch, phân tách bằng dấu phẩy.
    # Khớp chính xác host hoặc subdomain của host trong danh sách (`example.com`
    # không cho phép `evil-example.com`). Rỗng ⇒ mọi URL bị từ chối.
    web_ingest_allowed_hosts: str = ""
    # Bắt buộc HTTPS; HTTP bị từ chối (không tự nâng cấp rồi âm thầm đi tiếp).
    web_ingest_require_https: bool = True
    # Trần byte mỗi lần tải (stream, vượt ⇒ dừng đọc, không nạp hết vào RAM).
    web_max_fetch_bytes: int = 5 * 1024 * 1024
    # Trần thời gian toàn bộ một lần fetch (giây, gồm mọi redirect).
    web_fetch_timeout_seconds: float = 20.0
    web_fetch_connect_timeout_seconds: float = 5.0
    # Trần số redirect; vượt ⇒ `WEB_TOO_MANY_REDIRECTS`.
    web_max_redirects: int = 3
    # Trần ký tự text sau khi trích từ HTML (chặn HTML khổng lồ làm treo parser).
    web_max_extracted_chars: int = 2_000_000
    # Trần byte robots.txt; lỗi/từ chối ⇒ KHÔNG fetch (conservative).
    web_robots_max_bytes: int = 64 * 1024
    web_robots_cache_seconds: int = 3600
    web_robots_timeout_seconds: float = 5.0
    # Tôn trọng robots.txt. Tắt cờ này là quyết định vận hành có hệ quả pháp lý —
    # mặc định BẬT và không tự tắt trong code.
    web_ingest_respect_robots: bool = True
    # Cổng expose API để UI biết tính năng có bật hay không.
    web_ingest_user_agent: str = "SopiSkillBot/1.0 (+source-ingest)"
    # Phiên bản pipeline web/arXiv (đổi ⇒ document mới, không ghi đè chunk cũ).
    web_pipeline_version: str = "p4.2-v1"
    # Host trần cho arXiv (cố định, KHÔNG lấy từ client); vẫn phải nằm trong
    # allowlist để ADAPTER không tự mở quyền.
    arxiv_api_host: str = "export.arxiv.org"
    arxiv_pdf_host: str = "arxiv.org"
    # `abs` (mặc định): đọc trang abstract với thẻ Highwire `citation_*` — đường
    # này tôn trọng robots.txt của arXiv. `atom`: dùng Atom API export.arxiv.org;
    # API này đang `Disallow: /` trong robots nên CHỈ bật khi robots cho phép.
    arxiv_metadata_source: str = "abs"

    # ---------- P4.1 Embedding + Hybrid RAG ----------
    # Embedding mặc định là `hashing` (deterministic, KHÔNG network, KHÔNG tải
    # model). Đây KHÔNG phải semantic embedding của model thật — chỉ là baseline
    # lexical/subword để dev/test offline. Chất lượng phải được đo bằng eval.
    embedding_enabled: bool = True
    embedding_provider: str = "hashing"
    embedding_model: str = "hashing-ngram-v1"
    embedding_dimension: int = 256
    embedding_version: str = "v1"
    embedding_ngram_max: int = 2
    embedding_char_ngram: int = 3
    # `openai_compatible` — MẶC ĐỊNH TẮT vì cần key/chi phí. Thiếu cấu hình ⇒
    # lỗi `EMBEDDING_NOT_CONFIGURED`, KHÔNG âm thầm quay về hashing.
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_timeout_seconds: float = 30.0
    embedding_batch_size: int = 32
    embedding_reconcile_limit: int = 200

    # RAG (retrieval + citation trong tutor) — TẮT mặc định để không đổi hành vi
    # P3.x. Bật khi đã ingest nguồn và muốn câu trả lời có căn cứ.
    rag_enabled: bool = False
    rag_top_k: int = 6
    # Trần số chunk đưa vào bộ tính cosine/lexical (exact search có trần).
    rag_candidate_limit: int = 2000
    rag_lexical_limit: int = 40
    rag_rrf_k: int = 60
    # Ngưỡng điểm lexical tối thiểu (nhánh SQLite token-overlap VÀ PostgreSQL
    # ts_rank_cd được chuẩn hoá về [0,1] trước khi so). Dưới ngưỡng ⇒ coi như
    # "không khớp từ khoá" và chuyển sang nhánh vector-only (có ngưỡng riêng cao
    # hơn). Hiệu chỉnh trên `evals/rag_dataset.py`: câu ngoài chủ đề ≤0.32, câu
    # trong phạm vi ≥0.50. CẦN hiệu chỉnh lại khi đổi corpus/tokenizer.
    rag_min_lexical_score: float = 0.40
    # Ngưỡng cosine tối thiểu để một chunk vector-only được coi là liên quan,
    # dùng khi lexical CÓ khớp (RRF sẽ tự cân).
    rag_min_similarity: float = 0.10
    # Ngưỡng CAO HƠN cho trường hợp lexical KHÔNG khớp từ nào (câu hỏi hoàn toàn
    # paraphrase hoặc ngoài phạm vi). Hashing embedding cho câu ngoài chủ đề cosine
    # ~0.17–0.38, nên ngưỡng thấp sẽ trả đoạn không liên quan. Giá trị này được
    # hiệu chỉnh trên `evals/rag_dataset.py` (16 câu) — CẦN hiệu chỉnh lại khi đổi
    # embedding model hoặc mở rộng corpus; xem docs/specs/20-P41-HYBRID-RAG.md.
    rag_vector_only_min_similarity: float = 0.40
    rag_context_max_chars: int = 6000
    rag_max_citations: int = 5
    rag_max_query_chars: int = 1000

    @property
    def source_storage_configured(self) -> bool:
        if not self.source_ingest_enabled:
            return False
        backend = self.source_storage_backend.strip().lower()
        if backend == "memory":
            # Chỉ chấp nhận ngoài production: dữ liệu mất khi restart.
            return self.env != "production"
        if backend != "s3":
            return False
        return bool(
            self.source_storage_bucket
            and self.source_storage_endpoint
            and self.source_storage_access_key
            and self.source_storage_secret_key
        )

    @property
    def embedding_spec(self) -> tuple[str, str, int, str]:
        """Spec đang hoạt động. Vector khác spec KHÔNG được dùng để tính similarity."""
        return (
            (self.embedding_provider or "").strip().lower(),
            (self.embedding_model or "").strip(),
            int(self.embedding_dimension or 0),
            (self.embedding_version or "").strip(),
        )

    @property
    def embedding_configured(self) -> bool:
        """Fail-fast cho adapter thật: thiếu key/base/model/dimension ⇒ False."""
        if not self.embedding_enabled:
            return False
        provider = (self.embedding_provider or "").strip().lower()
        if provider == "hashing":
            return self.embedding_dimension > 0 and bool(self.embedding_model)
        if provider in ("openai_compatible", "openai"):
            return bool(
                self.embedding_base_url
                and self.embedding_api_key
                and self.embedding_model
                and self.embedding_dimension > 0
            )
        return False

    @property
    def rag_active(self) -> bool:
        return bool(self.rag_enabled and self.embedding_configured)

    @property
    def web_allowed_hosts(self) -> tuple[str, ...]:
        """Allowlist host đã chuẩn hoá (lowercase, bỏ rỗng, bỏ trùng, giữ thứ tự)."""
        seen: dict[str, None] = {}
        for raw in (self.web_ingest_allowed_hosts or "").split(","):
            host = raw.strip().lower().rstrip(".")
            if host:
                seen.setdefault(host, None)
        return tuple(seen)

    @property
    def web_ingest_active(self) -> bool:
        """Chỉ có hiệu lực khi bật cờ VÀ có ít nhất một host được phép."""
        return bool(self.web_ingest_enabled and self.web_allowed_hosts)

    @property
    def ocr_configured(self) -> bool:
        """OCR có hiệu lực thật? Cờ bật + engine hợp lệ + version khai báo.

        Import `app.services.ocr` ở đây sẽ tạo vòng import (ocr đọc Settings), nên
        chỉ kiểm tra cấu hình tĩnh; việc kiểm tra engine importable do
        `app.services.ocr.configured()` làm (dùng cùng điều kiện).
        """
        if not self.ocr_enabled:
            return False
        if (self.ocr_engine or "").strip().lower() not in ("rapidocr", "vietocr"):
            return False
        return bool((self.ocr_model_version or "").strip())

    # Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "sopiskill"
    jwt_audience: str = "sopiskill-web"
    access_token_ttl_minutes: int = 60 * 24 * 7
    allow_demo_header: bool = False
    cookie_secure: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.jwt_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
