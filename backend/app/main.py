from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.db.session import create_all

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.include_router(v1_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": settings.env, "provider": settings.llm_provider}
