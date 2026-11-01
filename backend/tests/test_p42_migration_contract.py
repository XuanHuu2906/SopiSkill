"""P4.2 migration contract — chain, expand-only, metadata, downgrade.

Không cần DB sống. Upgrade/downgrade thật trên PostgreSQL được ghi trong
`docs/migration-runbook.md` (temp DB, drop sau khi chạy).
"""

import importlib.util
import pathlib

import app.models  # noqa: F401  (side-effect: đăng ký mapper)
from app.db.base import Base

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0013_p42_web_ingest.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0013", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p41_head():
    module = _load()
    assert module.revision == "0013_p42_web_ingest"
    assert module.down_revision == "0012_p41_rag"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "op.add_column" in upgrade_body
    assert "op.drop_column" in source.split("def downgrade()")[1]


def test_metadata_has_web_origin_columns():
    table = Base.metadata.tables["source_documents"]
    for column in ("origin", "origin_url", "origin_meta", "rights_confirmed_at"):
        assert column in table.c, f"source_documents thiếu cột {column}"
    assert table.c.origin.nullable is False
    assert table.c.origin_url.nullable is True
    assert table.c.rights_confirmed_at.nullable is True


def test_origin_enum_values():
    from app.models import SourceDocumentOrigin

    assert {member.value for member in SourceDocumentOrigin} == {"upload", "web", "arxiv"}


def test_origin_url_index_exists_in_metadata():
    table = Base.metadata.tables["source_documents"]
    index_columns = {tuple(ix.columns.keys()) for ix in table.indexes}
    assert ("source_id", "origin_url") in index_columns


def test_downgrade_does_not_drop_source_tables():
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade()")[1]
    assert "drop_table" not in downgrade_body
