from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


# ---------- Source Registry (P3.0) ----------
SOURCE_TYPE = Literal["official_documentation", "academic", "user_document", "webpage"]
SOURCE_VISIBILITY = Literal["public", "private"]
SOURCE_VERIFICATION_STATUS = Literal[
    "unverified",
    "pending_review",
    "metadata_verified",
    "locator_verified",
    "evidence_supported",
    "corroborated",
    "rejected",
]
CITATION_VALIDATION_STATUS = Literal[
    "unverified",
    "locator_verified",
    "evidence_supported",
    "unavailable",
    "source_changed",
    "rejected",
]
LESSON_GROUNDING = Literal["source_grounded", "general_ai_knowledge"]


def _validate_http_url(value: str | None) -> str | None:
    """Chỉ chấp nhận http(s) tuyệt đối. KHÔNG fetch, KHÔNG suy ra độ tin cậy."""
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
    if any(ch in url for ch in ("\n", "\r", "\x00", " ")):
        raise ValueError("canonicalUrl chứa ký tự không hợp lệ.")
    return url


class SourceCreateRequest(BaseModel):
    sourceType: SOURCE_TYPE
    title: str = Field(min_length=1, max_length=300)
    canonicalUrl: str | None = Field(default=None, max_length=2048)
    author: str | None = Field(default=None, max_length=200)
    publisher: str | None = Field(default=None, max_length=200)
    publicationDate: str | None = Field(default=None, max_length=40)
    sourceUpdatedAt: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=120)
    visibility: SOURCE_VISIBILITY = "private"
    licenseInfo: str | None = Field(default=None, max_length=300)

    model_config = {"extra": "forbid"}

    @field_validator("canonicalUrl")
    @classmethod
    def _check_url(cls, value):
        return _validate_http_url(value)


class SourceOut(BaseModel):
    id: str
    sourceType: str
    title: str
    canonicalUrl: str | None
    author: str | None
    publisher: str | None
    publicationDate: str | None
    sourceUpdatedAt: str | None
    retrievedAt: str | None
    language: str | None
    version: str | None
    visibility: str
    licenseInfo: str | None
    contentHash: str | None
    verificationStatus: str
    ownerId: str | None
    createdAt: str | None = None


class SourceListOut(BaseModel):
    items: list[SourceOut]
    total: int
    limit: int
    offset: int
    hasMore: bool


class SourceCriterionOut(BaseModel):
    """Một tiêu chí đánh giá. `status=unknown` nghĩa là THIẾU dữ liệu, không phải 0 điểm."""

    key: str
    label: str
    status: Literal["strong", "moderate", "weak", "unknown", "penalized"]
    score: float | None
    reasons: list[str] = Field(default_factory=list)


class SourceEvaluationOut(BaseModel):
    sourceId: str
    criteria: list[SourceCriterionOut]
    knownWeight: float
    totalWeight: float
    weightedScore: float | None
    verdict: Literal["insufficient_metadata", "weak", "moderate", "strong"]
    suggestedVerificationStatus: str
    limitations: list[str] = Field(default_factory=list)
    evaluator: dict


class SourceLinkRequest(BaseModel):
    sourceId: str = Field(min_length=1, max_length=128)

    model_config = {"extra": "forbid"}


class CourseSourceOut(BaseModel):
    courseId: str
    source: SourceOut
    evaluation: dict | None
    linkedAt: str | None = None


class CourseSourceListOut(BaseModel):
    items: list[CourseSourceOut]
    total: int
    groundingAvailable: bool
    # Nguồn đã liên kết nhưng CHƯA ingest nội dung ⇒ bài học không thể grounded.
    contentIngested: bool
    notice: str | None = None


class SourceCandidateOut(BaseModel):
    """Kết quả discovery. Chưa phải Source đã đăng ký — cần người dùng xác nhận."""

    adapter: str
    externalId: str
    sourceType: str
    title: str
    canonicalUrl: str | None
    author: str | None
    publisher: str | None
    publicationDate: str | None
    language: str | None
    version: str | None
    licenseInfo: str | None
    deterministic: bool
    isMock: bool


class SourceDiscoveryOut(BaseModel):
    adapter: str
    query: str
    deterministic: bool
    isMock: bool
    items: list[SourceCandidateOut]
    notice: str | None = None


class CitationOut(BaseModel):
    citationId: str
    sourceId: str
    sourceVersion: str | None
    chunkId: str | None
    pageNumber: int | None
    sectionAnchor: str | None
    evidenceText: str | None
    validationStatus: str
    sourceTitle: str | None = None
    sourceUrl: str | None = None
    sourceVerificationStatus: str | None = None


