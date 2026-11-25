"""FastAPI entrypoint for `ai-api` (internal ClusterIP service)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.agents.providers import ProviderConfigError, get_llm_provider
from app.api.internal import router as internal_router
from app.core.config import get_settings
from app.core.internal_auth import InternalAuthMiddleware
from app.db.session import dispose_engine, ensure_sqlite_tables, get_session_factory
from app.rag.embedding import EmbeddingConfigError, get_embedding_provider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await ensure_sqlite_tables()
    yield
    await dispose_engine()


app = FastAPI(
    title="SopiSkill AI Engine (Internal)",
    version="1.0.0-phase1",
    lifespan=lifespan,
)
app.add_middleware(InternalAuthMiddleware)
app.include_router(internal_router)


async def _probe_db() -> str:
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))
    return "ok"


async def _probe_redis(redis_url: str, timeout: float) -> str:
    client = Redis.from_url(redis_url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        pong = await client.ping()
        return "ok" if pong else "error"
    finally:
        await client.aclose()


@app.get("/health")
async def health() -> dict:
    cfg = get_settings()
    return {"status": "ok", "service": cfg.service_name, "provider": cfg.llm_provider}


@app.get("/ready")
async def ready():
    cfg = get_settings()
    timeout = max(0.2, float(cfg.readiness_timeout_seconds))
    checks: dict[str, str] = {}
    healthy = True

    try:
        checks["database"] = await asyncio.wait_for(_probe_db(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — sanitized probe status
        logger.warning("ai_ready_db_failed type=%s", type(exc).__name__)
        checks["database"] = "error"
        healthy = False

    redis_url = (cfg.redis_url or "").strip()
    if redis_url:
        try:
            checks["redis"] = await asyncio.wait_for(_probe_redis(redis_url, timeout), timeout=timeout + 0.5)
            if checks["redis"] != "ok":
                healthy = False
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_ready_redis_failed type=%s", type(exc).__name__)
            checks["redis"] = "error"
            healthy = False
    else:
        checks["redis"] = "not_configured"

    try:
        get_llm_provider(cfg)
        get_embedding_provider(cfg)
        checks["providers"] = "ok"
    except (ProviderConfigError, EmbeddingConfigError):
        checks["providers"] = "invalid"
        healthy = False

    payload = {
        "status": "ready" if healthy else "not_ready",
        "provider": cfg.llm_provider,
        "checks": checks,
    }
    if not healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload
