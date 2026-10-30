"""Celery app module cho CLI: `celery -A app.worker.celery_app worker`.

Chỉ tạo app khi REDIS_URL được cấu hình; nếu không, app vẫn tồn tại nhưng
dispatch sẽ chạy inline fallback (xem generation.py).
"""

from app.core.config import get_settings

_settings = get_settings()

if _settings.redis_url:
    from celery import Celery

    celery_app = Celery(
        "ailp",
        broker=_settings.redis_url,
        backend=_settings.redis_url,
        include=["app.worker.generation"],
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        broker_connection_retry_on_startup=True,
    )
else:  # pragma: no cover
    celery_app = None  # type: ignore[assignment]
