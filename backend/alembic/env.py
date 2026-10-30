"""Alembic environment — hỗ trợ sync (migration chạy offline/online) với URL async.

URL async (postgresql+asyncpg) được chuyển sang sync driver (psycopg/aiosqlite)
để alembic chạy được mà không cần greenlet contexts.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from app.db.base import Base

# Import models để Base.metadata được populate. Không có import này thì
# autogenerate coi DB là "thừa toàn bộ bảng" và sinh migration drop hết.
import app.models  # noqa: E402,F401  (side-effect: đăng ký mapper)

config = context.config

target_metadata = Base.metadata

# Ghi chú: model dùng JSON().with_variant(JSONB, "postgresql") và Enum native,
# nên autogenerate trên PostgreSQL so sánh được trực tiếp. Các server_default
# viết tay trong revision cũ (vd. 'Learner') có thể hiện khác biệt cosmetic —
# review trước khi tạo revision mới, không tin autogenerate mù quáng.


def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./ailp.db")
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
