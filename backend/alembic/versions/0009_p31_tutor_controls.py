"""P3.1 — Tutor controls: cancel flag, usage allowance, status index

Revision ID: 0009_p31_tutor_controls
Revises: 0008_p30_tutor_core
Create Date: 2026-10-31

Phạm vi (expand-only, không drop/sửa dữ liệu cũ):
  - `tutor_messages.cancel_requested_at` (nullable): cờ stop do client yêu cầu.
    NULL = chưa ai yêu cầu dừng. Rows cũ hiển nhiên là NULL — không cần backfill.
  - Index `ix_tutor_messages_status` để đếm stream đang chạy và dọn message mồ
    côi mà không scan toàn bảng.
  - Bảng `tutor_usage_events`: metadata từng lượt gọi provider của tutor
    (provider/model/token/latency/finish_reason). KHÔNG lưu prompt hay nội dung.

Không thêm cột NOT NULL, không đổi kiểu cột cũ ⇒ upgrade an toàn trên DB đang có
dữ liệu. Token NULL nghĩa là "provider không báo", không phải 0.

Downgrade: trả cột + index + bảng mới về trạng thái 0008. Mất lịch sử usage của
tutor (không khôi phục được từ schema); thread/message/course không bị đụng.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_p31_tutor_controls"
down_revision: Union[str, None] = "0008_p30_tutor_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def _index_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def upgrade() -> None:
    conn = op.get_bind()

    if "cancel_requested_at" not in _columns(conn, "tutor_messages"):
        op.add_column(
            "tutor_messages",
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "ix_tutor_messages_status" not in _index_names(conn, "tutor_messages"):
        op.create_index("ix_tutor_messages_status", "tutor_messages", ["status"])

    if "tutor_usage_events" not in _table_names(conn):
        op.create_table(
            "tutor_usage_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column(
                "course_id", sa.Uuid(), sa.ForeignKey("courses.id"), nullable=True
            ),
            sa.Column(
                "message_id", sa.Uuid(), sa.ForeignKey("tutor_messages.id"), nullable=True
            ),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("finish_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_tutor_usage_events_user_id", "tutor_usage_events", ["user_id"]
        )
        op.create_index(
            "ix_tutor_usage_events_user_created",
            "tutor_usage_events",
            ["user_id", "created_at"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if "tutor_usage_events" in _table_names(conn):
        indexes = _index_names(conn, "tutor_usage_events")
        for name in (
            "ix_tutor_usage_events_user_created",
            "ix_tutor_usage_events_user_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="tutor_usage_events")
        op.drop_table("tutor_usage_events")

    if "ix_tutor_messages_status" in _index_names(conn, "tutor_messages"):
        op.drop_index("ix_tutor_messages_status", table_name="tutor_messages")

    if "cancel_requested_at" in _columns(conn, "tutor_messages"):
        op.drop_column("tutor_messages", "cancel_requested_at")
