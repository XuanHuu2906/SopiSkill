"""Wave 3 / P6.2 tests — Redis distributed rate-limiter, /ready probe, security headers,
controlled activation guardrails, and PostgreSQL backup/restore drill CLI (100% offline).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException, Request

from app.core.activation import check_activation_readiness
from app.core.config import Settings, get_settings
from app.core.limits import (
    clear_rate_limits,
    rate_limit,
    set_redis_client_for_tests,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_request(
    *,
    client_host: str = "10.0.0.1",
    user_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/test",
        "headers": raw_headers,
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    req = Request(scope)
    if user_id is not None:
        req.state.user_id = user_id
    return req


class _FakeSlidingWindowRedis:
    """In-memory emulator of the atomic Lua ZSET sliding-window script for multi-worker tests."""

    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, int]] = {}
        self.ttls: dict[str, int] = {}
        self.eval_calls = 0

    def eval(self, script: str, numkeys: int, key: str, now_ms: int, window_ms: int, limit: int, member: str):
        assert numkeys == 1
        assert "ZREMRANGEBYSCORE" in script
        self.eval_calls += 1
        cutoff = int(now_ms) - int(window_ms)
        entries = self.zsets.setdefault(key, {})
        for m in [k for k, score in entries.items() if score <= cutoff]:
            del entries[m]
        current = len(entries)
        if current >= int(limit):
            oldest = min(entries.values()) if entries else int(now_ms)
            retry_ms = max(1, oldest + int(window_ms) - int(now_ms))
            return [0, current, retry_ms]
        entries[str(member)] = int(now_ms)
        self.ttls[key] = int(window_ms) + 1000
        return [1, current + 1, 0]


class _BrokenRedis:
    def eval(self, *args, **kwargs):
        raise ConnectionError("redis://:super-secret-pass@redis:6379/0 refused")


# ---------- 1. Distributed Redis rate-limiter ----------


def test_redis_rate_limiter_enforces_shared_sliding_window_and_retry_after(monkeypatch):
    clear_rate_limits()
    fake = _FakeSlidingWindowRedis()
    set_redis_client_for_tests(fake)
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")

    now = [1_700_000_000.0]
    monkeypatch.setattr("app.core.limits.time.time", lambda: now[0])

    try:
        req_worker_a = _make_request(user_id="user-1")
        req_worker_b = _make_request(user_id="user-1")

        rate_limit(req_worker_a, "tutor_message", limit=2, window_seconds=10)
        rate_limit(req_worker_b, "tutor_message", limit=2, window_seconds=10)
        assert fake.eval_calls == 2

        with pytest.raises(HTTPException) as exc:
            rate_limit(req_worker_a, "tutor_message", limit=2, window_seconds=10)
        assert exc.value.status_code == 429
        assert exc.value.detail["code"] == "RATE_LIMITED"
        assert int(exc.value.headers["Retry-After"]) >= 1

        # Advancing past the window allows new requests cleanly.
        now[0] += 11.0
        rate_limit(req_worker_b, "tutor_message", limit=2, window_seconds=10)
    finally:
        clear_rate_limits()


def test_redis_rate_limiter_fail_open_falls_back_to_memory_without_leaking_url(monkeypatch, caplog):
    clear_rate_limits()
    set_redis_client_for_tests(_BrokenRedis())
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_fail_closed", False)

    try:
        req = _make_request(client_host="10.1.2.3")
        with caplog.at_level("WARNING"):
            rate_limit(req, "auth_login", limit=1, window_seconds=60)
            with pytest.raises(HTTPException) as exc:
                rate_limit(req, "auth_login", limit=1, window_seconds=60)
        assert exc.value.status_code == 429
        # Secret password in Redis error must never appear in logs.
        assert "super-secret-pass" not in caplog.text
    finally:
        clear_rate_limits()


def test_redis_rate_limiter_fail_closed_returns_503(monkeypatch):
    clear_rate_limits()
    set_redis_client_for_tests(_BrokenRedis())
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "rate_limit_fail_closed", True)

    try:
        req = _make_request(client_host="10.1.2.4")
        with pytest.raises(HTTPException) as exc:
            rate_limit(req, "auth_login", limit=5, window_seconds=60)
        assert exc.value.status_code == 503
        assert exc.value.detail["code"] == "RATE_LIMITER_UNAVAILABLE"
    finally:
        clear_rate_limits()


def test_proxy_headers_ignored_by_default_and_respected_when_trusted(monkeypatch):
    clear_rate_limits()
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")

    try:
        # Default: trust_proxy_headers=False → spoofed X-Forwarded-For cannot bypass IP limit.
        monkeypatch.setattr(settings, "trust_proxy_headers", False)
        r1 = _make_request(client_host="198.51.100.10", headers={"X-Forwarded-For": "1.1.1.1"})
        r2 = _make_request(client_host="198.51.100.10", headers={"X-Forwarded-For": "2.2.2.2"})
        rate_limit(r1, "login_probe", limit=1, window_seconds=60)
        with pytest.raises(HTTPException) as exc:
            rate_limit(r2, "login_probe", limit=1, window_seconds=60)
        assert exc.value.status_code == 429

        # Trusted proxy: distinct X-Forwarded-For IPs get separate buckets.
        clear_rate_limits()
        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        rate_limit(r1, "login_probe", limit=1, window_seconds=60)
        rate_limit(r2, "login_probe", limit=1, window_seconds=60)
    finally:
        clear_rate_limits()


# ---------- 2. Deep readiness probe (/ready) & security headers ----------


@pytest.mark.asyncio
async def test_ready_probe_ok_and_security_headers(client):
    r = await client.get("/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "not_configured"
    assert body["checks"]["config"] == "ok"

    # Baseline security headers present; HSTS omitted in non-HTTPS dev mode.
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in r.headers


@pytest.mark.asyncio
async def test_ready_probe_returns_503_when_database_fails_without_leaking_secrets(client, monkeypatch):
    async def broken_db():
        raise RuntimeError("postgresql://ailp:top-secret-db-pass@db:5432/ailp failed")

    monkeypatch.setattr("app.main._probe_database", broken_db)
    r = await client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "error"
    assert "top-secret-db-pass" not in r.text


@pytest.mark.asyncio
async def test_ready_probe_checks_redis_when_configured(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379/0")

    async def ok_redis(url: str, timeout: float) -> str:
        return "ok"

    monkeypatch.setattr("app.main._probe_redis", ok_redis)
    r_ok = await client.get("/ready")
    assert r_ok.status_code == 200
    assert r_ok.json()["checks"]["redis"] == "ok"

    async def bad_redis(url: str, timeout: float) -> str:
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr("app.main._probe_redis", bad_redis)
    r_bad = await client.get("/ready")
    assert r_bad.status_code == 503
    assert r_bad.json()["checks"]["redis"] == "error"


@pytest.mark.asyncio
async def test_hsts_header_enabled_when_cookie_secure_true(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    r = await client.get("/health")
    assert r.status_code == 200
    assert "max-age=31536000" in (r.headers.get("strict-transport-security") or "")


# ---------- 3. Controlled activation guardrails (Decision D7) ----------


def test_default_settings_keep_wave3_feature_flags_off():
    # Construct fresh Settings ignoring local .env to assert code defaults.
    cfg = Settings(_env_file=None)
    assert cfg.tutor_enabled is False
    assert cfg.p50_enabled is False
    assert cfg.rag_enabled is False
    report = check_activation_readiness(cfg)
    assert report.ok is True
    assert report.errors == []


def test_production_guardrails_block_unsafe_tutor_and_auth_config():
    unsafe_prod = Settings(
        _env_file=None,
        env="production",
        jwt_secret="",
        cookie_secure=False,
        allow_demo_header=True,
        redis_url="",
        llm_provider="openai_compatible",
        tutor_enabled=True,
        tutor_messages_per_day=0,
        tutor_tokens_per_day=0,
        rag_enabled=True,
        embedding_provider="hashing",
    )
    report = check_activation_readiness(unsafe_prod)
    assert report.ok is False
    assert "PROD_JWT_SECRET_MISSING" in report.errors
    assert "PROD_DEMO_HEADER_ENABLED" in report.errors
    assert "PROD_COOKIE_SECURE_FALSE" in report.errors
    assert "PROD_DISTRIBUTED_RATE_LIMIT_REQUIRED" in report.errors
    assert "TUTOR_DAILY_QUOTAS_REQUIRED" in report.errors
    assert "RAG_USING_HASHING_EMBEDDING_BASELINE" in report.warnings


def test_production_guardrails_pass_with_wave3_quotas_and_redis():
    safe_prod = Settings(
        _env_file=None,
        env="production",
        jwt_secret="x" * 48,
        cookie_secure=True,
        allow_demo_header=False,
        redis_url="redis://redis:6379/0",
        rate_limit_backend="redis",
        rate_limit_fail_closed=True,
        llm_provider="openai_compatible",
        tutor_enabled=True,
        tutor_messages_per_day=30,
        tutor_tokens_per_day=100_000,
        p50_enabled=True,
        rag_enabled=False,
    )
    report = check_activation_readiness(safe_prod)
    assert report.ok is True, report.to_dict()
    assert report.errors == []
    assert report.features["distributedRateLimit"] is True
    assert report.features["tutorEnabled"] is True
    assert report.features["p50Enabled"] is True


def test_wave3_compose_override_contract():
    override_path = REPO_ROOT / "docker-compose.wave3.yml"
    assert override_path.is_file()
    data = yaml.safe_load(override_path.read_text(encoding="utf-8"))
    backend_env = data["services"]["backend"]["environment"]
    assert backend_env["RATE_LIMIT_BACKEND"] == "redis"
    assert str(backend_env["RATE_LIMIT_FAIL_CLOSED"]).lower() == "true"
    assert str(backend_env["TUTOR_ENABLED"]).lower() == "true"
    assert "30" in str(backend_env["TUTOR_MESSAGES_PER_DAY"])
    assert "100000" in str(backend_env["TUTOR_TOKENS_PER_DAY"])
    assert str(backend_env["P50_ENABLED"]).lower() == "true"
    assert "false" in str(backend_env["RAG_ENABLED"]).lower()


# ---------- 4. PostgreSQL backup & restore drill CLI ----------


def _load_backup_script():
    script_path = REPO_ROOT / "backend" / "scripts" / "pg_backup_restore.py"
    spec = importlib.util.spec_from_file_location("pg_backup_restore", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_script_parses_asyncpg_url_and_never_puts_password_in_argv():
    mod = _load_backup_script()
    conn = mod.parse_pg_connection(
        database_url="postgresql+asyncpg://ailp:very-secret-pw@db.internal:5433/sopiskill"
    )
    assert conn["host"] == "db.internal"
    assert conn["port"] == "5433"
    assert conn["user"] == "ailp"
    assert conn["dbname"] == "sopiskill"
    assert conn["password"] == "very-secret-pw"

    dump_cmd = mod.build_pg_dump_cmd(conn, Path("/tmp/out.dump"))
    restore_cmd = mod.build_pg_restore_cmd(conn, "ailp_restore_drill", Path("/tmp/out.dump"))
    assert "very-secret-pw" not in " ".join(dump_cmd)
    assert "very-secret-pw" not in " ".join(restore_cmd)


def test_backup_artifacts_verify_and_detect_tampering(tmp_path: Path):
    mod = _load_backup_script()
    dump = tmp_path / "ailp_20261123T000000Z.dump"
    dump.write_bytes(b"PGDMP\x01\x0e\x00dummy-payload")

    meta = mod.write_backup_artifacts(dump, dbname="ailp")
    assert meta["database"] == "ailp"
    assert "password" not in json.dumps(meta).lower()

    verified = mod.verify_backup_file(dump)
    assert verified["ok"] is True
    assert verified["checksumFileVerified"] is True

    # Tamper 1 byte -> verify must fail.
    dump.write_bytes(b"PGDMP\x01\x0e\x00tampered-data")
    with pytest.raises(ValueError, match="SHA-256"):
        mod.verify_backup_file(dump)

    # Non-PGDMP magic -> verify must fail.
    bad_file = tmp_path / "not_a_dump.dump"
    bad_file.write_bytes(b"NOTPGDMP")
    with pytest.raises(ValueError, match="PGDMP"):
        mod.verify_backup_file(bad_file)


def test_restore_drill_blocks_production_db_name_by_default(tmp_path: Path, monkeypatch):
    mod = _load_backup_script()
    dump = tmp_path / "ailp.dump"
    dump.write_bytes(b"PGDMP\x01\x0e\x00ok")
    mod.write_backup_artifacts(dump, dbname="ailp")

    invoked = []
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: invoked.append(a))

    rc = mod.main(["restore-drill", "--backup", str(dump), "--target-db", "ailp"])
    assert rc == 2
    assert invoked == []  # Never executed pg_restore on non-scratch DB!

    assert mod.is_safe_drill_target("ailp_restore_drill") is True
    assert mod.is_safe_drill_target("ailp_scratch") is True
    assert mod.is_safe_drill_target("ailp") is False


def test_restore_drill_happy_path_with_mocked_pg_tools(tmp_path: Path, monkeypatch, capsys):
    mod = _load_backup_script()
    dump = tmp_path / "ailp.dump"
    dump.write_bytes(b"PGDMP\x01\x0e\x00ok")
    mod.write_backup_artifacts(dump, dbname="ailp")

    calls: list[list[str]] = []

    def fake_run(cmd, *, env, capture_output, text):
        calls.append(cmd)
        if cmd[0] == "pg_restore":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "psql":
            return SimpleNamespace(returncode=0, stdout="0017_p1_course_language|27|5|12|89\n", stderr="")
        raise AssertionError(f"Unexpected cmd: {cmd}")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    rc = mod.main(["restore-drill", "--backup", str(dump), "--target-db", "ailp_restore_drill"])
    assert rc == 0
    assert [c[0] for c in calls] == ["pg_restore", "psql"]
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["alembicHead"] == "0017_p1_course_language"
    assert out["tableCount"] == 27
    assert out["lessonsCount"] == 89
