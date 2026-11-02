"""P5.2 migration contract — chain, expand-only, names, metadata. Không cần DB sống."""

import importlib.util
import pathlib

import app.models  # noqa: F401  (side-effect: đăng ký mapper)
from app.db.base import Base

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0016_p52_exposure.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("migration_0016", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p50_head():
    module = _load()
    assert module.revision == "0016_p52_exposure"
    assert module.down_revision == "0015_p50_learner_profile"


def test_upgrade_is_expand_only_and_has_no_raw_ddl():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body
    assert "op.execute" not in upgrade_body
    assert "_has_table('courses')" in upgrade_body or '_has_table("courses")' in upgrade_body


def test_model_registered_with_exact_names():
    assert "recommendation_events" in Base.metadata.tables
    table = Base.metadata.tables["recommendation_events"]
    names = {c.name for c in table.constraints}
    assert "uq_recommendation_event_context" in names
    assert "ix_recommendation_events_course" in {i.name for i in table.indexes}
    assert "ix_recommendation_events_user" in {i.name for i in table.indexes}


def test_arm_id_is_not_nullable():
    table = Base.metadata.tables["recommendation_events"]
    assert table.c.arm_id.nullable is False
    assert table.c.lesson_content_version.nullable is False
    assert table.c.propensity.nullable is False
    assert table.c.context_hash.nullable is False


def test_id_prefix_parses_exposure_id():
    from app.services import course_service

    uid = "12345678-1234-5678-1234-567812345678"
    assert course_service.parse_prefixed_uuid(f"rce_{uid}") is not None
