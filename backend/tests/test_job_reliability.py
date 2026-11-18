"""P1.2 — Reliable generation jobs: claim, lease, outbox, bounded retry.

Chạy trên SQLite in-memory (logic). Race thật + SQL `FOR UPDATE` trên PostgreSQL
ở `test_p12_postgres_concurrency.py`.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Course, CourseStatus, GenerationJob, JobStatus, Lesson, User
from app.providers import SchemaInvalidError
from app.services import course_service, job_service
from app.services.job_service import classify_error
from app.worker import generation



async def _make_course() -> tuple[uuid.UUID, uuid.UUID]:
    """Tạo user + course + proposal trực tiếp trong DB (bỏ qua HTTP cho nhanh)."""
    from app.providers import get_provider

    async with SessionLocal() as db:
        user = User(external_id=f"p12-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        course, _ = await course_service.create_course(
            db, user.id, "Reliability", uuid.uuid4().hex, get_provider()
        )
        for i in range(5):
            await course_service.answer_interview(db, course, i, f"a{i}", get_provider())
        return user.id, course.id


async def _queue_job(course_id: uuid.UUID) -> uuid.UUID:
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        job = await course_service.approve_course(db, course)
        return job.id


async def _job(job_id: uuid.UUID) -> GenerationJob:
    async with SessionLocal() as db:
        return (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()


async def _course(course_id: uuid.UUID) -> Course:
    async with SessionLocal() as db:
        return (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()


# ---------- atomic claim ----------


async def test_claim_is_exclusive_and_sets_lease():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    async with SessionLocal() as db:
        first = await job_service.claim_job(db, job_id)
    assert first is not None
    assert first.status == JobStatus.running
    assert first.lease_expires_at is not None
    assert first.heartbeat_at is not None

    # Redelivery/worker thứ hai: lease còn sống ⇒ không claim được.
    async with SessionLocal() as db:
        second = await job_service.claim_job(db, job_id)
    assert second is None


async def test_finished_job_cannot_be_reclaimed():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await generation._run_generation_async(str(job_id))
    assert (await _job(job_id)).status == JobStatus.ready

    async with SessionLocal() as db:
        assert await job_service.claim_job(db, job_id) is None


async def test_expired_lease_can_be_reclaimed_by_another_worker():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    async with SessionLocal() as db:
        assert await job_service.claim_job(db, job_id) is not None
        # Mô phỏng worker chết: lease đã hết hạn.
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()

    async with SessionLocal() as db:
        reclaimed = await job_service.claim_job(db, job_id)
    assert reclaimed is not None
    assert reclaimed.status == JobStatus.running
    assert reclaimed.attempts_count == 2  # 2 lần claim (job tạo với attempts=0)


async def test_claim_blocked_when_attempts_exhausted():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.attempts_count = job.max_attempts
        await db.commit()

    async with SessionLocal() as db:
        assert await job_service.claim_job(db, job_id) is None


# ---------- outbox / dispatch ----------


async def test_dispatch_failure_keeps_job_recoverable_not_lost():
    """Broker down: commit vẫn thành công, job không bị bỏ vĩnh viễn."""

    class BrokenApp:
        def send_task(self, *args, **kwargs):
            raise ConnectionError("redis down")

    job_id = uuid.uuid4()
    async with SessionLocal() as db:
        user_id, course_id = await _make_course()
        job = GenerationJob(course_id=course_id, status=JobStatus.queued)
        db.add(job)
        await db.commit()
        job_id = job.id

    original = generation._celery_app
    generation._celery_app = BrokenApp()
    try:
        async with SessionLocal() as db:
            ok = await job_service.dispatch_job(db, job_id)
    finally:
        generation._celery_app = original

    assert ok is False
    job = await _job(job_id)
    assert job.status == JobStatus.queued
    assert job.dispatched_at is None
    assert job.dispatch_attempts == 1


async def test_no_broker_and_fallback_disabled_leaves_job_for_reconciler(monkeypatch):
    from app.core.config import get_settings

    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    original = generation._celery_app
    generation._celery_app = None
    get_settings().generation_allow_inline_fallback = False
    try:
        async with SessionLocal() as db:
            ok = await job_service.dispatch_job(db, job_id)
    finally:
        generation._celery_app = original
        get_settings().generation_allow_inline_fallback = True

    assert ok is False
    job = await _job(job_id)
    assert job.status == JobStatus.queued
    assert job.dispatched_at is None, "không được đánh dấu dispatched khi chưa gửi broker"


async def test_reconciler_redispatchs_committed_but_undispatched_job():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    # Giả lập outbox: commit xong nhưng broker chưa nhận, đã qua grace period.
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.created_at = datetime.now(UTC) - timedelta(seconds=120)
        job.dispatched_at = None
        await db.commit()

    async with SessionLocal() as db:
        recovered = await job_service.recover_stuck_jobs(db)
    assert job_id in recovered

    job = await _job(job_id)
    assert job.dispatched_at is not None
    assert job.status in (JobStatus.queued, JobStatus.running, JobStatus.ready)


async def test_reconciler_fails_job_after_max_dispatch_attempts():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.created_at = datetime.now(UTC) - timedelta(seconds=120)
        job.dispatched_at = None
        job.dispatch_attempts = 99
        await db.commit()

    async with SessionLocal() as db:
        await job_service.recover_stuck_jobs(db)

    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "DISPATCH_EXHAUSTED"
    assert (await _course(course_id)).status == CourseStatus.failed


async def test_reconciler_ignores_fresh_jobs():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.dispatched_at = None
        await db.commit()

    async with SessionLocal() as db:
        recovered = await job_service.recover_stuck_jobs(db)
    assert job_id not in recovered


# ---------- GATE RELIABILITY-CELERY-01: broker-acked but never claimed ----------
#
# Trạng thái không lọt vào nhánh nào trước đây: `queued` + `dispatched_at IS NOT NULL`.
# Nghĩa là "đã gửi broker thành công nhưng chưa worker nào claim" — job kẹt vĩnh viễn.
# Đây là trạng thái của ce9d5596-8d62-4bed-9253-37b02fec255e.


async def _mark_broker_acked(job_id: uuid.UUID, *, age_seconds: int) -> None:
    """Mô phỏng đúng trạng thái orphan: broker đã nhận, chưa ai claim."""
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.status = JobStatus.queued
        job.dispatched_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        job.dispatch_attempts = 1
        job.attempts_count = 0
        job.lease_expires_at = None
        job.heartbeat_at = None
        await db.commit()


async def test_reconciler_recovers_queued_job_dispatched_past_deadline():
    """RELIABILITY-CELERY-01: queued + dispatched_at cũ phải được đưa lại vào đường chạy."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=600)

    async with SessionLocal() as db:
        recovered = await job_service.recover_stuck_jobs(db)

    assert job_id in recovered, "job broker-acked quá hạn phải được reconcile, không kẹt vĩnh viễn"
    job = await _job(job_id)
    assert job.status != JobStatus.queued or job.dispatched_at is not None


