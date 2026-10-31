import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class CourseStatus(str, enum.Enum):
    interview = "interview"
    proposed = "proposed"
    approved = "approved"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    ready = "ready"
    failed = "failed"


class LessonStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"


class SourceType(str, enum.Enum):
    official_documentation = "official_documentation"
    academic = "academic"
    user_document = "user_document"
    webpage = "webpage"


class SourceVisibility(str, enum.Enum):
    public = "public"
    private = "private"


class SourceVerificationStatus(str, enum.Enum):
    """Mức xác thực của NGUỒN (metadata), không phải mức nội dung đúng.

    Thang tăng dần: unverified < metadata_verified < locator_verified
    < evidence_supported < corroborated. Không bao giờ tự nhảy bậc vì URL hợp lệ
    hoặc vì LLM khai báo.
    """

    unverified = "unverified"
    pending_review = "pending_review"
    metadata_verified = "metadata_verified"
    locator_verified = "locator_verified"
    evidence_supported = "evidence_supported"
    corroborated = "corroborated"
    rejected = "rejected"


class CitationValidationStatus(str, enum.Enum):
    """Mức kiểm chứng của MỘT citation, tách biệt hoàn toàn với độ đúng của claim."""

    unverified = "unverified"
    locator_verified = "locator_verified"
    evidence_supported = "evidence_supported"
    unavailable = "unavailable"
    source_changed = "source_changed"
    rejected = "rejected"


class LessonGrounding(str, enum.Enum):
    source_grounded = "source_grounded"
    general_ai_knowledge = "general_ai_knowledge"


class TutorMessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class TutorMessageStatus(str, enum.Enum):
    """Trạng thái của một message trong thread tutor.

    `pending` chỉ tồn tại trong transaction chuẩn bị stream; khi stream bắt đầu
    message assistant chuyển `running`, và chỉ được ghi `completed`/`failed`/
    `cancelled` bởi chính task đang giữ message đó. Nếu tiến trình chết giữa
    chừng, row có thể còn `running` — client thấy trạng thái thật thay vì bị
    báo nhầm là đã xong.
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SourceResearchStatus(str, enum.Enum):
    """Trạng thái của một lần nghiên cứu nguồn (P2.SR).

    `running` chỉ tồn tại trong thời gian request; nếu tiến trình chết giữa chừng
    row sẽ ở `running` và bị coi là không dùng được (không tự đánh dấu completed).
    """

    running = "running"
    completed = "completed"
    insufficient_evidence = "insufficient_evidence"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    external_id: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str] = mapped_column(Text, default="Learner")
    xp: Mapped[int] = mapped_column(Integer, default=0)
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("user_id", "client_course_id", name="uq_course_client_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    topic: Mapped[str] = mapped_column(Text)
    status: Mapped[CourseStatus] = mapped_column(
        Enum(CourseStatus, name="course_status"), default=CourseStatus.interview
    )
    client_course_id: Mapped[str] = mapped_column(Text)
    units: Mapped[list["Unit"]] = relationship(back_populates="course", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourseInterview(Base):
    __tablename__ = "course_interviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), unique=True)
    questions: Mapped[list] = mapped_column(JSONVariant, default=list)
    answers: Mapped[list] = mapped_column(JSONVariant, default=list)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourseProposal(Base):
    __tablename__ = "course_proposals"
    __table_args__ = (UniqueConstraint("course_id", "version", name="uq_proposal_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSONVariant)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (Index("ix_generation_jobs_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), default=JobStatus.queued)
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_done: Mapped[int] = mapped_column(Integer, default=0)
    lessons_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    # Số lần worker đã claim job (bắt đầu từ 0). Bounded bởi `max_attempts`.
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    # P1.2 reliability
    proposal_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # P2.2 — usage/cost tổng hợp của job (cập nhật dần khi sinh bài). Để NULL khi
    # chưa cấu hình giá model: NULL = chưa biết, KHÔNG phải miễn phí.
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("course_id", "order_index", name="uq_unit_order"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    blurb: Mapped[str] = mapped_column(Text, default="")
    course: Mapped[Course] = relationship(back_populates="units")
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="unit", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("unit_id", "order_index", name="uq_lesson_order"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[list] = mapped_column(JSONVariant, default=list)
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[LessonStatus] = mapped_column(
        Enum(LessonStatus, name="lesson_status"), default=LessonStatus.pending
    )
    # P3 source-first: bài học dựa trên nguồn đã liên kết hay kiến thức chung của AI.
    # Default giữ cho mọi row cũ đọc được như "kiến thức chung, chưa kiểm chứng".
    grounding: Mapped[LessonGrounding] = mapped_column(
        Enum(LessonGrounding, name="lesson_grounding"),
        default=LessonGrounding.general_ai_knowledge,
    )
    unit: Mapped[Unit] = relationship(back_populates="lessons")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Source(Base):
    """Source Registry — metadata của một nguồn tri thức (P3.0).

    Bảng này KHÔNG chứa nội dung tài liệu (text/chunks thuộc P4). Nó chỉ lưu
    metadata + mức xác thực metadata, để citation có thể trỏ tới một nguồn có
    quyền truy cập và có phiên bản rõ ràng.

    `dedupe_key` là hash deterministic của (scope sở hữu, source_type, canonical
    URL/title, content_hash) ⇒ tạo lại cùng một nguồn trả về bản ghi cũ thay vì
    sinh duplicate vô hạn.
    """

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_source_dedupe"),
        Index("ix_sources_visibility_owner", "visibility", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type"), default=SourceType.webpage
    )
    title: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    visibility: Mapped[SourceVisibility] = mapped_column(
        Enum(SourceVisibility, name="source_visibility"), default=SourceVisibility.private
    )
    license_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[SourceVerificationStatus] = mapped_column(
        Enum(SourceVerificationStatus, name="source_verification_status"),
        default=SourceVerificationStatus.unverified,
    )
    dedupe_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourseSource(Base):
    """Liên kết n–n Course ↔ Source.

    `evaluation` là snapshot đánh giá chất lượng tại thời điểm liên kết (JSON) để
    hiển thị lại kể cả khi thuật toán chấm điểm thay đổi. Không dùng để suy ra
    "nội dung đúng".
    """

    __tablename__ = "course_sources"
    __table_args__ = (
        UniqueConstraint("course_id", "source_id", name="uq_course_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    evaluation: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LessonCitation(Base):
    """Citation/provenance cho một bài học (P3.0 evidence contract).

    Tách biệt bốn mức: metadata verified, locator verified, evidence supports
    claim, claim corroborated. Bảng này chỉ ghi bằng chứng THỰC SỰ có (locator +
    đoạn evidence nếu có); trạng thái mặc định luôn `unverified`.
    """

    __tablename__ = "lesson_citations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), index=True)
    # Snapshot phiên bản nguồn tại thời điểm sinh bài — citation cũ không được âm
    # thầm trỏ sang phiên bản mới khi source.version thay đổi.
    source_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_anchor: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[CitationValidationStatus] = mapped_column(
        Enum(CitationValidationStatus, name="citation_validation_status"),
        default=CitationValidationStatus.unverified,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SourceResearchRun(Base):
    """Một lần Source Research Agent chạy cho course (P2.SR).

    Bảng chỉ lưu **kết quả nghiên cứu** và bằng chứng về mức kiểm chứng tại thời
    điểm chạy. Nó KHÔNG phải registry: nguồn chỉ vào `sources` khi người dùng
    chấp nhận và service xác thực quyền. Vì vậy:
      - `sources` là JSON snapshot (adapter, metadata, verificationStatus, reason);
      - `is_mock` buộc phải đúng khi adapter không trả dữ liệu thật;
      - `request_fingerprint` chống tạo trùng khi client retry cùng yêu cầu.
    """

    __tablename__ = "source_research_runs"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "request_fingerprint", name="uq_research_run_fingerprint"
        ),
        Index("ix_research_runs_course_created", "course_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    # Owner được ghi lại để truy vấn scoped không phải join course mỗi lần.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[SourceResearchStatus] = mapped_column(
        Enum(SourceResearchStatus, name="source_research_status"),
        default=SourceResearchStatus.running,
    )
    topic: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text, default="general")
    adapter: Mapped[str] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(default=False)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    analysis: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    sources: Mapped[list] = mapped_column(JSONVariant, default=list)
    warnings: Mapped[list] = mapped_column(JSONVariant, default=list)
    error: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    insufficient_evidence: Mapped[bool] = mapped_column(default=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LlmUsageEvent(Base):
    """Một lời gọi LLM đã phát sinh (P2.2).

    Chỉ lưu **metadata** (provider/model/loại call/token/latency/chi phí ước tính).
    KHÔNG lưu prompt, câu trả lời của người học hay nội dung sinh ra.
    """

    __tablename__ = "llm_usage_events"
    __table_args__ = (
        Index("ix_llm_usage_events_job_id", "job_id"),
        Index("ix_llm_usage_events_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    # Gắn với job khi lời gọi xảy ra trong generation; NULL cho eval/API.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_jobs.id"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    # interview | proposal | lesson | judge | other
    kind: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL = chưa biết giá model, KHÔNG phải miễn phí.
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TutorThread(Base):
    """Một cuộc hội thoại tutor gắn với course + lesson (P3.0).

    Thread thuộc đúng một user và một course. `lesson_id` là ngữ cảnh mặc định
    để mở thread, nhưng mỗi message vẫn lưu `context_ref` riêng vì người học có
    thể hỏi ở block khác trong cùng bài. Ownership luôn kiểm tra ở server qua
    course; không tin `userId`/`courseId` từ client.
    """

    __tablename__ = "tutor_threads"
    __table_args__ = (
        Index("ix_tutor_threads_user_course_updated", "user_id", "course_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    # Đếm lượt hỏi đã CHẤP NHẬN (reserve quota P3.1 dùng lại cột này).
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TutorMessage(Base):
    """Một message trong thread tutor.

    `client_message_id` unique theo thread: retry cùng id không tạo message thứ
    hai và không gọi provider lần nữa. Nội dung assistant được ghi dần
    (`content`) trong lúc stream nhưng chỉ được coi là final khi `status` =
    `completed`.
    """

    __tablename__ = "tutor_messages"
    __table_args__ = (
        # Một lượt hỏi = đúng 1 user message + đúng 1 assistant message cho mỗi
        # (course, clientMessageId). Khóa theo **course** chứ không chỉ thread để
        # retry vẫn idempotent kể cả khi request đầu chưa kịp trả `threadId`
        # (double-click tạo 2 thread song song). `role` cho phép cặp user+assistant
        # cùng id mà không đụng nhau.
        UniqueConstraint(
            "course_id", "client_message_id", "role", name="uq_tutor_message_client_id"
        ),
        # `position` là thứ tự logic trong thread (0,1,2,…). Không dùng
        # `created_at` để sắp xếp vì độ phân giải giây làm user/assistant trùng
        # timestamp và thứ tự hiển thị sẽ ngẫu nhiên.
        Index("ix_tutor_messages_thread_position", "thread_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    thread_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tutor_threads.id"), index=True)
    # Denormalized để UNIQUE(course_id, client_message_id, role) enforce được ở DB.
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[TutorMessageRole] = mapped_column(
        Enum(TutorMessageRole, name="tutor_message_role")
    )
    status: Mapped[TutorMessageStatus] = mapped_column(
        Enum(TutorMessageStatus, name="tutor_message_status"),
        default=TutorMessageStatus.pending,
    )
    content: Mapped[str] = mapped_column(Text, default="")
    # Snapshot context của lượt hỏi: {lessonId, blockIndex, lessonTitle, blockType}.
    context_ref: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    # clientMessageId của LƯỢT HỎI (user message) mà assistant này trả lời.
    client_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LessonAttempt(Base):
    __tablename__ = "lesson_attempts"
    __table_args__ = (
        UniqueConstraint("lesson_id", "user_id", "client_attempt_id", name="uq_attempt_client_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lessons.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    client_attempt_id: Mapped[str] = mapped_column(Text)
    content_version: Mapped[int] = mapped_column(Integer)
    score_correct: Mapped[int] = mapped_column(Integer, default=0)
    score_total: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    results: Mapped[list] = mapped_column(JSONVariant, default=list)
    xp_awarded: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class XpEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (Index("ix_xp_events_lesson_version", "user_id", "lesson_id", "content_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
