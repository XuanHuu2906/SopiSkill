"""Phase L3 System Library Importer CLI (`import_open_library.py`).

Reads curated books from `sopiskill_manifest.jsonl` (Phase C6 cleaned output: pre-verified
`chunks.jsonl` + `brief.json` + `glossary.json`) when present, with automatic fallback to
read-only `catalog.db?mode=ro` (`clean.md` / `extracted.md`), upserts public metadata into
`core-api` via HMAC-signed `POST /internal/library/sources/upsert`, and batch-writes shared
chunks into `rag.document_chunks` (`owner_id = 'system:public_library'`).

Guarantees:
  - 100% strict domain ownership (`core.*` via `core-api` HMAC endpoint, `rag.*` via `ai-engine` `RagRepository`).
  - Idempotent on `(external_key, content_hash, pipeline_version)`: unchanged books skip in <5ms.
  - Supports `--manifest`, `--library-dir`, `--tiers`, `--domains`, `--commercial-only`, `--limit`, `--dry-run`, `--force`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
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
from app.db.session import dispose_engine, ensure_sqlite_tables, get_session_factory
from app.rag.brief_builder import build_source_brief
from app.rag.extractor import chunk_markdown_by_headings
from app.rag.repository import ChunkInput, FigureInput, PUBLIC_LIBRARY_OWNER_ID, RagRepository
from app.rag.storage import get_source_storage

PIPELINE_VERSION = "md-heading-v1"
CLEAN_MANIFEST_FILENAME = "sopiskill_manifest.jsonl"


def _strip_nul(obj: Any) -> Any:
    """Recursively remove NUL bytes and invalid lone surrogates before PostgreSQL UTF-8/JSONB writes."""
    if isinstance(obj, str):
        return obj.replace("\x00", "").encode("utf-8", errors="ignore").decode("utf-8")
    if isinstance(obj, list):
        return [_strip_nul(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _strip_nul(v) for k, v in obj.items()}
    return obj


@dataclass
class ImportSummary:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    missing_markdown: int = 0
    failed: int = 0
    total_chunks: int = 0
    total_figures: int = 0


def _normalize_figure_bytes(src_file: Path) -> tuple[bytes, str, str, int | None, int | None] | None:
    """Normalize local figure image to compressed <=1200px WebP (preserving SVG as image/svg+xml)."""
    if not src_file.exists() or not src_file.is_file():
        return None
    raw = src_file.read_bytes()
    if not raw or len(raw) > 15 * 1024 * 1024:
        return None
    ext = src_file.suffix.lower()
    if ext == ".svg" or raw[:300].lstrip().lower().startswith((b"<svg", b"<?xml")):
        return raw, ".svg", "image/svg+xml", None, None

    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw)) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            max_dim = 1200
            if max(img.width, img.height) > max_dim:
                img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=82, method=4)
            return buf.getvalue(), ".webp", "image/webp", img.width, img.height
    except Exception:
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
        if ext in mime_map:
            return raw, ext, mime_map[ext], None, None
        return None


async def _upload_and_prepare_figures(
    book: dict[str, Any],
    *,
    external_key: str,
    cfg: Settings,
    upload_figures: bool,
) -> list[FigureInput]:
    """Load `figures_manifest.json` next to `chunks.jsonl`, upload images to MinIO, and return FigureInputs."""
    chunks_path_raw = book.get("chunks_path")
    file_path_raw = book.get("file_path")
    book_dir = (
        Path(str(chunks_path_raw)).parent
        if chunks_path_raw
        else (Path(str(file_path_raw)).parent if file_path_raw else None)
    )
    if book_dir is None:
        return []
    manifest_file = book_dir / "figures_manifest.json"
    if not manifest_file.exists():
        return []

    try:
        raw_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw_figs = raw_manifest.get("figures") or []
    if not isinstance(raw_figs, list) or not raw_figs:
        return []

    safe_book_key = re.sub(r"[^a-zA-Z0-9._-]+", "_", external_key).strip("_")[:120] or "book"
    storage = get_source_storage(cfg) if upload_figures else None
    out: list[FigureInput] = []
    for fg in raw_figs:
        if not isinstance(fg, dict):
            continue
        fig_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(fg.get("figureId") or "")).strip("_")[:64]
        local_raw = fg.get("localPath")
        if not fig_id or not local_raw:
            continue
        norm = _normalize_figure_bytes(Path(str(local_raw)))
        if norm is None:
            continue
        data, ext, ctype, width, height = norm
        sha = hashlib.sha256(data).hexdigest()
        minio_key = f"library-figures/{safe_book_key}/{fig_id}{ext}"
        if storage is not None:
            await storage.put_bytes_async(minio_key, data, content_type=ctype)
        out.append(
            FigureInput(
                figure_id=fig_id,
                minio_key=minio_key,
                content_type=ctype,
                section_anchor=str(fg.get("sectionAnchor") or "")[:200] or None,
                page_number=int(fg["pageNumber"]) if fg.get("pageNumber") is not None else None,
                label=str(fg.get("label") or fig_id)[:120],
                caption=str(fg.get("caption") or "")[:1200],
                alt_text=str(fg.get("alt") or fg.get("caption") or fig_id)[:800],
                sha256=sha,
                width=width,
                height=height,
            )
        )
    return out


def load_manifest_candidates(
    manifest_path: Path,
    *,
    tiers: list[str] | None = None,
    domains: list[str] | None = None,
    commercial_only: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load pre-curated, Quality-Gate-verified books from `sopiskill_manifest.jsonl`."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

    tier_set = set(tiers) if tiers else None
    domain_set = set(domains) if domains else None
    rows: list[dict[str, Any]] = []

    with manifest_path.open("r", encoding="utf-8") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tier = str(rec.get("pedagogyTier") or "tier1_textbook")
            if tier_set and tier not in tier_set:
                continue

            primary_domain = str(rec.get("primaryDomain") or "general")
            rec_domains = list(rec.get("domains") or [primary_domain])
            if domain_set and not (domain_set.intersection(rec_domains) or primary_domain in domain_set):
                continue

            comm_safe = bool(rec.get("commercialSafe", False))
            if commercial_only and not comm_safe:
                continue

            ekey = str(rec.get("externalKey") or "").strip()
            src_name, _, src_id = ekey.partition(":")
            rows.append(
                {
                    "id": line_no,
                    "external_key": ekey,
                    "source": src_name or "library",
                    "source_id": src_id or str(line_no),
                    "title": str(rec.get("title") or "").strip(),
                    "authors": list(rec.get("authors") or []),
                    "publisher": rec.get("publisher"),
                    "year": rec.get("year"),
                    "language": str(rec.get("language") or "en")[:16],
                    "subject": primary_domain,
                    "domains": rec_domains,
                    "pedagogy_tier": tier,
                    "commercial_safe": comm_safe,
                    "license": rec.get("license"),
                    "license_url": rec.get("licenseUrl"),
                    "landing_url": rec.get("landingUrl"),
                    "download_url": rec.get("downloadUrl"),
                    "isbn": rec.get("isbn"),
                    "doi": rec.get("doi"),
                    "sha256": rec.get("sha256"),
                    "file_size": int(rec.get("fileSize") or 0),
                    "page_count": rec.get("pageCount"),
                    "cleaner_version": str(rec.get("cleanerVersion") or "clean-v1"),
                    "chunks_path": rec.get("chunksPath"),
                    "brief_path": rec.get("briefPath"),
                    "glossary_path": rec.get("glossaryPath"),
                    "clean_path": rec.get("cleanPath"),
                }
            )
            if limit and limit > 0 and len(rows) >= limit:
                break

    return rows


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
        tier_set = set(tiers) if tiers else None
        domain_set = set(domains) if domains else None
        raw_rows = [dict(r) for r in conn.execute("SELECT * FROM books ORDER BY id ASC").fetchall()]
        rows: list[dict[str, Any]] = []
        for r in raw_rows:
            if "curation_status" in cols and r.get("curation_status") != "active":
                continue
            r["external_key"] = f"{r['source']}:{r['source_id']}"
            r["authors"] = json.loads(r.get("authors_json") or "[]")
            r["domains"] = json.loads(r.get("domains_json") or "[]") or [r.get("subject") or "general"]
            r["pedagogy_tier"] = r.get("pedagogy_tier") or (
                "tier1_textbook"
                if r.get("source") in {"openstax", "otl"}
                else ("tier3_paper" if r.get("source") == "arxiv" else "tier2_monograph")
            )
            r["commercial_safe"] = bool(r.get("commercial_safe", 0))

            if tier_set and r["pedagogy_tier"] not in tier_set:
                continue
            if domain_set and not (domain_set.intersection(r["domains"]) or r.get("subject") in domain_set):
                continue
            if commercial_only and not r["commercial_safe"]:
                continue
            rows.append(r)
            if limit and limit > 0 and len(rows) >= limit:
                break
        return rows
    finally:
        conn.close()


def _load_prebuilt_chunks_and_brief(
    book: dict[str, Any],
) -> tuple[list[ChunkInput], dict[str, Any], str] | None:
    """Load pre-cleaned `chunks.jsonl` + `brief.json` produced by Phase C4/C6 when available."""
    chunks_path_raw = book.get("chunks_path")
    if not chunks_path_raw:
        return None
    chunks_path = Path(str(chunks_path_raw))
    if not chunks_path.exists():
        return None

    chunks: list[ChunkInput] = []
    with chunks_path.open("r", encoding="utf-8") as fh:
        for idx, raw_line in enumerate(fh):
            line = raw_line.strip()
            if not line:
                continue
            item = json.loads(line)
            content = str(item.get("text") or item.get("content") or "").strip()
            if not content:
                continue
            page_raw = item.get("page_number")
            page_num = int(page_raw) if isinstance(page_raw, int) and page_raw >= 1 else None
            anchor = str(item.get("section_anchor") or "").strip()[:200] or None
            chunks.append(
                ChunkInput(
                    chunk_index=int(item.get("chunk_index", idx)),
                    content=content,
                    page_number=page_num,
                    section_anchor=anchor,
                )
            )
    if not chunks:
        return None

    brief_bundle: dict[str, Any] | None = None
    brief_path_raw = book.get("brief_path")
    if brief_path_raw and Path(str(brief_path_raw)).exists():
        raw_brief = json.loads(Path(str(brief_path_raw)).read_text(encoding="utf-8"))
        if isinstance(raw_brief, dict):
            inner = raw_brief.get("brief") if isinstance(raw_brief.get("brief"), dict) else raw_brief
            title_fallback = str(book.get("title") or "Untitled")
            brief_bundle = {
                "brief": {
                    "what": str(inner.get("what") or title_fallback)[:280],
                    "claims": list(inner.get("claims") or [title_fallback])[:10],
                    "notation": list(inner.get("notation") or [])[:20],
                    "assumes": list(inner.get("assumes") or [])[:10],
                    "sections": list(inner.get("sections") or [])[:60],
                },
                "wordCount": int(raw_brief.get("wordCount") or sum(len(c.content.split()) for c in chunks)),
                "durationMinutes": int(raw_brief.get("durationMinutes") or 30),
                "suggestedTopic": str(raw_brief.get("suggestedTopic") or title_fallback).strip()[:200],
            }

    if brief_bundle is None:
        brief_bundle = build_source_brief(title=str(book.get("title") or ""), chunks=chunks, max_sections=60)

    pipeline_ver = str(book.get("cleaner_version") or "clean-v1")[:64]
    return chunks, brief_bundle, pipeline_ver


async def import_open_library_books(
    *,
    library_dir: Path,
    manifest_path: Path | None = None,
    use_catalog_only: bool = False,
    tiers: list[str] | None = None,
    domains: list[str] | None = None,
    commercial_only: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    upload_figures: bool = False,
    settings: Settings | None = None,
    callback_client: CoreApiCallbackClient | None = None,
    rag_repo: RagRepository | None = None,
    db=None,
) -> ImportSummary:
    cfg = settings or get_settings()
    cb = callback_client or CoreApiCallbackClient(settings=cfg)
    repo = rag_repo or RagRepository(settings=cfg)
    summary = ImportSummary()

    resolved_manifest = manifest_path or (library_dir / CLEAN_MANIFEST_FILENAME)
    if not use_catalog_only and resolved_manifest.exists():
        books = load_manifest_candidates(
            resolved_manifest,
            tiers=tiers,
            domains=domains,
            commercial_only=commercial_only,
            limit=limit,
        )
    else:
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

    for idx, book in enumerate(books, start=1):
        external_key = str(book.get("external_key") or f"{book['source']}:{book['source_id']}")
        try:
            prebuilt = _load_prebuilt_chunks_and_brief(book)
            if prebuilt is not None:
                chunks, brief_bundle, pipeline_ver = prebuilt
            else:
                # Fallback: prefer clean.md over raw extracted.md
                file_path_raw = book.get("file_path")
                book_dir = Path(str(file_path_raw)).parent if file_path_raw else None
                clean_candidate = (
                    Path(str(book["clean_path"]))
                    if book.get("clean_path")
                    else (book_dir / "clean.md" if book_dir else None)
                )
                ext_candidate = (
                    Path(str(book["extracted_path"]))
                    if book.get("extracted_path")
                    else (book_dir / "extracted.md" if book_dir else None)
                )
                md_path = (
                    clean_candidate
                    if clean_candidate and clean_candidate.exists()
                    else (ext_candidate if ext_candidate and ext_candidate.exists() else None)
                )
                if md_path is None:
                    summary.missing_markdown += 1
                    continue

                md_text = md_path.read_text(encoding="utf-8")
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
                pipeline_ver = PIPELINE_VERSION

            if dry_run:
                summary.imported += 1
                summary.total_chunks += len(chunks)
                continue

            authors_list = book.get("authors") or []
            author_str = ", ".join(str(a) for a in authors_list[:6]) if authors_list else None
            suggested_topic = str(brief_bundle.get("suggestedTopic") or book["title"]).strip()[:200]
            upsert_payload = {
                "externalKey": external_key[:160],
                "sourceType": "open_textbook" if book["pedagogy_tier"] == "tier1_textbook" else "academic_paper",
                "title": str(book["title"])[:300],
                "canonicalUrl": book.get("landing_url") or book.get("download_url"),
                "author": author_str[:200] if author_str else None,
                "publisher": str(book["publisher"])[:200] if book.get("publisher") else None,
                "publicationDate": str(book["year"]) if book.get("year") else None,
                "language": str(book.get("language") or "en")[:16],
                "licenseInfo": book.get("license"),
                "contentHash": book.get("sha256"),
                "domainSlug": str(book.get("subject") or "general")[:64],
                "pedagogyTier": str(book["pedagogy_tier"])[:24],
                "commercialSafe": bool(book["commercial_safe"]),
                "isbn": str(book["isbn"])[:64] if book.get("isbn") else None,
                "doi": str(book["doi"])[:128] if book.get("doi") else None,
                "brief": brief_bundle["brief"],
                "wordCount": brief_bundle["wordCount"],
                "durationMinutes": brief_bundle["durationMinutes"],
                "suggestedTopic": suggested_topic,
                "pageCount": book.get("page_count"),
                "byteSize": int(book.get("file_size") or 0),
                "chunkCount": len(chunks),
                "pipelineVersion": pipeline_ver,
                "force": force,
            }

            resp = await cb.post_callback(
                "/internal/library/sources/upsert",
                _strip_nul(upsert_payload),
                correlation_id=f"lib_{book['id']}",
            )
            if isinstance(resp, dict) and resp.get("skipped"):
                summary.skipped += 1
                continue

            source_id = str(resp["sourceId"])
            document_id = str(resp["documentId"])

            should_upload_figs = upload_figures or (cfg.source_storage_backend or "").strip().lower() == "s3"
            fig_inputs = await _upload_and_prepare_figures(
                book,
                external_key=external_key,
                cfg=cfg,
                upload_figures=should_upload_figs,
            )

            if db is not None:
                inserted = await repo.replace_document_chunks(
                    db,
                    owner_id=PUBLIC_LIBRARY_OWNER_ID,
                    course_id=None,
                    source_id=source_id,
                    document_id=document_id,
                    source_title=str(book["title"])[:300],
                    chunks=chunks,
                )
                if fig_inputs:
                    summary.total_figures += await repo.replace_source_figures(
                        db,
                        owner_id=PUBLIC_LIBRARY_OWNER_ID,
                        source_id=source_id,
                        figures=fig_inputs,
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
                        source_title=str(book["title"])[:300],
                        chunks=chunks,
                    )
                    if fig_inputs:
                        summary.total_figures += await repo.replace_source_figures(
                            session,
                            owner_id=PUBLIC_LIBRARY_OWNER_ID,
                            source_id=source_id,
                            figures=fig_inputs,
                        )

            summary.imported += 1
            summary.total_chunks += inserted
            if idx % 10 == 0 or idx == summary.scanned:
                print(
                    f"[{idx}/{summary.scanned}] imported={summary.imported} skipped={summary.skipped} chunks={summary.total_chunks} figures={summary.total_figures}",
                    file=sys.stderr,
                )
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
        help="Path to Open Book Harvester library directory containing sopiskill_manifest.jsonl / catalog.db",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Explicit path to sopiskill_manifest.jsonl (auto-detected under --library-dir by default)",
    )
    parser.add_argument(
        "--from-catalog",
        action="store_true",
        help="Force reading directly from catalog.db instead of sopiskill_manifest.jsonl",
    )
    parser.add_argument("--tiers", type=str, default="tier1_textbook", help="Comma-separated pedagogy tiers")
    parser.add_argument("--domains", type=str, default=None, help="Optional comma-separated domain slugs")
    parser.add_argument("--commercial-only", action="store_true", help="Import only commercial_safe=true books")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of books to process")
    parser.add_argument("--dry-run", action="store_true", help="Validate & load without writing to core-api or rag DB")
    parser.add_argument("--force", action="store_true", help="Force re-indexing even if content hash matches")
    parser.add_argument("--upload-figures", action="store_true", help="Upload figures_manifest.json images to MinIO/S3")
    args = parser.parse_args()

    async def _run() -> ImportSummary:
        try:
            return await import_open_library_books(
                library_dir=args.library_dir,
                manifest_path=args.manifest,
                use_catalog_only=args.from_catalog,
                tiers=_parse_csv(args.tiers),
                domains=_parse_csv(args.domains),
                commercial_only=args.commercial_only,
                limit=args.limit,
                dry_run=args.dry_run,
                force=args.force,
                upload_figures=args.upload_figures,
            )
        finally:
            await dispose_engine()

    res = asyncio.run(_run())
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
