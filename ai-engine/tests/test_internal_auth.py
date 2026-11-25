"""Security tests for InternalAuthMiddleware: constant-time token + HMAC-SHA256 replay protection."""

from __future__ import annotations

import json
import time

from app.core.config import get_settings
from app.core.internal_auth import HEADER_CORRELATION, HEADER_SERVICE_AUTH, HEADER_SIGNATURE, HEADER_TIMESTAMP, sign_internal_headers
from tests.conftest import signed_json_request


async def test_ready_probe_accessible_without_internal_token(ai_client):
    resp = await ai_client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["providers"] == "ok"
    assert HEADER_CORRELATION in resp.headers


async def test_rejects_missing_or_wrong_token_with_401(ai_client):
    payload = {"courseId": "crs_1", "topic": "SQL", "language": "en"}

    r_missing = await ai_client.post("/internal/interview/questions", json=payload)
    assert r_missing.status_code == 401
    assert r_missing.json()["code"] == "INTERNAL_AUTH_INVALID"

    raw, headers = signed_json_request("POST", "/internal/interview/questions", payload)
    headers[HEADER_SERVICE_AUTH] = "wrong-token"
    r_wrong = await ai_client.post("/internal/interview/questions", content=raw, headers=headers)
    assert r_wrong.status_code == 401
    assert r_wrong.json()["code"] == "INTERNAL_AUTH_INVALID"


async def test_rejects_expired_timestamp_and_tampered_body_with_401(ai_client):
    payload = {"courseId": "crs_1", "topic": "SQL", "language": "en"}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    # 1. Expired timestamp (outside ±300s replay window)
    old_headers = sign_internal_headers(
        method="POST",
        path_with_query="/internal/interview/questions",
        raw_body=raw,
        settings=get_settings(),
        timestamp=int(time.time()) - 900,
    )
    old_headers["Content-Type"] = "application/json"
    r_old = await ai_client.post("/internal/interview/questions", content=raw, headers=old_headers)
    assert r_old.status_code == 401
    assert r_old.json()["code"] == "INTERNAL_TIMESTAMP_EXPIRED"

    # 2. Tampered body after signing
    valid_raw, valid_headers = signed_json_request("POST", "/internal/interview/questions", payload)
    tampered_raw = valid_raw.replace(b"SQL", b"HACK")
    r_tampered = await ai_client.post("/internal/interview/questions", content=tampered_raw, headers=valid_headers)
    assert r_tampered.status_code == 401
    assert r_tampered.json()["code"] == "INTERNAL_SIGNATURE_INVALID"

    # 3. Missing signature header
    no_sig_headers = dict(valid_headers)
    no_sig_headers.pop(HEADER_SIGNATURE)
    r_nosig = await ai_client.post("/internal/interview/questions", content=valid_raw, headers=no_sig_headers)
    assert r_nosig.status_code == 401
    assert r_nosig.json()["code"] == "INTERNAL_SIGNATURE_INVALID"

    # 4. Non-integer timestamp
    bad_ts_headers = dict(valid_headers)
    bad_ts_headers[HEADER_TIMESTAMP] = "not-an-epoch"
    r_badts = await ai_client.post("/internal/interview/questions", content=valid_raw, headers=bad_ts_headers)
    assert r_badts.status_code == 401
    assert r_badts.json()["code"] == "INTERNAL_TIMESTAMP_INVALID"


async def test_accepts_valid_signed_request_and_echoes_correlation_id(ai_client):
    payload = {"courseId": "crs_1", "topic": "Python", "language": "en"}
    raw, headers = signed_json_request(
        "POST", "/internal/interview/questions", payload, correlation_id="cor_trace_999"
    )
    resp = await ai_client.post("/internal/interview/questions", content=raw, headers=headers)
    assert resp.status_code == 200
    assert resp.headers[HEADER_CORRELATION] == "cor_trace_999"
    assert len(resp.json()["questions"]) == 5
