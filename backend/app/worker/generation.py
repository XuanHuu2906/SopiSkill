"""Generation task — atomic claim, lease heartbeat, bounded retry.

Luồng (P1.2):
  1. `claim_job` nguyên tử (UPDATE ... WHERE queued | lease hết hạn RETURNING).
     Không claim được ⇒ no-op (redelivery, worker khác đang chạy, hoặc đã xong).
  2. Mỗi lesson: `renew_lease` + kiểm tra `is_superseded` trước khi ghi.
  3. Lỗi phân loại: transient → requeue có backoff (bounded); fatal → failed.
  4. Kết thúc chỉ ghi khi vẫn giữ lease (guard ở mỗi UPDATE).

Dispatch tách ra `job_service` để route approve/retry không phải tự biết Celery.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from app.core.config import get_settings
from app.models import (
    Course,
    CourseProposal,
    CourseSource,
    GenerationJob,
    Lesson,
    LessonStatus,
    Source,
    Unit,
)
from app.providers import SchemaInvalidError, get_provider
from app.providers.usage import collect_usage
from app.schemas.schemas import ProposalPayload
from app.services import citation_service, source_evaluation, source_service
from app.services import llm_usage_service
from app.services import source_context as source_context_service

logger = logging.getLogger(__name__)

_settings = get_settings()

_celery_app = None
_use_celery = False

if _settings.redis_url:
    try:
        from app.worker.celery_app import celery_app as _configured_app

        if _configured_app is not None:
            _celery_app = _configured_app
            _use_celery = True
    except Exception:  # pragma: no cover — thiếu celery/redis không được làm sập app
        _celery_app = None
        _use_celery = False


def get_celery_app():
    return _celery_app


def _content_signature(blocks) -> str:
    """Chữ ký nội dung ổn định (JSON round-trip giống cách lưu JSONB/JSON).

    Pydantic model_dump() giữ tuple cho `pairs`, còn DB trả về list → so sánh
    trực tiếp sẽ luôn "khác". Chuẩn hoá qua JSON trước khi so.
    """
    return json.dumps(blocks or [], sort_keys=True, ensure_ascii=False)


async def _flush_usage_safely(db, usage, job_id, user_id) -> None:
    """Ghi usage event; lỗi accounting KHÔNG được làm hỏng job sinh bài."""
    if usage is None:
        return
    try:
        await llm_usage_service.flush_usage(
            db, usage, job_id=job_id, user_id=user_id
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — accounting là best-effort, không phải nội dung
        logger.warning("llm usage flush failed job_id=%s", job_id, exc_info=False)
        await db.rollback()


async def _run_generation_async(job_id: str) -> None:
    """Thân task generation — idempotent + lease-safe.

    Dùng engine RIÊNG tạo trong task này (mỗi asyncio.run tạo event loop mới;
    dùng chung engine/pool module-level gây lỗi asyncpg cross-loop với Celery).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.db.session import engine as app_engine

    settings = get_settings()
    engine = (
        app_engine
        if settings.database_url.startswith("sqlite")
        else create_async_engine(settings.database_url, pool_pre_ping=True)
    )
    WorkerSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        await _generate(WorkerSession, job_id)
    finally:
        if engine is not app_engine:
            await engine.dispose()


async def _generate(WorkerSession, job_id: str) -> None:
    from sqlalchemy import select

    from app.services import job_service

    try:
        jid = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return

    async with WorkerSession() as db:
        job = await job_service.claim_job(db, jid)
        if job is None:
            logger.info("generation job not claimed (done/claimed/exhausted) job_id=%s", jid)
            return

        # Giữ khóa ngoại dạng scalar: sau rollback các attribute của ORM object bị
        # hết hạn, đọc `course.id` sẽ ném MissingGreenlet.
        course_id = job.course_id
        course = (
            await db.execute(select(Course).where(Course.id == course_id))
        ).scalar_one_or_none()
        if course is None:
            await job_service.fail_or_requeue(db, jid, course_id, RuntimeError("COURSE_MISSING"))
            return
        # Scalar owner id phải đọc TRƯỚC rollback (P2.2 usage attribution).
        course_user_id = course.user_id

        try:
            with collect_usage() as usage:
                try:
                    await _generate_lessons(db, job, course, usage)
                except Exception:
                    # Chi phí đã phát sinh dù job lỗi → ghi usage trong transaction
                    # mới (transaction nội dung đã ở trạng thái lỗi) để không mất
                    # dấu chi phí, rồi mới rollback phần nội dung dở dang.
                    await db.rollback()
                    await _flush_usage_safely(db, usage, jid, course_user_id)
                    raise
        except Exception as exc:  # noqa: BLE001 — mọi lỗi phải phân loại rõ ràng
            await db.rollback()
            outcome = await job_service.fail_or_requeue(db, jid, course_id, exc)
            if outcome == "queued":
                fresh = (
                    await db.execute(select(GenerationJob).where(GenerationJob.id == jid))
                ).scalar_one()
                await job_service.dispatch_job(db, jid, countdown=job_service.retry_countdown(fresh))
            logger.warning(
                "generation job failed job_id=%s outcome=%s error=%s",
                jid,
                outcome,
                type(exc).__name__,
            )


