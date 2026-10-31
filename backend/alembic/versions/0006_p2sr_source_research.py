"""P2.SR — Source Research Agent runs

Revision ID: 0006_p2sr_source_research
Revises: 0005_p30_source_registry
Create Date: 2026-10-31

Phạm vi (expand-only):
  - bảng `source_research_runs`: kết quả một lần nghiên cứu nguồn.
  - enum `source_research_status`.
  - UNIQUE(course_id, request_fingerprint) ⇒ retry cùng yêu cầu trả lại lần chạy
    cũ thay vì nhân bản (idempotency).
  - KHÔNG thêm cột vào bảng cũ, KHÔNG sửa dữ liệu hiện có.

Rollback (downgrade):
  - drop index/bảng/enum của P2.SR. Mất lịch sử nghiên cứu (không thể khôi phục
    từ schema). `sources`/`course_sources`/`lesson_citations` không bị đụng tới.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_p2sr_source_research"
down_revision: Union[str, None] = "0005_p30_source_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

RESEARCH_STATUS = ("running", "completed", "insufficient_evidence", "failed")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enum(name: str, values: tuple[str, ...], *, create_type: bool) -> sa.Enum:
    if _is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=create_type)
    return sa.Enum(*values, name=name)


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    if _is_postgres():
        postgresql.ENUM(*RESEARCH_STATUS, name="source_research_status").create(
            conn, checkfirst=True
        )

    if "source_research_runs" not in _table_names(conn):
        op.create_table(
            "source_research_runs",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "status",
                _enum("source_research_status", RESEARCH_STATUS, create_type=False),
                nullable=False,
                server_default="running",
            ),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("domain", sa.Text(), nullable=False, server_default="general"),
            sa.Column("adapter", sa.Text(), nullable=False),
            sa.Column("is_mock", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("request_fingerprint", sa.Text(), nullable=False),
            sa.Column("analysis", JSONVariant, nullable=True),
            sa.Column("sources", JSONVariant, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("warnings", JSONVariant, nullable=False, server_default=sa.text("'[]'")),
            sa.Column("error", JSONVariant, nullable=True),
            sa.Column(
                "insufficient_evidence", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "course_id", "request_fingerprint", name="uq_research_run_fingerprint"
            ),
        )
        op.create_index(
            "ix_source_research_runs_course_id", "source_research_runs", ["course_id"]
        )
        op.create_index("ix_source_research_runs_user_id", "source_research_runs", ["user_id"])
        op.create_index(
            "ix_research_runs_course_created",
            "source_research_runs",
            ["course_id", "created_at"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if "source_research_runs" in _table_names(conn):
        op.drop_table("source_research_runs")

    if _is_postgres():
        postgresql.ENUM(name="source_research_status").drop(conn, checkfirst=True)
