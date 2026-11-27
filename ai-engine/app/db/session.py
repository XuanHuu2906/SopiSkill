"""Async SQLAlchemy engine & session factory scoped to `rag.*`."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    if _session_factory is None:
        raise RuntimeError("Database session factory failed to initialize.")
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def ensure_sqlite_tables() -> None:
    """Create lightweight SQLite table for offline unit tests (PostgreSQL uses Alembic)."""
    engine = get_engine()
    if engine.dialect.name != "sqlite":
        return
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    course_id TEXT,
                    source_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    source_title TEXT,
                    chunk_index INTEGER NOT NULL,
                    page_number INTEGER,
                    section_anchor TEXT,
                    content TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_version TEXT NOT NULL,
                    embedding_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS source_figures (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    figure_id TEXT NOT NULL,
                    section_anchor TEXT,
                    page_number INTEGER,
                    label TEXT,
                    caption TEXT,
                    alt_text TEXT,
                    minio_key TEXT NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'image/webp',
                    sha256 TEXT,
                    width INTEGER,
                    height INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (owner_id, source_id, figure_id)
                )
                """
            )
        )


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
