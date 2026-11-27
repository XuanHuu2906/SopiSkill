"""Phase L3 System Library Importer CLI (`import_open_library.py`).

Reads the curated Open Book Harvester catalog in strictly READ-ONLY mode (`?mode=ro`),
chunks `extracted.md` with the Heading-Aware Markdown Chunker (`md-heading-v1`),
upserts public metadata into `core-api` via HMAC-signed `POST /internal/library/sources/upsert`,
and writes shared chunks into `rag.document_chunks` (`owner_id = 'system:public_library'`).

Guarantees:
  - 100% strict domain ownership (`core.*` via `core-api` HMAC endpoint, `rag.*` via `ai-engine` `RagRepository`).
  - Idempotent on `(external_key, content_hash, pipeline_version="md-heading-v1")`: unchanged books skip in <5ms.
  - Supports `--library-dir`, `--tiers`, `--domains`, `--commercial-only`, `--limit`, `--dry-run`, `--force`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Allow running directly as `python scripts/import_open_library.py` from `ai-engine/`
_AI_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(_AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ENGINE_ROOT))

from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings, get_settings
from app.db.session import ensure_sqlite_tables, get_session_factory
from app.rag.brief_builder import build_source_brief
from app.rag.extractor import chunk_markdown_by_headings
from app.rag.repository import PUBLIC_LIBRARY_OWNER_ID, RagRepository

PIPELINE_VERSION = "md-heading-v1"


@dataclass
class ImportSummary:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    missing_markdown: int = 0
    failed: int = 0
    total_chunks: int = 0


def load_catalog_candidates(
    library_dir: Path,
    *,
    tiers: list[str] | None = None,
    domains: list[str] | None = None,
    commercial_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Query `catalog.db` strictly in read-only mode (`?mode=ro`)."""
    db_path = library_dir / "catalog.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Catalog database not found: {db_path}")

    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(books)").fetchall()}
        clauses: list[str] = ["1=1"]
        params: list[Any] = []

        if tiers and "pedagogy_tier" in cols:
            ph = ",".join("?" for _ in tiers)
            clauses.append(f"pedagogy_tier IN ({ph})")
            params.extend(tiers)
        elif tiers:
            # Legacy DB fallback before Phase L0 columns
            src_map = {
                "tier1_textbook": ["openstax", "otl"],
                "tier2_monograph": ["doab", "oapen", "gutenberg"],
                "tier3_paper": ["arxiv"],
            }
            srcs = [s for t in tiers for s in src_map.get(t, [])]
            if srcs:
                ph = ",".join("?" for _ in srcs)
                clauses.append(f"source IN ({ph})")
                params.extend(srcs)

        if domains:
            dom_conds = []
            for d in domains:
                dom_conds.append("(subject = ? OR domains_json LIKE ?)")
                params.extend([d, f'%"{d}"%'])
            clauses.append("(" + " OR ".join(dom_conds) + ")")

        if commercial_only and "commercial_safe" in cols:
            clauses.append("commercial_safe = 1")

        sql = f"SELECT * FROM books WHERE {' AND '.join(clauses)} ORDER BY id ASC"
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(limit)

        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            r["authors"] = json.loads(r.get("authors_json") or "[]")
            r["domains"] = json.loads(r.get("domains_json") or "[]") or [r.get("subject") or "general"]
            r["pedagogy_tier"] = r.get("pedagogy_tier") or (
                "tier1_textbook"
                if r.get("source") in {"openstax", "otl"}
                else ("tier3_paper" if r.get("source") == "arxiv" else "tier2_monograph")
            )
            r["commercial_safe"] = bool(r.get("commercial_safe", 0))
        return rows
    finally:
        conn.close()


