"""P4.0 ingest migration contract — metadata + chain, không cần DB sống.

Upgrade/downgrade thật trên PostgreSQL ghi ở `docs/migration-runbook.md`.
Ở đây kiểm:
  - chuỗi revision nối đúng vào 0010 (P3.1 lát B);
  - upgrade chỉ thêm bảng/index/enum (expand-only), downgrade có thật;
  - metadata (dùng cho SQLite `create_all`) có đủ bảng/cột/index/unique;
  - KHÔNG có bảng/cột embedding hay text trong `source_documents` (P4.1).
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401  (side-effect: đăng ký mapper)

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0011_p40_source_ingest.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0011", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p31b_head():
    module = _load()
    assert module.revision == "0011_p40_source_ingest"
    assert module.down_revision == "0010_p31_tutor_tools"


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
    assert "drop_table" in source.split("def downgrade()")[1]


def test_metadata_has_document_and_chunk_tables():
    assert "source_documents" in Base.metadata.tables
    assert "source_chunks" in Base.metadata.tables

    documents = Base.metadata.tables["source_documents"]
    for column in (
        "source_id",
        "content_hash",
        "mime",
        "byte_size",
        "page_count",
        "pipeline_version",
        "status",
        "original_filename",
        "storage_key",
        "attempts_count",
        "max_attempts",
        "lease_expires_at",
        "dispatched_at",
        "error_code",
        "ingested_at",
    ):
        assert column in documents.c, f"source_documents thiếu cột {column}"

    chunks = Base.metadata.tables["source_chunks"]
    for column in (
        "document_id",
        "source_id",
        "chunk_index",
        "page_number",
        "char_start",
        "char_end",
        "section_anchor",
        "text",
        "text_hash",
    ):
        assert column in chunks.c, f"source_chunks thiếu cột {column}"


def test_document_idempotency_unique_constraint():
    documents = Base.metadata.tables["source_documents"]
    names = {c.name for c in documents.constraints}
    assert "uq_source_document_version" in names
    assert "uq_source_chunk_index" in {c.name for c in Base.metadata.tables["source_chunks"].constraints}


def test_indexes_present_for_ingest_and_lookup():
    document_indexes = {ix.name for ix in Base.metadata.tables["source_documents"].indexes}
    for name in ("ix_source_documents_source_id", "ix_source_documents_status_created"):
        assert name in document_indexes, f"thiếu index {name}"

    chunk_indexes = {ix.name for ix in Base.metadata.tables["source_chunks"].indexes}
    for name in (
        "ix_source_chunks_document_id",
        "ix_source_chunks_source_id",
        "ix_source_chunks_source_page",
    ):
        assert name in chunk_indexes, f"thiếu index {name}"


def test_no_embedding_or_vector_columns_in_p40():
    """pgvector/dimension thuộc P4.1 sau benchmark — không được lén thêm ở P4.0."""
    for table_name in ("source_documents", "source_chunks"):
        table = Base.metadata.tables[table_name]
        for column in table.c:
            assert column.name not in ("embedding", "embedding_model", "vector"), (
                f"{table_name}.{column.name} thuộc P4.1, chưa được thêm"
            )


def test_documents_table_stores_no_raw_text():
    documents = Base.metadata.tables["source_documents"]
    for forbidden in ("text", "content", "raw_text", "extracted_text"):
        assert forbidden not in documents.c, f"source_documents không được chứa '{forbidden}'"


def test_foreign_keys_cascade():
    documents = Base.metadata.tables["source_documents"]
    targets = {fk.target_fullname for fk in documents.foreign_keys}
    assert "sources.id" in targets

    chunks = Base.metadata.tables["source_chunks"]
    chunk_targets = {fk.target_fullname for fk in chunks.foreign_keys}
    assert "source_documents.id" in chunk_targets
    assert "sources.id" in chunk_targets
