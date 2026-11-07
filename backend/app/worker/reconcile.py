"""Reconciler task — outbox dispatch + lease expiry recovery (P1.2).

Chạy định kỳ bởi Celery beat. Nhiệm vụ:
  - Gửi lại job đã commit DB nhưng broker không nhận (`dispatched_at IS NULL`
    sau grace period) → không để job kẹt `queued` vĩnh viễn.
  - Requeue job `running` có lease hết hạn (worker chết) → worker khác claim.
  - Job vượt số lần dispatch tối đa → `failed` với mã `DISPATCH_EXHAUSTED`.

An toàn: dùng engine riêng mỗi lần chạy (event loop riêng của Celery task) và
chỉ UPDATE trên trạng thái an toàn; không đụng job `ready/failed`.
"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


async def _run_reconcile_async(limit: int = 20) -> list[str]:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.services import job_service

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            recovered = await job_service.recover_stuck_jobs(db, limit=limit)
            if recovered:
                logger.info("reconciler recovered jobs count=%s", len(recovered))
            return [str(job_id) for job_id in recovered]
    finally:
        await engine.dispose()


def _celery_app():
    from app.worker import generation

    return generation.get_celery_app()


_app = _celery_app()

if _app is not None:

    @_app.task(name="app.worker.reconcile.reconcile_jobs", bind=True, max_retries=0)
    def reconcile_jobs(self, limit: int = 20):  # noqa: ANN001
        return asyncio.run(_run_reconcile_async(limit))


def reconcile_now(limit: int = 20) -> list[uuid.UUID]:
    """Entry point đồng bộ cho test/CLI (không cần Celery)."""
    return [uuid.UUID(x) for x in asyncio.run(_run_reconcile_async(limit))]


async def _run_skills_backfill_async() -> int:
    """P5.0 — backfill skill cho course cũ chưa có `lesson_skills`.

    Chỉ chạy khi `P50_BACKFILL_ENABLED=true`; service tự no-op khi tắt.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.services import learner_profile_service

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with Session() as db:
            written = await learner_profile_service.backfill_all_skills(db)
            if written:
                logger.info("reconciler backfilled skill links count=%s", written)
            return written
    finally:
        await engine.dispose()


if _app is not None:

    @_app.task(name="app.worker.reconcile.reconcile_skills", bind=True, max_retries=0)
    def reconcile_skills(self):  # noqa: ANN001
        return asyncio.run(_run_skills_backfill_async())
