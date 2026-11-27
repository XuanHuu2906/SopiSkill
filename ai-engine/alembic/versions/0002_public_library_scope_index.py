"""Add partial index for shared curated public library chunks (`owner_id = 'system:public_library'`).

Revision ID: 0002_public_library_scope_index
Revises: 0001_init_rag_schema
Create Date: 2026-11-27
"""

from __future__ import annotations

from alembic import op

revision = "0002_public_library_scope_index"
down_revision = "0001_init_rag_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_public_source "
            "ON rag.document_chunks (source_id) "
            "WHERE owner_id = 'system:public_library'"
        )
    else:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_public_source "
            "ON document_chunks (owner_id, source_id)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS rag.ix_rag_chunks_public_source")
    else:
        op.execute("DROP INDEX IF EXISTS ix_rag_chunks_public_source")
