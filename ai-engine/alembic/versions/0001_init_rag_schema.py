"""Initialize `rag` schema with pgvector HNSW + PostgreSQL FTS GIN indexes.

Revision ID: 0001_init_rag_schema
Revises: None
Create Date: 2026-11-25
"""

from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

revision = "0001_init_rag_schema"
down_revision = None
branch_labels = None
depends_on = None

EMBED_DIM = int(os.environ.get("EMBEDDING_DIMENSION", "256"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE SCHEMA IF NOT EXISTS rag")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS rag.document_chunks (
                id VARCHAR(64) PRIMARY KEY,
                owner_id VARCHAR(128) NOT NULL,
                course_id VARCHAR(128),
                source_id VARCHAR(128) NOT NULL,
                document_id VARCHAR(128) NOT NULL,
                source_title VARCHAR(300),
                chunk_index INTEGER NOT NULL,
                page_number INTEGER,
                section_anchor VARCHAR(200),
                content TEXT NOT NULL,
                embedding_provider VARCHAR(64) NOT NULL,
                embedding_model VARCHAR(128) NOT NULL,
                embedding_version VARCHAR(32) NOT NULL,
                embedding vector({EMBED_DIM}),
                tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_owner_course "
            "ON rag.document_chunks (owner_id, course_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_source "
            "ON rag.document_chunks (source_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_document "
            "ON rag.document_chunks (document_id)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_tsv_gin "
            "ON rag.document_chunks USING GIN (tsv)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw "
            "ON rag.document_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    else:
        # SQLite fallback for offline unit tests
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("owner_id", sa.String(128), nullable=False),
            sa.Column("course_id", sa.String(128), nullable=True),
            sa.Column("source_id", sa.String(128), nullable=False),
            sa.Column("document_id", sa.String(128), nullable=False),
            sa.Column("source_title", sa.String(300), nullable=True),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("section_anchor", sa.String(200), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding_provider", sa.String(64), nullable=False),
            sa.Column("embedding_model", sa.String(128), nullable=False),
            sa.Column("embedding_version", sa.String(32), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_embedding_hnsw")
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_tsv_gin")
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_document")
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_source")
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_owner_course")
        op.execute("DROP TABLE IF EXISTS rag.document_chunks")
    else:
        op.drop_table("document_chunks")
