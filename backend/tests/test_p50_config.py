"""P5.0 — cấu hình learner profile/mastery/FSRS có giá trị mặc định an toàn."""

from app.core.config import Settings


def test_p50_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.p50_enabled is False
    assert settings.p50_backfill_enabled is False
    assert settings.mastery_pass_threshold == 0.7
    assert settings.mastery_recency_half_life_days == 30
    assert settings.fsrs_desired_retention == 0.9


def test_p50_enabled_can_be_set(monkeypatch):
    monkeypatch.setenv("P50_ENABLED", "true")
    monkeypatch.setenv("MASTERY_PASS_THRESHOLD", "0.8")
    settings = Settings(_env_file=None)
    assert settings.p50_enabled is True
    assert settings.mastery_pass_threshold == 0.8