class SourceContextEntry(BaseModel):
    """Metadata nguồn gửi cho provider. KHÔNG chứa nội dung khi chưa ingest."""

    sourceId: str
    title: str
    publisher: str | None = None
    canonicalUrl: str | None = None
    sourceVersion: str | None = None
    verificationStatus: str
    excerpt: str | None = None


# ---------- Source Research Agent (P2.SR) ----------
class ResearchRequestIn(BaseModel):
    """Body của POST /v1/courses/{id}/research-runs.

    KHÔNG có `courseId`/`ownerId`: server lấy từ path + identity đã xác thực.
    """

    maxSources: int = Field(default=8, ge=1, le=20)
    learningGoals: list[str] = Field(default_factory=list, max_length=8)
    learnerLevel: Literal["beginner", "intermediate", "advanced"] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("learningGoals")
    @classmethod
    def _clean_goals(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for goal in value:
            text = " ".join(str(goal).split())
            if not text:
                continue
            if len(text) > 200:
                raise ValueError("learningGoals mỗi mục tối đa 200 ký tự.")
            cleaned.append(text)
        return cleaned


class ResearchSourceOut(BaseModel):
    candidateId: str
    title: str
    sourceType: str
    canonicalUrl: str | None
    publisher: str | None
    author: str | None
    publicationDate: str | None
    language: str | None
    version: str | None
    licenseInfo: str | None
    verificationStatus: str
    relevanceScore: float
    selectionReason: str
    isMock: bool
    scores: dict


class ResearchRunOut(BaseModel):
    researchRunId: str
    courseId: str
    topic: str
    domain: str
    status: str
    sources: list[ResearchSourceOut]
    warnings: list[str]
    insufficientEvidence: bool
    analysis: dict
    error: dict | None = None
    adapter: str
    isMock: bool
    toolCalls: int
    notice: str | None = None
    reused: bool = False
    createdAt: str | None = None


class ResearchRunListOut(BaseModel):
    items: list[ResearchRunOut]
    total: int


# ---------- Learner profile (server-derived from interview, P2.1) ----------
class LearnerProfile(BaseModel):
    """Hồ sơ học viên do **server** suy ra từ 5 câu trả lời (rule-based).

    Không suy diễn thuộc tính nhạy cảm; chỉ dùng các tín hiệu người học tự nêu.
    """

    goal: str = Field(default="", max_length=400)
    currentLevel: Literal["beginner", "intermediate", "advanced"] = "beginner"
    weeklyMinutes: int | None = Field(default=None, ge=0, le=10_080)
    preferredStyles: list[str] = Field(default_factory=list, max_length=6)
    depth: Literal["broad", "balanced", "deep"] = "balanced"
    warnings: list[str] = Field(default_factory=list, max_length=8)


# ---------- Curriculum graph (P2.1) ----------
BLOOM_LEVEL = Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]


