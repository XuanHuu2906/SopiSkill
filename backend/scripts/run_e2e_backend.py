"""Khởi chạy backend FastAPI cục bộ cho Playwright E2E (SQLite throwaway + MockProvider).

Không phụ thuộc Docker Desktop hay PostgreSQL bên ngoài; không gọi API trả phí.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

import uvicorn

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def main() -> None:
    port = int(os.environ.get("E2E_BACKEND_PORT", "8100"))
    frontend_origin = os.environ.get("E2E_FRONTEND_ORIGIN", "http://127.0.0.1:3100")
    db_file = pathlib.Path(tempfile.gettempdir()) / f"sopiskill_playwright_e2e_{port}.db"
    if db_file.exists():
        db_file.unlink()

    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file}"
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["REDIS_URL"] = ""
    os.environ["JWT_SECRET"] = "playwright-e2e-only-not-production-secret"
    os.environ["LESSON_SHUFFLE_SECRET"] = "playwright-e2e-shuffle-secret"
    os.environ["ALLOW_DEMO_HEADER"] = "false"
    os.environ["COOKIE_SECURE"] = "false"
    os.environ["GENERATION_INLINE_BLOCKING"] = "true"
    os.environ["SOURCE_STORAGE_BACKEND"] = "memory"
    os.environ["CORS_ORIGINS"] = f"{frontend_origin},http://localhost:3100"
    os.environ.setdefault("TUTOR_ENABLED", "false")

    from app.db.session import create_all

    asyncio.run(create_all())
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
