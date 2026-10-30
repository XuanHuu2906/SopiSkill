import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Text, UniqueConstraint, func
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    external_id: Mapped[str] = mapped_column(Text, unique=True)
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

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), default=JobStatus.queued)
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_done: Mapped[int] = mapped_column(Integer, default=0)
    lessons_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    attempts_count: Mapped[int] = mapped_column(Integer, default=1)
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
    unit: Mapped[Unit] = relationship(back_populates="lessons")
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class XpEvent(Base):
    __tablename__ = "xp_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
