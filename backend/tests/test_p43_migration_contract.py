"""P4.3 migration contract — chain, expand-only, metadata, downgrade.

Không cần DB sống. Upgrade/downgrade thật trên PostgreSQL được chạy bằng
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
    / "0014_p43_ocr.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0014", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p42_head():
    module = _load()
    assert module.revision == "0014_p43_ocr"
    assert module.down_revision == "0013_p42_web_ingest"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body
    assert "op.add_column" in upgrade_body
    assert "op.drop_column" in source.split("def downgrade()")[1]


def test_document_metadata_has_ocr_provenance_columns():
    table = Base.metadata.tables["source_documents"]
    for column in ("text_source", "ocr_pages", "ocr_engine", "ocr_version"):
        assert column in table.c, f"source_documents thiếu cột {column}"
    assert table.c.text_source.nullable is True
    assert table.c.ocr_pages.nullable is False
    assert table.c.ocr_engine.nullable is True
    assert table.c.ocr_version.nullable is True


def test_chunk_metadata_has_ocr_provenance_columns():
    table = Base.metadata.tables["source_chunks"]
    for column in ("text_source", "ocr_confidence", "ocr_bbox"):
        assert column in table.c, f"source_chunks thiếu cột {column}"
    assert table.c.text_source.nullable is True
    assert table.c.ocr_confidence.nullable is True
    assert table.c.ocr_bbox.nullable is True


def test_downgrade_drops_only_new_columns():
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade_body = source.split("def downgrade()")[1]
    assert "drop_table" not in downgrade_body
    assert "source_chunks" in downgrade_body
    assert "source_documents" in downgrade_body


def test_ocr_is_opt_in_by_default():
    """Bật OCR mặc định sẽ đổi trạng thái PDF scan của mọi deployment — không được."""
    import os

    from app.core.config import Settings

    # Tạo Settings sạch, bỏ qua .env để đọc đúng default của class.
    clean = Settings(**{k: v for k, v in os.environ.items() if not k.startswith("OCR_")})
    assert clean.ocr_enabled is False
    assert clean.ocr_engine == "rapidocr"
    assert clean.ocr_configured is False
