"""P4.2 — web/arXiv source documents: origin, canonical URL, rights audit

Revision ID: 0013_p42_web_ingest
Revises: 0012_p41_rag
Create Date: 2026-11-01

Phạm vi (EXPAND-ONLY, không xóa/không sửa dữ liệu đã có):
  - enum `source_document_origin` = upload | web | arxiv.
  - `source_documents.origin` (NOT NULL, default `upload`) — document P4.0 hiện
    hữu được gán `upload` qua server_default rồi mới bỏ default? KHÔNG: giữ
    server_default để mọi insert cũ (worker/test cũ) tiếp tục hợp lệ.
  - `source_documents.origin_url` (nullable) — URL canonical đã fetch; bằng
    chứng citation trỏ nguồn thực.
  - `source_documents.origin_meta` (JSONB/JSON, nullable) — metadata arXiv đã
    kiểm (id/version/authors/categories) — KHÔNG chứa nội dung tài liệu.
  - `source_documents.rights_confirmed_at` (nullable) — audit xác nhận quyền
    sử dụng của người dùng; NULL = chưa xác nhận.
  - index `ix_source_documents_origin_url(source_id, origin_url)` để tra
    document theo URL (idempotency/UX).

Rollback (downgrade): drop index + 4 cột + enum. KHÔNG xóa `source_documents`
hay `source_chunks`; document web đã ingest vẫn còn nhưng mất thông tin origin
⇒ downgrade làm citation URL không còn. Backup trước trên DB thật.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_p42_web_ingest"
down_revision: Union[str, None] = "0012_p41_rag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

ORIGIN_VALUES = ("upload", "web", "arxiv")
INDEX_NAME = "ix_source_documents_origin_url"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _inspector():
    from sqlalchemy import inspect

    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _column_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {col["name"] for col in _inspector().get_columns(table)}


def _index_names(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {ix["name"] for ix in _inspector().get_indexes(table)}


def _enum_exists(name: str) -> bool:
    if not _is_postgres():
        return False
    return (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": name})
        .first()
        is not None
    )


def _origin_enum(*, create_type: bool) -> sa.Enum:
    if _is_postgres():
        return postgresql.ENUM(*ORIGIN_VALUES, name="source_document_origin", create_type=create_type)
    return sa.Enum(*ORIGIN_VALUES, name="source_document_origin")


def upgrade() -> None:
    if not _has_table("source_documents"):
        raise RuntimeError(
            "source_documents chưa tồn tại — cần chạy 0011_p40_source_ingest trước."
        )

    if _is_postgres() and not _enum_exists("source_document_origin"):
        _origin_enum(create_type=True).create(op.get_bind(), checkfirst=True)

    columns = _column_names("source_documents")
    if "origin" not in columns:
        op.add_column(
            "source_documents",
            sa.Column(
                "origin",
                _origin_enum(create_type=False),
                nullable=False,
                server_default="upload",
            ),
        )
    if "origin_url" not in columns:
        op.add_column("source_documents", sa.Column("origin_url", sa.Text(), nullable=True))
    if "origin_meta" not in columns:
        op.add_column(
            "source_documents", sa.Column("origin_meta", JSONVariant, nullable=True)
        )
    if "rights_confirmed_at" not in columns:
        op.add_column(
            "source_documents",
            sa.Column("rights_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )

    if INDEX_NAME not in _index_names("source_documents"):
        op.create_index(
            INDEX_NAME, "source_documents", ["source_id", "origin_url"]
        )


def downgrade() -> None:
    if not _has_table("source_documents"):
        return

    if INDEX_NAME in _index_names("source_documents"):
        op.drop_index(INDEX_NAME, table_name="source_documents")

    columns = _column_names("source_documents")
    for name in ("rights_confirmed_at", "origin_meta", "origin_url", "origin"):
        if name in columns:
            op.drop_column("source_documents", name)

    if _is_postgres() and _enum_exists("source_document_origin"):
        postgresql.ENUM(name="source_document_origin").drop(op.get_bind(), checkfirst=True)
