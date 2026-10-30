"""Provider registry — chọn adapter theo `LLM_PROVIDER`, fail-fast khi sai (P2.0).

Quan trọng: provider lạ/thiếu cấu hình **không** được fallback im lặng sang Mock.
Mock là lựa chọn tường minh (`LLM_PROVIDER=mock`), không phải chỗ trú ẩn.
"""

from app.core.config import get_settings
from app.providers.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderBudgetError,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    SchemaInvalidError,
)
from app.providers.mock_provider import MockProvider
from app.providers.openai_compatible_provider import OpenAICompatibleProvider

__all__ = [
    "LLMProvider",
    "ProviderError",
    "ProviderConfigError",
    "ProviderAuthError",
    "ProviderBudgetError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderTransientError",
    "SchemaInvalidError",
    "MockProvider",
    "OpenAICompatibleProvider",
    "get_provider",
    "provider_name",
]

_registry: dict[str, type[LLMProvider]] = {
    "mock": MockProvider,
    "openai": OpenAICompatibleProvider,
    "openai_compatible": OpenAICompatibleProvider,
}


def provider_name() -> str:
    return (get_settings().llm_provider or "mock").strip().lower()


def get_provider() -> LLMProvider:
    """Trả instance provider theo cấu hình. Raise ProviderConfigError nếu không hợp lệ."""
    name = provider_name()
    cls = _registry.get(name)
    if cls is None:
        raise ProviderConfigError(
            f"Provider '{name}' chưa được hỗ trợ. Hợp lệ: {', '.join(sorted(_registry))}."
        )
    return cls()
