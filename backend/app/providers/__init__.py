from app.core.config import get_settings
from app.providers.base import LLMProvider, ProviderError, SchemaInvalidError
from app.providers.mock_provider import MockProvider

__all__ = ["LLMProvider", "ProviderError", "SchemaInvalidError", "MockProvider", "get_provider"]

_registry: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
}


def get_provider() -> LLMProvider:
    settings = get_settings()
    provider_name = settings.llm_provider.lower()
    cls = _registry.get(provider_name)
    if cls is None:
        # Provider chưa đăng ký → fallback mock, không crash (ghi log ở caller).
        return MockProvider()
    return cls()
