"""P5.0 migration contract — chain, expand-only, metadata. Không cần DB sống."""

import importlib.util
import pathlib

import app.models  # noqa: F401  (side-effect: đăng ký mapper)
from app.db.base import Base

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0015_p50_learner_profile.py"
)

NEW_TABLES = {"skills", "lesson_skills", "skill_mastery", "review_cards", "review_events"}


def _load():
    spec = importlib.util.spec_from_file_location("migration_0015", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain_links_to_p43_head():
    module = _load()
    assert module.revision == "0015_p50_learner_profile"
    assert module.down_revision == "0014_p43_ocr"


def test_upgrade_is_expand_only():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade() -> None:")[1].split("def downgrade()")[0]
    assert "drop_table" not in upgrade_body
    assert "drop_column" not in upgrade_body
    assert "alter_column" not in upgrade_body


def test_models_are_registered():
    assert NEW_TABLES <= set(Base.metadata.tables)


def test_required_unique_constraints():
    skills = Base.metadata.tables["skills"]
    assert "uq_skill_course_key" in {c.name for c in skills.constraints}

    cards = Base.metadata.tables["review_cards"]
    assert "uq_review_card_user_lesson" in {c.name for c in cards.constraints}

    events = Base.metadata.tables["review_events"]
    assert "uq_review_event_client_id" in {c.name for c in events.constraints}


def test_review_cards_have_due_index():
    cards = Base.metadata.tables["review_cards"]
    assert "ix_review_cards_user_due" in {i.name for i in cards.indexes}
