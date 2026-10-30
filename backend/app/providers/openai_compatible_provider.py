"""OpenAI-compatible chat adapter (P2.0).

Dùng cho bất kỳ endpoint tương thích `/chat/completions` (OpenAI, Azure-compatible
gateway, self-hosted vLLM/Ollama…). Key **chỉ** đọc từ server env — không bao giờ
gửi xuống client hay ghi log.

Bảo vệ chi phí & độ bền:
  - Timeout per-request, retry có backoff+jitter chỉ cho lỗi recoverable (429/5xx/timeout).
  - Budget tối đa token mỗi request; giới hạn số lần retry cứng.
  - Output parse JSON → Pydantic → semantic lint (`providers.validation`).
  - Không tự fallback sang MockProvider khi lỗi.
"""

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from app.core.config import get_settings
from app.providers.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderBudgetError,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    SchemaInvalidError,
)
from app.providers.validation import (
    validate_interview_questions,
    validate_lesson,
    validate_proposal,
)
from app.schemas.schemas import LessonContent, ProposalPayload

logger = logging.getLogger(__name__)

PROMPT_VERSION = "p2.0-v1"

INTERVIEW_SYSTEM = (
    "Bạn là chuyên gia thiết kế chương trình học. Hãy đặt đúng 5 câu hỏi phỏng vấn "
    "ngắn để hiểu người học: trình độ hiện tại, mục tiêu, thời gian mỗi tuần, "
    "phong cách học ưa thích, và độ sâu mong muốn. Trả về JSON: "
    '{"questions": ["...", "...", "...", "...", "..."]}'
)

PROPOSAL_SYSTEM = (
    "Bạn là chuyên gia thiết kế chương trình học. Từ chủ đề và câu trả lời phỏng vấn, "
    "hãy tạo proposal khóa học bằng tiếng Việt. Trả về JSON đúng schema: "
    '{"name": str, "objective": str, "units": [{"title": str, "blurb": str, '
    '"lessonTitles": [str]}], "outcomes": [str]}. '
    "Yêu cầu: 2-4 unit, mỗi unit 2-5 bài, tiêu đề bài không trùng nhau, "
    "outcome viết theo động từ đo được (Bloom)."
)

