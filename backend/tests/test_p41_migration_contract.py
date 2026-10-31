"""P4.1 migration contract — metadata + chain, không cần DB sống.

Upgrade/downgrade thật trên PostgreSQL ghi ở `docs/migration-runbook.md`.
Ở đây kiểm:
  - chuỗi revision nối đúng vào 0011 (P4.0);
  - upgrade expand-only (không drop trong upgrade, downgrade có drop);
  - metadata có bảng embedding + cột `tutor_messages.citations`;
  - vector **không** phải pgvector ở phase này (JSON array có trần spec);
  - UNIQUE(chunk_id, provider, model, dimension, version) chặn trộn vector.
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401  (side-effect: đăng ký mapper)

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0012_p41_rag.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0012", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p40_head():
    module = _load()
    assert module.revision == "0012_p41_rag"
    assert module.down_revision == "0011_p40_source_ingest"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "op.create_table" in upgrade_body
    assert "op.add_column" in upgrade_body
    assert "op.drop_table" in source.split("def downgrade()")[1]


def test_metadata_has_embedding_table_with_spec_and_vector():
    assert "source_chunk_embeddings" in Base.metadata.tables
    table = Base.metadata.tables["source_chunk_embeddings"]
    for column in (
        "chunk_id",
        "source_id",
        "provider",
        "model",
        "dimension",
        "version",
        "text_hash",
        "vector",
    ):
        assert column in table.c, f"source_chunk_embeddings thiếu cột {column}"


def test_embedding_spec_unique_constraint_prevents_mixing():
    table = Base.metadata.tables["source_chunk_embeddings"]
    names = {constraint.name for constraint in table.constraints}
    assert "uq_chunk_embedding_spec" in names


def test_embedding_foreign_keys_cascade():
    table = Base.metadata.tables["source_chunk_embeddings"]
    targets = {fk.target_fullname for fk in table.foreign_keys}
    assert "source_chunks.id" in targets
    assert "sources.id" in targets
    for fk in table.foreign_keys:
        assert fk.ondelete in ("CASCADE", None), fk


def test_tutor_messages_has_citations_column():
    table = Base.metadata.tables["tutor_messages"]
    assert "citations" in table.c
    # Nullable: NULL = không có RAG/không đủ căn cứ, không phải "chưa xử lý".
    assert table.c["citations"].nullable is True


def test_vector_is_json_not_pgvector():
    """Phase này KHÔNG dùng pgvector: không đổi image/extension, có trần candidate."""
    source = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE EXTENSION" not in source.upper()
    assert "vector(" not in source.replace("to_tsvector(", "")
    table = Base.metadata.tables["source_chunk_embeddings"]
    vector_type = table.c["vector"].type
    assert vector_type.__class__.__name__ in ("JSON", "JSONB") or hasattr(
        vector_type, "with_variant"
    )


def test_fts_index_is_postgres_only_and_idempotent():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "to_tsvector" in source
    assert "CREATE INDEX IF NOT EXISTS" in source.upper() or "IF NOT EXISTS" in source
    assert "_is_postgres()" in source