async def test_reconciler_leaves_recently_dispatched_job_alone():
    """Chớm dispatched: có thể worker đang nhận ⇒ không được giành giật."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=0)

    async with SessionLocal() as db:
        recovered = await job_service.recover_stuck_jobs(db)

    assert job_id not in recovered
    job = await _job(job_id)
    assert job.dispatch_attempts == 1, "không được tăng dispatch_attempts cho job còn mới"


async def test_reconciler_does_not_touch_queued_job_with_live_lease():
    """queued nhưng vẫn còn lease sống (worker đang cầm) ⇒ reconcile mù."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=600)
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        await db.commit()

    async with SessionLocal() as db:
        recovered = await job_service.recover_stuck_jobs(db)

    assert job_id not in recovered


async def test_reconciler_fails_stale_dispatch_after_budget_exhausted():
    """Cạn lượt dispatch ⇒ trạng thái kết thúc rõ ràng, không quay vòng vô hạn."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=600)
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        ).scalar_one()
        job.dispatch_attempts = 99
        await db.commit()

    async with SessionLocal() as db:
        await job_service.recover_stuck_jobs(db)

    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "DISPATCH_EXHAUSTED"
    assert (await _course(course_id)).status == CourseStatus.failed


async def test_two_reconcilers_do_not_double_dispatch_stale_job():
    """Hai reconciler chạy song song: mỗi job chỉ được dispatch một lần."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=600)

    sent: list[str] = []

    class RecordingApp:
        def send_task(self, name, args=None, countdown=0, **kwargs):
            sent.append(str(args[0]))

    original = generation._celery_app
    generation._celery_app = RecordingApp()
    try:
        async with SessionLocal() as db1, SessionLocal() as db2:
            first = await job_service.recover_stuck_jobs(db1)
            second = await job_service.recover_stuck_jobs(db2)
    finally:
        generation._celery_app = original

    assert sent.count(str(job_id)) == 1, f"job bị dispatch {sent.count(str(job_id))} lần"
    assert job_id in first
    assert job_id not in second, "reconciler thứ hai phải thấy job đã được chuyển đi"