LESSON_SYSTEM = (
    "Bạn là giáo viên thiết kế bài học tương tác. Trả về JSON đúng schema: "
    '{"title": str, "blocks": [ ... ]} trong đó block là một trong: '
    '{"type":"teach","title":str,"paragraphs":[str]}, '
    '{"type":"mc","question":str,"options":[str],"answerIndex":int}, '
    '{"type":"blank","sentence":str,"answer":str}, '
    '{"type":"order","prompt":str,"items":[str]}, '
    '{"type":"match","prompt":str,"pairs":[[str,str]]}, '
    '{"type":"short","question":str,"acceptedAnswers":[str]}. '
    "Bắt buộc có ít nhất 1 block teach và ít nhất 1 câu hỏi; answerIndex phải nằm "
    "trong options; đáp án blank phải xuất hiện trong sentence."
)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.llm_api_key_resolved
        self.base_url = (base_url or settings.llm_base_url or "").rstrip("/")
        self.model = model or settings.llm_model
        self.timeout = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries
        self.max_output_tokens = settings.llm_max_output_tokens
        self.max_input_chars = settings.llm_max_input_chars
        self._transport = transport

        if not self.api_key:
            raise ProviderConfigError("Thiếu LLM_API_KEY cho provider thật.")
        if not self.base_url:
            raise ProviderConfigError("Thiếu LLM_BASE_URL cho provider thật.")
        if not self.model:
            raise ProviderConfigError("Thiếu LLM_MODEL cho provider thật.")

    # ---------- public contract ----------

    async def generate_interview_questions(self, topic: str) -> list[str]:
        data = await self._chat_json(
            system=INTERVIEW_SYSTEM,
            user=f"Chủ đề khóa học: {self._safe(topic, 200)}",
        )
        questions = data.get("questions")
        if not isinstance(questions, list):
            raise SchemaInvalidError("Output interview thiếu mảng 'questions'.")
        return validate_interview_questions([str(q) for q in questions])

    async def generate_proposal(
        self, topic: str, interview_questions: list[str], interview_answers: list[str]
    ) -> ProposalPayload:
        qa = "\n".join(
            f"- Hỏi: {self._safe(q, 300)}\n  Đáp: {self._safe(a, 600)}"
            for q, a in zip(interview_questions, interview_answers)
        )
        data = await self._chat_json(
            system=PROPOSAL_SYSTEM,
            user=f"Chủ đề: {self._safe(topic, 200)}\n\nPhỏng vấn:\n{qa}",
        )
        try:
            payload = ProposalPayload.model_validate(data)
        except Exception as exc:  # noqa: BLE001 — biến lỗi Pydantic thành taxonomy của provider
            raise SchemaInvalidError(f"Proposal sai schema: {str(exc)[:200]}") from exc
        return validate_proposal(payload)

    async def generate_lesson(
        self,
        topic: str,
        proposal: ProposalPayload,
        unit_title: str,
        lesson_title: str,
        previous_titles: list[str],
    ) -> LessonContent:
        previous = ", ".join(self._safe(t, 120) for t in previous_titles[-8:]) or "(chưa có)"
        data = await self._chat_json(
            system=LESSON_SYSTEM,
            user=(
                f"Chủ đề khóa học: {self._safe(topic, 200)}\n"
                f"Mục tiêu khóa: {self._safe(proposal.objective, 400)}\n"
                f"Unit: {self._safe(unit_title, 160)}\n"
                f"Bài cần soạn: {self._safe(lesson_title, 160)}\n"
                f"Các bài trước: {previous}\n"
                "Soạn 1 bài học ngắn (3-6 block), tiếng Việt, có ví dụ cụ thể."
            ),
        )
        try:
            content = LessonContent.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            raise SchemaInvalidError(f"Lesson sai schema: {str(exc)[:200]}") from exc
        return validate_lesson(content)

    # ---------- HTTP core ----------

    @staticmethod
    def _safe(text: str, limit: int) -> str:
        """Cắt input để không gửi quá nhiều dữ liệu người dùng ra ngoài."""
        clean = " ".join(str(text or "").split())
        return clean[:limit]

    async def _chat_json(self, *, system: str, user: str) -> dict[str, Any]:
        if len(user) > self.max_input_chars:
            user = user[: self.max_input_chars]

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "max_tokens": self.max_output_tokens,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = await self._post(payload)
                return self._parse_json(raw)
            except (ProviderTimeoutError, ProviderTransientError, ProviderRateLimitError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self._backoff(attempt, getattr(exc, "retry_after", None))
                logger.warning(
                    "llm retry provider=%s model=%s prompt_version=%s attempt=%s code=%s delay=%.2f",
                    self.name,
                    self.model,
                    PROMPT_VERSION,
                    attempt + 1,
                    exc.code,
                    delay,
                )
                await asyncio.sleep(delay)
            except (ProviderAuthError, ProviderBudgetError, SchemaInvalidError, ProviderConfigError):
                raise

        assert last_error is not None
        raise last_error

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(float(retry_after), 30.0)
        base = min(30.0, 0.5 * (2**attempt))
        return base + random.uniform(0, base * 0.25)

    async def _post(self, payload: dict[str, Any]) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout), transport=self._transport
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Provider timeout sau {self.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderTransientError(f"Lỗi kết nối provider: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(f"Provider từ chối xác thực ({response.status_code}).")
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            try:
                parsed = float(retry_after) if retry_after else None
            except ValueError:
                parsed = None
            raise ProviderRateLimitError("Provider rate limit (429).", retry_after=parsed)
        if response.status_code >= 500:
            raise ProviderTransientError(f"Provider lỗi {response.status_code}.")
        if response.status_code >= 400:
            # 400/422 = request sai (prompt/schema) → không retry, không lộ body.
            raise SchemaInvalidError(f"Provider từ chối request ({response.status_code}).")

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderTransientError("Response provider không phải JSON.") from exc

        usage = body.get("usage") or {}
        completion_tokens = usage.get("completion_tokens")
        if isinstance(completion_tokens, int) and completion_tokens >= self.max_output_tokens:
            raise ProviderBudgetError(
                f"Output chạm trần token ({completion_tokens} >= {self.max_output_tokens})."
            )

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderTransientError("Response provider thiếu 'choices'.")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderTransientError("Response provider rỗng.")
        # Chỉ log metadata đã redacted — không log prompt/nội dung.
        logger.info(
            "llm call ok provider=%s model=%s prompt_version=%s prompt_tokens=%s completion_tokens=%s",
            self.name,
            self.model,
            PROMPT_VERSION,
            usage.get("prompt_tokens"),
            completion_tokens,
        )
        return content

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise SchemaInvalidError("Provider không trả JSON hợp lệ.") from exc
        if not isinstance(data, dict):
            raise SchemaInvalidError("Provider phải trả JSON object.")
        return data
