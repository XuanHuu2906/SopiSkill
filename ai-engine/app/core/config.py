"""Typed configuration for SopiSkill ai-engine (ai-api, ai-worker-llm, ai-worker-ingest).

Safe defaults:
  - `LLM_PROVIDER=mock` and `EMBEDDING_PROVIDER=hashing` for zero-cost offline CI/E2E.
  - `WEB_INGEST_ENABLED=false`, `OCR_ENABLED=false` (fail-closed until explicitly enabled).
  - Never log secret values or connection strings containing passwords.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    service_name: str = "sopiskill-ai-engine"

    # Database (owns ONLY `rag.*` schema via Alembic)
    database_url: str = "sqlite+aiosqlite:///./ai_engine_local.db"
    rag_schema: str = "rag"

    # Redis 7 (Streams broker: queue:ai:llm & queue:ai:ingest)
    redis_url: str = "redis://127.0.0.1:6380/0"
    stream_llm_key: str = "queue:ai:llm"
    stream_llm_group: str = "ai-worker-llm-group"
    stream_llm_dlq_key: str = "queue:ai:llm:dlq"
    stream_ingest_key: str = "queue:ai:ingest"
    stream_ingest_group: str = "ai-worker-ingest-group"
    stream_ingest_dlq_key: str = "queue:ai:ingest:dlq"
    stream_claim_idle_ms: int = 300_000
    stream_max_retries: int = 3
    stream_block_ms: int = 2_000

    # Internal auth & replay protection (core-api <-> ai-engine)
    internal_service_token: str = "dev-internal-service-token-change-me"
    internal_hmac_secret: str = "dev-internal-hmac-secret-change-me"
    internal_max_clock_skew_seconds: int = 300
    core_api_url: str = "http://core-api:8080"
    callback_timeout_seconds: float = 15.0
    callback_max_retries: int = 3

    # LLM Provider (mock default — 0 cost in CI/dev)
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    llm_max_input_chars: int = 16_000
    llm_max_output_tokens_lesson: int = 4000
    llm_max_output_tokens_tutor: int = 1500
    llm_max_output_tokens_dispute: int = 600

    # Embedding & Hybrid RAG (hashing baseline default — 0 cost; pgvector HNSW + FTS + RRF)
    embedding_provider: str = "hashing"
    embedding_model: str = "hashing-ngram-v1"
    embedding_dimension: int = 256
    embedding_version: str = "v1"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_timeout_seconds: float = 20.0
    rag_rrf_k: int = 60
    rag_candidate_limit: int = 30

    # Object storage (MinIO/S3)
    source_storage_backend: str = "memory"  # "memory" | "s3"
    s3_endpoint: str = "http://127.0.0.1:9010"
    s3_access_key: str = "sopiskill_minio"
    s3_secret_key: str = "sopiskill_minio_password"
    s3_bucket: str = "sopiskill-sources"
    s3_secure: bool = False

    # Outbound web ingest SSRF guard (fail-closed by default)
    web_ingest_enabled: bool = False
    web_ingest_allowed_hosts: str = ""
    web_ingest_timeout_seconds: float = 15.0
    web_ingest_max_bytes: int = 10 * 1024 * 1024
    web_ingest_max_redirects: int = 3

    # Optional OCR gate (fail-fast if enabled without engine installed)
    ocr_enabled: bool = False
    ocr_engine: str = "vietocr"

    # Phase 3: 2-Tier Validator QA & progressive generation
    validator_llm_enabled: bool = False
    lesson_images_enabled: bool = False

    readiness_timeout_seconds: float = 2.0

    @property
    def allowed_web_hosts(self) -> tuple[str, ...]:
        parts = [p.strip().lower().rstrip(".") for p in (self.web_ingest_allowed_hosts or "").split(",")]
        return tuple(p for p in parts if p)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
