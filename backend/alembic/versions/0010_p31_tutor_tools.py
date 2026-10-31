"""P3.1 lát B — Tutor tool audit

Revision ID: 0010_p31_tutor_tools
Revises: 0009_p31_tutor_controls
Create Date: 2026-10-31

Phạm vi (expand-only, chỉ thêm bảng mới):
  - Bảng `tutor_tool_calls`: audit metadata mỗi lần model đề xuất/được chạy một
    tool read-only (tên, ok, duration, summary do server dựng, error code).
  - Index theo `message_id` (xem toàn bộ tool của một lượt trả lời) và `created_at`
    (audit theo thời gian).
  - FK tới `users`/`courses`/`tutor_messages`; xóa message kéo theo audit của nó.

KHÔNG lưu nội dung tool trả về, prompt hay câu trả lời người học: nội dung đó chỉ
đi vào prompt của lượt hỏi hiện tại và không được nhân bản vào DB.

Downgrade: drop 2 index + bảng. Mất audit tool (không khôi phục từ schema);
thread/message/course/lesson không bị đụng.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_p31_tutor_tools"
down_revision: Union[str, None] = "0009_p31_tutor_controls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    if "tutor_tool_calls" in _table_names(conn):
        return

    op.create_table(
        "tutor_tool_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("tutor_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_tutor_tool_calls_user_id", "tutor_tool_calls", ["user_id"])
    op.create_index("ix_tutor_tool_calls_course_id", "tutor_tool_calls", ["course_id"])
    op.create_index(
        "ix_tutor_tool_calls_message_id", "tutor_tool_calls", ["message_id"]
    )
    op.create_index(
        "ix_tutor_tool_calls_created_at", "tutor_tool_calls", ["created_at"]
    )


def downgrade() -> None:
    conn = op.get_bind()
    if "tutor_tool_calls" not in _table_names(conn):
        return
    indexes = _index_names(conn, "tutor_tool_calls")
    for name in (
        "ix_tutor_tool_calls_created_at",
        "ix_tutor_tool_calls_message_id",
        "ix_tutor_tool_calls_course_id",
        "ix_tutor_tool_calls_user_id",
    ):
        if name in indexes:
            op.drop_index(name, table_name="tutor_tool_calls")
    op.drop_table("tutor_tool_calls")
