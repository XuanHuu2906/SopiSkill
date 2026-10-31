"""P3.1 lát B tool-audit migration contract — metadata + chain, không cần DB sống.

Upgrade/downgrade thật trên PostgreSQL được ghi ở `docs/migration-runbook.md`.
Ở đây kiểm:
  - chuỗi revision nối đúng vào 0009 (P3.1 lát A);
  - upgrade chỉ thêm bảng/index (expand-only), downgrade có thật;
  - metadata (dùng cho SQLite `create_all`) có bảng + cột + index;
  - bảng audit **không** có cột nội dung/prompt/args thô.
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401 — đăng ký mapper

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0010_p31_tutor_tools.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0010", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p31a_head():
    module = _load()
    assert module.revision == "0010_p31_tutor_tools"
    assert module.down_revision == "0009_p31_tutor_controls"


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


def test_metadata_has_tool_audit_table_and_indexes():
    assert "tutor_tool_calls" in Base.metadata.tables
    table = Base.metadata.tables["tutor_tool_calls"]
    for column in (
        "user_id",
        "course_id",
        "message_id",
        "name",
        "ok",
        "duration_ms",
        "summary",
        "error_code",
        "created_at",
    ):
        assert column in table.c, f"tutor_tool_calls thiếu cột {column}"

    indexes = {ix.name for ix in table.indexes}
    for name in (
        "ix_tutor_tool_calls_user_id",
        "ix_tutor_tool_calls_course_id",
        "ix_tutor_tool_calls_message_id",
        "ix_tutor_tool_calls_created_at",
    ):
        assert name in indexes, f"thiếu index {name}"

    # FK tới message để audit luôn truy được về lượt trả lời tương ứng.
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert "tutor_messages.id" in fk_targets


def test_audit_table_stores_no_content_or_raw_args():
    table = Base.metadata.tables["tutor_tool_calls"]
    for forbidden in ("content", "prompt", "args", "tool_result", "answer"):
        assert forbidden not in table.c, f"audit không được lưu '{forbidden}'"
