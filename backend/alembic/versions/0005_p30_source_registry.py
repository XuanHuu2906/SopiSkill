"""P3.0 — Source Registry, Course↔Source links and lesson citation provenance

Revision ID: 0005_p30_source_registry
Revises: 0004_p12_job_reliability
Create Date: 2026-10-31

Phạm vi (expand-only, KHÔNG xóa/sửa dữ liệu hiện có):
  - sources                : metadata nguồn tri thức + mức xác thực metadata.
  - course_sources         : liên kết n–n course ↔ source + snapshot đánh giá.
  - lesson_citations       : provenance/citation của bài học.
  - lessons.grounding      : source_grounded | general_ai_knowledge.
                             server_default='general_ai_knowledge' ⇒ mọi bài học
                             cũ đọc được và được hiểu là "kiến thức chung, chưa
                             kiểm chứng"; không backfill dữ liệu giả.

Rollback (downgrade):
  - drop bảng citation/source/course_sources và cột grounding.
  - Việc downgrade MẤT metadata nguồn + citation đã tạo sau P3.0 (không thể
    khôi phục từ chính schema). Trên DB thật: backup trước, và chỉ downgrade khi
    thực sự cần; dữ liệu course/lesson/quiz/progress không bị đụng tới.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_p30_source_registry"
down_revision: Union[str, None] = "0004_p12_job_reliability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

SOURCE_TYPE = ("official_documentation", "academic", "user_document", "webpage")
SOURCE_VISIBILITY = ("public", "private")
SOURCE_VERIFICATION = (
    "unverified",
    "pending_review",
    "metadata_verified",
    "locator_verified",
    "evidence_supported",
    "corroborated",
    "rejected",
)
CITATION_VALIDATION = (
    "unverified",
    "locator_verified",
    "evidence_supported",
    "unavailable",
    "source_changed",
    "rejected",
)
LESSON_GROUNDING = ("source_grounded", "general_ai_knowledge")

_ENUM_TYPES = {
    "source_type": SOURCE_TYPE,
    "source_visibility": SOURCE_VISIBILITY,
    "source_verification_status": SOURCE_VERIFICATION,
    "citation_validation_status": CITATION_VALIDATION,
    "lesson_grounding": LESSON_GROUNDING,
}


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enum(name: str, values: tuple[str, ...], *, create_type: bool) -> sa.Enum:
    if _is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=create_type)
    return sa.Enum(*values, name=name)


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if _is_postgres():
        for name, values in _ENUM_TYPES.items():
            postgresql.ENUM(*values, name=name).create(conn, checkfirst=True)

    tables = _table_names(conn)

    if "sources" not in tables:
        op.create_table(
            "sources",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "source_type",
                _enum("source_type", SOURCE_TYPE, create_type=False),
                nullable=False,
                server_default="webpage",
            ),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("canonical_url", sa.Text(), nullable=True),
            sa.Column("author", sa.Text(), nullable=True),
            sa.Column("publisher", sa.Text(), nullable=True),
            sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("language", sa.Text(), nullable=True),
            sa.Column("version", sa.Text(), nullable=True),
            sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column(
                "visibility",
                _enum("source_visibility", SOURCE_VISIBILITY, create_type=False),
                nullable=False,
                server_default="private",
            ),
            sa.Column("license_info", sa.Text(), nullable=True),
            sa.Column("content_hash", sa.Text(), nullable=True),
            sa.Column(
                "verification_status",
                _enum("source_verification_status", SOURCE_VERIFICATION, create_type=False),
                nullable=False,
                server_default="unverified",
            ),
            sa.Column("dedupe_key", sa.Text(), nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("dedupe_key", name="uq_source_dedupe"),
        )
        op.create_index("ix_sources_owner_id", "sources", ["owner_id"])
        op.create_index("ix_sources_visibility_owner", "sources", ["visibility", "owner_id"])

    if "course_sources" not in tables:
        op.create_table(
            "course_sources",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id"), nullable=False),
            sa.Column("evaluation", JSONVariant, nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
            sa.UniqueConstraint("course_id", "source_id", name="uq_course_source"),
        )
        op.create_index("ix_course_sources_course_id", "course_sources", ["course_id"])
        op.create_index("ix_course_sources_source_id", "course_sources", ["source_id"])

    if "lesson_citations" not in tables:
        op.create_table(
            "lesson_citations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id"), nullable=False),
            sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id"), nullable=False),
            sa.Column("source_version", sa.Text(), nullable=True),
            sa.Column("chunk_id", sa.Text(), nullable=True),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("section_anchor", sa.Text(), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column(
                "validation_status",
                _enum("citation_validation_status", CITATION_VALIDATION, create_type=False),
                nullable=False,
                server_default="unverified",
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
            ),
        )
        op.create_index("ix_lesson_citations_lesson_id", "lesson_citations", ["lesson_id"])
        op.create_index("ix_lesson_citations_source_id", "lesson_citations", ["source_id"])

    if "grounding" not in _columns(conn, "lessons"):
        op.add_column(
            "lessons",
            sa.Column(
                "grounding",
                _enum("lesson_grounding", LESSON_GROUNDING, create_type=False),
                nullable=False,
                server_default="general_ai_knowledge",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)

    if "grounding" in _columns(conn, "lessons"):
        op.drop_column("lessons", "grounding")

    if "lesson_citations" in tables:
        op.drop_table("lesson_citations")
    if "course_sources" in tables:
        op.drop_table("course_sources")
    if "sources" in tables:
        op.drop_table("sources")

    if _is_postgres():
        for name in reversed(list(_ENUM_TYPES)):
            postgresql.ENUM(name=name).drop(conn, checkfirst=True)
