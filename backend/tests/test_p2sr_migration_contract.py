"""P2.SR migration contract — kiểm tra cấu trúc revision mà không cần DB sống.

Test thật trên PostgreSQL (upgrade/downgrade/legacy row) chạy bằng tay trên DB
throwaway — xem `docs/development-progress.md` (P2.SR).
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401 — đăng ký mapper vào metadata

VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION = VERSIONS / "0006_p2sr_source_research.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p30_head():
    module = _load(MIGRATION, "migration_0006")
    assert module.revision == "0006_p2sr_source_research"
    assert module.down_revision == "0005_p30_source_registry"


def test_upgrade_and_downgrade_are_implemented():
    module = _load(MIGRATION, "migration_0006")
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_p30_migration_is_not_modified():
    module = _load(VERSIONS / "0005_p30_source_registry.py", "migration_0005")
    assert module.down_revision == "0004_p12_job_reliability"
    assert module.revision == "0005_p30_source_registry"


def test_migration_does_not_drop_existing_columns():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    assert "drop_table" in source.split("def downgrade()")[1]


def test_metadata_contains_research_run_table_and_constraints():
    table = Base.metadata.tables["source_research_runs"]
    for column in (
        "id",
        "course_id",
        "user_id",
        "status",
        "topic",
        "domain",
        "adapter",
        "is_mock",
        "request_fingerprint",
        "analysis",
        "sources",
        "warnings",
        "error",
        "insufficient_evidence",
        "tool_calls",
    ):
        assert column in table.c, f"source_research_runs thiếu cột {column}"
    assert any(
        constraint.name == "uq_research_run_fingerprint" for constraint in table.constraints
    )
    assert table.c.course_id.foreign_keys
    assert table.c.user_id.foreign_keys