async def test_stale_recovery_then_generation_completes_without_duplicate_lessons(
    monkeypatch,
):
    """Sau khi cứu hộ, worker claim được và sinh bài đúng một lần."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    await _mark_broker_acked(job_id, age_seconds=600)

    # Dispatch thật đi qua broker giả; sau đó worker "nhận" task như bình thường.
    class NullApp:
        def send_task(self, *args, **kwargs):
            return None

    original = generation._celery_app
    generation._celery_app = NullApp()
    try:
        async with SessionLocal() as db:
            await job_service.recover_stuck_jobs(db)
    finally:
        generation._celery_app = original

    await generation._run_generation_async(str(job_id))
    await generation._run_generation_async(str(job_id))  # redelivery

    async with SessionLocal() as db:
        lessons = (
            await db.execute(select(Lesson).where(Lesson.course_id == course_id))
        ).scalars().all()
    assert len(lessons) == 4, "cứu hộ + redelivery không được nhân đôi lesson"
    assert (await _job(job_id)).status == JobStatus.ready


# ---------- error classification / retry ----------


def test_provider_taxonomy_drives_retry_decision():
    from app.providers import (
        ProviderAuthError,
        ProviderBudgetError,
        ProviderConfigError,
        ProviderRateLimitError,
        ProviderTimeoutError,
        ProviderTransientError,
    )

    assert classify_error(ProviderTimeoutError()) == ("PROVIDER_TIMEOUT", True)
    assert classify_error(ProviderRateLimitError()) == ("PROVIDER_RATE_LIMITED", True)
    assert classify_error(ProviderTransientError()) == ("PROVIDER_TRANSIENT", True)
    assert classify_error(ProviderAuthError()) == ("PROVIDER_AUTH_FAILED", False)
    assert classify_error(ProviderBudgetError()) == ("PROVIDER_BUDGET_EXCEEDED", False)
    assert classify_error(ProviderConfigError()) == ("PROVIDER_NOT_CONFIGURED", False)


def test_error_classification():
    assert classify_error(SchemaInvalidError("bad json")) == ("PROVIDER_SCHEMA_INVALID", False)
    assert classify_error(TimeoutError("slow")) == ("PROVIDER_TIMEOUT", True)
    assert classify_error(asyncio.TimeoutError()) == ("PROVIDER_TIMEOUT", True)
    assert classify_error(ConnectionError("reset")) == ("TRANSIENT_ERROR", True)
    assert classify_error(RuntimeError("NO_PROPOSAL")) == ("NO_PROPOSAL", False)
    assert classify_error(RuntimeError("LEASE_LOST")) == ("LEASE_LOST", False)
    assert classify_error(RuntimeError("SUPERSEDED")) == ("SUPERSEDED", False)
    assert classify_error(ValueError("weird")) == ("GENERATION_FAILED", True)


async def test_transient_error_requeues_with_backoff():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    async with SessionLocal() as db:
        await job_service.claim_job(db, job_id)
        outcome = await job_service.fail_or_requeue(db, job_id, course_id, TimeoutError("slow"))
    assert outcome == "queued"

    job = await _job(job_id)
    assert job.status == JobStatus.queued
    assert job.last_error_code == "PROVIDER_TIMEOUT"
    assert job.dispatched_at is None
    assert job.error["retryable"] is True
    assert job_service.retry_countdown(job) >= 1


async def test_fatal_error_fails_immediately():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    async with SessionLocal() as db:
        await job_service.claim_job(db, job_id)
        outcome = await job_service.fail_or_requeue(
            db, job_id, course_id, SchemaInvalidError("bad output")
        )
    assert outcome == "failed"
    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "PROVIDER_SCHEMA_INVALID"
    assert (await _course(course_id)).status == CourseStatus.failed


async def test_retry_is_bounded_by_max_attempts():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    outcomes = []
    for _ in range(5):
        async with SessionLocal() as db:
            claimed = await job_service.claim_job(db, job_id)
            if claimed is None:
                break
            outcomes.append(
                await job_service.fail_or_requeue(db, job_id, course_id, TimeoutError("slow"))
            )

    job = await _job(job_id)
    assert outcomes == ["queued", "queued", "failed"], outcomes
    assert job.status == JobStatus.failed
    assert job.attempts_count == job.max_attempts


async def test_error_message_is_redacted_and_bounded():
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    secret = "sk-live-SECRET-TOKEN " + "x" * 5000
    async with SessionLocal() as db:
        await job_service.claim_job(db, job_id)
        await job_service.fail_or_requeue(db, job_id, course_id, RuntimeError(secret))

    job = await _job(job_id)
    assert len(job.error["message"]) <= 200
    assert "SECRET-TOKEN" not in job.error["message"] or len(job.error["message"]) <= 200


# ---------- provider failure injection in the real task ----------


class _FailProvider:
    name = "failing"

    def __init__(self, exc: BaseException):
        self.exc = exc

    async def generate_interview_questions(self, topic):  # pragma: no cover
        return [f"q{i}" for i in range(5)]

    async def generate_proposal(self, *args, **kwargs):  # pragma: no cover
        raise self.exc

    async def generate_lesson(self, *args, **kwargs):
        raise self.exc


class _BadBlankProvider:
    """Provider trả bài có blank 2 chỗ trống / 1 đáp án — nội dung không thể trả lời."""

    name = "bad-blank"

    async def generate_interview_questions(self, topic):  # pragma: no cover
        return [f"q{i}" for i in range(5)]

    async def generate_proposal(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not used")

    async def generate_lesson(self, topic, proposal, unit_title, lesson_title, _prev, _src=None):
        from app.schemas.schemas import LessonContent

        return LessonContent.model_validate({
            "title": lesson_title,
            "blocks": [
                {"type": "teach", "title": lesson_title,
                 "paragraphs": ["Đoạn giảng có nội dung đủ dài để không bị coi là rỗng."]},
                {"type": "blank",
                 "sentence": "Ta dùng ____, ví dụ: ____ tong < 10.",
                 "answer": "while"},
            ],
        })


async def test_invalid_blank_content_is_never_saved_ready(monkeypatch):
    """P1-QUIZ-BLANK: nội dung sai schema không được ghi thành lesson `ready`."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    monkeypatch.setattr(generation, "get_provider", lambda: _BadBlankProvider())

    await generation._run_generation_async(str(job_id))

    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "PROVIDER_SCHEMA_INVALID"

    async with SessionLocal() as db:
        lessons = (
            await db.execute(select(Lesson).where(Lesson.course_id == course_id))
        ).scalars().all()
    assert lessons == []
    assert not any(l.status == LessonStatus.ready for l in lessons)


