from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.research import router as research_router
from app.api.v1.routes import router as v1_router
from app.api.v1.sources import router as sources_router
from app.api.v1.tutor import router as tutor_router
from app.core.config import get_settings
from app.db.session import create_all

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

app.include_router(auth_router)
app.include_router(v1_router)
app.include_router(sources_router)
app.include_router(research_router)
app.include_router(tutor_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.env, "provider": settings.llm_provider}
