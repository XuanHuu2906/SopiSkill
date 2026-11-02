from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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

CITATION_NOTICE = (
    "P3.0 chưa ingest nội dung nguồn: câu trả lời KHÔNG có trích dẫn đã kiểm chứng. "
    "Nếu người học hỏi cần bằng chứng, nói rõ là chưa có đoạn nguồn để kiểm chứng."
)



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


# ---------- Source Ingestion (P4.0) ----------
SOURCE_DOCUMENT_STATUS = Literal["queued", "extracting", "ready", "no_text", "failed"]
SOURCE_DOCUMENT_ORIGIN = Literal["upload", "web", "arxiv"]


class WebDocumentRequest(BaseModel):
    """Body của ingest từ URL/arXiv (P4.2).

    `userConfirmedRights` BẮT BUỘC và phải đúng `true`; đây là audit xác nhận
    quyền sử dụng, không phải checkbox trang trí. Chỉ một trong `url`/`arxivId`.
    """

    url: str | None = Field(default=None, max_length=2048)
    arxivId: str | None = Field(default=None, max_length=200)
    userConfirmedRights: bool = False
    title: str | None = Field(default=None, max_length=300)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _exactly_one_locator(self):
        has_url = bool((self.url or "").strip())
        has_arxiv = bool((self.arxivId or "").strip())
        if has_url == has_arxiv:
            raise ValueError("Chọn đúng một trong hai: url hoặc arxivId.")
        if not self.userConfirmedRights:
            raise ValueError(
                "userConfirmedRights phải là true — cần xác nhận quyền sử dụng nguồn."
            )
        return self


class SourceDocumentOut(BaseModel):
    """Trạng thái ingest của MỘT file. Không bao giờ chứa text hay storage key.

    `chunkCount` chỉ > 0 khi `status=ready`. `preview` là vài trăm ký tự đầu của
    chunk đầu tiên, chỉ để người dùng nhận biết tài liệu — KHÔNG phải bằng chứng
    và không được dùng làm citation.
    """

    id: str
    sourceId: str
    status: SOURCE_DOCUMENT_STATUS
    origin: SOURCE_DOCUMENT_ORIGIN = "upload"
    originUrl: str | None = None
    mime: str
    byteSize: int
    pageCount: int | None
    pipelineVersion: str
    originalFilename: str | None
    chunkCount: int = 0
    preview: str | None = None
    error: dict | None = None
    attempts: int = 0
    rightsConfirmed: bool = False
    # P4.3 — text đến từ đâu: `native` (text layer PDF), `ocr`, hay `mixed`.
    # `null` = document cũ trước P4.3 (không suy đoán ngược).
    textSource: Literal["native", "ocr", "mixed"] | None = None
    # Số trang đã OCR + engine/version. Chỉ để truy vết "text do máy đọc".
    ocrPages: int = 0
    ocrEngine: str | None = None
    ocrVersion: str | None = None
    ingestedAt: str | None = None
    createdAt: str | None = None


class SourceDocumentListOut(BaseModel):
    sourceId: str
    items: list[SourceDocumentOut]
    total: int
    contentIngested: bool
    notice: str | None = None


class SourceIngestConfigOut(BaseModel):
    """Cho UI biết upload có khả dụng hay không (không lộ endpoint/credential)."""

    ingestEnabled: bool
    storageConfigured: bool
    maxPdfBytes: int
    maxPdfPages: int
    pipelineVersion: str
    # P4.1 — trạng thái lập chỉ mục. `embeddingConfigured=false` ⇒ tìm kiếm
    # ngữ nghĩa KHÔNG chạy; UI phải nói thật thay vì giả vờ có RAG.
    embeddingEnabled: bool = True
    embeddingConfigured: bool = True
    embeddingProvider: str = "hashing"
    embeddingModel: str = "hashing-ngram-v1"
    embeddingDimension: int = 256
    ragEnabled: bool = False
    # P4.2 — URL/arXiv ingest. `webEnabled=false` ⇒ UI phải ẩn form; server cũng
    # từ chối nếu client cố gọi. `webAllowedHostCount` cho biết có allowlist.
    webEnabled: bool = False
    webAllowedHostCount: int = 0
    webMaxFetchBytes: int = 0
    webRespectRobots: bool = True
    arxivEnabled: bool = False
    # P4.3 — OCR cho PDF scan. `ocrConfigured=false` ⇒ scan vẫn `no_text`; UI phải
    # nói thật là "chưa bật OCR", không hứa đọc được bản scan.
    ocrEnabled: bool = False
    ocrConfigured: bool = False
    ocrEngine: str = ""
    ocrVersion: str = ""
    ocrMaxPages: int = 0
    ocrDpi: int = 0


