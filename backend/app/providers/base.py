"""Provider contract + error taxonomy (P2.0).

Mọi adapter phải:
  - Trả structured output đã validate Pydantic (hoặc raise SchemaInvalidError).
  - Raise lỗi thuộc taxonomy dưới đây để tầng trên phân loại retry đúng.
  - Không bao giờ tự fallback sang MockProvider khi được cấu hình là provider thật.
"""

from abc import ABC, abstractmethod

from app.schemas.schemas import LessonContent, ProposalPayload, SourceContextEntry


class ProviderError(Exception):
    """Lỗi gốc của provider. `retryable` quyết định worker có requeue hay không."""

    code = "PROVIDER_ERROR"
    retryable = False

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)


class ProviderConfigError(ProviderError):
    """Cấu hình sai/thiếu (provider lạ, thiếu key, thiếu model). KHÔNG retry."""

    code = "PROVIDER_NOT_CONFIGURED"
    retryable = False


class ProviderAuthError(ProviderError):
    """401/403 từ provider — key sai/hết hạn. KHÔNG retry."""

    code = "PROVIDER_AUTH_FAILED"
    retryable = False


class ProviderTimeoutError(ProviderError):
    code = "PROVIDER_TIMEOUT"
    retryable = True


class ProviderRateLimitError(ProviderError):
    code = "PROVIDER_RATE_LIMITED"
    retryable = True

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTransientError(ProviderError):
    """5xx, lỗi mạng, response cắt cụt — có thể thử lại."""

    code = "PROVIDER_TRANSIENT"
    retryable = True


class ProviderBudgetError(ProviderError):
    """Vượt ngân sách cấu hình cho một request. KHÔNG retry."""

    code = "PROVIDER_BUDGET_EXCEEDED"
    retryable = False


class SchemaInvalidError(ProviderError):
    """Output không parse được hoặc sai schema/semantic rules. KHÔNG retry tự động."""

    code = "PROVIDER_SCHEMA_INVALID"
    retryable = False


class LLMProvider(ABC):
    """Interface trung lập cho mọi nhà cung cấp LLM.

    Không hardcode model/key — cấu hình qua settings. Provider phải trả
    structured output đã validate (Pydantic) hoặc raise SchemaInvalidError.
    """

    name: str = "base"

    @abstractmethod
    async def generate_interview_questions(self, topic: str) -> list[str]:
        """Sinh đúng 5 câu hỏi phỏng vấn cho topic."""

    @abstractmethod
    async def generate_proposal(
        self, topic: str, interview_questions: list[str], interview_answers: list[str]
    ) -> ProposalPayload:
        """Sinh proposal có cấu trúc từ topic + câu trả lời phỏng vấn."""

    @abstractmethod
    async def generate_lesson(
        self,
        topic: str,
        proposal: ProposalPayload,
        unit_title: str,
        lesson_title: str,
        previous_titles: list[str],
        source_context: list[SourceContextEntry] | None = None,
    ) -> LessonContent:
        """Sinh nội dung 1 bài học dạng blocks.

        `source_context` chỉ chứa metadata (và excerpt nếu đã ingest) của nguồn do
        SERVER chọn từ Source Registry. Provider không được tự tạo sourceId, URL,
        số trang hay đoạn trích. Nội dung không có nguồn ⇒ vẫn sinh bình thường và
        bài học được đánh dấu `general_ai_knowledge`.
        """
