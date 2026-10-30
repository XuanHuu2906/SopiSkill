"""P1.1 — quiz integrity: XP attribution per content version + attempt reward ledger

Revision ID: 0003_p11_quiz_integrity
Revises: 0002_auth_columns
Create Date: 2026-10-30

Thay đổi (expand-only, không drop cột nào, dữ liệu cũ giữ nguyên):
  - lesson_attempts.xp_awarded: XP thực sự được cộng cho attempt này. Dùng để
    trả lại đúng reward khi client retry cùng clientAttemptId (idempotent).
  - xp_events.content_version: version nội dung bài học tại thời điểm cộng XP,
    để tính "đã cộng bao nhiêu XP cho (user, lesson, version)" và chặn farm.
  - index hỗ trợ truy vấn XP theo (user, lesson, content_version).

Ghi chú: rows cũ có xp_awarded = 0 (default) và content_version = NULL; không
backfill vì không thể tái dựng chính xác số XP đã cộng cho từng attempt lịch sử.
Downard-recovery chỉ là restore từ backup nếu cần (không khuyến nghị chạy).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_p11_quiz_integrity"
down_revision: Union[str, None] = "0002_auth_columns"
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


def upgrade() -> None:
    conn = op.get_bind()

    if "xp_awarded" not in _columns(conn, "lesson_attempts"):
        op.add_column(
            "lesson_attempts",
            sa.Column("xp_awarded", sa.Integer(), nullable=False, server_default="0"),
        )

    if "content_version" not in _columns(conn, "xp_events"):
        op.add_column("xp_events", sa.Column("content_version", sa.Integer(), nullable=True))

    if "ix_xp_events_lesson_version" not in _index_names(conn, "xp_events"):
        op.create_index(
            "ix_xp_events_lesson_version",
            "xp_events",
            ["user_id", "lesson_id", "content_version"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "ix_xp_events_lesson_version" in _index_names(conn, "xp_events"):
        op.drop_index("ix_xp_events_lesson_version", table_name="xp_events")
    if "content_version" in _columns(conn, "xp_events"):
        op.drop_column("xp_events", "content_version")
    if "xp_awarded" in _columns(conn, "lesson_attempts"):
        op.drop_column("lesson_attempts", "xp_awarded")