class RagSearchRequest(BaseModel):
    """Body của POST /v1/courses/{id}/sources/search.

    `sourceIds` chỉ THU HẸP phạm vi: server luôn giao với các nguồn đã liên kết
    và thuộc quyền user, nên client không thể mở rộng sang nguồn khác.
    """

    query: str = Field(min_length=1, max_length=1000)
    sourceIds: list[str] = Field(default_factory=list, max_length=20)
    topK: int = Field(default=6, ge=1, le=20)

    model_config = {"extra": "forbid"}


class RagChunkOut(BaseModel):
    chunkId: str
    sourceId: str
    documentId: str
    pageNumber: int
    charStart: int
    charEnd: int
    sectionAnchor: str | None = None
    textHash: str
    sourceTitle: str
    sourceVersion: str | None = None
    # P4.2 — URL nguồn thực (web/arXiv); None với PDF upload.
    sourceUrl: str | None = None
    # P4.3 — `native` hay `ocr`. Đoạn do máy đọc ảnh phải được nói rõ cho người
    # học/người review, không giả vờ là text gốc.
    textSource: Literal["native", "ocr"] = "native"
    ocrConfidence: float | None = None
    ocrBbox: list[float] | None = None
    snippet: str
    lexicalRank: int | None = None
    vectorRank: int | None = None
    similarity: float | None = None
    rrfScore: float


class RagSearchOut(BaseModel):
    query: str
    embeddingSpec: str
    items: list[RagChunkOut]
    total: int
    insufficientEvidence: bool
    # Không đủ căn cứ ⇒ UI phải nói "chưa đủ thông tin", không hiển thị nguồn giả.
    notice: str | None = None


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
    # Cho UI gọi các endpoint scoped theo course (progress, tutor) mà không phải
    # đoán ngược từ URL. Server vẫn kiểm ownership ở mọi request.
    courseId: str | None = None
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
    # P5.0 — additive: UI hiện "Đã thêm vào lịch ôn tập" khi True.
    reviewCardCreated: bool = False


# ---------- AI Tutor (P3.0) ----------
class TutorContextRef(BaseModel):
    """Tham chiếu ngữ cảnh do client gửi. Server luôn resolve lại từ DB."""

    lessonId: str = Field(min_length=1, max_length=64)
    blockIndex: int = Field(ge=0, le=200)

    model_config = {"extra": "forbid"}


class TutorMessageRequest(BaseModel):
    """Body của POST /v1/courses/{courseId}/tutor/messages.

    KHÔNG có `userId`, `courseId`, `systemPrompt`, `lessonContent`, `sources`
    hay `ownerId`: server lấy identity từ session, course/lesson từ DB, và các
    field đó bị từ chối rõ ràng (extra=forbid).
    """

    clientMessageId: str = Field(min_length=8, max_length=64)
    threadId: str | None = Field(default=None, max_length=64)
    text: str = Field(min_length=1, max_length=4000)
    contextRef: TutorContextRef

    model_config = {"extra": "forbid"}


class TutorCitationOut(BaseModel):
    """Citation đã verify server-side (P4.1). Chỉ id do retrieval trả về."""

    chunkId: str
    sourceId: str
    documentId: str | None = None
    pageNumber: int | None = None
    charStart: int | None = None
    charEnd: int | None = None
    sectionAnchor: str | None = None
    textHash: str | None = None
    sourceTitle: str | None = None
    sourceVersion: str | None = None
    # P4.2 — URL nguồn thực cho tài liệu web/arXiv; None với PDF upload.
    sourceUrl: str | None = None
    evidenceText: str | None = None
    validationStatus: str
    # P4.1 LUÔN False: locator_verified chỉ xác minh vị trí, không xác minh claim.
    evidenceSupported: bool = False


class TutorMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    status: str
    content: str
    contextRef: dict | None = None
    errorCode: str | None = None
    finishReason: str | None = None
    citations: list[TutorCitationOut] = Field(default_factory=list)
    createdAt: str | None = None


