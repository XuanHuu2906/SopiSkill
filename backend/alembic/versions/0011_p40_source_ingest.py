"""P4.0 — PDF text ingestion & source provenance

Revision ID: 0011_p40_source_ingest
Revises: 0010_p31_tutor_tools
Create Date: 2026-10-31

Phạm vi (expand-only, KHÔNG xóa/sửa dữ liệu hiện có):
  - `source_documents`: trạng thái ingest của một file đã upload (mime, byte size,
    page count, content hash, pipeline version, storage key ngẫu nhiên, lease
    retry bounded, mã lỗi ổn định). Không chứa text.
  - `source_chunks`: đoạn text có provenance (page number, char offsets,
    section anchor, text hash) để P4.1 retrieval/citation đối chiếu thật.
  - enum `source_document_status` = queued | extracting | ready | no_text | failed.
  - UNIQUE(source_id, content_hash, pipeline_version) ⇒ retry/upload lại cùng
    bytes không sinh document hay chunk trùng.
  - Index status/created cho ingest worker + (source_id, page_number) cho
    provenance lookup.

KHÔNG thêm bảng embedding/vector: pgvector và dimension thuộc P4.1 sau benchmark
model (chưa chốt). Không đụng `sources`/`course_sources`/`lesson_citations`.

Rollback (downgrade):
  - drop 3 index + 2 bảng + enum. Việc downgrade MẤT text đã trích và trạng thái
    ingest (không khôi phục từ schema); file gốc trong object storage vẫn còn
    nhưng không còn bản ghi tham chiếu. Backup trước khi downgrade trên DB thật.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_p40_source_ingest"
down_revision: Union[str, None] = "0010_p31_tutor_tools"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_DOCUMENT_STATUS = ("queued", "extracting", "ready", "no_text", "failed")

_ENUM_TYPES = {"source_document_status": SOURCE_DOCUMENT_STATUS}


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


def _enum_exists(conn, name: str) -> bool:
    if not _is_postgres():
        return False
    return conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": name}
    ).first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    existing = _table_names(conn)

    if _is_postgres() and not _enum_exists(conn, "source_document_status"):
        _enum("source_document_status", SOURCE_DOCUMENT_STATUS, create_type=True).create(
            conn, checkfirst=False
        )

    if "source_documents" not in existing:
        op.create_table(
            "source_documents",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "source_id",
                sa.Uuid(),
                sa.ForeignKey("sources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("content_hash", sa.Text(), nullable=False),
            sa.Column("mime", sa.Text(), nullable=False, server_default="application/pdf"),
            sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("pipeline_version", sa.Text(), nullable=False),
            sa.Column(
                "status",
                _enum("source_document_status", SOURCE_DOCUMENT_STATUS, create_type=False),
                nullable=False,
                server_default="queued",
            ),
            sa.Column("original_filename", sa.Text(), nullable=True),
            sa.Column("storage_key", sa.Text(), nullable=False),
            sa.Column("attempts_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_code", sa.Text(), nullable=True),
            sa.Column(
                "error",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            ),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
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
                "source_id", "content_hash", "pipeline_version", name="uq_source_document_version"
            ),
        )

    doc_indexes = _index_names(conn, "source_documents")
    if "ix_source_documents_source_id" not in doc_indexes:
        op.create_index("ix_source_documents_source_id", "source_documents", ["source_id"])
    if "ix_source_documents_status_created" not in doc_indexes:
        op.create_index(
            "ix_source_documents_status_created", "source_documents", ["status", "created_at"]
        )

    if "source_chunks" not in existing:
        op.create_table(
            "source_chunks",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "document_id",
                sa.Uuid(),
                sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                sa.Uuid(),
                sa.ForeignKey("sources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=False),
            sa.Column("char_start", sa.Integer(), nullable=False),
            sa.Column("char_end", sa.Integer(), nullable=False),
            sa.Column("section_anchor", sa.Text(), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("document_id", "chunk_index", name="uq_source_chunk_index"),
        )

    chunk_indexes = _index_names(conn, "source_chunks")
    if "ix_source_chunks_document_id" not in chunk_indexes:
        op.create_index("ix_source_chunks_document_id", "source_chunks", ["document_id"])
    if "ix_source_chunks_source_id" not in chunk_indexes:
        op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])
    if "ix_source_chunks_source_page" not in chunk_indexes:
        op.create_index(
            "ix_source_chunks_source_page", "source_chunks", ["source_id", "page_number"]
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)

    if "source_chunks" in tables:
        for name in (
            "ix_source_chunks_source_page",
            "ix_source_chunks_source_id",
            "ix_source_chunks_document_id",
        ):
            if name in _index_names(conn, "source_chunks"):
                op.drop_index(name, table_name="source_chunks")
        op.drop_table("source_chunks")

    if "source_documents" in tables:
        for name in (
            "ix_source_documents_status_created",
            "ix_source_documents_source_id",
        ):
            if name in _index_names(conn, "source_documents"):
                op.drop_index(name, table_name="source_documents")
        op.drop_table("source_documents")

    if _is_postgres():
        postgresql.ENUM(name="source_document_status").drop(conn, checkfirst=True)