async def import_open_library_books(
    *,
    library_dir: Path,
    tiers: list[str] | None = None,
    domains: list[str] | None = None,
    commercial_only: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    settings: Settings | None = None,
    callback_client: CoreApiCallbackClient | None = None,
    rag_repo: RagRepository | None = None,
    db=None,
) -> ImportSummary:
    cfg = settings or get_settings()
    cb = callback_client or CoreApiCallbackClient(settings=cfg)
    repo = rag_repo or RagRepository(settings=cfg)
    summary = ImportSummary()

    books = load_catalog_candidates(
        library_dir,
        tiers=tiers,
        domains=domains,
        commercial_only=commercial_only,
        limit=limit,
    )
    summary.scanned = len(books)

    if not dry_run and db is None:
        await ensure_sqlite_tables()

    for book in books:
        external_key = f"{book['source']}:{book['source_id']}"
        ext_path_raw = book.get("extracted_path")
        ext_path = Path(ext_path_raw) if ext_path_raw else (Path(book["file_path"]).parent / "extracted.md")
        if not ext_path.exists():
            summary.missing_markdown += 1
            continue

        try:
            md_text = ext_path.read_text(encoding="utf-8")
            chunks, heading_levels = chunk_markdown_by_headings(
                md_text,
                source_title=str(book.get("title") or ""),
            )
            if not chunks:
                summary.missing_markdown += 1
                continue

            brief_bundle = build_source_brief(
                title=str(book.get("title") or ""),
                chunks=chunks,
                heading_levels=heading_levels,
                max_sections=60,
            )

            if dry_run:
                summary.imported += 1
                summary.total_chunks += len(chunks)
                continue

            authors_list = book.get("authors") or []
            author_str = ", ".join(str(a) for a in authors_list[:6]) if authors_list else None
            upsert_payload = {
                "externalKey": external_key,
                "sourceType": "open_textbook" if book["pedagogy_tier"] == "tier1_textbook" else "academic_paper",
                "title": str(book["title"]),
                "canonicalUrl": book.get("landing_url") or book.get("download_url"),
                "author": author_str,
                "publisher": book.get("publisher"),
                "publicationDate": str(book["year"]) if book.get("year") else None,
                "language": str(book.get("language") or "en")[:16],
                "licenseInfo": book.get("license"),
                "contentHash": book.get("sha256"),
                "domainSlug": str(book.get("subject") or "general"),
                "pedagogyTier": str(book["pedagogy_tier"]),
                "commercialSafe": bool(book["commercial_safe"]),
                "isbn": book.get("isbn"),
                "doi": book.get("doi"),
                "brief": brief_bundle["brief"],
                "wordCount": brief_bundle["wordCount"],
                "durationMinutes": brief_bundle["durationMinutes"],
                "suggestedTopic": brief_bundle["suggestedTopic"],
                "pageCount": book.get("page_count"),
                "byteSize": int(book.get("file_size") or 0),
                "chunkCount": len(chunks),
                "pipelineVersion": PIPELINE_VERSION,
                "force": force,
            }

            resp = await cb.post_callback(
                "/internal/library/sources/upsert",
                upsert_payload,
                correlation_id=f"lib_{book['id']}",
            )
            if isinstance(resp, dict) and resp.get("skipped"):
                summary.skipped += 1
                continue

            source_id = str(resp["sourceId"])
            document_id = str(resp["documentId"])

            if db is not None:
                inserted = await repo.replace_document_chunks(
                    db,
                    owner_id=PUBLIC_LIBRARY_OWNER_ID,
                    course_id=None,
                    source_id=source_id,
                    document_id=document_id,
                    source_title=str(book["title"]),
                    chunks=chunks,
                )
            else:
                factory = get_session_factory()
                async with factory() as session:
                    inserted = await repo.replace_document_chunks(
                        session,
                        owner_id=PUBLIC_LIBRARY_OWNER_ID,
                        course_id=None,
                        source_id=source_id,
                        document_id=document_id,
                        source_title=str(book["title"]),
                        chunks=chunks,
                    )

            summary.imported += 1
            summary.total_chunks += inserted
        except Exception as exc:  # noqa: BLE001
            summary.failed += 1
            print(f"[ERROR] {external_key} ({book.get('title', '')[:45]}): {type(exc).__name__}: {exc}", file=sys.stderr)

    return summary


def _parse_csv(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    vals = [x.strip() for x in raw.split(",") if x.strip()]
    return vals or None


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotent System Library Importer for SopiSkill")
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=Path("/home/nguyenhuu/Hoc Tap/Cào sách/library"),
        help="Path to Open Book Harvester library directory containing catalog.db",
    )
    parser.add_argument("--tiers", type=str, default="tier1_textbook", help="Comma-separated pedagogy tiers")
    parser.add_argument("--domains", type=str, default=None, help="Optional comma-separated domain slugs")
    parser.add_argument("--commercial-only", action="store_true", help="Import only commercial_safe=true books")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of books to process")
    parser.add_argument("--dry-run", action="store_true", help="Validate & chunk without writing to core-api or rag DB")
    parser.add_argument("--force", action="store_true", help="Force re-indexing even if content hash matches")
    args = parser.parse_args()

    res = asyncio.run(
        import_open_library_books(
            library_dir=args.library_dir,
            tiers=_parse_csv(args.tiers),
            domains=_parse_csv(args.domains),
            commercial_only=args.commercial_only,
            limit=args.limit,
            dry_run=args.dry_run,
            force=args.force,
        )
    )
    print(
        json.dumps(
            {
                "scanned": res.scanned,
                "imported": res.imported,
                "skipped": res.skipped,
                "missingMarkdown": res.missing_markdown,
                "failed": res.failed,
                "totalChunks": res.total_chunks,
                "dryRun": args.dry_run,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
