"""auth columns — thêm email + password_hash (nullable, backward-compatible với DB cũ tạo bằng create_all)

Revision ID: 0002_auth_columns
Revises: 0001_initial
Create Date: 2026-10-30

An toàn cho dữ liệu cũ:
  - Chỉ ADD COLUMN nullable → không mất dữ liệu, không khóa bảng lớn.
  - external_id cũ (demo user "xxx") giữ nguyên; email có thể NULL.
  - Migration này được viết để chạy idempotent trên DB ĐÃ có schema tạo bằng
    create_all(): chỉ thêm 2 cột, mọi thứ còn lại đã trùng khớp 0001
    (đã xác minh bằng information_schema trước khi chạy — xem development-progress).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_auth_columns"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_columns(conn) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table("users"):
        return set()
    return {col["name"] for col in insp.get_columns("users")}


def _has_unique_constraint(conn, name: str) -> bool:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table("users"):
        return False
    for uq in insp.get_unique_constraints("users"):
        if uq.get("name") == name:
            return True
    return False


def upgrade() -> None:
    conn = op.get_bind()
    existing = _users_columns(conn)
    # DB tạo bằng create_all() trước thời điểm auth đã có sẵn 2 cột này → bỏ qua.
    added_email = "email" not in existing
    added_hash = "password_hash" not in existing
    if added_email:
        op.add_column("users", sa.Column("email", sa.Text(), nullable=True))
    if added_hash:
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))
    if not _has_unique_constraint(conn, "uq_users_email"):
        if conn.dialect.name == "sqlite":
            # SQLite không hỗ trợ ALTER ADD CONSTRAINT → batch copy-and-move.
            with op.batch_alter_table("users") as batch:
                batch.create_unique_constraint("uq_users_email", ["email"])
        else:
            op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"
    if _has_unique_constraint(conn, "uq_users_email"):
        if is_sqlite:
            with op.batch_alter_table("users") as batch:
                batch.drop_constraint("uq_users_email", type_="unique")
        else:
            op.drop_constraint("uq_users_email", "users", type_="unique")
    existing = _users_columns(conn)
    if "password_hash" in existing:
        op.drop_column("users", "password_hash")
    if "email" in existing:
        op.drop_column("users", "email")
