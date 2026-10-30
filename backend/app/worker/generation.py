"""Celery app + generation task.

Có 2 chế độ:
1. Redis khả dụng: task chạy qua Celery worker (bất đồng bộ thật).
2. Fallback: chạy task inline ngay trong request (khi REDIS_URL rỗng hoặc
   không kết nối được) — vẫn giữ trạng thái job trong DB để client poll.
"""

import asyncio
import uuid

from app.core.config import get_settings
from app.models import Course, CourseProposal, CourseStatus, GenerationJob, JobStatus, Lesson, LessonStatus, Unit
from app.providers import SchemaInvalidError, get_provider
from app.schemas.schemas import ProposalPayload

_settings = get_settings()

_celery_app = None
_use_celery = False

if _settings.redis_url:
    try:
        from app.worker.celery_app import celery_app as _configured_app

        if _configured_app is not None:
            _celery_app = _configured_app
            _use_celery = True
    except Exception:
        _celery_app = None
        _use_celery = False


def get_celery_app():
    return _celery_app


def dispatch_generation(job_id: str) -> None:
    """Gửi job tới worker hoặc chạy inline fallback."""
    if _use_celery and _celery_app is not None:
        _celery_app.send_task("app.worker.generation.run_generation_task", args=[job_id])
        return
    # Fallback inline — chạy background task nếu đang trong event loop
    # (request handler); nếu không, tạo loop mới (worker thread / script).
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_run_generation_async(job_id))
    else:
        loop.create_task(_run_generation_async(job_id))


async def _run_generation_async(job_id: str) -> None:
    """Thân task generation — idempotent theo job_id.

    Dùng engine RIÊNG tạo trong task này (mỗi asyncio.run tạo event loop mới;
    dùng chung engine/pool module-level gây lỗi asyncpg cross-loop với Celery).
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.session import engine as app_engine

    # Dùng engine của app nếu URL trùng (tránh tạo bảng mới trên sqlite :memory:);
    # Celery worker sẽ có engine riêng theo settings của process đó.
    settings = get_settings()
    engine = app_engine if settings.database_url.startswith("sqlite") else create_async_engine(
        settings.database_url, pool_pre_ping=True
    )
    WorkerSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        await _generate(WorkerSession, select, job_id)
    finally:
        if engine is not app_engine:
            await engine.dispose()


async def _generate(WorkerSession, select, job_id: str) -> None:
    async with WorkerSession() as db:
        try:
            jid = uuid.UUID(job_id)
        except (ValueError, TypeError):
            return

        result = await db.execute(select(GenerationJob).where(GenerationJob.id == jid))
        job = result.scalar_one_or_none()
        if job is None or job.status in (JobStatus.ready,):
            return  # đã hoàn tất — no-op (idempotency khi redeliver)

        course_result = await db.execute(select(Course).where(Course.id == job.course_id))
        course = course_result.scalar_one_or_none()
        if course is None:
            job.status = JobStatus.failed
            job.error = {"code": "COURSE_MISSING", "message": "Course không tồn tại"}
            await db.commit()
            return

        try:
            job.status = JobStatus.running
            job.stage = "reading_answers"
            await db.commit()

            # Lấy proposal
            prop_result = await db.execute(
                select(CourseProposal)
                .where(CourseProposal.course_id == course.id)
                .order_by(CourseProposal.version.desc())
                .limit(1)
            )
            proposal_row = prop_result.scalars().first()
            if proposal_row is None:
                raise RuntimeError("NO_PROPOSAL")
            proposal = ProposalPayload.model_validate(proposal_row.payload)

            provider = get_provider()

            job.stage = "outline"
            await db.commit()

            # Sinh units + lessons (upsert theo order_index — không trùng khi retry)
            lesson_total = sum(len(u.lessonTitles) for u in proposal.units)
            job.lessons_total = lesson_total
            job.stage = "lessons"
            await db.commit()

            existing_units = (
                await db.execute(select(Unit).where(Unit.course_id == course.id))
            ).scalars().all()
            unit_by_order = {u.order_index: u for u in existing_units}

            previous_titles: list[str] = []
            lesson_index = 0
            for u_idx, proposal_unit in enumerate(proposal.units):
                unit = unit_by_order.get(u_idx)
                if unit is None:
                    unit = Unit(course_id=course.id, order_index=u_idx, title=proposal_unit.title, blurb=proposal_unit.blurb)
                    db.add(unit)
                    await db.flush()
                else:
                    unit.title = proposal_unit.title
                    unit.blurb = proposal_unit.blurb

                existing_lessons = (
                    await db.execute(
                        select(Lesson).where(Lesson.unit_id == unit.id)
                    )
                ).scalars().all()
                lesson_by_order = {l.order_index: l for l in existing_lessons}

                for l_idx, lesson_title in enumerate(proposal_unit.lessonTitles):
                    lesson_index += 1
                    content = await provider.generate_lesson(
                        course.topic, proposal, proposal_unit.title, lesson_title, previous_titles
                    )
                    if content is None or not content.blocks:
                        raise SchemaInvalidError(f"Lesson không hợp lệ: '{lesson_title}'")

                    if lesson_by_order.get(l_idx) is None:
                        lesson_row = Lesson(
                            unit_id=unit.id,
                            course_id=course.id,
                            order_index=l_idx,
                            title=content.title,
                            content=content.model_dump()["blocks"],
                            content_version=1,
                            status=LessonStatus.ready,
                        )
                        db.add(lesson_row)
                    else:
                        lesson_row = lesson_by_order[l_idx]
                        lesson_row.title = content.title
                        lesson_row.content = content.model_dump()["blocks"]
                        lesson_row.content_version += 1
                        lesson_row.status = LessonStatus.ready

                    previous_titles.append(content.title)
                    job.lessons_done = lesson_index
                    await db.commit()

            course.status = CourseStatus.ready
            job.status = JobStatus.ready
            job.stage = "done"
            await db.commit()

        except (SchemaInvalidError, Exception) as exc:  # noqa: BLE001
            await db.rollback()
            # Reload sau rollback
            job = (await db.execute(select(GenerationJob).where(GenerationJob.id == jid))).scalar_one_or_none()
            course = (await db.execute(select(Course).where(Course.id == course.id))).scalar_one_or_none()
            if job is not None:
                job.status = JobStatus.failed
                job.error = {"code": "GENERATION_FAILED", "message": str(exc)[:500]}
                await db.commit()
            if course is not None:
                course.status = CourseStatus.failed
                await db.commit()


if _use_celery and _celery_app is not None:

    @_celery_app.task(name="app.worker.generation.run_generation_task", bind=True, max_retries=0)
    def run_generation_task(self, job_id: str):  # noqa: ANN001
        asyncio.run(_run_generation_async(job_id))
