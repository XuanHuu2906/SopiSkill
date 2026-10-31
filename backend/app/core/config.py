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
    # Số lượt hỏi tối đa/ngày/user. 0 = không giới hạn (P3.1 làm quota đầy đủ).
    tutor_messages_per_day: int = 0

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
