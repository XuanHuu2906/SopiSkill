"""P3.0 tutor migration contract — kiểm tra revision & metadata không cần DB sống.

Test thật upgrade/downgrade/legacy trên PostgreSQL được ghi trong
`docs/migration-runbook.md`. Ở đây kiểm:
  - chuỗi revision nối đúng vào 0007 (P2.2);
  - upgrade/downgrade đều triển khai (rollback không phải NotImplemented);
  - upgrade là expand-only (không drop cột/bảng cũ);
  - `create_all` (SQLite test/dev) có đủ bảng/cột/constraint của P3.0 tutor;
  - UNIQUE chống duplicate **theo course + clientMessageId + role**.
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401 — đăng ký mapper

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0008_p30_tutor_core.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0008", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p22_head():
    module = _load()
    assert module.revision == "0008_p30_tutor_core"
    assert module.down_revision == "0007_p22_eval_cost"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_migration_does_not_drop_existing_columns():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_column" not in upgrade_body
    assert "drop_table" not in upgrade_body
    assert "drop_table" in source.split("def downgrade()")[1]


def test_metadata_contains_tutor_tables_and_columns():
    for table in ("tutor_threads", "tutor_messages"):
        assert table in Base.metadata.tables, f"thiếu bảng {table} trong metadata"

    threads = Base.metadata.tables["tutor_threads"]
    for column in ("user_id", "course_id", "lesson_id", "title", "message_count"):
        assert column in threads.c, f"tutor_threads thiếu cột {column}"

    messages = Base.metadata.tables["tutor_messages"]
    for column in (
        "thread_id",
        "course_id",
        "position",
        "role",
        "status",
        "content",
        "context_ref",
        "client_message_id",
        "error_code",
        "finish_reason",
    ):
        assert column in messages.c, f"tutor_messages thiếu cột {column}"

    unique = [
        constraint
        for constraint in messages.constraints
        if constraint.name == "uq_tutor_message_client_id"
    ]
    assert unique, "thiếu UNIQUE chống duplicate message"
    columns = {col.name for col in unique[0].columns}
    assert columns == {"course_id", "client_message_id", "role"}, columns
