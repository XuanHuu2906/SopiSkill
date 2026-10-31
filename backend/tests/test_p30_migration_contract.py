"""P3.0 migration contract — kiểm tra cấu trúc revision mà không cần DB sống.

Test thật trên PostgreSQL (upgrade/downgrade/legacy row) được ghi trong
`docs/migration-runbook.md` và chạy bằng tay trên DB throwaway. Ở đây kiểm tra:
  - chuỗi revision nối đúng vào 0004;
  - `upgrade`/`downgrade` đều tồn tại (rollback không phải NotImplemented);
  - migration là expand-only với dữ liệu cũ (không drop cột thuộc bảng cũ);
  - metadata `create_all` (đường test/dev SQLite) chứa đủ bảng/cột P3.0.
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401 — đăng ký mapper vào metadata

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0005_p30_source_registry.py"


def _load():
    spec = importlib.util.spec_from_file_location("migration_0005", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p12_head():
    module = _load()
    assert module.revision == "0005_p30_source_registry"
    assert module.down_revision == "0004_p12_job_reliability"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_does_not_drop_existing_columns():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    # Expand-only: upgrade không được drop cột/bảng hiện có.
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    # Downgrade phải dọn đúng phần P3.0 thêm vào.
    assert "drop_column" in source.split("def downgrade()")[1]


def test_metadata_contains_p30_tables_and_grounding_column():
    for table in ("sources", "course_sources", "lesson_citations"):
        assert table in Base.metadata.tables, f"thiếu bảng {table} trong metadata"

    lessons = Base.metadata.tables["lessons"]
    assert "grounding" in lessons.c
    assert lessons.c.grounding.nullable is False

    sources = Base.metadata.tables["sources"]
    for column in (
        "source_type",
        "title",
        "canonical_url",
        "owner_id",
        "visibility",
        "content_hash",
        "verification_status",
        "dedupe_key",
    ):
        assert column in sources.c, f"sources thiếu cột {column}"
    assert any(
        constraint.name == "uq_source_dedupe" for constraint in sources.constraints
    )

    citations = Base.metadata.tables["lesson_citations"]
    for column in (
        "lesson_id",
        "source_id",
        "source_version",
        "chunk_id",
        "page_number",
        "section_anchor",
        "evidence_text",
        "validation_status",
    ):
        assert column in citations.c, f"lesson_citations thiếu cột {column}"

    links = Base.metadata.tables["course_sources"]
    assert any(constraint.name == "uq_course_source" for constraint in links.constraints)
