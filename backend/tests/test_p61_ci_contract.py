"""P6.1 — CI pipeline contract.

Kiểm chứng *bằng test* rằng file CI và các script gate thật sự tồn tại với nội
dung mong đợi, để việc sửa nhầm (đổi lint về wizard tương tác, bỏ bước
migration, thêm quyền ghi, nhúng secret) làm test đỏ thay vì âm thầm mất gate.
Không chạy CI runner ở đây — chỉ đọc cấu hình.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
FRONTEND_PKG = REPO_ROOT / "frontend" / "package.json"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.is_file(), f"thiếu workflow {WORKFLOW}"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return job.get("steps") or []


def _run_text(steps: list[dict]) -> str:
    return "\n".join(str(s.get("run", "")) for s in steps)


def test_workflow_is_valid_yaml_with_expected_jobs(workflow):
    jobs = workflow["jobs"]
    assert {"backend-tests", "postgres-migrations", "postgres-race", "frontend", "security"} <= set(
        jobs
    )


def test_workflow_runs_on_pull_request_to_main(workflow):
    # `on` có thể bị YAML parse thành True khi không quote — chấp nhận cả hai.
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" in triggers
    assert "main" in (triggers["pull_request"].get("branches") or [])


def test_workflow_has_read_only_token_permissions(workflow):
    assert workflow.get("permissions", {}).get("contents") == "read"
    for name, job in workflow["jobs"].items():
        perms = job.get("permissions")
        if perms is not None:
            assert perms.get("contents") in (None, "read"), name


def test_ci_never_references_repository_secrets(workflow):
    """CI phải chạy được trên PR từ fork: không đọc `secrets.*` nào."""
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in raw


def test_backend_job_runs_the_pytest_suite(workflow):
    steps = _steps(workflow["jobs"]["backend-tests"])
    assert "python -m pytest" in _run_text(steps)
    install = _run_text(steps)
    assert "requirements-dev.txt" in install


def test_migration_job_upgrades_empty_db_and_exercises_downgrade(workflow):
    job = workflow["jobs"]["postgres-migrations"]
    run_text = _run_text(_steps(job))
    assert "alembic upgrade head" in run_text
    assert "alembic downgrade -1" in run_text
    # Phải chạy trên PostgreSQL thật, không phải SQLite.
    assert any(
        svc.get("image", "").startswith("postgres")
        for svc in (job.get("services") or {}).values()
    )


def _job_env(job: dict, workflow: dict) -> dict:
    """env hiệu lực của job: workflow-level rồi job-level rồi step-level."""
    merged: dict = dict(workflow.get("env") or {})
    merged.update(job.get("env") or {})
    for step in _steps(job):
        merged.update(step.get("env") or {})
    return merged


def test_race_job_points_both_database_vars_at_postgresql(workflow):
    """`POSTGRES_TEST_URL` chỉ lái fixture của test.

    Code resolve settings (`SessionLocal`, `llm_usage_service.record_standalone`)
    đọc `DATABASE_URL`; nếu biến đó vẫn là SQLite thì job tên "PostgreSQL" vẫn
    chạy SQLite ở các đường ấy.
    """
    job = workflow["jobs"]["postgres-race"]
    env = _job_env(job, workflow)
    for name in ("POSTGRES_TEST_URL", "DATABASE_URL"):
        assert env.get(name, "").startswith("postgresql"), f"{name}={env.get(name)!r}"
    assert "postgres_concurrency" in _run_text(_steps(job))


def test_race_job_cannot_pass_vacuously(workflow):
    """`pytest` thoát 0 khi mọi test bị skip ⇒ sai tên biến sẽ 'xanh' mà 0 test."""
    steps = _steps(workflow["jobs"]["postgres-race"])
    run_text = _run_text(steps)
    assert "POSTGRES_TEST_URL" in run_text, "phải có bước guard kiểm tra biến môi trường"
    for bad in ("|| true", "--ignore", "-p no:cacheprovider --co"):
        assert bad not in run_text, f"race job chứa {bad!r} — gate có thể pass giả"


def test_no_gate_step_swallows_failures(workflow):
    """`|| true`, `continue-on-error: true` biến gate thành lời khuyên."""
    for name, job in workflow["jobs"].items():
        for step in _steps(job):
            assert step.get("continue-on-error") is not True, f"{name}/{step.get('name')}"
            assert "|| true" not in str(step.get("run", "")), f"{name}/{step.get('name')}"


def test_migration_job_walks_all_the_way_down_to_base(workflow):
    """`history --verbose` chỉ in chuỗi; phải thật sự downgrade hết rồi upgrade lại."""
    run_text = _run_text(_steps(workflow["jobs"]["postgres-migrations"]))
    assert "alembic downgrade base" in run_text
    assert "alembic upgrade head" in run_text
    assert "alembic heads" in run_text, "phải kiểm tra graph chỉ có một head"


def test_eslint_flat_config_dependency_is_declared():
    """`eslint.config.mjs` import `@eslint/eslintrc` trực tiếp.

    Hiện nó chỉ resolve được nhờ eslint kéo theo và npm hoist; khai báo tường
    minh để đổi lockfile/hoisting hoặc chuyển package manager không làm gãy lint.
    """
    pkg = json.loads(FRONTEND_PKG.read_text(encoding="utf-8"))
    assert "@eslint/eslintrc" in pkg["devDependencies"]

    config = (REPO_ROOT / "frontend" / "eslint.config.mjs").read_text(encoding="utf-8")
    if "@eslint/eslintrc" in config:
        assert "@eslint/eslintrc" in pkg["devDependencies"]


def test_frontend_job_runs_lint_typecheck_and_build(workflow):
    steps = _steps(workflow["jobs"]["frontend"])
    run_text = _run_text(steps)
    assert "npm ci" in run_text
    assert "npm run lint" in run_text
    assert "npm run typecheck" in run_text
    assert "npm run build" in run_text


def test_security_job_covers_python_and_node(workflow):
    steps = _steps(workflow["jobs"]["security"])
    run_text = _run_text(steps)
    assert "bandit -r app" in run_text
    assert "pip_audit" in run_text or "pip-audit" in run_text
    assert "npm audit --omit=dev --audit-level=high" in run_text


def test_frontend_lint_script_is_non_interactive_and_strict():
    pkg = json.loads(FRONTEND_PKG.read_text(encoding="utf-8"))
    scripts = pkg["scripts"]
    lint = scripts["lint"]
    assert lint.startswith("eslint"), "`next lint` mở wizard tương tác trong CI"
    assert "--max-warnings=0" in lint, "warning phải chặn merge, không chỉ error"
    assert scripts["typecheck"] == "tsc --noEmit"


def test_next_is_pinned_to_a_patched_15x_release():
    """Next 15.1.6 có advisory RCE/DoS; phải pin >= 15.5.28 và giữ trong major 15."""
    pkg = json.loads(FRONTEND_PKG.read_text(encoding="utf-8"))
    pinned = pkg["dependencies"]["next"]
    assert pinned == pkg["devDependencies"]["eslint-config-next"]
    major, minor, patch = (int(p) for p in pinned.split(".")[:3])
    assert major == 15
    assert (minor, patch) >= (5, 28), f"next {pinned} vẫn dính advisory đã biết"
