"""P4.1 PostgreSQL — retrieval scope + embedding upsert trên DB thật (throwaway).

Chạy:
  POSTGRES_TEST_URL=postgresql+asyncpg://ailp:ailp_password@127.0.0.1:5433/p41_race_check \
    python -m pytest tests/test_p41_postgres_concurrency.py -q

Kiểm trên PostgreSQL thật (không chỉ SQLite):
  - FTS `to_tsvector('simple')` tìm được tiếng Việt có dấu.
  - Ownership filter áp dụng Ở SQL: user B không nhận chunk của A dù cùng course
    (dữ liệu test cố tình link nguồn A vào course B).
  - Embedding upsert đồng thời cùng spec ⇒ đúng MỘT row/chunk (UNIQUE).
  - Vector stale (`text_hash` khác) bị loại khỏi vector ranking.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import (
    Course,
    CourseSource,
    Source,
    SourceChunk,
    SourceChunkEmbedding,
    SourceDocument,
    SourceDocumentStatus,
    SourceVisibility,
    User,
)
from app.services import embedding_service, retrieval_service

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


async def _seed(sm, *, user: User, texts: list[str]) -> tuple[uuid.UUID, uuid.UUID]:
    async with sm() as db:
        course = Course(user_id=user.id, topic="RAG", client_course_id=uuid.uuid4().hex[:16])
        source = Source(
            source_type="user_document",
            title="Tài liệu PostgreSQL",
            visibility=SourceVisibility.private,
            owner_id=user.id,
            dedupe_key=f"p41-{uuid.uuid4().hex}",
            version="1.0",
        )
        db.add_all([course, source])
        await db.flush()
        document = SourceDocument(
            source_id=source.id,
            content_hash=uuid.uuid4().hex * 2,
            pipeline_version="p4.0-v1",
            storage_key=f"sources/{source.id}/{uuid.uuid4().hex}",
            status=SourceDocumentStatus.ready,
        )
        db.add(document)
        await db.flush()
        chunks = []
        for index, text in enumerate(texts):
            chunk = SourceChunk(
                document_id=document.id,
                source_id=source.id,
                chunk_index=index,
                page_number=index + 1,
                char_start=0,
                char_end=len(text),
                text=text,
                text_hash=embedding_service.hashlib.sha256(text.encode()).hexdigest(),
            )
            db.add(chunk)
            chunks.append(chunk)
        await db.flush()
        await embedding_service.embed_chunks(db, chunks)
        db.add(CourseSource(course_id=course.id, source_id=source.id))
        await db.commit()
        return course.id, source.id


async def _seed_user(sm) -> User:
    async with sm() as db:
        user = User(external_id=f"p41-{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def test_postgres_fts_finds_vietnamese_with_diacritics():
    async def run():
        engine, sm = await _prepare()
        try:
            user = await _seed_user(sm)
            course_id, _source_id = await _seed(
                sm,
                user=user,
                texts=["Ngăn xếp hoạt động theo nguyên tắc vào sau ra trước."],
            )
            async with sm() as db:
                result = await retrieval_service.retrieve(
                    db, course_id=course_id, user_id=user.id, query="ngăn xếp"
                )
            assert result.items, result.reason
            assert result.lexical_hits >= 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_postgres_never_returns_other_users_chunks():
    async def run():
        engine, sm = await _prepare()
        try:
            user_a = await _seed_user(sm)
            user_b = await _seed_user(sm)
            course_a, source_a = await _seed(
                sm, user=user_a, texts=["Bí mật lượng tử của người dùng A."]
            )
            # Cố tình link nguồn private của A vào course của B (dữ liệu xấu).
            async with sm() as db:
                course_b = Course(
                    user_id=user_b.id, topic="B", client_course_id=uuid.uuid4().hex[:16]
                )
                db.add(course_b)
                await db.flush()
                db.add(CourseSource(course_id=course_b.id, source_id=source_a))
                await db.commit()
                bad_course_id = course_b.id

            async with sm() as db:
                leaked = await retrieval_service.retrieve(
                    db, course_id=bad_course_id, user_id=user_b.id, query="lượng tử"
                )
                own = await retrieval_service.retrieve(
                    db, course_id=course_a, user_id=user_a.id, query="lượng tử"
                )
            assert leaked.items == [], "ownership filter phải áp dụng ở SQL"
            assert own.items
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_concurrent_embedding_upsert_creates_one_row_per_chunk():
    async def run():
        engine, sm = await _prepare()
        try:
            user = await _seed_user(sm)
            _course_id, source_id = await _seed(
                sm,
                user=user,
                texts=["Vòng lặp while kiểm tra điều kiện.", "Vòng lặp for đếm số lần."],
            )

            async with sm() as db:
                chunks = list(
                    (
                        await db.execute(
                            select(SourceChunk).where(SourceChunk.source_id == source_id)
                        )
                    ).scalars().all()
                )
                # Xóa vector để mô phỏng 8 tiến trình cùng backfill.
                await db.execute(
                    SourceChunkEmbedding.__table__.delete().where(
                        SourceChunkEmbedding.source_id == source_id
                    )
                )
                await db.commit()
                chunk_ids = [chunk.id for chunk in chunks]

            async def worker(session_maker):
                async with session_maker() as db:
                    rows = list(
                        (
                            await db.execute(
                                select(SourceChunk).where(SourceChunk.id.in_(chunk_ids))
                            )
                        ).scalars().all()
                    )
                    try:
                        await embedding_service.embed_chunks(db, rows)
                        await db.commit()
                    except Exception:  # noqa: BLE001 — race có thể thua UNIQUE
                        await db.rollback()

            await asyncio.gather(*[worker(sm) for _ in range(8)])

            async with sm() as db:
                count = (
                    await db.execute(
                        select(func.count())
                        .select_from(SourceChunkEmbedding)
                        .where(SourceChunkEmbedding.source_id == source_id)
                    )
                ).scalar_one()
            # Một row cho mỗi chunk (không nhân bản dù 8 worker).
            assert count == len(chunk_ids)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_stale_embedding_is_not_used_for_similarity():
    async def run():
        engine, sm = await _prepare()
        try:
            user = await _seed_user(sm)
            course_id, source_id = await _seed(
                sm, user=user, texts=["Nội dung gốc về cấu trúc dữ liệu."]
            )
            async with sm() as db:
                chunk = (
                    await db.execute(
                        select(SourceChunk).where(SourceChunk.source_id == source_id)
                    )
                ).scalar_one()
                # Đổi text + text_hash nhưng KHÔNG embed lại ⇒ vector stale.
                chunk.text = "Nội dung hoàn toàn khác về nấu ăn."
                chunk.text_hash = embedding_service.hashlib.sha256(
                    chunk.text.encode()
                ).hexdigest()
                await db.commit()

                pending = await embedding_service.chunks_missing_embedding(
                    db, source_id=source_id
                )
                assert len(pending) == 1, "chunk stale phải được coi là thiếu embedding"

                spec = embedding_service.active_spec()
                rows = (
                    await db.execute(
                        select(SourceChunkEmbedding).where(
                            SourceChunkEmbedding.source_id == source_id,
                            SourceChunkEmbedding.version == spec.version,
                            SourceChunkEmbedding.text_hash == chunk.text_hash,
                        )
                    )
                ).scalars().all()
                assert rows == [], "vector stale không được khớp text_hash mới"
        finally:
            await engine.dispose()

    asyncio.run(run())
