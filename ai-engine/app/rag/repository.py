"""Hybrid RAG repository: PostgreSQL pgvector (HNSW cosine) + PostgreSQL FTS (GIN) + RRF.

All queries are strictly scoped by `owner_id` (and `course_id` / optional `source_ids`) so
cross-tenant chunks can never be retrieved.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.rag.embedding import EmbeddingProvider, fold_diacritics, get_embedding_provider, tokenize
from app.schemas.internal import RagChunkHitOut


@dataclass(frozen=True)
class ChunkInput:
    chunk_index: int
    content: str
    page_number: int | None = None
    section_anchor: str | None = None


def _pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def combine_rrf(
    vector_rows: list[dict],
    fts_rows: list[dict],
    *,
    rrf_k: int = 60,
    top_k: int = 5,
) -> list[RagChunkHitOut]:
    """Reciprocal Rank Fusion (RRF) combining vector + full-text rankings deterministically."""
    scores: dict[str, float] = {}
    meta: dict[str, dict] = {}

    for rank, row in enumerate(vector_rows, start=1):
        cid = str(row["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        meta.setdefault(cid, row)

    for rank, row in enumerate(fts_rows, start=1):
        cid = str(row["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
        meta.setdefault(cid, row)

    ranked_ids = sorted(scores.keys(), key=lambda cid: (-scores[cid], cid))[:top_k]
    hits: list[RagChunkHitOut] = []
    for cid in ranked_ids:
        row = meta[cid]
        hits.append(
            RagChunkHitOut(
                chunkId=cid,
                sourceId=str(row["source_id"]),
                documentId=row.get("document_id"),
                sourceTitle=row.get("source_title"),
                pageNumber=row.get("page_number"),
                sectionAnchor=row.get("section_anchor"),
                content=str(row["content"]),
                score=round(scores[cid], 6),
            )
        )
    return hits


class RagRepository:
    """Owner-scoped storage and Hybrid RAG RRF retrieval on `rag.document_chunks`."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedder = embedding_provider or get_embedding_provider(self._settings)

    async def replace_document_chunks(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        course_id: str | None,
        source_id: str,
        document_id: str,
        source_title: str | None,
        chunks: list[ChunkInput],
    ) -> int:
        """Replace all chunks for `(owner_id, source_id, document_id)` transactionally."""
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"

        if dialect == "postgresql":
            await db.execute(
                text(
                    "DELETE FROM rag.document_chunks "
                    "WHERE owner_id = :owner_id AND document_id = :document_id"
                ),
                {"owner_id": owner_id, "document_id": document_id},
            )
        else:
            await db.execute(
                text(
                    "DELETE FROM document_chunks "
                    "WHERE owner_id = :owner_id AND document_id = :document_id"
                ),
                {"owner_id": owner_id, "document_id": document_id},
            )

        if not chunks:
            await db.commit()
            return 0

        vectors = await self._embedder.embed_documents([c.content for c in chunks])
        spec = self._embedder.spec

        for chunk, vec in zip(chunks, vectors):
            chunk_id = f"chk_{uuid.uuid4().hex[:20]}"
            if dialect == "postgresql":
                await db.execute(
                    text(
                        """
                        INSERT INTO rag.document_chunks (
                            id, owner_id, course_id, source_id, document_id, source_title,
                            chunk_index, page_number, section_anchor, content,
                            embedding_provider, embedding_model, embedding_version, embedding
                        ) VALUES (
                            :id, :owner_id, :course_id, :source_id, :document_id, :source_title,
                            :chunk_index, :page_number, :section_anchor, :content,
                            :emb_provider, :emb_model, :emb_version, CAST(:embedding AS vector)
                        )
                        """
                    ),
                    {
                        "id": chunk_id,
                        "owner_id": owner_id,
                        "course_id": course_id,
                        "source_id": source_id,
                        "document_id": document_id,
                        "source_title": source_title,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "section_anchor": chunk.section_anchor,
                        "content": chunk.content,
                        "emb_provider": spec.provider,
                        "emb_model": spec.model,
                        "emb_version": spec.version,
                        "embedding": _pgvector_literal(vec),
                    },
                )
            else:
                await db.execute(
                    text(
                        """
                        INSERT INTO document_chunks (
                            id, owner_id, course_id, source_id, document_id, source_title,
                            chunk_index, page_number, section_anchor, content,
                            embedding_provider, embedding_model, embedding_version, embedding_json
                        ) VALUES (
                            :id, :owner_id, :course_id, :source_id, :document_id, :source_title,
                            :chunk_index, :page_number, :section_anchor, :content,
                            :emb_provider, :emb_model, :emb_version, :embedding_json
                        )
                        """
                    ),
                    {
                        "id": chunk_id,
                        "owner_id": owner_id,
                        "course_id": course_id,
                        "source_id": source_id,
                        "document_id": document_id,
                        "source_title": source_title,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "section_anchor": chunk.section_anchor,
                        "content": chunk.content,
                        "emb_provider": spec.provider,
                        "emb_model": spec.model,
                        "emb_version": spec.version,
                        "embedding_json": json.dumps(vec),
                    },
                )

        await db.commit()
        return len(chunks)

    async def search(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        course_id: str,
        query: str,
        source_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> tuple[Literal["hybrid_rrf", "fts_only", "hashing_baseline"], list[RagChunkHitOut]]:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        qvec = await self._embedder.embed_query(query)
        spec = self._embedder.spec
        cand_limit = max(top_k * 4, int(self._settings.rag_candidate_limit))
        rrf_k = max(1, int(self._settings.rag_rrf_k))

        if dialect == "postgresql":
            params: dict = {
                "owner_id": owner_id,
                "course_id": course_id,
                "emb_provider": spec.provider,
                "emb_model": spec.model,
                "emb_version": spec.version,
                "qvec": _pgvector_literal(qvec),
                "query_text": query,
                "cand_limit": cand_limit,
            }
            if source_ids:
                params["source_ids"] = list(source_ids)
                vec_sql = text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor, content
                    FROM rag.document_chunks
                    WHERE owner_id = :owner_id
                      AND (course_id = :course_id OR course_id IS NULL)
                      AND embedding_provider = :emb_provider
                      AND embedding_model = :emb_model
                      AND embedding_version = :emb_version
                      AND embedding IS NOT NULL
                      AND source_id = ANY(:source_ids)
                    ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                    LIMIT :cand_limit
                    """
                )
                fts_sql = text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor, content
                    FROM rag.document_chunks
                    WHERE owner_id = :owner_id
                      AND (course_id = :course_id OR course_id IS NULL)
                      AND tsv @@ plainto_tsquery('simple', :query_text)
                      AND source_id = ANY(:source_ids)
                    ORDER BY ts_rank_cd(tsv, plainto_tsquery('simple', :query_text)) DESC
                    LIMIT :cand_limit
                    """
                )
            else:
                vec_sql = text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor, content
                    FROM rag.document_chunks
                    WHERE owner_id = :owner_id
                      AND (course_id = :course_id OR course_id IS NULL)
                      AND embedding_provider = :emb_provider
                      AND embedding_model = :emb_model
                      AND embedding_version = :emb_version
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                    LIMIT :cand_limit
                    """
                )
                fts_sql = text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor, content
                    FROM rag.document_chunks
                    WHERE owner_id = :owner_id
                      AND (course_id = :course_id OR course_id IS NULL)
                      AND tsv @@ plainto_tsquery('simple', :query_text)
                    ORDER BY ts_rank_cd(tsv, plainto_tsquery('simple', :query_text)) DESC
                    LIMIT :cand_limit
                    """
                )
            vec_res = await db.execute(vec_sql, params)
            fts_res = await db.execute(fts_sql, params)
            vec_rows = [dict(r) for r in vec_res.mappings().all()]
            fts_rows = [dict(r) for r in fts_res.mappings().all()]
            hits = combine_rrf(vec_rows, fts_rows, rrf_k=rrf_k, top_k=top_k)
            return "hybrid_rrf", hits

        # SQLite fallback for offline unit tests (identical tenant/course filter + RRF).
        rows_res = await db.execute(
            text(
                """
                SELECT id, source_id, document_id, source_title, page_number, section_anchor,
                       content, embedding_json
                FROM document_chunks
                WHERE owner_id = :owner_id
                  AND (course_id = :course_id OR course_id IS NULL)
                  AND embedding_provider = :emb_provider
                  AND embedding_model = :emb_model
                  AND embedding_version = :emb_version
                """
            ),
            {
                "owner_id": owner_id,
                "course_id": course_id,
                "emb_provider": spec.provider,
                "emb_model": spec.model,
                "emb_version": spec.version,
            },
        )
        all_rows = [dict(r) for r in rows_res.mappings().all()]
        if source_ids:
            allowed_sources = set(source_ids)
            all_rows = [r for r in all_rows if r["source_id"] in allowed_sources]

        q_tokens = set(tokenize(fold_diacritics(query)))
        vec_scored: list[tuple[float, dict]] = []
        fts_scored: list[tuple[float, dict]] = []
        for row in all_rows:
            vec = json.loads(row.get("embedding_json") or "[]")
            vscore = _cosine(qvec, vec)
            vec_scored.append((vscore, row))
            c_tokens = set(tokenize(fold_diacritics(str(row["content"]))))
            overlap = len(q_tokens & c_tokens)
            if overlap > 0:
                fts_scored.append((overlap / max(1, len(q_tokens)), row))

        vec_ranked = [r for _, r in sorted(vec_scored, key=lambda pair: (-pair[0], pair[1]["id"]))[:cand_limit]]
        fts_ranked = [r for _, r in sorted(fts_scored, key=lambda pair: (-pair[0], pair[1]["id"]))[:cand_limit]]
        hits = combine_rrf(vec_ranked, fts_ranked, rrf_k=rrf_k, top_k=top_k)
        return "hashing_baseline", hits

    async def delete_by_user(self, db: AsyncSession, owner_id: str) -> int:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        stmt = (
            text("DELETE FROM rag.document_chunks WHERE owner_id = :owner_id")
            if dialect == "postgresql"
            else text("DELETE FROM document_chunks WHERE owner_id = :owner_id")
        )
        res = await db.execute(stmt, {"owner_id": owner_id})
        await db.commit()
        return int(res.rowcount or 0)

    async def delete_by_course(self, db: AsyncSession, course_id: str) -> int:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        stmt = (
            text("DELETE FROM rag.document_chunks WHERE course_id = :course_id")
            if dialect == "postgresql"
            else text("DELETE FROM document_chunks WHERE course_id = :course_id")
        )
        res = await db.execute(stmt, {"course_id": course_id})
        await db.commit()
        return int(res.rowcount or 0)

    async def delete_by_source(self, db: AsyncSession, source_id: str) -> int:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        stmt = (
            text("DELETE FROM rag.document_chunks WHERE source_id = :source_id")
            if dialect == "postgresql"
            else text("DELETE FROM document_chunks WHERE source_id = :source_id")
        )
        res = await db.execute(stmt, {"source_id": source_id})
        await db.commit()
        return int(res.rowcount or 0)
