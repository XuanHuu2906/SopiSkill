from abc import ABC, abstractmethod

from app.schemas.schemas import LessonContent, ProposalPayload


class ProviderError(Exception):
    """Provider không sinh được kết quả hợp lệ sau các lần retry."""


class SchemaInvalidError(ProviderError):
    """Kết quả provider sai schema."""


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
    ) -> LessonContent:
        """Sinh nội dung 1 bài học dạng blocks."""
