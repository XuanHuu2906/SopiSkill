"""Wave 4 (P1-GLOSSARY) — Add course_glossary_terms table.

Revision ID: 0018_wave4_glossary
Revises: 0017_p1_course_language
Create Date: 2026-11-23

Phạm vi (EXPAND-ONLY, không sửa/xoá bảng hay cột cũ):
  - Thêm bảng `course_glossary_terms` lưu thuật ngữ rút trích từ `teach` blocks
    của từng bài học trong khóa học (`UNIQUE(course_id, term_key)`).

Rollback (downgrade): drop bảng `course_glossary_terms`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_wave4_glossary"
down_revision: Union[str, None] = "0017_p1_course_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    from sqlalchemy import inspect

    return inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has_table("course_glossary_terms"):
        op.create_table(
            "course_glossary_terms",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("course_id", sa.Uuid(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lesson_id", sa.Uuid(), sa.ForeignKey("lessons.id", ondelete="SET NULL"), nullable=True),
            sa.Column("term_key", sa.String(length=120), nullable=False),
            sa.Column("term", sa.Text(), nullable=False),
            sa.Column("definition", sa.Text(), nullable=False),
            sa.Column("example", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("course_id", "term_key", name="uq_course_glossary_term_key"),
        )
        op.create_index("ix_course_glossary_terms_course_id", "course_glossary_terms", ["course_id"])
        op.create_index("ix_course_glossary_terms_lesson_id", "course_glossary_terms", ["lesson_id"])


def downgrade() -> None:
    if _has_table("course_glossary_terms"):
        op.drop_index("ix_course_glossary_terms_lesson_id", table_name="course_glossary_terms")
        op.drop_index("ix_course_glossary_terms_course_id", table_name="course_glossary_terms")
        op.drop_table("course_glossary_terms")
