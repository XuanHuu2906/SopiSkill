"""P3.0 — AI Tutor Core: threads + messages

Revision ID: 0008_p30_tutor_core
Revises: 0007_p22_eval_cost
Create Date: 2026-10-31

Phạm vi (expand-only, không drop/sửa dữ liệu cũ):
  - Bảng `tutor_threads`: hội thoại theo (user, course, lesson) + `message_count`.
  - Bảng `tutor_messages`: message user/assistant, `status`, `context_ref` JSON,
    usage token của lời gọi provider.
  - UNIQUE(thread_id, client_message_id) ⇒ retry cùng yêu cầu không tạo message
    thứ hai; UNIQUE cho phép nhiều NULL (assistant message không có client id)
    trên PostgreSQL lẫn SQLite.
  - Enum `tutor_message_role`, `tutor_message_status`.

Không thêm cột vào bảng cũ. Thread/message cũ không có vì bảng mới.

Downgrade: drop index + bảng + enum của P3.0 tutor. Mất lịch sử hội thoại tutor
(không thể khôi phục từ schema); course/lesson/source không bị đụng tới.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_p30_tutor_core"
down_revision: Union[str, None] = "0007_p22_eval_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

ROLES = ("user", "assistant")
STATUSES = ("pending", "running", "completed", "failed", "cancelled")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enum(name: str, values: tuple[str, ...], *, create_type: bool) -> sa.Enum:
    if _is_postgres():
        return postgresql.ENUM(*values, name=name, create_type=create_type)
    return sa.Enum(*values, name=name)


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def _index_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if _is_postgres():
        postgresql.ENUM(*ROLES, name="tutor_message_role").create(conn, checkfirst=True)
        postgresql.ENUM(*STATUSES, name="tutor_message_status").create(conn, checkfirst=True)

    existing = _table_names(conn)

    if "tutor_threads" not in existing:
        op.create_table(
            "tutor_threads",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id"), nullable=False),
            sa.Column("title", sa.Text(), nullable=False, server_default=""),
            sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
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
        )
        op.create_index("ix_tutor_threads_user_id", "tutor_threads", ["user_id"])
        op.create_index("ix_tutor_threads_course_id", "tutor_threads", ["course_id"])
        op.create_index("ix_tutor_threads_lesson_id", "tutor_threads", ["lesson_id"])
        op.create_index(
            "ix_tutor_threads_user_course_updated",
            "tutor_threads",
            ["user_id", "course_id", "updated_at"],
        )

    if "tutor_messages" not in existing:
        op.create_table(
            "tutor_messages",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "thread_id",
                sa.Uuid(),
                sa.ForeignKey("tutor_threads.id"),
                nullable=False,
            ),
            # Thứ tự logic trong thread (0,1,2,…) — không dựa vào timestamp vì
            # độ phân giải giây làm user/assistant trùng nhau.
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
            sa.Column(
                "role",
                _enum("tutor_message_role", ROLES, create_type=False),
                nullable=False,
            ),
            sa.Column(
                "status",
                _enum("tutor_message_status", STATUSES, create_type=False),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("context_ref", JSONVariant, nullable=True),
            sa.Column("client_message_id", sa.Text(), nullable=True),
            sa.Column("error_code", sa.Text(), nullable=True),
            sa.Column("finish_reason", sa.Text(), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
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
                "course_id", "client_message_id", "role", name="uq_tutor_message_client_id"
            ),
        )
        op.create_index("ix_tutor_messages_thread_id", "tutor_messages", ["thread_id"])
        op.create_index("ix_tutor_messages_course_id", "tutor_messages", ["course_id"])
        op.create_index(
            "ix_tutor_messages_thread_position",
            "tutor_messages",
            ["thread_id", "position"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    existing = _table_names(conn)

    if "tutor_messages" in existing:
        indexes = _index_names(conn, "tutor_messages")
        if "ix_tutor_messages_thread_position" in indexes:
            op.drop_index("ix_tutor_messages_thread_position", table_name="tutor_messages")
        if "ix_tutor_messages_thread_id" in indexes:
            op.drop_index("ix_tutor_messages_thread_id", table_name="tutor_messages")
        if "ix_tutor_messages_course_id" in indexes:
            op.drop_index("ix_tutor_messages_course_id", table_name="tutor_messages")
        op.drop_table("tutor_messages")

    if "tutor_threads" in existing:
        indexes = _index_names(conn, "tutor_threads")
        for name in (
            "ix_tutor_threads_user_course_updated",
            "ix_tutor_threads_lesson_id",
            "ix_tutor_threads_course_id",
            "ix_tutor_threads_user_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="tutor_threads")
        op.drop_table("tutor_threads")

    if _is_postgres():
        postgresql.ENUM(name="tutor_message_status").drop(conn, checkfirst=True)
        postgresql.ENUM(name="tutor_message_role").drop(conn, checkfirst=True)
