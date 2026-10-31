"""Source Research Service (P2.SR) — cầu nối giữa agent và Source Registry.

Vai trò (giữ agent "thuần", không truy cập DB):
  - resolve identity/quyền sở hữu course ở server trước khi chạy agent;
  - tạo `SourceResearchRun` idempotent theo `request_fingerprint`;
  - lưu kết quả nghiên cứu (kể cả trạng thái failed);
  - chuyển nguồn đã được chấp nhận vào registry qua `source_service` (dùng lại
    logic dedupe/ownership đã có, không viết lại);
  - cung cấp hook cho generation khi `SOURCE_RESEARCH_AUTO_LINK=true`.

Quy tắc trung thực:
  - Nguồn mock (`isMock=true`) KHÔNG BAO GIỜ được ghi vào registry.
  - Chỉ nguồn `metadata_verified` mới được link tự động; `discovered` cần người
    dùng xem xét (và hiện tại vẫn cần qua API tạo source thủ công).
  - Không tự đặt `verification_status` cao hơn `unverified` khi tạo bản ghi.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.source_research import ResearchRequest, ResearchResult, SourceResearchAgent, build_toolbox
from app.agents.source_research.adapters.base import ResearchDiscoveryAdapter
from app.agents.source_research.adapters.mock import MockResearchDiscoveryAdapter
from app.core.config import Settings, get_settings
from app.models import (
    Course,
    Source,
    SourceResearchRun,
    SourceResearchStatus,
    SourceType,
    SourceVisibility,
)
from app.schemas.schemas import SourceCreateRequest
from app.services import source_discovery, source_service

logger = logging.getLogger(__name__)

AGENT_ALLOWED_SOURCE_TYPES = {item.value for item in SourceType}


class ResearchDisabledError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOURCE_RESEARCH_DISABLED",
                "message": "Tính năng nghiên cứu nguồn chưa được bật trên server.",
            },
        )


class ResearchNotFoundError(HTTPException):
    def __init__(self) -> None:
        # 404 thay vì 403: không xác nhận sự tồn tại của research run của user khác.
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESEARCH_RUN_NOT_FOUND", "message": "Lần nghiên cứu không tồn tại."},
        )


class ResearchNotLinkableError(HTTPException):
    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RESEARCH_SOURCES_NOT_LINKABLE", "message": message},
        )


def resolve_adapter(settings: Settings | None = None) -> ResearchDiscoveryAdapter:
    """Chọn adapter theo cấu hình. `web` (network) bị từ chối — chưa triển khai."""
    settings = settings or get_settings()
    key = (settings.source_research_provider or "mock").strip().lower()
    if key == "mock":
        return MockResearchDiscoveryAdapter()
    if key == "curated":
        # Tái sử dụng adapter curated đã có (đọc JSON env, không network).
        return source_discovery.CuratedCatalogAdapter()  # type: ignore[return-value]
    if key == "web":
        raise source_discovery.SourceDiscoveryConfigError(
            "Adapter web chưa triển khai cho Source Research (cần SSRF guard, P4.2)."
        )
    raise source_discovery.SourceDiscoveryConfigError(
        f"SOURCE_RESEARCH_PROVIDER '{key}' không hợp lệ. Hợp lệ: mock, curated."
    )


def request_fingerprint(request: ResearchRequest, adapter_name: str) -> str:
    """Hash của toàn bộ tham số ảnh hưởng kết quả (trừ run_id).

    Có adapter name để đổi cấu hình adapter không trả lại kết quả cũ.
    """
    material = json.dumps(
        {
            "courseId": str(request.courseId),
            "topic": request.topic,
            "learnerLevel": request.learnerLevel,
            "learningGoals": request.learningGoals,
            "preferredLanguage": request.preferredLanguage,
            "maxSources": request.maxSources,
            "adapter": adapter_name,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


_NOTICE_MOCK = (
    "Kết quả MOCK: KHÔNG phải tìm kiếm thật, KHÔNG xác minh nội dung. "
    "Không dùng làm citation trong khóa học thật."
)
_NOTICE_CURATED = (
    "Metadata do danh mục curated cung cấp; chưa đối chiếu nội dung gốc."
)
_NOTICE_INSUFFICIENT = (
    "Không tìm đủ nguồn phù hợp; nội dung khóa học chỉ dựa trên kiến thức chung của AI."
)


def _notice_for(row: SourceResearchRun) -> str:
    if row.status is SourceResearchStatus.failed:
        return "Nghiên cứu nguồn thất bại. Không có nguồn nào được đề xuất."
    if row.is_mock:
        return _NOTICE_MOCK
    if row.insufficient_evidence:
        return _NOTICE_INSUFFICIENT
    return _NOTICE_CURATED


def to_run_out(row: SourceResearchRun, *, reused: bool = False) -> dict:
    return {
        "researchRunId": f"rr_{row.id}",
        "courseId": f"crs_{row.course_id}",
        "topic": row.topic,
        "domain": row.domain,
        "status": row.status.value,
        "sources": list(row.sources or []),
        "warnings": list(row.warnings or []),
        "insufficientEvidence": bool(row.insufficient_evidence),
        "analysis": row.analysis or {},
        "error": row.error,
        "adapter": row.adapter,
        "isMock": bool(row.is_mock),
        "toolCalls": row.tool_calls,
        "notice": _notice_for(row),
        "reused": reused,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def parse_run_id(raw: str) -> uuid.UUID | None:
    value = (raw or "").strip()
    if value.startswith("rr_"):
        value = value[3:]
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def _find_existing(db: AsyncSession, course_id: uuid.UUID, fingerprint: str) -> SourceResearchRun | None:
    return (
        await db.execute(
            select(SourceResearchRun).where(
                SourceResearchRun.course_id == course_id,
                SourceResearchRun.request_fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()


def _is_stale_running(row: SourceResearchRun, settings: Settings) -> bool:
    """Run `running` quá hạn = process chết giữa chừng ⇒ cho phép chạy lại cùng row."""
    if row.status is not SourceResearchStatus.running or row.created_at is None:
        return False
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - created).total_seconds()
    return age > max(60.0, settings.source_research_timeout_seconds * 4)


def _pending_run(course: Course, request: ResearchRequest, adapter_name: str, fingerprint: str) -> SourceResearchRun:
    return SourceResearchRun(
        course_id=course.id,
        user_id=course.user_id,
        status=SourceResearchStatus.running,
        topic=request.topic,
        domain="general",
        adapter=adapter_name,
        is_mock=False,
        request_fingerprint=fingerprint,
        analysis=None,
        sources=[],
        warnings=[],
        error=None,
        insufficient_evidence=True,
        tool_calls=0,
    )


def _apply_result(row: SourceResearchRun, result: ResearchResult) -> None:
    row.status = SourceResearchStatus(result.status)
    row.domain = result.domain
    row.adapter = result.adapter
    row.is_mock = result.isMock
    row.analysis = result.analysis.model_dump(mode="json")
    row.sources = [source.model_dump(mode="json") for source in result.sources]
    row.warnings = list(result.warnings)
    row.error = result.error.model_dump(mode="json") if result.error else None
    row.insufficient_evidence = result.insufficientEvidence
    row.tool_calls = result.toolCalls


async def run_research(
    db: AsyncSession,
    course: Course,
    *,
    max_sources: int | None = None,
    learning_goals: list[str] | None = None,
    learner_level: str | None = None,
    run_id: uuid.UUID | None = None,
) -> tuple[SourceResearchRun, bool]:
    """Chạy agent cho một course. Idempotent theo fingerprint.

    Trả (row, created). Nếu đã có run cùng fingerprint ⇒ trả bản cũ, không chạy lại.
    """
    settings = get_settings()
    if not settings.source_research_enabled:
        raise ResearchDisabledError()

    request = ResearchRequest(
        courseId=course.id,
        topic=course.topic,
        learnerLevel=learner_level,
        learningGoals=learning_goals or [],
        maxSources=max_sources or settings.source_research_max_sources,
    )

    try:
        adapter = resolve_adapter(settings)
    except source_discovery.SourceDiscoveryError:
        # Cấu hình sai phải fail-fast, không âm thầm dùng mock.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SOURCE_RESEARCH_NOT_CONFIGURED",
                "message": "Source Research chưa được cấu hình hợp lệ trên server.",
            },
        )

    fingerprint = request_fingerprint(request, adapter.name)
    existing = await _find_existing(db, course.id, fingerprint)
    if existing is not None:
        if existing.status is SourceResearchStatus.failed or _is_stale_running(existing, settings):
            # Retry (hoặc dọn run treo do process chết) dùng LẠI cùng row: không
            # nhân bản research run, fingerprint/UNIQUE vẫn bảo vệ.
            existing.status = SourceResearchStatus.running
            existing.error = None
            existing.warnings = []
            existing.insufficient_evidence = True
            await db.commit()
            row = existing
        else:
            return existing, False
    else:
        row = _pending_run(course, request, adapter.name, fingerprint)
        row.id = run_id or uuid.uuid4()
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            # Race: request đồng thời đã tạo run cùng fingerprint.
            await db.rollback()
            found = await _find_existing(db, course.id, fingerprint)
            if found is None:
                raise
            return found, False

    async def saver(_payload: dict) -> None:
        # Kết quả được ghi bởi `run_research` sau khi agent xong; saver chỉ giữ hợp
        # đồng "agent không tự ghi DB" và chặn ghi trùng.
        return None

    toolbox = build_toolbox(
        adapter=adapter,
        max_tool_calls=settings.source_research_max_tool_calls,
        tool_timeout_seconds=settings.source_research_tool_timeout_seconds,
        saver=saver,
    )
    agent = SourceResearchAgent(toolbox)

    try:
        result = await asyncio.wait_for(
            agent.run(request, run_id=row.id),
            timeout=settings.source_research_timeout_seconds,
        )
    except asyncio.TimeoutError:
        row.status = SourceResearchStatus.failed
        row.error = {
            "code": "SOURCE_RESEARCH_TIMEOUT",
            "message": "Nghiên cứu nguồn vượt thời gian cho phép.",
            "retryable": True,
        }
        row.warnings = [*(row.warnings or []), "Nghiên cứu nguồn quá thời gian cho phép."]
        row.insufficient_evidence = True
        await db.commit()
        logger.warning(
            "source research timeout course_id=%s adapter=%s", course.id, adapter.name
        )
        return row, True
    except Exception as exc:  # noqa: BLE001 — không để row kẹt `running` và 500
        logger.warning(
            "source research crashed course_id=%s adapter=%s err=%s",
            course.id,
            adapter.name,
            type(exc).__name__,
        )
        row.status = SourceResearchStatus.failed
        row.error = {
            "code": "SOURCE_RESEARCH_INTERNAL_ERROR",
            "message": "Nghiên cứu nguồn gặp lỗi nội bộ.",
            "retryable": True,
        }
        row.warnings = [*(row.warnings or []), "Nghiên cứu nguồn gặp lỗi nội bộ."]
        row.insufficient_evidence = True
        await db.commit()
        return row, True

    _apply_result(row, result)
    await db.commit()
    await db.refresh(row)
    return row, True


async def get_run(db: AsyncSession, course: Course, run_id: str) -> SourceResearchRun:
    parsed = parse_run_id(run_id)
    if parsed is None:
        raise ResearchNotFoundError()
    row = (
        await db.execute(
            select(SourceResearchRun).where(
                SourceResearchRun.id == parsed,
                SourceResearchRun.course_id == course.id,
                SourceResearchRun.user_id == course.user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ResearchNotFoundError()
    return row


async def list_runs(db: AsyncSession, course: Course, limit: int = 20, offset: int = 0) -> dict:
    rows = (
        (
            await db.execute(
                select(SourceResearchRun)
                .where(
                    SourceResearchRun.course_id == course.id,
                    SourceResearchRun.user_id == course.user_id,
                )
                .order_by(SourceResearchRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [to_run_out(row) for row in rows], "total": len(rows)}


async def link_verified_sources(
    db: AsyncSession, course: Course, run: SourceResearchRun
) -> list[Source]:
    """Chuyển các nguồn **metadata_verified** của run vào registry + link course.

    Từ chối nếu run là mock hoặc không có nguồn nào đủ điều kiện: better to fail
    loudly than to inject fake sources into a user's course.
    """
    if run.is_mock:
        raise ResearchNotLinkableError(
            "Kết quả nghiên cứu là MOCK; không thể đưa nguồn giả vào khóa học."
        )
    if run.status is not SourceResearchStatus.completed:
        raise ResearchNotLinkableError("Chỉ liên kết được từ lần nghiên cứu hoàn tất.")

    linkable = [
        item
        for item in (run.sources or [])
        if item.get("verificationStatus") == "metadata_verified" and not item.get("isMock")
    ]
    if not linkable:
        raise ResearchNotLinkableError(
            "Không có nguồn nào đã qua kiểm tra metadata; hãy tạo nguồn thủ công và xem xét trước."
        )

    created: list[Source] = []
    for item in linkable:
        source_type = item.get("sourceType")
        if source_type not in AGENT_ALLOWED_SOURCE_TYPES:
            # Không mở rộng enum qua đường agent; loại không biết ⇒ bỏ, ghi lý do.
            logger.info("skip research source with unsupported type course_id=%s", course.id)
            continue
        body = SourceCreateRequest(
            sourceType=source_type,
            title=str(item.get("title"))[:300],
            canonicalUrl=item.get("canonicalUrl"),
            author=item.get("author"),
            publisher=item.get("publisher"),
            publicationDate=item.get("publicationDate"),
            language=item.get("language"),
            version=item.get("version"),
            licenseInfo=item.get("licenseInfo"),
            visibility=SourceVisibility.private.value,
        )
        source, _created = await source_service.create_source(db, course.user_id, body)
        await source_service.link_source_to_course(
            db, course, course.user_id, f"src_{source.id}"
        )
        created.append(source)
    return created


async def maybe_auto_link_for_generation(db: AsyncSession, course: Course) -> SourceResearchRun | None:
    """Hook cho worker: chỉ chạy khi flag bật. Không bao giờ làm job thất bại vì
    nghiên cứu nguồn lỗi — nguồn là phần bổ sung, không phải điều kiện sinh bài.
    """
    settings = get_settings()
    if not settings.source_research_enabled or not settings.source_research_auto_link:
        return None
    try:
        row, _created = await run_research(db, course)
    except Exception as exc:  # noqa: BLE001 — không được chặn generation
        logger.warning(
            "source research auto-link skipped course_id=%s err=%s",
            course.id,
            type(exc).__name__,
        )
        await db.rollback()
        return None
    if row.is_mock:
        # Mock chỉ để kiểm thử luồng; không bao giờ ghi nguồn giả vào khóa học.
        return row
    try:
        await link_verified_sources(db, course, row)
    except HTTPException as exc:
        logger.info(
            "source research auto-link found no linkable source course_id=%s code=%s",
            course.id,
            (exc.detail or {}).get("code") if isinstance(exc.detail, dict) else "n/a",
        )
    return row
