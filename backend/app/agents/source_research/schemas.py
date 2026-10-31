"""Contracts cho Source Research Agent (P2.SR).

Nguyên tắc thiết kế:
  - Mọi trường đầu vào đều bị chặn trên (độ dài/tần suất/số lượng) để agent
    không thể bị khuếch đại chi phí từ input của người dùng.
  - `ResearchResult.sources` KHÔNG chứa `sourceId` registry: id chỉ được cấp khi
    service lưu nguồn thật vào DB. Điều này ngăn agent "tự nhận" là nguồn đã đăng ký.
  - `verificationStatus` chỉ có 3 giá trị agent được phép tự kết luận
    (`discovered`, `metadata_verified`, `rejected`). `content_available` và
    `evidence_verified` thuộc về ingestion/retrieval (P4) và sẽ bị validator từ chối.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_TOPIC_LENGTH = 300
MAX_GOALS = 8
MAX_GOAL_LENGTH = 200
MAX_SOURCES_LIMIT = 20
MIN_SOURCES_LIMIT = 1

AGENT_VERIFIABLE_STATUSES = ("discovered", "metadata_verified", "rejected")
SOURCE_KINDS = (
    "official_documentation",
    "standard_specification",
    "clinical_guideline",
    "systematic_review",
    "academic",
    "government_health",
    "university_course",
    "technical_book",
    "educational_resource",
    "curated_reference",
    "webpage",
    "community_tutorial",
    "user_document",
)


def _http_url_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    if len(url) > 2048:
        raise ValueError("canonicalUrl quá dài (>2048).")
    lowered = url.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        raise ValueError("canonicalUrl phải là http(s) tuyệt đối.")
    if any(ch in url for ch in ("\n", "\r", "\x00", " ", "\t")):
        raise ValueError("canonicalUrl chứa ký tự không hợp lệ.")
    host = urlparse(url).hostname
    if not host:
        raise ValueError("canonicalUrl thiếu host.")
    return url


class ResearchRequest(BaseModel):
    """Yêu cầu nghiên cứu. `courseId` chỉ dùng làm khóa tra cứu sau khi server đã
    xác thực ownership; agent không tự dùng nó để đọc dữ liệu."""

    courseId: UUID
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)
    learnerLevel: Literal["beginner", "intermediate", "advanced"] | None = None
    learningGoals: list[str] = Field(default_factory=list, max_length=MAX_GOALS)
    preferredLanguage: str = Field(default="vi", min_length=2, max_length=20)
    maxSources: int = Field(default=8, ge=MIN_SOURCES_LIMIT, le=MAX_SOURCES_LIMIT)

    model_config = {"extra": "forbid"}

    @field_validator("topic")
    @classmethod
    def _topic_not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("topic không được rỗng.")
        return cleaned

    @field_validator("learningGoals")
    @classmethod
    def _clean_goals(cls, goals: list[str]) -> list[str]:
        cleaned: list[str] = []
        for goal in goals:
            text = " ".join(str(goal).split())
            if not text:
                continue
            if len(text) > MAX_GOAL_LENGTH:
                raise ValueError(f"learningGoals mỗi mục tối đa {MAX_GOAL_LENGTH} ký tự.")
            cleaned.append(text)
        return cleaned


class TopicAnalysis(BaseModel):
    mainTopic: str
    domain: Literal["programming", "medicine", "general"]
    subTopics: list[str] = Field(default_factory=list, max_length=16)
    prerequisites: list[str] = Field(default_factory=list, max_length=16)
    learnerLevel: Literal["beginner", "intermediate", "advanced"]
    language: str
    learningGoals: list[str] = Field(default_factory=list, max_length=MAX_GOALS)
    recommendedSourceTypes: list[str] = Field(default_factory=list, max_length=8)
    searchQueries: list[str] = Field(default_factory=list, max_length=6)
    notes: list[str] = Field(default_factory=list, max_length=8)


class SourceCandidate(BaseModel):
    """Ứng viên nguồn từ adapter. Chưa phải bản ghi registry."""

    adapter: str = Field(min_length=1, max_length=40)
    candidateId: str = Field(min_length=1, max_length=128)
    sourceType: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=300)
    canonicalUrl: str | None = Field(default=None, max_length=2048)
    publisher: str | None = Field(default=None, max_length=200)
    author: str | None = Field(default=None, max_length=200)
    publicationDate: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=120)
    licenseInfo: str | None = Field(default=None, max_length=300)
    deterministic: bool = True
    isMock: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("canonicalUrl")
    @classmethod
    def _check_url(cls, value):
        return _http_url_or_none(value)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("title không được rỗng.")
        return cleaned


class CandidateScores(BaseModel):
    """Điểm xếp hạng. Chỉ để so sánh trong một lần nghiên cứu, KHÔNG phải xác suất
    nguồn đúng. `unknown` nghĩa là thiếu dữ liệu, không phải 0."""

    authority: float | None = None
    relevance: float | None = None
    freshness: float | None = None
    metadataCompleteness: float | None = None
    total: float
    notes: list[str] = Field(default_factory=list)


class RankedSourceOut(BaseModel):
    adapter: str
    candidateId: str
    sourceId: str | None = None
    title: str
    sourceType: str
    canonicalUrl: str | None
    publisher: str | None
    author: str | None
    publicationDate: str | None
    language: str | None
    version: str | None
    licenseInfo: str | None
    verificationStatus: Literal["discovered", "metadata_verified", "rejected"]
    relevanceScore: float
    scores: CandidateScores
    selectionReason: str
    isMock: bool
    deterministic: bool
    warnings: list[str] = Field(default_factory=list)


class ResearchError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ResearchResult(BaseModel):
    researchRunId: UUID
    courseId: UUID
    topic: str
    domain: Literal["programming", "medicine", "general"]
    status: Literal["completed", "insufficient_evidence", "failed"]
    sources: list[RankedSourceOut] = Field(default_factory=list, max_length=MAX_SOURCES_LIMIT)
    warnings: list[str] = Field(default_factory=list, max_length=40)
    insufficientEvidence: bool
    analysis: TopicAnalysis
    error: ResearchError | None = None
    adapter: str
    isMock: bool
    toolCalls: int = 0
    notice: str

    @model_validator(mode="after")
    def _enforce_contracts(self) -> "ResearchResult":
        for source in self.sources:
            if source.verificationStatus not in AGENT_VERIFIABLE_STATUSES:
                raise ValueError(
                    f"verificationStatus '{source.verificationStatus}' không thuộc phạm vi agent."
                )
            if source.sourceId is not None:
                raise ValueError("Agent không được tự cấp sourceId registry.")
        if self.status == "failed" and self.error is None:
            raise ValueError("status=failed phải kèm error.")
        if self.status == "insufficient_evidence" and not self.insufficientEvidence:
            raise ValueError("status=insufficient_evidence phải đặt insufficientEvidence=True.")
        return self
