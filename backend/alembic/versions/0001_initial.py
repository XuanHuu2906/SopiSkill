"""initial schema — users (auth) + courses + interviews + proposals + jobs + units + lessons + attempts + xp

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-30

Viết tay dựa trên app.models (Base.metadata) để kiểm soát JSONB variant trên PostgreSQL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("external_id", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=True, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=False, server_default="Learner"),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_active_date", sa.Text(), nullable=True),
        *_timestamps(),
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("interview", "proposed", "approved", "generating", "ready", "failed", name="course_status"), nullable=False),
        sa.Column("client_course_id", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "client_course_id", name="uq_course_client_id"),
    )
    op.create_index("ix_courses_user_id", "courses", ["user_id"])

    op.create_table(
        "course_interviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False, unique=True),
        sa.Column("questions", JSONVariant, nullable=False),
        sa.Column("answers", JSONVariant, nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )

    op.create_table(
        "course_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", JSONVariant, nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("course_id", "version", name="uq_proposal_version"),
    )
    op.create_index("ix_course_proposals_course_id", "course_proposals", ["course_id"])

    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("status", sa.Enum("queued", "running", "ready", "failed", name="job_status"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("lessons_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lessons_total", sa.Integer(), nullable=True),
        sa.Column("error", JSONVariant, nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
    )
    op.create_index("ix_generation_jobs_course_id", "generation_jobs", ["course_id"])

    op.create_table(
        "units",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("blurb", sa.Text(), nullable=False, server_default=""),
        *_timestamps(),
        sa.UniqueConstraint("course_id", "order_index", name="uq_unit_order"),
    )
    op.create_index("ix_units_course_id", "units", ["course_id"])

    op.create_table(
        "lessons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("unit_id", sa.Uuid(), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", JSONVariant, nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Enum("pending", "ready", "failed", name="lesson_status"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("unit_id", "order_index", name="uq_lesson_order"),
    )
    op.create_index("ix_lessons_course_id", "lessons", ["course_id"])

    op.create_table(
        "lesson_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_attempt_id", sa.Text(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=False),
        sa.Column("score_correct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("results", JSONVariant, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("lesson_id", "user_id", "client_attempt_id", name="uq_attempt_client_id"),
    )
    op.create_index("ix_lesson_attempts_lesson_id", "lesson_attempts", ["lesson_id"])
    op.create_index("ix_lesson_attempts_user_id", "lesson_attempts", ["user_id"])

    op.create_table(
        "xp_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id"), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_xp_events_user_id", "xp_events", ["user_id"])


def downgrade() -> None:
    op.drop_table("xp_events")
    op.drop_table("lesson_attempts")
    op.drop_table("lessons")
    op.drop_table("units")
    op.drop_table("generation_jobs")
    op.drop_table("course_proposals")
    op.drop_table("course_interviews")
    op.drop_table("courses")
    op.drop_table("users")
    for enum_name in ("course_status", "job_status", "lesson_status"):
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