class TutorThreadSummaryOut(BaseModel):
    id: str
    courseId: str
    lessonId: str
    title: str
    messageCount: int
    createdAt: str | None = None
    updatedAt: str | None = None


class TutorThreadOut(TutorThreadSummaryOut):
    messages: list[TutorMessageOut] = Field(default_factory=list)
    # P3.0 không hỗ trợ replay byte-by-byte (chưa có event log bền vững).
    replaySupported: bool = False
    notice: str | None = None


class TutorThreadListOut(BaseModel):
    items: list[TutorThreadSummaryOut]
    total: int


class TutorQuotaUsageOut(BaseModel):
    messages: int
    tokens: int


class TutorQuotaLimitsOut(BaseModel):
    """0 = không giới hạn (không phải "cấm dùng")."""

    messagesPerDay: int
    tokensPerDay: int
    maxConcurrentStreams: int


class TutorQuotaRemainingOut(BaseModel):
    """None = không có trần tương ứng, không phải "còn 0". """

    messages: int | None = None
    tokens: int | None = None


class TutorUsageOut(BaseModel):
    courseId: str
    windowSeconds: int
    used: TutorQuotaUsageOut
    limits: TutorQuotaLimitsOut
    remaining: TutorQuotaRemainingOut
    runningStreams: int
    # False = provider chưa báo token lần nào ⇒ trần token không phản ánh chi phí thật.
    tokensKnown: bool


class TutorStopOut(BaseModel):
    messageId: str
    status: str
    # Luôn False ở P3.1: dừng là best-effort, provider có thể đã tính phí phần đã sinh.
    providerStopGuaranteed: bool = False
    notice: str | None = None


# ---------- Learner profile, mastery & FSRS (P5.0) ----------
class SkillMasteryOut(BaseModel):
    skillId: str
    title: str
    bloomLevel: str
    # Heuristic accuracy có trọng số thời gian — KHÔNG phải xác suất đã hiệu chuẩn.
    masteryScore: float
    method: str = "rule_based"
    attempts: int
    correct: int
    total: int
    lastAttemptAt: str | None = None
    passThreshold: float


class MasteryOut(BaseModel):
    items: list[SkillMasteryOut]
    coursePercent: float
    reviewDueCount: int


class LearningPathReasonOut(BaseModel):
    code: str
    message: str


class LearningPathNextLessonOut(BaseModel):
    lessonId: str
    title: str
    reason: LearningPathReasonOut


class LearningPathPrerequisiteOut(BaseModel):
    skillId: str
    title: str
    masteryScore: float
    met: bool


class LearningPathBlockedOut(BaseModel):
    lessonId: str
    title: str
    prerequisites: list[LearningPathPrerequisiteOut]
    reason: LearningPathReasonOut


class PrerequisiteDagNodeOut(BaseModel):
    id: str
    title: str
    bloomLevel: str


class PrerequisiteDagOut(BaseModel):
    nodes: list[PrerequisiteDagNodeOut]
    edges: list[list[str]]


class LearningPathOut(BaseModel):
    nextLesson: LearningPathNextLessonOut | None = None
    reviewLessonId: str | None = None
    reviewDueCount: int
    blockedBy: list[LearningPathBlockedOut]
    prerequisitesDag: PrerequisiteDagOut


class DueReviewOut(BaseModel):
    cardId: str
    lessonId: str
    lessonTitle: str
    skillTitle: str | None = None
    # stability/difficulty cố tình KHÔNG trả ra: chỉ dùng nội bộ, tránh gây hiểu
    # nhầm là điểm số của người học.
    dueAt: str
    state: int
    overdueDays: int


class ReviewDueOut(BaseModel):
    items: list[DueReviewOut]
    total: int


class ReviewGradeRequest(BaseModel):
    rating: int = Field(ge=1, le=4)
    clientReviewId: str = Field(min_length=1, max_length=64)
    durationMs: int | None = Field(default=None, ge=0)


class ReviewCardOut(BaseModel):
    cardId: str
    lessonId: str
    state: int
    dueAt: str
    lastReviewAt: str | None = None


class ReviewGradeOut(BaseModel):
    card: ReviewCardOut
    eventId: str
    duplicate: bool
