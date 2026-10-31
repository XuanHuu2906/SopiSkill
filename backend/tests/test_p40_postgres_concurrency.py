"""P4.0 PostgreSQL — ingest claim/idempotency trên DB thật (throwaway).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p40_race_check \
    python -m pytest tests/test_p40_postgres_concurrency.py -q

Kiểm:
  - Upload cùng bytes từ nhiều tiến trình ⇒ đúng MỘT document (unique constraint).
  - Claim document nguyên tử: nhiều worker claim cùng lúc ⇒ chỉ một thắng.
  - Không đọc được document của user khác ở tầng query.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import (
    Source,
    SourceDocument,
    SourceDocumentStatus,
    SourceVisibility,
    SourceVerificationStatus,
    User,
)
from app.services import ingest

from .pdf_fixtures import pdf_with_heading_pages

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests"
)


async def _prepare():
    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed_source(sm) -> tuple[uuid.UUID, uuid.UUID]:
    async with sm() as db:
        user = User(external_id=f"p40-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.flush()
        source = Source(
            source_type="user_document",
            title=f"Doc {uuid.uuid4().hex[:6]}",
            visibility=SourceVisibility.private,
            verification_status=SourceVerificationStatus.unverified,
            owner_id=user.id,
            dedupe_key=f"p40-{uuid.uuid4().hex}",
        )
        db.add(source)
        await db.commit()
        return user.id, source.id


def test_concurrent_register_creates_one_document():
    async def run():
        engine, sm = await _prepare()
        try:
            _user_id, source_id = await _seed_source(sm)
            data = pdf_with_heading_pages()

            async def upload() -> uuid.UUID:
                async with sm() as db:
                    source = (
                        await db.execute(select(Source).where(Source.id == source_id))
                    ).scalar_one()
                    document, _created = await ingest.register_document(
                        db, source, data=data, filename="race.pdf"
                    )
                    return document.id

            ids = await asyncio.gather(*[upload() for _ in range(8)])
            assert len(set(ids)) == 1

            async with sm() as db:
                count = len(
                    (
                        await db.execute(
                            select(SourceDocument).where(SourceDocument.source_id == source_id)
                        )
                    )
                    .scalars()
                    .all()
                )
            assert count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_atomic_claim_allows_single_worker():
    async def run():
        engine, sm = await _prepare()
        try:
            _user_id, source_id = await _seed_source(sm)
            async with sm() as db:
                source = (
                    await db.execute(select(Source).where(Source.id == source_id))
                ).scalar_one()
                document, _ = await ingest.register_document(
                    db, source, data=pdf_with_heading_pages(), filename="claim.pdf"
                )
                document_id = document.id

            async def claim() -> bool:
                async with sm() as db:
                    claimed = await ingest.claim_document(db, document_id)
                    return claimed is not None

            results = await asyncio.gather(*[claim() for _ in range(6)])
            assert sum(1 for ok in results if ok) == 1

            async with sm() as db:
                row = (
                    await db.execute(
                        select(SourceDocument).where(SourceDocument.id == document_id)
                    )
                ).scalar_one()
            assert row.status == SourceDocumentStatus.extracting
            assert row.attempts_count == 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cross_user_document_lookup_is_denied():
    async def run():
        engine, sm = await _prepare()
        try:
            owner_id, source_id = await _seed_source(sm)
            async with sm() as db:
                source = (
                    await db.execute(select(Source).where(Source.id == source_id))
                ).scalar_one()
                document, _ = await ingest.register_document(
                    db, source, data=pdf_with_heading_pages(), filename="cross.pdf"
                )
                document_id = document.id

            async with sm() as db:
                found, _source = await ingest.get_owned_document(db, str(document_id), owner_id)
                assert found.id == document_id

            async with sm() as db:
                with pytest.raises(ingest.IngestError) as exc:
                    await ingest.get_owned_document(db, str(document_id), uuid.uuid4())
                assert exc.value.code == "SOURCE_DOCUMENT_NOT_FOUND"
        finally:
            await engine.dispose()

    asyncio.run(run())
