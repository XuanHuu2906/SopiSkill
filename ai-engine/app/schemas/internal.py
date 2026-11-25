"""Strict Pydantic v2 schemas matching `contracts/internal-ai.yaml`."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FORBIDDEN_ANSWER_KEY_FIELDS = frozenset(
    {"answerIndex", "acceptedAnswers", "answer_key", "solution", "answer", "pairs"}
)


class LlmUsageOut(BaseModel):
    provider: str = "mock"
    model: str = "mock-v1"
    promptTokens: int = Field(default=0, ge=0)
    completionTokens: int = Field(default=0, ge=0)
    totalTokens: int = Field(default=0, ge=0)
    latencyMs: int = Field(default=0, ge=0)


class InterviewQuestionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courseId: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=300)
    language: Literal["vi", "en"] = "vi"
    sourceBrief: dict[str, Any] | None = None
    onboardingProfile: dict[str, Any] | None = None


class InterviewQuestionItem(BaseModel):
    index: int = Field(ge=0)
    prompt: str
    kind: Literal["freeform", "single", "multi"] = "freeform"
    choices: list[str] = Field(default_factory=list)


class InterviewQuestionsResponse(BaseModel):
    questions: list[InterviewQuestionItem]
    usage: LlmUsageOut = Field(default_factory=LlmUsageOut)


class InterviewAnswerItem(BaseModel):
    question: str = Field(min_length=1, max_length=600)
    answer: str = Field(default="", max_length=2000)


class InterviewEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courseId: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=300)
    language: Literal["vi", "en"] = "vi"
    answers: list[InterviewAnswerItem] = Field(min_length=1, max_length=20)
    onboardingProfile: dict[str, Any] | None = None


class LearnerProfileOut(BaseModel):
    currentLevel: Literal["beginner", "intermediate", "advanced"]
    depth: Literal["overview", "practical", "deep"]
    preferredStyles: list[str] = Field(default_factory=list)
    weeklyMinutes: int | None = None
    goal: str | None = None


class InterviewEvaluateResponse(BaseModel):
    learnerProfile: LearnerProfileOut


class GradeShortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lessonId: str = Field(min_length=1, max_length=128)
    blockIndex: int = Field(ge=0)
    language: Literal["vi", "en"] = "vi"
    prompt: str = Field(min_length=1, max_length=2000)
    learnerAnswer: str = Field(default="", max_length=4000)
    acceptedAnswers: list[str] = Field(default_factory=list)
    modelAnswer: str | None = None
    rubric: str | None = None
    dispute: bool = False


class GradeShortResponse(BaseModel):
    correct: bool
    verdict: Literal["got_it", "almost", "not_yet"]
    keyPoints: list[str] = Field(default_factory=list)
    feedback: str
    method: Literal["exact", "semantic_rubric", "llm_dispute", "fallback"]
    usage: LlmUsageOut = Field(default_factory=LlmUsageOut)


class TutorLessonContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lessonId: str = Field(min_length=1, max_length=128)
    lessonTitle: str = Field(min_length=1, max_length=300)
    activeBlockIndex: int = Field(ge=0)
    publicBlocks: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("publicBlocks")
    @classmethod
    def _reject_answer_keys(cls, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for idx, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise ValueError(f"publicBlocks[{idx}] must be an object.")
            leaked = FORBIDDEN_ANSWER_KEY_FIELDS.intersection(block.keys())
            if leaked:
                raise ValueError(
                    f"Answer-key privacy violation: forbidden fields {sorted(leaked)} in publicBlocks[{idx}]."
                )
        return blocks


class TutorHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class TutorStreamInternalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ownerId: str = Field(min_length=1, max_length=128)
    courseId: str = Field(min_length=1, max_length=128)
    threadId: str = Field(min_length=1, max_length=128)
    messageId: str = Field(min_length=1, max_length=128)
    language: Literal["vi", "en"] = "vi"
    entryPoint: Literal[
        "tab", "wrong_answer", "teach_block", "term", "path_harder", "proposal"
    ] = "tab"
    userMessage: str = Field(min_length=1, max_length=2000)
    lessonContext: TutorLessonContext | None = None
    unitContext: dict[str, Any] | None = None
    proposalContext: dict[str, Any] | None = None
    sourceBrief: dict[str, Any] | None = None
    delayMs: int = Field(default=0, ge=0, le=2000)
    history: list[TutorHistoryItem] = Field(default_factory=list, max_length=40)
    ragEnabled: bool = False
    allowedTools: list[
        Literal[
            "read_lesson",
            "explain_deeper",
            "read_source",
            "flag_question",
            "revise_proposal",
            "regenerate_unit",
        ]
    ] = Field(
        default_factory=lambda: [
            "read_lesson",
            "explain_deeper",
            "read_source",
            "flag_question",
            "revise_proposal",
            "regenerate_unit",
        ]
    )


class RagSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ownerId: str = Field(min_length=1, max_length=128)
    courseId: str = Field(min_length=1, max_length=128)
    sourceIds: list[str] | None = None
    query: str = Field(min_length=1, max_length=1000)
    topK: int = Field(default=5, ge=1, le=20)


class RagChunkHitOut(BaseModel):
    chunkId: str
    sourceId: str
    documentId: str | None = None
    sourceTitle: str | None = None
    pageNumber: int | None = None
    sectionAnchor: str | None = None
    content: str
    score: float


class RagSearchResponse(BaseModel):
    retrievalMode: Literal["hybrid_rrf", "fts_only", "hashing_baseline"]
    chunks: list[RagChunkHitOut] = Field(default_factory=list)


class RagDeleteResponse(BaseModel):
    deletedChunks: int = Field(ge=0)
