from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"

    database_url: str = "sqlite+aiosqlite:///./ailp.db"

    redis_url: str = ""

    llm_provider: str = "mock"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model: str = ""

    cors_origins: str = "http://localhost:3000"

    generation_max_schema_retries: int = 2

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