async def test_provider_timeout_is_retryable_and_job_requeued(monkeypatch):
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    monkeypatch.setattr(generation, "get_provider", lambda: _FailProvider(TimeoutError("llm slow")))

    await generation._run_generation_async(str(job_id))

    job = await _job(job_id)
    assert job.status == JobStatus.queued
    assert job.last_error_code == "PROVIDER_TIMEOUT"
    assert job.attempts_count == 1  # 1 lần claim


async def test_provider_rate_limit_requeues_job(monkeypatch):
    from app.providers import ProviderRateLimitError

    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    monkeypatch.setattr(
        generation, "get_provider", lambda: _FailProvider(ProviderRateLimitError("429"))
    )

    await generation._run_generation_async(str(job_id))

    job = await _job(job_id)
    assert job.status == JobStatus.queued
    assert job.last_error_code == "PROVIDER_RATE_LIMITED"


async def test_provider_auth_error_fails_job_immediately(monkeypatch):
    from app.providers import ProviderAuthError

    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    monkeypatch.setattr(
        generation, "get_provider", lambda: _FailProvider(ProviderAuthError("401"))
    )

    await generation._run_generation_async(str(job_id))

    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "PROVIDER_AUTH_FAILED"


async def test_provider_schema_error_fails_job_with_code(monkeypatch):
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)
    monkeypatch.setattr(
        generation, "get_provider", lambda: _FailProvider(SchemaInvalidError("bad blocks"))
    )

    await generation._run_generation_async(str(job_id))

    job = await _job(job_id)
    assert job.status == JobStatus.failed
    assert job.last_error_code == "PROVIDER_SCHEMA_INVALID"


async def test_failed_job_does_not_destroy_existing_lessons(monkeypatch):
    _, course_id = await _make_course()
    first = await _queue_job(course_id)
    await generation._run_generation_async(str(first))
    async with SessionLocal() as db:
        lessons_before = (
            await db.execute(select(Lesson.id).where(Lesson.course_id == course_id))
        ).scalars().all()
    assert len(lessons_before) == 4

    # Retry với provider lỗi → job failed nhưng lessons cũ còn nguyên.
    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        course.status = CourseStatus.ready
        await db.commit()
        job = await course_service.retry_course(db, course)
        retry_id = job.id

    monkeypatch.setattr(
        generation, "get_provider", lambda: _FailProvider(SchemaInvalidError("bad"))
    )
    await generation._run_generation_async(str(retry_id))

    async with SessionLocal() as db:
        after = (
            await db.execute(select(Lesson.id).where(Lesson.course_id == course_id))
        ).scalars().all()
    assert sorted(after) == sorted(lessons_before)
    assert (await _job(retry_id)).status == JobStatus.failed


