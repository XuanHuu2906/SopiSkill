"""Job reliability service — atomic claim, lease/heartbeat, dispatch outbox.

State machine (P1.2):

    queued ──claim(atomic UPDATE ... RETURNING)──> running ──> ready
      ▲                                              │
      └──────── requeue (transient, bounded) ◄───────┤
                                                     └──> failed (fatal / hết lượt)

Bất biến quan trọng:
  - **Chỉ một worker** giữ lease của một job tại một thời điểm (claim là
    `UPDATE ... WHERE status='queued' OR lease hết hạn`, không phải check-then-set).
  - `dispatched_at IS NULL` = cam kết DB đã commit nhưng broker chưa nhận →
    reconciler sẽ gửi lại (outbox pattern), không bỏ job kẹt `queued` vĩnh viễn.
  - Mỗi bước ghi lesson phải giữ được lease (`heartbeat`); mất lease → dừng,
    không ghi đè kết quả của job/worker khác.
  - Retry bounded bởi `max_attempts` + backoff, không vòng lặp vô hạn.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Course, CourseStatus, GenerationJob, JobStatus

logger = logging.getLogger(__name__)

TASK_NAME = "app.worker.generation.run_generation_task"

# Lỗi "tạm thời" → cho phép requeue có giới hạn. Lỗi schema/nghiệp vụ → fatal.
TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _lease_deadline(seconds: int | None = None) -> datetime:
    seconds = seconds or get_settings().generation_lease_seconds
    return _now() + timedelta(seconds=seconds)


def classify_error(exc: BaseException) -> tuple[str, bool]:
    """Trả (error_code, retryable) — code ngắn, không chứa nội dung người dùng.

    Provider tự khai báo `code`/`retryable` (taxonomy P2.0) nên worker không cần
    biết chi tiết từng SDK.
    """
    from app.providers import ProviderError

    if isinstance(exc, ProviderError):
        return exc.code, bool(exc.retryable)
    if isinstance(exc, TRANSIENT_EXCEPTIONS):
        return "PROVIDER_TIMEOUT" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "TRANSIENT_ERROR", True
    message = str(exc)
    # P2.2 — vượt trần token/chi phí của job: retry chỉ đốt thêm tiền ⇒ fatal.
    if message.startswith("BUDGET_EXCEEDED"):
        return "BUDGET_EXCEEDED", False
    if message.startswith("NO_PROPOSAL"):
        return "NO_PROPOSAL", False
    if message.startswith("LEASE_LOST"):
        return "LEASE_LOST", False
    if message.startswith("SUPERSEDED"):
        return "SUPERSEDED", False
    return "GENERATION_FAILED", True


async def claim_job(db: AsyncSession, job_id: uuid.UUID) -> GenerationJob | None:
    """Claim nguyên tử. Trả job nếu claim được, None nếu không (đã chạy/đã xong/hết lượt)."""
    now = _now()
    lease = _lease_deadline()
    result = await db.execute(
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status.in_((JobStatus.queued, JobStatus.running)),
            or_(
                GenerationJob.status == JobStatus.queued,
                GenerationJob.lease_expires_at.is_(None),
                GenerationJob.lease_expires_at < now,
            ),
            GenerationJob.attempts_count < GenerationJob.max_attempts,
        )
        .values(
            status=JobStatus.running,
            lease_expires_at=lease,
            heartbeat_at=now,
            attempts_count=GenerationJob.attempts_count + 1,
        )
        .returning(GenerationJob.id)
    )
    claimed_id = result.scalar_one_or_none()
    if claimed_id is None:
        await db.rollback()
        return None
    await db.commit()
    return (
        await db.execute(select(GenerationJob).where(GenerationJob.id == claimed_id))
    ).scalar_one()


async def renew_lease(db: AsyncSession, job_id: uuid.UUID) -> bool:
    """Heartbeat + gia hạn lease. False = đã mất job (worker khác chiếm/đã kết thúc)."""
    result = await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.running)
        .values(heartbeat_at=_now(), lease_expires_at=_lease_deadline())
        .returning(GenerationJob.id)
    )
    return result.scalar_one_or_none() is not None


async def is_superseded(db: AsyncSession, job: GenerationJob) -> bool:
    """Có job mới hơn cho cùng course (đã queued/running) ⇒ job này không được ghi kết quả."""
    newer = await db.execute(
        select(GenerationJob.id)
        .where(
            GenerationJob.course_id == job.course_id,
            GenerationJob.id != job.id,
            GenerationJob.created_at > job.created_at,
        )
        .limit(1)
    )
    return newer.scalar_one_or_none() is not None


async def finish_ready(db: AsyncSession, job_id: uuid.UUID, course_id: uuid.UUID) -> None:
    await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.status == JobStatus.running)
        .values(
            status=JobStatus.ready,
            stage="done",
            lease_expires_at=None,
            heartbeat_at=_now(),
            last_error_code=None,
            error=None,
        )
    )
    await db.execute(
        update(Course)
        .where(Course.id == course_id)
        .values(status=CourseStatus.ready)
    )
    await db.commit()


async def fail_or_requeue(
    db: AsyncSession,
    job_id: uuid.UUID,
    course_id: uuid.UUID,
    exc: BaseException,
) -> str:
    """Phân loại lỗi → requeue có backoff hoặc failed. Trả 'queued'|'failed'."""
    settings = get_settings()
    code, retryable = classify_error(exc)
    job = (
        await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return "failed"

    can_retry = retryable and job.attempts_count < max(job.max_attempts, settings.generation_max_attempts)
    safe_message = _safe_message(exc)

    if can_retry:
        await db.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id)
            .values(
                status=JobStatus.queued,
                stage=None,
                lease_expires_at=None,
                heartbeat_at=None,
                dispatched_at=None,
                last_error_code=code,
                error={"code": code, "message": safe_message, "retryable": True},
            )
        )
        await db.commit()
        return "queued"

    await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id)
        .values(
            status=JobStatus.failed,
            lease_expires_at=None,
            heartbeat_at=_now(),
            last_error_code=code,
            error={"code": code, "message": safe_message, "retryable": False},
        )
    )
    await db.execute(
        update(Course).where(Course.id == course_id).values(status=CourseStatus.failed)
    )
    await db.commit()
    return "failed"


def _safe_message(exc: BaseException) -> str:
    """Message ngắn cho người dùng — không lộ prompt/nội dung/PII/secrets."""
    text = str(exc).strip().replace("\n", " ")
    return text[:200] if text else exc.__class__.__name__


def retry_countdown(job: GenerationJob) -> int:
    """Backoff lũy thừa có chặn: base * 2^(n-1), tối đa 60s."""
    base = get_settings().generation_retry_backoff_seconds
    return min(60, base * (2 ** max(0, job.attempts_count - 1)))


# ---------- dispatch / outbox ----------


def _celery_app():
    """Import muộn để tránh vòng import và để test patch được."""
    from app.worker import generation

    return generation.get_celery_app()


async def dispatch_job(db: AsyncSession, job_id: uuid.UUID, countdown: int = 0) -> bool:
    """Gửi job sang broker. Trả True nếu broker đã nhận.

    - Thành công: set `dispatched_at` (outbox ack).
    - Thất bại: giữ `dispatched_at IS NULL` và tăng `dispatch_attempts` để
      reconciler thử lại. KHÔNG raise làm hỏng response approve/retry.
    """
    app = _celery_app()
    if app is None:
        if not get_settings().generation_allow_inline_fallback:
            # Production: không có broker ⇒ để job `queued`, reconciler xử lý.
            # Không đánh dấu dispatched để outbox recovery nhìn thấy.
            logger.warning(
                "generation not dispatched: broker unavailable and inline fallback disabled job_id=%s",
                job_id,
            )
            return False
        await _mark_dispatched(db, job_id)
        if countdown > 0:
            # Retry có backoff mà không có broker: để job `queued` cho reconciler
            # (dispatch ngay lập tức sẽ phá backoff và có thể đệ quy vô hạn).
            return True
        if get_settings().generation_inline_blocking:
            # Dev/test: chạy đồng bộ để không có task nền dùng chung session.
            await _run_inline(job_id)
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            await _run_inline(job_id)
            return True
        loop.create_task(_run_inline(job_id))
        return True

    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                app.send_task, TASK_NAME, args=[str(job_id)], countdown=countdown
            ),
            timeout=get_settings().generation_dispatch_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — broker down là tình huống phải chịu được
        logger.warning(
            "generation dispatch failed job_id=%s code=%s err=%s",
            job_id,
            type(exc).__name__,
            str(exc)[:120],
        )
        await db.execute(
            update(GenerationJob)
            .where(GenerationJob.id == job_id, GenerationJob.dispatched_at.is_(None))
            .values(dispatch_attempts=GenerationJob.dispatch_attempts + 1)
        )
        await db.commit()
        return False

    await _mark_dispatched(db, job_id)
    return True


async def _mark_dispatched(db: AsyncSession, job_id: uuid.UUID) -> None:
    await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job_id)
        .values(dispatched_at=_now(), dispatch_attempts=GenerationJob.dispatch_attempts + 1)
    )
    await db.commit()


async def _run_inline(job_id: uuid.UUID) -> None:
    from app.worker.generation import _run_generation_async

    try:
        await _run_generation_async(str(job_id))
    except Exception:  # pragma: no cover — task nền không được làm sập request
        logger.exception("inline generation crashed job_id=%s", job_id)


async def recover_stuck_jobs(db: AsyncSession, limit: int = 20) -> list[uuid.UUID]:
    """Reconciler: dispatch lại job committed-nhưng-chưa-gửi + job có lease hết hạn.

    Trả danh sách job đã xử lý. Chỉ chạm đúng các trạng thái an toàn.
    """
    settings = get_settings()
    now = _now()
    grace = timedelta(seconds=settings.generation_dispatch_grace_seconds)

    rows = await db.execute(
        select(GenerationJob)
        .where(
            or_(
                # Outbox: commit xong nhưng chưa gửi broker (đã qua grace để tránh
                # đua với dispatcher của request approve/retry).
                (GenerationJob.status == JobStatus.queued)
                & GenerationJob.dispatched_at.is_(None)
                & (GenerationJob.created_at < now - grace),
                # Lease hết hạn: worker chết giữa chừng.
                (GenerationJob.status == JobStatus.running)
                & or_(
                    GenerationJob.lease_expires_at.is_(None),
                    GenerationJob.lease_expires_at < now,
                ),
            )
        )
        .order_by(GenerationJob.created_at)
        .limit(limit)
    )
    jobs = list(rows.scalars().all())

    recovered: list[uuid.UUID] = []
    for job in jobs:
        if job.dispatch_attempts >= settings.generation_max_dispatch_attempts:
            await _fail_exhausted(db, job)
            recovered.append(job.id)
            continue
        await dispatch_job(db, job.id)
        recovered.append(job.id)
    return recovered


async def _fail_exhausted(db: AsyncSession, job: GenerationJob) -> None:
    await db.execute(
        update(GenerationJob)
        .where(GenerationJob.id == job.id)
        .values(
            status=JobStatus.failed,
            lease_expires_at=None,
            last_error_code="DISPATCH_EXHAUSTED",
            error={
                "code": "DISPATCH_EXHAUSTED",
                "message": "Không gửi được job tới worker sau nhiều lần thử.",
                "retryable": False,
            },
        )
    )
    await db.execute(
        update(Course).where(Course.id == job.course_id).values(status=CourseStatus.failed)
    )
    await db.commit()
