"""Phase 0 contract drift and invariant tests for contracts/public-api.yaml & contracts/internal-ai.yaml."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONTRACT = REPO_ROOT / "contracts" / "public-api.yaml"
INTERNAL_CONTRACT = REPO_ROOT / "contracts" / "internal-ai.yaml"
EXPORTER_SCRIPT = REPO_ROOT / "backend" / "scripts" / "export_public_openapi.py"


def _load_build_public_openapi():
    spec = importlib.util.spec_from_file_location("export_public_openapi", EXPORTER_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_public_openapi


def test_public_openapi_contract_matches_live_fastapi_without_drift():
    assert PUBLIC_CONTRACT.exists(), "contracts/public-api.yaml must exist"
    committed = yaml.safe_load(PUBLIC_CONTRACT.read_text(encoding="utf-8"))
    generated = _load_build_public_openapi()()

    assert committed["openapi"] == "3.1.0"
    assert sorted(committed["paths"].keys()) == sorted(generated["paths"].keys())
    assert committed == generated, (
        "contracts/public-api.yaml drifted from live FastAPI routes/schemas. "
        "Re-run: cd backend && .venv/bin/python scripts/export_public_openapi.py"
    )


def test_public_openapi_contract_declares_security_and_sse_invariants():
    doc = yaml.safe_load(PUBLIC_CONTRACT.read_text(encoding="utf-8"))
    schemes = doc["components"]["securitySchemes"]
    assert "AccessCookieAuth" in schemes
    assert schemes["AccessCookieAuth"]["in"] == "cookie"
    assert schemes["AccessCookieAuth"]["name"] == "access_token"
    assert "CsrfHeaderAuth" in schemes
    assert schemes["CsrfHeaderAuth"]["in"] == "header"
    assert schemes["CsrfHeaderAuth"]["name"] == "X-CSRF-Token"

    # All 7 routers must be represented (including P2.SR research-runs)
    paths = doc["paths"]
    for required_path in [
        "/health",
        "/ready",
        "/v1/auth/login",
        "/v1/me/stats",
        "/v1/courses",
        "/v1/courses/{course_id}/proposal",
        "/v1/courses/{course_id}/glossary",
        "/v1/courses/{course_id}/research-runs",
        "/v1/courses/{course_id}/tutor/messages",
        "/v1/lessons/{lesson_id}",
        "/v1/lessons/{lesson_id}/blocks/{block_index}/grade",
        "/v1/reviews/due",
        "/v1/sources",
    ]:
        assert required_path in paths, f"Missing frozen route: {required_path}"

    tutor_post = paths["/v1/courses/{course_id}/tutor/messages"]["post"]
    assert "text/event-stream" in tutor_post["responses"]["200"]["content"]
    headers = tutor_post["responses"]["200"]["headers"]
    assert "X-Tutor-Thread-Id" in headers
    assert "X-Tutor-Message-Id" in headers
    assert "X-Accel-Buffering" in headers


def test_internal_ai_contract_declares_hmac_replay_streams_and_zero_answer_keys():
    assert INTERNAL_CONTRACT.exists(), "contracts/internal-ai.yaml must exist"
    doc = yaml.safe_load(INTERNAL_CONTRACT.read_text(encoding="utf-8"))

    assert doc["openapi"] == "3.1.0"

    # Security schemes: constant-time service token + HMAC timestamp replay + correlation ID
    schemes = doc["components"]["securitySchemes"]
    assert schemes["InternalServiceToken"]["name"] == "X-Internal-Service-Token"
    assert schemes["InternalTimestamp"]["name"] == "X-Internal-Timestamp"
    assert schemes["InternalHmacSignature"]["name"] == "X-Internal-Signature"
    assert schemes["CorrelationId"]["name"] == "X-Correlation-Id"

    replay = doc["x-replay-protection"]
    assert replay["algorithm"] == "HMAC-SHA256"
    assert replay["constantTimeComparisonRequired"] is True
    assert 60 <= replay["maxClockSkewSeconds"] <= 600

    # Redis Streams contract for KEDA workers
    streams = doc["x-redis-streams"]["streams"]
    assert "queue:ai:llm" in streams
    assert "queue:ai:ingest" in streams
    assert streams["queue:ai:llm"]["producer"] == "core-api"
    assert streams["queue:ai:ingest"]["producer"] == "core-api"

    # Required internal endpoints & callbacks
    paths = doc["paths"]
    for required_path in [
        "/ready",
        "/internal/interview/questions",
        "/internal/interview/evaluate",
        "/internal/lessons/grade-short",
        "/internal/tutor/stream",
        "/internal/rag/search",
        "/internal/rag/users/{userId}",
        "/internal/jobs/{jobId}/complete",
        "/internal/jobs/{jobId}/lesson-ready",
        "/internal/sources/{sourceId}/complete",
    ]:
        assert required_path in paths, f"Missing internal contract route: {required_path}"

    # Answer-key privacy invariant on Tutor stream request schema
    tutor_req = doc["components"]["schemas"]["TutorStreamInternalRequest"]
    assert tutor_req.get("additionalProperties") is False
    lesson_ctx = tutor_req["properties"]["lessonContext"]
    assert "publicBlocks" in lesson_ctx["properties"]
    for forbidden in ("answerIndex", "acceptedAnswers", "answer_key", "solution"):
        assert forbidden not in lesson_ctx["properties"]
        assert forbidden not in tutor_req["properties"]
