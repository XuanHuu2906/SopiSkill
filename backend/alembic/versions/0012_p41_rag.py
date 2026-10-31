"""P4.1 — chunk embeddings, tutor citations, retrieval-friendly indexes

Revision ID: 0012_p41_rag
Revises: 0011_p40_source_ingest
Create Date: 2026-10-31

Phạm vi (EXPAND-ONLY, không xóa/không sửa dữ liệu đã có):
  - `source_chunk_embeddings`: vector của chunk theo MỘT spec
    (provider+model+dimension+version), UNIQUE(chunk_id, provider, model,
    dimension, version). Vector lưu JSON array để portable PostgreSQL + SQLite;
    **KHÔNG dùng pgvector** ở phase này (xem docs/specs/20-P41-HYBRID-RAG.md).
  - `tutor_messages.citations`: citation đã verify server-side cho câu trả lời
    (NULL = không có RAG/không đủ căn cứ — KHÔNG phải "chưa xử lý").
  - Index `ix_source_chunks_text_hash` để phát hiện chunk đổi nội dung khi
    re-embed; `ix_chunk_embeddings_source` để filter ownership ở SQL.

Index FTS cho PostgreSQL (`to_tsvector('simple', text)`) được tạo bằng raw SQL
có kiểm tra dialect: SQLite (dev/test) bỏ qua vì dùng token-overlap trong Python.
Expression index không tạo được bằng `op.create_index` nên dùng `sa.text` với
`IF NOT EXISTS` — idempotent, an toàn khi chạy lại.

Rollback (downgrade): drop FTS index + 3 index + bảng embeddings + cột
`citations`. MẤT vector đã tính và citation đã lưu; nội dung gốc (`sources`,
`source_documents`, `source_chunks`, `tutor_messages.content`) KHÔNG bị đụng.
Re-embed/re-retrieve khôi phục được nhưng có chi phí; backup trước trên DB thật.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_p41_rag"
down_revision: Union[str, None] = "0011_p40_source_ingest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

FTS_INDEX = "ix_source_chunks_fts_simple"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _table_names(conn) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(conn).get_table_names())


def _index_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def _column_names(conn, table: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(conn)
    if not insp.has_table(table):
        return set()
    return {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    existing = _table_names(conn)

    # ---- tutor_messages.citations (expand-only, nullable) ----
    if "tutor_messages" in existing and "citations" not in _column_names(conn, "tutor_messages"):
        op.add_column(
            "tutor_messages", sa.Column("citations", JSONVariant, nullable=True)
        )

    # ---- source_chunks: index theo text_hash để phát hiện chunk stale ----
    chunk_indexes = _index_names(conn, "source_chunks")
    if "source_chunks" in existing and "ix_source_chunks_text_hash" not in chunk_indexes:
        op.create_index("ix_source_chunks_text_hash", "source_chunks", ["text_hash"])

    # ---- source_chunk_embeddings ----
    if "source_chunk_embeddings" not in existing:
        op.create_table(
            "source_chunk_embeddings",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "chunk_id",
                sa.Uuid(),
                sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "source_id",
                sa.Uuid(),
                sa.ForeignKey("sources.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("model", sa.Text(), nullable=False),
            sa.Column("dimension", sa.Integer(), nullable=False),
            sa.Column("version", sa.Text(), nullable=False),
            sa.Column("text_hash", sa.Text(), nullable=False),
            sa.Column("vector", JSONVariant, nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "chunk_id",
                "provider",
                "model",
                "dimension",
                "version",
                name="uq_chunk_embedding_spec",
            ),
        )

    emb_indexes = _index_names(conn, "source_chunk_embeddings")
    for name, cols in (
        ("ix_source_chunk_embeddings_chunk_id", ["chunk_id"]),
        ("ix_source_chunk_embeddings_source_id", ["source_id"]),
        ("ix_chunk_embeddings_spec", ["provider", "model", "dimension", "version"]),
    ):
        if name not in emb_indexes:
            op.create_index(name, "source_chunk_embeddings", cols)

    # ---- PostgreSQL FTS expression index (lexical retrieval) ----
    if _is_postgres() and "source_chunks" in existing:
        conn.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {FTS_INDEX} ON source_chunks "
                "USING gin (to_tsvector('simple', text))"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _is_postgres():
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {FTS_INDEX}"))

    if "source_chunk_embeddings" in _table_names(conn):
        for name in (
            "ix_chunk_embeddings_spec",
            "ix_source_chunk_embeddings_source_id",
            "ix_source_chunk_embeddings_chunk_id",
        ):
            if name in _index_names(conn, "source_chunk_embeddings"):
                op.drop_index(name, table_name="source_chunk_embeddings")
        op.drop_table("source_chunk_embeddings")

    if "source_chunks" in _table_names(conn):
        if "ix_source_chunks_text_hash" in _index_names(conn, "source_chunks"):
            op.drop_index("ix_source_chunks_text_hash", table_name="source_chunks")

    if "tutor_messages" in _table_names(conn) and "citations" in _column_names(
        conn, "tutor_messages"
    ):
        with op.batch_alter_table("tutor_messages") as batch:
            batch.drop_column("citations")
