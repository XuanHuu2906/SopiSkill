"""Export and enrich SopiSkill's live FastAPI OpenAPI 3.1 contract to contracts/public-api.yaml.

Usage:
    cd backend && .venv/bin/python scripts/export_public_openapi.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

PUBLIC_CONTRACT_PATH = REPO_ROOT / "contracts" / "public-api.yaml"

PUBLIC_NO_AUTH_ROUTES: set[tuple[str, str]] = {
    ("/health", "get"),
    ("/ready", "get"),
    ("/v1/auth/register", "post"),
    ("/v1/auth/login", "post"),
}

MUTATING_METHODS = {"post", "put", "patch", "delete"}


def build_public_openapi() -> dict[str, Any]:
    """Return enriched OpenAPI 3.1 document derived directly from live FastAPI routes."""
    schema = copy.deepcopy(app.openapi())

    schema["info"] = {
        "title": "SopiSkill Public API",
        "version": "1.0.0-wave4-baseline",
        "description": (
            "Frozen Phase 0 public HTTP/SSE API contract between frontend (Next.js 15) "
            "and core-api (Spring Boot 3.4+ cutover target, parity 100% with Wave 4 backend). "
            "Authentication uses HttpOnly JWT cookie (`access_token`) plus double-submit CSRF "
            "(`csrf_token` cookie matched against `X-CSRF-Token` header on mutating routes). "
            "All quiz grading is strictly server-authoritative: GET /v1/lessons/{lesson_id} "
            "never exposes answer keys."
        ),
        "x-contract-freeze": {
            "phase": "phase-0",
            "baseline": "wave-4",
            "compatibilityPolicy": "strict-parity-through-phase-2-additive-only-from-phase-3",
        },
    }

    components = schema.setdefault("components", {})
    components["securitySchemes"] = {
        "AccessCookieAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "access_token",
            "description": "HttpOnly SameSite=Lax JWT access token issued by /v1/auth/login or /v1/auth/register.",
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Optional Bearer JWT fallback for non-browser CLI/tests.",
        },
        "CsrfHeaderAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-CSRF-Token",
            "description": "Double-submit CSRF token matching the non-HttpOnly `csrf_token` cookie on mutating requests.",
        },
    }

    schemas = components.setdefault("schemas", {})
    schemas.setdefault(
        "ErrorDetail",
        {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string", "examples": ["NOT_AUTHENTICATED", "CSRF_INVALID", "RATE_LIMITED"]},
                "message": {"type": "string"},
                "currentVersion": {"type": "integer"},
                "details": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": True,
        },
    )
    schemas.setdefault(
        "ErrorEnvelope",
        {
            "type": "object",
            "required": ["detail"],
            "properties": {
                "detail": {
                    "oneOf": [
                        {"$ref": "#/components/schemas/ErrorDetail"},
                        {"type": "string"},
                    ]
                }
            },
        },
    )
    schemas.setdefault(
        "TutorSseEvent",
        {
            "type": "object",
            "description": (
                "Server-Sent Event payload emitted by POST /v1/courses/{course_id}/tutor/messages. "
                "Each SSE frame follows `id: <stream_id>:<seq>\\nevent: <kind>\\ndata: <single-line JSON>\\n\\n`."
            ),
            "required": ["event", "data"],
            "properties": {
                "id": {"type": "string", "examples": ["tmsg_abc123:1"]},
                "event": {
                    "type": "string",
                    "enum": ["delta", "tool", "citations", "done", "cancelled", "error", "heartbeat"],
                },
                "data": {
                    "type": "object",
                    "properties": {
                        "messageId": {"type": "string"},
                        "threadId": {"type": "string"},
                        "text": {"type": "string"},
                        "name": {"type": "string"},
                        "status": {"type": "string"},
                        "summary": {"type": "string"},
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "citations": {"type": "array", "items": {"type": "object"}},
                        "unverified": {"type": "array", "items": {"type": "object"}},
                        "insufficientEvidence": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
            },
        },
    )

    paths = schema.get("paths", {})
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            if not isinstance(op, dict):
                continue

            key = (path, method.lower())
            if key in PUBLIC_NO_AUTH_ROUTES:
                op["security"] = []
            elif path == "/v1/auth/logout":
                op["security"] = [{"CsrfHeaderAuth": []}]
            elif method.lower() in MUTATING_METHODS:
                op["security"] = [
                    {"AccessCookieAuth": [], "CsrfHeaderAuth": []},
                    {"BearerAuth": [], "CsrfHeaderAuth": []},
                ]
            else:
                op["security"] = [
                    {"AccessCookieAuth": []},
                    {"BearerAuth": []},
                ]

            responses = op.setdefault("responses", {})
            if key not in PUBLIC_NO_AUTH_ROUTES and path != "/v1/auth/logout":
                responses.setdefault(
                    "401",
                    {
                        "description": "Unauthorized (missing or invalid session JWT)",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )
            if method.lower() in MUTATING_METHODS and key not in PUBLIC_NO_AUTH_ROUTES:
                responses.setdefault(
                    "403",
                    {
                        "description": "Forbidden (invalid or missing CSRF token)",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )

            if path == "/v1/courses/{course_id}/tutor/messages" and method.lower() == "post":
                responses["200"] = {
                    "description": "SSE stream of TutorSseEvent frames (`delta`, `tool`, `citations`, `done`, `cancelled`, `error`, `heartbeat`).",
                    "headers": {
                        "X-Tutor-Thread-Id": {
                            "description": "Resolved tutor thread identifier.",
                            "schema": {"type": "string"},
                        },
                        "X-Tutor-Message-Id": {
                            "description": "Assistant message identifier for stop/correlation.",
                            "schema": {"type": "string"},
                        },
                        "X-Accel-Buffering": {
                            "description": "Disabled (`no`) to prevent reverse-proxy buffering of SSE frames.",
                            "schema": {"type": "string", "enum": ["no"]},
                        },
                    },
                    "content": {
                        "text/event-stream": {
                            "schema": {"$ref": "#/components/schemas/TutorSseEvent"}
                        }
                    },
                }

    # Normalize ordering deterministically for clean diffs.
    schema["paths"] = {k: paths[k] for k in sorted(paths.keys())}
    components["schemas"] = {k: schemas[k] for k in sorted(schemas.keys())}
    return schema


def serialize_openapi_yaml(document: dict[str, Any]) -> str:
    header = (
        "# AUTO-GENERATED FROM LIVE FASTAPI APP + CONTRACT ENRICHMENTS (Phase 0 Freeze)\n"
        "# Regenerate via: cd backend && .venv/bin/python scripts/export_public_openapi.py\n"
        "# Verified by: backend/tests/test_contracts_openapi.py\n"
    )
    body = yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )
    return header + body


def main() -> None:
    doc = build_public_openapi()
    PUBLIC_CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_CONTRACT_PATH.write_text(serialize_openapi_yaml(doc), encoding="utf-8", newline="\n")
    print(
        f"Wrote {PUBLIC_CONTRACT_PATH} "
        f"({len(doc['paths'])} paths, {len(doc['components']['schemas'])} schemas)"
    )


if __name__ == "__main__":
    main()
