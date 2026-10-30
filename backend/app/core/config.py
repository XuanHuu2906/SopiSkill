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
    llm_max_output_tokens: int = 2000
    llm_max_input_chars: int = 12_000
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