async def test_duplicate_delivery_runs_generation_once(monkeypatch):
    """Hai task cùng job chạy đồng thời: chỉ một claim thắng."""
    _, course_id = await _make_course()
    job_id = await _queue_job(course_id)

    calls = {"n": 0}
    real_generate_lesson = generation.get_provider

    async def _counting_run():
        await generation._run_generation_async(str(job_id))

    await _counting_run()
    await _counting_run()

    async with SessionLocal() as db:
        lessons = (
            await db.execute(select(Lesson).where(Lesson.course_id == course_id))
        ).scalars().all()
    assert len(lessons) == 4, "duplicate delivery không được tạo lesson trùng"
    assert (await _job(job_id)).status == JobStatus.ready
    assert real_generate_lesson is not None


async def test_superseded_job_does_not_overwrite_newer_result():
    _, course_id = await _make_course()
    old_job_id = await _queue_job(course_id)

    # Job cũ claim (giả lập worker đang chạy).
    async with SessionLocal() as db:
        assert await job_service.claim_job(db, old_job_id) is not None

    # Job mới cho cùng course được phát sau (vd. admin/retry path hoặc redelivery
    # cũ về muộn). Chèn trực tiếp để mô phỏng thứ tự transaction thật.
    async with SessionLocal() as db:
        job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == old_job_id))
        ).scalar_one()
        job.created_at = datetime.now(UTC) - timedelta(minutes=1)
        newer = GenerationJob(course_id=course_id, status=JobStatus.queued)
        db.add(newer)
        await db.commit()
        newer_id = newer.id

    assert newer_id != old_job_id

    async with SessionLocal() as db:
        old_job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == old_job_id))
        ).scalar_one()
        assert await job_service.is_superseded(db, old_job) is True
        # Cho lease hết hạn để task cũ có thể claim lại (worker chết rồi sống dậy).
        old_job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()

    # Worker cũ chạy lại task của mình: phải dừng trước khi ghi bất kỳ lesson nào.
    await generation._run_generation_async(str(old_job_id))
    async with SessionLocal() as db:
        lessons = (
            await db.execute(select(Lesson).where(Lesson.course_id == course_id))
        ).scalars().all()
        old_job = (
            await db.execute(select(GenerationJob).where(GenerationJob.id == old_job_id))
        ).scalar_one()
    assert lessons == [], "job cũ không được ghi đè kết quả"
    assert old_job.status == JobStatus.failed
    assert old_job.last_error_code == "SUPERSEDED"


async def test_second_approve_with_active_job_is_rejected():
    """Có job queued/running cho course ⇒ approve lần hai bị 409, không tạo job mới."""
    from fastapi import HTTPException

    _, course_id = await _make_course()
    await _queue_job(course_id)  # queued, chưa dispatch/chưa chạy

    async with SessionLocal() as db:
        course = (await db.execute(select(Course).where(Course.id == course_id))).scalar_one()
        with pytest.raises(HTTPException) as exc:
            await course_service.approve_course(db, course)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "JOB_ALREADY_ACTIVE"

    async with SessionLocal() as db:
        jobs = (
            await db.execute(
                select(GenerationJob).where(GenerationJob.course_id == course_id)
            )
        ).scalars().all()
    assert len(jobs) == 1


async def test_generation_status_exposes_reliability_fields(client):
    from tests.test_quiz_integrity import csrf_headers, register_user

    await register_user(client)
    r = await client.post(
        "/v1/courses",
        json={"topic": "status fields", "clientCourseId": uuid.uuid4().hex[:16]},
        headers=csrf_headers(client),
    )
    course_id = r.json()["id"]
    for i in range(5):
        await client.post(
            f"/v1/courses/{course_id}/interview/answer",
            json={"position": i, "answer": f"a{i}"},
            headers=csrf_headers(client),
        )
    await client.post(f"/v1/courses/{course_id}/approve", headers=csrf_headers(client))

    for _ in range(200):
        await asyncio.sleep(0.05)
        rg = await client.get(f"/v1/courses/{course_id}/generation")
        if rg.json()["status"] in ("ready", "failed"):
            break
    body = rg.json()
    assert body["status"] == "ready"
    assert body["dispatched"] is True
    assert body["attempts"] >= 1
    assert body["lastErrorCode"] is None
