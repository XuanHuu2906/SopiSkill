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

# System owner for shared curated open-library books (visibility='public' in core.sources).
# Accessible ONLY when an explicit `source_ids` list (pre-authorized by core-api) is passed to `search()`.
PUBLIC_LIBRARY_OWNER_ID = "system:public_library"


@dataclass(frozen=True)
class ChunkInput:
    chunk_index: int
    content: str
    page_number: int | None = None
    section_anchor: str | None = None


@dataclass(frozen=True)
class FigureInput:
    figure_id: str
    minio_key: str
    content_type: str = "image/webp"
    section_anchor: str | None = None
    page_number: int | None = None
    label: str | None = None
    caption: str | None = None
    alt_text: str | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None


def _pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


def _sanitize_pg_text(value: str | None) -> str:
    """Remove NUL bytes and invalid lone surrogates rejected by PostgreSQL UTF-8."""
    if not value:
        return ""
    cleaned = value.replace("\x00", "")
    return cleaned.encode("utf-8", errors="ignore").decode("utf-8")


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

        spec = self._embedder.spec
        embed_batch_size = 512
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), embed_batch_size):
            batch_texts = [c.content for c in chunks[start : start + embed_batch_size]]
            vectors.extend(await self._embedder.embed_documents(batch_texts))

        safe_title = _sanitize_pg_text(source_title)[:300] or None
        insert_batch_size = 500
        if dialect == "postgresql":
            insert_sql = text(
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
            )
            for start in range(0, len(chunks), insert_batch_size):
                rows = [
                    {
                        "id": f"chk_{uuid.uuid4().hex[:20]}",
                        "owner_id": owner_id,
                        "course_id": course_id,
                        "source_id": source_id,
                        "document_id": document_id,
                        "source_title": safe_title,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "section_anchor": _sanitize_pg_text(chunk.section_anchor)[:200] or None,
                        "content": _sanitize_pg_text(chunk.content),
                        "emb_provider": spec.provider,
                        "emb_model": spec.model,
                        "emb_version": spec.version,
                        "embedding": _pgvector_literal(vec),
                    }
                    for chunk, vec in zip(
                        chunks[start : start + insert_batch_size],
                        vectors[start : start + insert_batch_size],
                    )
                ]
                await db.execute(insert_sql, rows)
        else:
            insert_sql = text(
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
            )
            for start in range(0, len(chunks), insert_batch_size):
                rows = [
                    {
                        "id": f"chk_{uuid.uuid4().hex[:20]}",
                        "owner_id": owner_id,
                        "course_id": course_id,
                        "source_id": source_id,
                        "document_id": document_id,
                        "source_title": safe_title,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "section_anchor": _sanitize_pg_text(chunk.section_anchor)[:200] or None,
                        "content": _sanitize_pg_text(chunk.content),
                        "emb_provider": spec.provider,
                        "emb_model": spec.model,
                        "emb_version": spec.version,
                        "embedding_json": json.dumps(vec),
                    }
                    for chunk, vec in zip(
                        chunks[start : start + insert_batch_size],
                        vectors[start : start + insert_batch_size],
                    )
                ]
                await db.execute(insert_sql, rows)

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
                params["public_owner_id"] = PUBLIC_LIBRARY_OWNER_ID
                vec_sql = text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor, content
                    FROM rag.document_chunks
                    WHERE source_id = ANY(:source_ids)
                      AND (
                        (owner_id = :owner_id AND (course_id = :course_id OR course_id IS NULL))
                        OR (owner_id = :public_owner_id AND course_id IS NULL)
                      )
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
                    WHERE source_id = ANY(:source_ids)
                      AND (
                        (owner_id = :owner_id AND (course_id = :course_id OR course_id IS NULL))
                        OR (owner_id = :public_owner_id AND course_id IS NULL)
                      )
                      AND tsv @@ plainto_tsquery('simple', :query_text)
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

        # SQLite fallback for offline unit tests (identical tenant/course/public-library filter + RRF).
        if source_ids:
            rows_res = await db.execute(
                text(
                    """
                    SELECT id, source_id, document_id, source_title, page_number, section_anchor,
                           content, embedding_json
                    FROM document_chunks
                    WHERE (
                        (owner_id = :owner_id AND (course_id = :course_id OR course_id IS NULL))
                        OR (owner_id = :public_owner_id AND course_id IS NULL)
                    )
                      AND embedding_provider = :emb_provider
                      AND embedding_model = :emb_model
                      AND embedding_version = :emb_version
                    """
                ),
                {
                    "owner_id": owner_id,
                    "course_id": course_id,
                    "public_owner_id": PUBLIC_LIBRARY_OWNER_ID,
                    "emb_provider": spec.provider,
                    "emb_model": spec.model,
                    "emb_version": spec.version,
                },
            )
            allowed_sources = set(source_ids)
            all_rows = [dict(r) for r in rows_res.mappings().all() if r["source_id"] in allowed_sources]
        else:
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
        fig_stmt = (
            text("DELETE FROM rag.source_figures WHERE source_id = :source_id")
            if dialect == "postgresql"
            else text("DELETE FROM source_figures WHERE source_id = :source_id")
        )
        await db.execute(fig_stmt, {"source_id": source_id})
        await db.commit()
        return int(res.rowcount or 0)

    async def replace_source_figures(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        source_id: str,
        figures: list[FigureInput],
    ) -> int:
        """Replace all indexed figures for `(owner_id, source_id)` transactionally."""
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        if dialect == "postgresql":
            await db.execute(
                text("DELETE FROM rag.source_figures WHERE owner_id = :owner_id AND source_id = :source_id"),
                {"owner_id": owner_id, "source_id": source_id},
            )
            insert_sql = text(
                """
                INSERT INTO rag.source_figures (
                    id, owner_id, source_id, figure_id, section_anchor, page_number,
                    label, caption, alt_text, minio_key, content_type, sha256, width, height
                ) VALUES (
                    :id, :owner_id, :source_id, :figure_id, :section_anchor, :page_number,
                    :label, :caption, :alt_text, :minio_key, :content_type, :sha256, :width, :height
                )
                """
            )
        else:
            await db.execute(
                text("DELETE FROM source_figures WHERE owner_id = :owner_id AND source_id = :source_id"),
                {"owner_id": owner_id, "source_id": source_id},
            )
            insert_sql = text(
                """
                INSERT INTO source_figures (
                    id, owner_id, source_id, figure_id, section_anchor, page_number,
                    label, caption, alt_text, minio_key, content_type, sha256, width, height
                ) VALUES (
                    :id, :owner_id, :source_id, :figure_id, :section_anchor, :page_number,
                    :label, :caption, :alt_text, :minio_key, :content_type, :sha256, :width, :height
                )
                """
            )
        if not figures:
            await db.commit()
            return 0
        rows = []
        seen_fig_ids: set[str] = set()
        for fig in figures:
            fid = _sanitize_pg_text(fig.figure_id)[:64].strip()
            if not fid or fid in seen_fig_ids:
                continue
            seen_fig_ids.add(fid)
            rows.append(
                {
                    "id": f"{source_id}:{fid}"[:128],
                    "owner_id": owner_id,
                    "source_id": source_id,
                    "figure_id": fid,
                    "section_anchor": (_sanitize_pg_text(fig.section_anchor)[:200] or None)
                    if fig.section_anchor
                    else None,
                    "page_number": fig.page_number,
                    "label": (_sanitize_pg_text(fig.label)[:120] or None) if fig.label else None,
                    "caption": _sanitize_pg_text(fig.caption)[:1200] if fig.caption else None,
                    "alt_text": _sanitize_pg_text(fig.alt_text)[:800] if fig.alt_text else None,
                    "minio_key": _sanitize_pg_text(fig.minio_key)[:512],
                    "content_type": (_sanitize_pg_text(fig.content_type)[:64] or "image/webp"),
                    "sha256": (_sanitize_pg_text(fig.sha256)[:64] or None) if fig.sha256 else None,
                    "width": fig.width,
                    "height": fig.height,
                }
            )
        if rows:
            for start in range(0, len(rows), 200):
                await db.execute(insert_sql, rows[start : start + 200])
        await db.commit()
        return len(rows)

    async def list_figures_for_sources(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        source_ids: list[str],
        section_anchors: list[str] | None = None,
        query: str | None = None,
        limit: int = 4,
    ) -> list[dict]:
        """Return strictly scoped figures for authorized `source_ids`, ranked by anchor & query overlap."""
        if not source_ids:
            return []
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        if dialect == "postgresql":
            res = await db.execute(
                text(
                    """
                    SELECT source_id, figure_id, section_anchor, page_number,
                           label, caption, alt_text, minio_key, content_type, width, height
                    FROM rag.source_figures
                    WHERE owner_id IN (:owner_id, :public_owner_id)
                      AND source_id = ANY(:source_ids)
                    ORDER BY page_number ASC NULLS LAST, figure_id ASC
                    LIMIT 120
                    """
                ),
                {
                    "owner_id": owner_id,
                    "public_owner_id": PUBLIC_LIBRARY_OWNER_ID,
                    "source_ids": list(source_ids),
                },
            )
            candidates = [dict(r) for r in res.mappings().all()]
        else:
            res = await db.execute(
                text(
                    """
                    SELECT source_id, figure_id, section_anchor, page_number,
                           label, caption, alt_text, minio_key, content_type, width, height
                    FROM source_figures
                    WHERE owner_id IN (:owner_id, :public_owner_id)
                    ORDER BY page_number ASC, figure_id ASC
                    """
                ),
                {"owner_id": owner_id, "public_owner_id": PUBLIC_LIBRARY_OWNER_ID},
            )
            allowed = set(source_ids)
            candidates = [dict(r) for r in res.mappings().all() if r["source_id"] in allowed]

        if not candidates:
            return []

        anchor_set = {a.strip().lower() for a in (section_anchors or []) if a and a.strip()}
        q_tokens = set(tokenize(fold_diacritics(query or "")))

        def _score(row: dict) -> tuple[float, int, str]:
            score = 0.0
            row_anchor = str(row.get("section_anchor") or "").strip().lower()
            if row_anchor and row_anchor in anchor_set:
                score += 10.0
            elif row_anchor and any(a in row_anchor or row_anchor in a for a in anchor_set):
                score += 4.0
            if q_tokens:
                text_blob = f"{row.get('label') or ''} {row.get('caption') or ''} {row.get('alt_text') or ''}"
                f_tokens = set(tokenize(fold_diacritics(text_blob)))
                score += float(len(q_tokens & f_tokens)) * 1.5
            return (-score, int(row.get("page_number") or 999999), str(row.get("figure_id") or ""))

        ranked = sorted(candidates, key=_score)[: max(1, min(limit, 8))]
        return [
            {
                "figureId": str(r["figure_id"]),
                "sourceId": str(r["source_id"]),
                "sectionAnchor": r.get("section_anchor"),
                "pageNumber": r.get("page_number"),
                "label": r.get("label") or r["figure_id"],
                "caption": r.get("caption") or "",
                "alt": r.get("alt_text") or r.get("caption") or r.get("label") or "Textbook figure",
                "contentType": r.get("content_type") or "image/webp",
                "url": f"/v1/library/figures/{r['source_id']}/{r['figure_id']}",
            }
            for r in ranked
        ]

    async def get_figure(
        self,
        db: AsyncSession,
        *,
        source_id: str,
        figure_id: str,
        owner_id: str | None = None,
    ) -> dict | None:
        """Fetch a single figure registry record by `(source_id, figure_id)` scoped to owner or public library."""
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
        owners = [PUBLIC_LIBRARY_OWNER_ID]
        if owner_id and owner_id != PUBLIC_LIBRARY_OWNER_ID:
            owners.append(owner_id)
        if dialect == "postgresql":
            res = await db.execute(
                text(
                    """
                    SELECT source_id, figure_id, minio_key, content_type, label, caption, alt_text
                    FROM rag.source_figures
                    WHERE source_id = :source_id
                      AND figure_id = :figure_id
                      AND owner_id = ANY(:owners)
                    LIMIT 1
                    """
                ),
                {"source_id": source_id, "figure_id": figure_id, "owners": owners},
            )
            row = res.mappings().first()
            return dict(row) if row else None
        res = await db.execute(
            text(
                """
                SELECT owner_id, source_id, figure_id, minio_key, content_type, label, caption, alt_text
                FROM source_figures
                WHERE source_id = :source_id AND figure_id = :figure_id
                """
            ),
            {"source_id": source_id, "figure_id": figure_id},
        )
        for r in res.mappings().all():
            if r["owner_id"] in owners:
                return dict(r)
        return None
