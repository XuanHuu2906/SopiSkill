"""Source Registry service (P3.0) — metadata nguồn, ownership, liên kết course.

Nguyên tắc bảo mật & trung thực:
  - Ownership do SERVER quyết định từ identity đã xác thực; không tin `ownerId`
    từ client. Nguồn `private` chỉ chủ sở hữu đọc/link được; `public` dùng chung.
  - Tạo nguồn KHÔNG bao giờ tự đánh dấu verified. URL hợp lệ không đồng nghĩa
    nguồn đáng tin; chỉ metadata đầy đủ mới đủ điều kiện "metadata_verified" do
    evaluator đề xuất (không tự áp dụng).
  - Dedupe deterministic để retry không sinh duplicate vô hạn.
  - Không log nội dung tài liệu/URL riêng tư; log chỉ id + loại nguồn.
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Course,
    CourseSource,
    Source,
    SourceType,
    SourceVerificationStatus,
    SourceVisibility,
)
from app.schemas.schemas import SourceCreateRequest, SourceOut

logger = logging.getLogger(__name__)


class SourceAccessError(HTTPException):
    def __init__(self) -> None:
        # 404 (không phải 403): không xác nhận sự tồn tại của nguồn private người khác.
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SOURCE_NOT_FOUND", "message": "Nguồn không tồn tại hoặc không thuộc quyền của bạn."},
        )


def _norm_text(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _parse_dt(value: str | None) -> datetime | None:
    """Parse ISO-8601 (chấp nhận 'YYYY-MM-DD'). Không đoán mò khi sai format."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def compute_dedupe_key(
    *,
    owner_id: uuid.UUID | None,
    source_type: SourceType | str,
    canonical_url: str | None,
    title: str,
    content_hash: str | None,
) -> str:
    """Hash ổn định: scope sở hữu + loại + URL chuẩn hoá (hoặc title) + contentHash.

    Public source (owner NULL) dedupe toàn cục; private source dedupe theo owner để
    hai người dùng có thể có nguồn riêng cùng tiêu đề mà không đụng nhau.
    """
    scope = f"user:{owner_id}" if owner_id else "public"
    type_value = source_type.value if isinstance(source_type, SourceType) else str(source_type)
    locator = _norm_text(canonical_url) or _norm_text(title)
    material = "|".join([scope, type_value, locator, _norm_text(content_hash)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def to_source_out(source: Source) -> SourceOut:
    return SourceOut(
        id=f"src_{source.id}",
        sourceType=source.source_type.value,
        title=source.title,
        canonicalUrl=source.canonical_url,
        author=source.author,
        publisher=source.publisher,
        publicationDate=_iso(source.publication_date),
        sourceUpdatedAt=_iso(source.source_updated_at),
        retrievedAt=_iso(source.retrieved_at),
        language=source.language,
        version=source.version,
        visibility=source.visibility.value,
        licenseInfo=source.license_info,
        contentHash=source.content_hash,
        verificationStatus=source.verification_status.value,
        ownerId=f"usr_{source.owner_id}" if source.owner_id else None,
        createdAt=_iso(source.created_at),
    )


def parse_source_id(raw: str) -> uuid.UUID | None:
    value = (raw or "").strip()
    if value.startswith("src_"):
        value = value[4:]
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def create_source(
    db: AsyncSession, user_id: uuid.UUID, body: SourceCreateRequest
) -> tuple[Source, bool]:
    """Tạo hoặc trả nguồn đã tồn tại (idempotent theo dedupe_key). Trả (source, created)."""
    source_type = SourceType(body.sourceType)
    visibility = SourceVisibility(body.visibility)
    # Public source không thuộc riêng ai; private luôn gắn owner hiện tại.
    owner_id = None if visibility == SourceVisibility.public else user_id

    dedupe_key = compute_dedupe_key(
        owner_id=owner_id,
        source_type=source_type,
        canonical_url=body.canonicalUrl,
        title=body.title,
        content_hash=None,
    )

    existing = (
        await db.execute(select(Source).where(Source.dedupe_key == dedupe_key))
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    source = Source(
        source_type=source_type,
        title=body.title.strip(),
        canonical_url=body.canonicalUrl,
        author=body.author,
        publisher=body.publisher,
        publication_date=_parse_dt(body.publicationDate),
        source_updated_at=_parse_dt(body.sourceUpdatedAt),
        language=body.language,
        version=body.version,
        owner_id=owner_id,
        visibility=visibility,
        license_info=body.licenseInfo,
        # KHÔNG suy ra verified từ URL/metadata có sẵn ở bước tạo.
        verification_status=SourceVerificationStatus.unverified,
        dedupe_key=dedupe_key,
    )
    db.add(source)
    try:
        await db.commit()
    except IntegrityError:
        # Race: request đồng thời đã tạo cùng dedupe_key. Trả bản ghi đã có.
        await db.rollback()
        found = (
            await db.execute(select(Source).where(Source.dedupe_key == dedupe_key))
        ).scalar_one_or_none()
        if found is None:
            raise
        return found, False

    await db.refresh(source)
    logger.info("source created source_id=%s type=%s visibility=%s", source.id, source_type.value, visibility.value)
    return source, True


async def get_accessible_source(
    db: AsyncSession, source_id: str, user_id: uuid.UUID
) -> Source:
    """Nguồn công khai hoặc nguồn private của chính user. Còn lại ⇒ 404."""
    sid = parse_source_id(source_id)
    if sid is None:
        raise SourceAccessError()
    result = await db.execute(
        select(Source).where(
            Source.id == sid,
            or_(
                Source.visibility == SourceVisibility.public,
                Source.owner_id == user_id,
            ),
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise SourceAccessError()
    return source


async def get_owned_source(
    db: AsyncSession, source_id: str, user_id: uuid.UUID
) -> Source:
    """Nguồn PRIVATE thuộc đúng user hiện tại.

    Dùng cho thao tác ghi (upload/xóa): nguồn public dùng chung **không** được
    phép bị một người sửa nội dung, và nguồn private người khác trả 404 như
    `get_accessible_source` (không xác nhận tồn tại).
    """
    sid = parse_source_id(source_id)
    if sid is None:
        raise SourceAccessError()
    source = (
        await db.execute(
            select(Source).where(
                Source.id == sid,
                Source.visibility == SourceVisibility.private,
                Source.owner_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise SourceAccessError()
    return source


async def list_accessible_sources(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 20, offset: int = 0
) -> dict:
    condition = or_(Source.visibility == SourceVisibility.public, Source.owner_id == user_id)
    total = (
        await db.execute(select(func.count()).select_from(Source).where(condition))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Source)
            .where(condition)
            .order_by(Source.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    items = [to_source_out(source) for source in rows]
    return {
        "items": items,
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "hasMore": offset + len(items) < int(total),
    }


async def link_source_to_course(
    db: AsyncSession,
    course: Course,
    user_id: uuid.UUID,
    source_id: str,
    evaluation: dict | None = None,
) -> tuple[CourseSource, Source, bool]:
    """Liên kết nguồn có quyền truy cập với course của chính user.

    Idempotent theo (course_id, source_id). Authorization: source phải accessible
    với user hiện tại; course đã được route xác thực ownership trước đó.
    """
    source = await get_accessible_source(db, source_id, user_id)

    existing = (
        await db.execute(
            select(CourseSource).where(
                CourseSource.course_id == course.id,
                CourseSource.source_id == source.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, source, False

    link = CourseSource(course_id=course.id, source_id=source.id, evaluation=evaluation)
    db.add(link)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        found = (
            await db.execute(
                select(CourseSource).where(
                    CourseSource.course_id == course.id,
                    CourseSource.source_id == source.id,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise
        return found, source, False

    await db.refresh(link)
    return link, source, True


async def unlink_source_from_course(
    db: AsyncSession, course: Course, source_id: str
) -> None:
    sid = parse_source_id(source_id)
    if sid is None:
        raise SourceAccessError()
    link = (
        await db.execute(
            select(CourseSource).where(
                CourseSource.course_id == course.id, CourseSource.source_id == sid
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise SourceAccessError()
    await db.delete(link)
    await db.commit()


async def list_course_sources(
    db: AsyncSession, course_id: uuid.UUID, user_id: uuid.UUID
) -> list[tuple[CourseSource, Source]]:
    """Nguồn đã liên kết với course, chỉ gồm nguồn user hiện tại còn quyền xem.

    Nguồn private của người khác (nếu từng bị link do lỗi/lịch sử) bị lọc bỏ,
    không lộ metadata.
    """
    rows = (
        await db.execute(
            select(CourseSource, Source)
            .join(Source, Source.id == CourseSource.source_id)
            .where(
                CourseSource.course_id == course_id,
                or_(
                    Source.visibility == SourceVisibility.public,
                    Source.owner_id == user_id,
                ),
            )
            .order_by(CourseSource.created_at.asc())
        )
    ).all()
    return [(link, source) for link, source in rows]


async def load_course_sources_for_generation(
    db: AsyncSession, course: Course
) -> list[tuple[CourseSource, Source]]:
    """Load cho worker: course thuộc một user, nên lọc theo `course.user_id`.

    Worker không có identity request; ownership suy từ row course đã được xác thực
    ở tầng approve/claim.
    """
    rows = (
        await db.execute(
            select(CourseSource, Source)
            .join(Source, Source.id == CourseSource.source_id)
            .where(
                CourseSource.course_id == course.id,
                or_(
                    Source.visibility == SourceVisibility.public,
                    Source.owner_id == course.user_id,
                ),
            )
            .order_by(CourseSource.created_at.asc())
        )
    ).all()
    return [(link, source) for link, source in rows]
