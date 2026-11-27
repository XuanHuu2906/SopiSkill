"""Phase M2 (P2): Grounded Figure Asset Registry (`rag.source_figures`) linked to MinIO objects.

Revision ID: 0003_source_figures_registry
Revises: 0002_public_library_scope_index
Create Date: 2026-11-27
"""

from __future__ import annotations

from alembic import op

revision = "0003_source_figures_registry"
down_revision = "0002_public_library_scope_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS rag.source_figures (
                id VARCHAR(128) PRIMARY KEY,
                owner_id VARCHAR(64) NOT NULL,
                source_id VARCHAR(64) NOT NULL,
                figure_id VARCHAR(64) NOT NULL,
                section_anchor VARCHAR(200),
                page_number INTEGER,
                label VARCHAR(120),
                caption TEXT,
                alt_text TEXT,
                minio_key VARCHAR(512) NOT NULL,
                content_type VARCHAR(64) NOT NULL DEFAULT 'image/webp',
                sha256 VARCHAR(64),
                width INTEGER,
                height INTEGER,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_rag_source_figures_scope UNIQUE (owner_id, source_id, figure_id)
            )
            """
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_source_figures_lookup "
            "ON rag.source_figures (owner_id, source_id, section_anchor)"
        )
    else:
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS source_figures (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                figure_id TEXT NOT NULL,
                section_anchor TEXT,
                page_number INTEGER,
                label TEXT,
                caption TEXT,
                alt_text TEXT,
                minio_key TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'image/webp',
                sha256 TEXT,
                width INTEGER,
                height INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (owner_id, source_id, figure_id)
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS rag.source_figures")
    else:
        op.execute("DROP TABLE IF EXISTS source_figures")
