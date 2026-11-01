"""P4.2 PostgreSQL — concurrent web ingest idempotency trên DB thật (throwaway).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p42_race_check \
    python -m pytest tests/test_p42_postgres_concurrency.py -q

Kiểm trên PostgreSQL thật (không chỉ SQLite):
  - 10 request fetch CÙNG nội dung đồng thời ⇒ đúng MỘT `source_document` và
    MỘT bộ chunk (UNIQUE(source_id, content_hash, pipeline_version)).
  - `rights_confirmed_at` được ghi thật, `origin` = web.
  - Chunk của document web có provenance offset khớp text đã lưu.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import (
    Source,
    SourceChunk,
    SourceDocument,
    SourceDocumentOrigin,
    SourceVisibility,
    User,
)
from app.services import storage, url_fetcher, web_ingest

TEST_URL = os.environ.get("POSTGRES_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Set POSTGRES_TEST_URL to a throwaway PostgreSQL DB to run race tests"
)

PUBLIC_IP = "93.184.216.34"
HOST = "docs.example.com"

PAGE = """<html><head><title>RAG</title></head><body>
<h1>Truy xuất tăng cường</h1>
<p>RAG kết hợp truy xuất tài liệu với mô hình sinh ngôn ngữ để trả lời có căn cứ.</p>
<h2>Đánh giá</h2>
<p>Đo recall, precision và mức độ trung thực của câu trả lời.</p>
</body></html>"""


def _settings():
    from app.core.config import get_settings

    settings = get_settings()
    # Settings được cache; patch trực tiếp instance cho test này.
    settings.web_ingest_enabled = True  # type: ignore[misc]
    settings.web_ingest_allowed_hosts = HOST  # type: ignore[misc]
    settings.web_ingest_respect_robots = False  # type: ignore[misc]
    return settings


def _transport():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=PAGE.encode()
        )

    return httpx.MockTransport(handler)


async def _prepare():
    engine = create_async_engine(TEST_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(sm) -> uuid.UUID:
    async with sm() as db:
        user = User(external_id=f"p42-{uuid.uuid4().hex[:8]}", display_name="Racer")
        db.add(user)
        await db.flush()
        source = Source(
            source_type="webpage",
            title="Nguồn web race",
            visibility=SourceVisibility.private,
            owner_id=user.id,
            dedupe_key=f"p42-{uuid.uuid4().hex}",
        )
        db.add(source)
        await db.commit()
        return source.id


async def test_concurrent_web_fetch_creates_one_document():
    original_resolve = url_fetcher.resolve_host_ips

    async def fake_resolve(host: str) -> list[str]:
        return [PUBLIC_IP]

    url_fetcher.resolve_host_ips = fake_resolve
    transport = _transport()
    settings = _settings()
    original_build = url_fetcher.build_pinned_transport
    url_fetcher.build_pinned_transport = lambda **_kw: transport

    engine, sm = await _prepare()
    try:
        source_id = await _seed(sm)

        async def one() -> uuid.UUID:
            async with sm() as db:
                source = await db.get(Source, source_id)
                document, _created = await web_ingest.register_web_document(
                    db,
                    source,
                    url=f"https://{HOST}/rag",
                    user_confirmed_rights=True,
                    settings=settings,
                )
                return document.id

        ids = await asyncio.gather(*[one() for _ in range(10)])
        assert len(set(ids)) == 1, "fetch đồng thời cùng nội dung phải trả CÙNG document"

        async with sm() as db:
            doc_count = (
                await db.execute(
                    select(func.count())
                    .select_from(SourceDocument)
                    .where(SourceDocument.source_id == source_id)
                )
            ).scalar_one()
            assert doc_count == 1

            document = (
                await db.execute(
                    select(SourceDocument).where(SourceDocument.source_id == source_id)
                )
            ).scalar_one()
            assert document.origin == SourceDocumentOrigin.web
            assert document.rights_confirmed_at is not None
            assert document.origin_url == f"https://{HOST}/rag"

        # Worker xử lý document (chạy đúng pipeline web), chỉ một bộ chunk.
        # Dùng `_ingest` với sessionmaker của DB test (không phải engine mặc định
        # của app, vốn trỏ SQLite trong bộ test offline).
        from app.worker.ingest import _ingest

        await _ingest(sm, str(document.id))
        async with sm() as db:
            refreshed = await db.get(SourceDocument, document.id)
            assert refreshed is not None
            assert refreshed.status.value == "ready"
            chunks = list(
                (
                    await db.execute(
                        select(SourceChunk)
                        .where(SourceChunk.document_id == document.id)
                        .order_by(SourceChunk.chunk_index)
                    )
                ).scalars().all()
            )
            assert chunks
            assert len({chunk.chunk_index for chunk in chunks}) == len(chunks)

            extraction = web_ingest.parse_web_extraction(
                storage.get_storage().get(refreshed.storage_key)
            )
            for chunk in chunks:
                assert chunk.text == extraction.text[chunk.char_start : chunk.char_end]

        # Ingest lại (retry) không nhân bản chunk.
        await _ingest(sm, str(document.id))
        async with sm() as db:
            count_after = (
                await db.execute(
                    select(func.count())
                    .select_from(SourceChunk)
                    .where(SourceChunk.document_id == document.id)
                )
            ).scalar_one()
        assert count_after == len(chunks)
    finally:
        url_fetcher.resolve_host_ips = original_resolve
        url_fetcher.build_pinned_transport = original_build
        await engine.dispose()