class CurriculumSkill(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    # Tiêu đề bài học (khớp `lessonTitles`) mà skill này được dạy.
    lesson: str = Field(min_length=1, max_length=200)
    bloomLevel: BLOOM_LEVEL = "understand"
    outcome: str = Field(default="", max_length=300)


# ---------- Proposal structured output (provider → DB) ----------
class ProposalUnit(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    blurb: str = Field(default="", max_length=400)
    lessonTitles: list[str] = Field(min_length=1, max_length=12)


class ProposalPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=600)
    units: list[ProposalUnit] = Field(min_length=2, max_length=6)
    outcomes: list[str] = Field(min_length=2, max_length=8)
    # P2.1 — optional để proposal cũ (chưa có 2 field này) vẫn đọc được.
    learnerProfile: LearnerProfile | None = None
    skills: list[CurriculumSkill] = Field(default_factory=list, max_length=48)
    # Cạnh [prerequisiteSkillId, skillId]: học cái trước rồi mới tới cái sau.
    prerequisites: list[tuple[str, str]] = Field(default_factory=list, max_length=96)


# ---------- Lesson blocks structured output ----------
class TeachBlock(BaseModel):
    type: Literal["teach"]
    title: str = Field(min_length=1, max_length=200)
    paragraphs: list[str] = Field(min_length=1, max_length=30)


class MCBlock(BaseModel):
    type: Literal["mc"]
    question: str = Field(min_length=1, max_length=400)
    options: list[str] = Field(min_length=2, max_length=6)
    answerIndex: int = Field(ge=0)


class BlankBlock(BaseModel):
    type: Literal["blank"]
    sentence: str = Field(min_length=1, max_length=400)
    answer: str = Field(min_length=1, max_length=120)


class OrderBlock(BaseModel):
    type: Literal["order"]
    prompt: str = Field(min_length=1, max_length=300)
    items: list[str] = Field(min_length=2, max_length=8)


class MatchBlock(BaseModel):
    type: Literal["match"]
    prompt: str = Field(min_length=1, max_length=300)
    pairs: list[tuple[str, str]] = Field(min_length=2, max_length=8)


class ShortBlock(BaseModel):
    type: Literal["short"]
    question: str = Field(min_length=1, max_length=400)
    acceptedAnswers: list[str] = Field(min_length=1, max_length=10)


AnyBlock = MCBlock | BlankBlock | OrderBlock | MatchBlock | ShortBlock | TeachBlock


class LessonContent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    blocks: list[Annotated[AnyBlock, Field(discriminator="type")]] = Field(
        min_length=1, max_length=40
    )

    model_config = {"extra": "forbid"}


# ---------- API request/response ----------
class CourseCreateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    clientCourseId: str = Field(min_length=8, max_length=64)


class CourseOut(BaseModel):
    id: str
    topic: str
    status: str
    clientCourseId: str


class InterviewOut(BaseModel):
    questions: list[str]
    completedCount: int


class InterviewAnswerRequest(BaseModel):
    position: int = Field(ge=0, le=4)
    answer: str = Field(min_length=1, max_length=2000)


class ProposalOut(BaseModel):
    version: int
    approved: bool
    payload: dict


class GenerationOut(BaseModel):
    jobId: str
    status: str
    stage: str | None
    lessonsDone: int
    lessonsTotal: int | None
    error: dict | None
    # P1.2 observability — không chứa prompt/nội dung người dùng
    attempts: int = 0
    dispatched: bool = True
    lastErrorCode: str | None = None
    # P2.2 — usage/cost của job. KHÔNG chứa prompt. `costEstimateUsd = null` và
    # `costKnown = false` nghĩa là chưa cấu hình giá model (không phải miễn phí).
    llmCalls: int = 0
    promptTokens: int | None = None
    completionTokens: int | None = None
    costEstimateUsd: float | None = None
    costKnown: bool = False


class UnitOut(BaseModel):
    id: str
    orderIndex: int
    title: str
    blurb: str
    lessons: list["LessonSummaryOut"]


class LessonSummaryOut(BaseModel):
    id: str
    orderIndex: int
    title: str
    status: str
    contentVersion: int
    completed: bool = False


class CourseListItemOut(BaseModel):
    id: str
    topic: str
    status: str
    createdAt: str | None = None
    updatedAt: str | None = None
    progress: dict
    resumeLessonId: str | None = None
    resumeLessonTitle: str | None = None
    lastCompletedLessonTitle: str | None = None


class CourseListOut(BaseModel):
    items: list[CourseListItemOut]
    total: int
    limit: int
    offset: int
    hasMore: bool


class CourseDetailOut(BaseModel):
    id: str
    topic: str
    status: str
    units: list[UnitOut]
    progress: dict


class LessonOut(BaseModel):
    id: str
    title: str
    orderIndex: int
    contentVersion: int
    status: str
    blocks: list[dict]
    # P3.0: provenance. `grounding` mô tả bài dựa trên nguồn hay kiến thức chung.
    grounding: LESSON_GROUNDING = "general_ai_knowledge"
    citations: list[CitationOut] = Field(default_factory=list)
    evidenceNotice: str | None = None


class AttemptResultOut(BaseModel):
    index: int
    type: str
    correct: bool
    # Đáp án chỉ xuất hiện trong response sau khi nộp (post-submit policy).
    solution: dict = Field(default_factory=dict)


class AttemptRequest(BaseModel):
    clientAttemptId: str = Field(min_length=8, max_length=64)
    contentVersion: int
    durationMs: int | None = Field(default=None, ge=0)
    answers: list["AttemptAnswer"] = Field(min_length=1)


class AttemptAnswer(BaseModel):
    index: int = Field(ge=0)
    answer: str | int | list | dict | None = None
    model_config = {"extra": "forbid"}

    @field_validator("answer", mode="before")
    @classmethod
    def _reject_bool(cls, value):
        # Pydantic smart-union coerce `true` → 1; bool là int trong Python và sẽ
        # vô tình khớp answerIndex. Từ chối sớm để client không "đoán đúng" rẻ.
        if isinstance(value, bool):
            raise ValueError("answer không chấp nhận boolean")
        return value


class AttemptOut(BaseModel):
    attemptId: str
    duplicate: bool
    score: dict
    rewards: dict
    results: list[AttemptResultOut]
