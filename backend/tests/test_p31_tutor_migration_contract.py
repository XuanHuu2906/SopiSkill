"""P3.1 tutor controls migration contract — metadata + chain, không cần DB sống.

Test upgrade/downgrade thật trên PostgreSQL được ghi ở `docs/migration-runbook.md`.
Ở đây kiểm:
  - chuỗi revision nối đúng vào 0008 (P3.0 tutor);
  - upgrade là expand-only (không drop cột/bảng cũ), downgrade có thật;
  - metadata (dùng cho SQLite `create_all`) có cột/bảng/index của P3.1;
  - `tutor_usage_events` không có cột nội dung (prompt/answer).
"""

import importlib.util
import pathlib

from app.db.base import Base
import app.models  # noqa: F401 — đăng ký mapper

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0009_p31_tutor_controls.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0009", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p30_tutor_head():
    module = _load()
    assert module.revision == "0009_p31_tutor_controls"
    assert module.down_revision == "0008_p30_tutor_core"


def test_upgrade_and_downgrade_are_implemented():
    module = _load()
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    downgrade_body = source.split("def downgrade()")[1]
    assert "drop_table" in downgrade_body
    assert "drop_column" in downgrade_body


def test_metadata_has_cancel_flag_and_status_index():
    messages = Base.metadata.tables["tutor_messages"]
    assert "cancel_requested_at" in messages.c
    assert messages.c["cancel_requested_at"].nullable is True
    indexes = {ix.name for ix in messages.indexes}
    assert "ix_tutor_messages_status" in indexes


def test_metadata_has_tutor_usage_events_without_content():
    assert "tutor_usage_events" in Base.metadata.tables
    usage = Base.metadata.tables["tutor_usage_events"]
    for column in (
        "user_id",
        "course_id",
        "message_id",
        "provider",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "finish_reason",
        "created_at",
    ):
        assert column in usage.c, f"tutor_usage_events thiếu cột {column}"
    # Metadata-only: không được có cột chứa prompt/câu trả lời/nội dung sinh ra.
    for forbidden in ("prompt", "content", "answer", "messages"):
        assert forbidden not in usage.c, f"usage event không được lưu '{forbidden}'"

    indexes = {ix.name for ix in usage.indexes}
    assert "ix_tutor_usage_events_user_created" in indexes
