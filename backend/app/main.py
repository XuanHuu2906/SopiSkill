import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.auth import router as auth_router
from app.api.v1.learner import router as learner_router
from app.api.v1.research import router as research_router
from app.api.v1.routes import router as v1_router
from app.api.v1.sources import router as sources_router
from app.api.v1.tutor import router as tutor_router
from app.core.activation import check_activation_readiness
from app.core.config import get_settings
from app.db.session import SessionLocal, create_all

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema management:
    #   - Tests (SQLite in-memory) → create_all tiện cho pytest.
    #   - Development với SQLite file → create_all cho tiện dev nhanh.
    #   - Production/PostgreSQL → BẮT BUỘC chạy `alembic upgrade head` trước khi start
    #     (entrypoint docker đã chạy; app không tự đụng schema).
    if settings.database_url.startswith("sqlite"):
        await create_all()
    yield


app = FastAPI(title="AI Learning Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Attach baseline security headers without exposing secrets or breaking SSE/CORS."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    cfg = get_settings()
    if cfg.cookie_secure or (cfg.env or "").strip().lower() == "production":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(auth_router)
app.include_router(v1_router)
app.include_router(sources_router)
app.include_router(research_router)
app.include_router(tutor_router)
app.include_router(learner_router)


async def _probe_database() -> str:
    async with SessionLocal() as db:
        await db.execute(text("SELECT 1"))
    return "ok"


def _probe_redis_sync(redis_url: str, timeout: float) -> str:
    import redis

    client = redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )
    try:
        pong = client.ping()
        return "ok" if pong else "error"
    finally:
        client.close()


async def _probe_redis(redis_url: str, timeout: float) -> str:
    return await asyncio.to_thread(_probe_redis_sync, redis_url, timeout)


@app.get("/health")
async def health() -> dict:
    """Fast liveness probe (không truy cập external dependencies)."""
    cfg = get_settings()
    return {"status": "ok", "env": cfg.env, "provider": cfg.llm_provider}


@app.get("/ready")
async def ready():
    """Deep readiness probe (OPS-005): kiểm tra DB, Redis (nếu cấu hình) và activation guardrails.

    Không bao giờ trả connection string, credentials hay traceback.
    """
    cfg = get_settings()
    timeout = max(0.2, float(cfg.readiness_timeout_seconds or 2.0))
    checks: dict[str, str] = {}
    healthy = True

    # 1. Database (bắt buộc)
    try:
        checks["database"] = await asyncio.wait_for(_probe_database(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — sanitized probe status
        logger.warning("readiness database check failed type=%s", type(exc).__name__)
        checks["database"] = "error"
        healthy = False

    # 2. Redis (bắt buộc nếu REDIS_URL đã được cấu hình)
    redis_url = (cfg.redis_url or "").strip()
    if redis_url:
        try:
            checks["redis"] = await asyncio.wait_for(
                _probe_redis(redis_url, timeout), timeout=timeout + 0.5
            )
            if checks["redis"] != "ok":
                healthy = False
        except Exception as exc:  # noqa: BLE001 — sanitized probe status
            logger.warning("readiness redis check failed type=%s", type(exc).__name__)
            checks["redis"] = "error"
            healthy = False
    else:
        checks["redis"] = "not_configured"

    # 3. Activation & production config invariants
    activation = check_activation_readiness(cfg)
    checks["config"] = "ok" if activation.ok else "invalid"
    if not activation.ok:
        healthy = False

    payload = {
        "status": "ready" if healthy else "not_ready",
        "env": cfg.env,
        "provider": cfg.llm_provider,
        "checks": checks,
        "warnings": activation.warnings,
    }
    if activation.errors:
        payload["errors"] = activation.errors

    if not healthy:
        return JSONResponse(status_code=503, content=payload)
    return payload
