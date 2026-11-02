"""Celery app module cho CLI: `celery -A app.worker.celery_app:celery_app worker|beat`.

Chỉ tạo app khi REDIS_URL được cấu hình; nếu không, dispatch fallback inline
(xem `app.services.job_service.dispatch_job`) — chỉ dùng cho dev/test.

P1.2:
  - `beat_schedule` chạy reconciler `recover_stuck_jobs` định kỳ để gửi lại job
    đã commit DB nhưng chưa tới broker (outbox) và job có lease hết hạn.
  - `task_acks_late` + `worker_prefetch_multiplier=1` (task không idempotent
    tuyệt đối, nhưng claim nguyên tử đảm bảo chỉ một lần chạy thực sự).
  - `visibility_timeout` lớn hơn thời gian generation tối đa để không
    redeliver khi task còn chạy.
"""

from app.core.config import get_settings

_settings = get_settings()

if _settings.redis_url:
    from celery import Celery

    celery_app = Celery(
        "ailp",
        broker=_settings.redis_url,
        backend=_settings.redis_url,
        include=["app.worker.generation", "app.worker.reconcile", "app.worker.ingest"],
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        broker_connection_retry_on_startup=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=int(_settings.generation_lesson_timeout_seconds * 40),
        task_soft_time_limit=int(_settings.generation_lesson_timeout_seconds * 30),
        worker_visibility_timeout=int(_settings.generation_lesson_timeout_seconds * 60),
        beat_schedule={
            "recover-stuck-generation-jobs": {
                "task": "app.worker.reconcile.reconcile_jobs",
                "schedule": float(_settings.generation_reconcile_interval_seconds),
            },
            # P4.0 — ingest là outbox riêng: document queued chưa gửi broker hoặc
            # lease hết hạn cần được worker khác claim lại.
            "recover-stuck-ingest-documents": {
                "task": "app.worker.ingest.reconcile_ingest",
                "schedule": float(_settings.generation_reconcile_interval_seconds),
            },
            # P4.1 — backfill embedding cho chunk thiếu/stale (ingest xong nhưng
            # embedding lỗi tạm thời, hoặc vừa đổi model/version).
            "backfill-chunk-embeddings": {
                "task": "app.worker.ingest.reconcile_embeddings",
                "schedule": float(_settings.generation_reconcile_interval_seconds),
            },
            # P5.0 — backfill skill cho course sinh trước P5.0 (chỉ chạy khi
            # P50_BACKFILL_ENABLED=true; service tự no-op khi tắt).
            "backfill-course-skills": {
                "task": "app.worker.reconcile.reconcile_skills",
                "schedule": float(_settings.generation_reconcile_interval_seconds),
            },
        },
    )
else:  # pragma: no cover
    celery_app = None  # type: ignore[assignment]
