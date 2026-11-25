"""P1-LANG — Add course language column (`vi` | `en`)

Revision ID: 0017_p1_course_language
Revises: 0016_p52_exposure
Create Date: 2026-11-22

Phạm vi (EXPAND-ONLY, không sửa/xoá bảng hay cột cũ):
  - Thêm cột `courses.language VARCHAR(16) NOT NULL DEFAULT 'vi'` để truyền ngôn ngữ
    khóa học xuyên suốt interview → proposal → lesson → tutor.
  - Dữ liệu khóa học cũ mặc định giữ `'vi'` (tương thích ngược hoàn toàn).

Rollback (downgrade): chỉ drop cột `courses.language`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_p1_course_language"
down_revision: Union[str, None] = "0016_p52_exposure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(op.get_bind())
    if not inspector.has_table(table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("courses", "language"):
        op.add_column(
            "courses",
            sa.Column(
                "language",
                sa.String(length=16),
                nullable=False,
                server_default="vi",
            ),
        )


def downgrade() -> None:
    if _has_column("courses", "language"):
        op.drop_column("courses", "language")