async def _generate_lessons(db, job: GenerationJob, course: Course, usage=None) -> None:
    from sqlalchemy import select

    from app.services import job_service

    settings = get_settings()
    job.stage = "reading_answers"
    await db.commit()

    # Pin proposal: dùng đúng version đã snapshot cho job (nếu có), tránh sinh từ
    # proposal mới hơn trong khi job cũ đang chạy.
    proposal_query = select(CourseProposal).where(CourseProposal.course_id == course.id)
    if job.proposal_version is not None:
        proposal_query = proposal_query.where(CourseProposal.version == job.proposal_version)
    else:
        proposal_query = proposal_query.order_by(CourseProposal.version.desc())
    proposal_row = (await db.execute(proposal_query.limit(1))).scalars().first()
    if proposal_row is None:
        raise RuntimeError("NO_PROPOSAL")
    proposal = ProposalPayload.model_validate(proposal_row.payload)
    # P2.1 — proposal tạo trước P2.1 có thể thiếu curriculum; chuẩn hoá để mỗi
    # bài luôn có skill/outcome khi soạn nội dung (không ghi lại vào DB).
    from app.services import pedagogy

    proposal = pedagogy.normalize_curriculum(proposal)

    provider = get_provider()

    # P2.SR — Source Research (tuỳ chọn, mặc định TẮT). Nếu bật, agent có thể
    # nghiên cứu + link nguồn đã kiểm tra metadata TRƯỚC khi resolve source context.
    # Lỗi ở bước này không làm job thất bại: nguồn là phần bổ sung, không phải
    # điều kiện sinh bài (xem `maybe_auto_link_for_generation`).
    from app.services import source_research_service

    await source_research_service.maybe_auto_link_for_generation(db, course)

    # P3.0 — Source Resolution. Danh sách nguồn do SERVER đọc từ registry (scoped
    # theo owner của course). P3.0 CHƯA ingest nội dung nên:
    #   - chỉ metadata (title/publisher/url) được đưa vào prompt, excerpt = None;
    #   - bài học KHÔNG được gọi là `source_grounded` (không có đoạn nguồn thật);
    #   - citation vẫn được ghi để truy vết, nhưng ở trạng thái unverified/
    #     unavailable chứ không giả vờ đã kiểm chứng.
    linked_sources: list[tuple[CourseSource, Source]] = []
    if get_settings().source_context_enabled:
        linked_sources = await source_service.load_course_sources_for_generation(db, course)
    # P4.0 — nguồn đã ingest text THẬT hay chưa. Chỉ dùng để ghi trạng thái citation
    # trung thực (`unverified` thay vì `unavailable`), chưa có retrieval (P4.1).
    from app.services import ingest as ingest_service

    has_ingested_content = False
    for _link, source in linked_sources:
        if await ingest_service.source_has_content(db, source.id):
            has_ingested_content = True
            break
    # P4.0 KHÔNG cấp excerpt_provider: chưa có retrieval nên chưa có đoạn nguồn
    # thật gắn với nội dung bài. Grounding vẫn `general_ai_knowledge`.
    source_context = source_context_service.build_source_context(linked_sources)

    job.stage = "outline"
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
            unit = Unit(
                course_id=course.id,
                order_index=u_idx,
                title=proposal_unit.title,
                blurb=proposal_unit.blurb,
            )
            db.add(unit)
            await db.flush()
        else:
            unit.title = proposal_unit.title
            unit.blurb = proposal_unit.blurb

        # Stage theo unit giúp UI/log thấy tiến độ phân cấp (không lộ nội dung).
        job.stage = f"unit_{u_idx + 1}/{len(proposal.units)}"
        await db.commit()

        existing_lessons = (
            await db.execute(select(Lesson).where(Lesson.unit_id == unit.id))
        ).scalars().all()
        lesson_by_order = {l.order_index: l for l in existing_lessons}

        for l_idx, lesson_title in enumerate(proposal_unit.lessonTitles):
            if not await job_service.renew_lease(db, job.id):
                raise RuntimeError("LEASE_LOST")
            if await job_service.is_superseded(db, job):
                raise RuntimeError("SUPERSEDED")

            lesson_index += 1
            try:
                content = await asyncio.wait_for(
                    provider.generate_lesson(
                        course.topic,
                        proposal,
                        proposal_unit.title,
                        lesson_title,
                        previous_titles,
                        source_context or None,
                    ),
                    timeout=settings.generation_lesson_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Provider không xong trong budget ⇒ lỗi tạm thời, job sẽ requeue.
                from app.providers import ProviderTimeoutError

                raise ProviderTimeoutError(
                    f"Provider vượt {settings.generation_lesson_timeout_seconds}s cho bài '{lesson_title}'."
                ) from None
            if content is None or not content.blocks:
                raise SchemaInvalidError(f"Lesson không hợp lệ: '{lesson_title}'")

            new_blocks = content.model_dump()["blocks"]
            if lesson_by_order.get(l_idx) is None:
                lesson_row = Lesson(
                    unit_id=unit.id,
                    course_id=course.id,
                    order_index=l_idx,
                    title=content.title,
                    content=new_blocks,
                    content_version=1,
                    status=LessonStatus.ready,
                )
                db.add(lesson_row)
                await db.flush()
            else:
                lesson_row = lesson_by_order[l_idx]
                # P1.1.7: chỉ tăng contentVersion khi nội dung thực sự đổi.
                changed = (
                    lesson_row.title != content.title
                    or _content_signature(lesson_row.content) != _content_signature(new_blocks)
                )
                if changed:
                    lesson_row.content_version += 1
                    lesson_row.title = content.title
                    lesson_row.content = new_blocks
                lesson_row.status = LessonStatus.ready

            # P3.0 — provenance. Grounding do server quyết định từ dữ liệu nguồn thật
            # (không phải model tự khai). Citation tái tạo mỗi lần ghi bài để không
            # giữ citation của phiên bản nội dung cũ trỏ sang nguồn đã đổi.
            lesson_row.grounding = source_context_service.lesson_grounding(source_context)
            await db.flush()
            await citation_service.replace_lesson_citations(
                db,
                lesson_row,
                course,
                [source for _link, source in linked_sources],
                evidence_by_source=None,
                has_ingested_content=has_ingested_content,
            )
            if linked_sources:
                # Snapshot đánh giá nguồn tại thời điểm sinh bài (chỉ để hiển thị lại).
                for link, source in linked_sources:
                    if link.evaluation is None:
                        link.evaluation = source_evaluation.evaluate_source(
                            source, topics=[course.topic]
                        ).to_dict()

            previous_titles.append(content.title)
            job.lessons_done = lesson_index
            job.heartbeat_at = datetime.now(UTC)
            await db.commit()

            # P2.2 — token/cost accounting. Flush sau mỗi bài để job luôn có số
            # liệu chi phí ngay cả khi worker chết giữa chừng; sau đó chặn job
            # vượt trần token/chi phí (fatal, không retry vì retry đốt thêm tiền).
            if usage is not None:
                await _flush_usage_safely(db, usage, job.id, course.user_id)
            await llm_usage_service.enforce_job_budget(db, job.id)

    if await job_service.is_superseded(db, job):
        raise RuntimeError("SUPERSEDED")

    # P5.0 — backfill skill ngay sau khi ghi lesson (idempotent). Lỗi ở bước này
    # KHÔNG được làm job thất bại: lộ trình đã sinh xong, skill có thể backfill lại
    # bằng reconciler sau.
    if get_settings().p50_enabled:
        from app.services import learner_profile_service

        try:
            await learner_profile_service.backfill_course_skills(
                db, course, proposal_version=job.proposal_version
            )
        except Exception:  # pragma: no cover - phòng thủ, không chặn job
            await db.rollback()
            logger.exception("p50 skill backfill failed course=%s", course.id)

    await job_service.finish_ready(db, job.id, course.id)


if _use_celery and _celery_app is not None:

    @_celery_app.task(name="app.worker.generation.run_generation_task", bind=True, max_retries=0)
    def run_generation_task(self, job_id: str):  # noqa: ANN001
        asyncio.run(_run_generation_async(job_id))
