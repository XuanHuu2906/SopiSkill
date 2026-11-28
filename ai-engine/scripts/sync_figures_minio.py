"""Fast figures-only uploader: syncs local `figures_manifest.json` assets to MinIO & `rag.source_figures`.

Never re-embeds or overwrites `rag.document_chunks`, making large batch figure rollouts fast and safe.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_AI_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(_AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ENGINE_ROOT))

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.rag.repository import FigureInput, PUBLIC_LIBRARY_OWNER_ID, RagRepository
from app.rag.storage import get_source_storage
from scripts.import_open_library import _normalize_figure_bytes


async def sync_figures_from_targets(
    targets_json: Path,
    *,
    concurrency: int = 8,
) -> dict[str, int]:
    cfg = get_settings()
    storage = get_source_storage(cfg)
    repo = RagRepository(settings=cfg)
    factory = get_session_factory()
    sem = asyncio.Semaphore(max(1, concurrency))

    targets: list[dict[str, Any]] = json.loads(targets_json.read_text(encoding="utf-8"))
    stats = {"scanned": len(targets), "books_synced": 0, "books_empty": 0, "figures_uploaded": 0, "failed": 0}

    async def _upload_one(minio_key: str, data: bytes, ctype: str) -> None:
        async with sem:
            await storage.put_bytes_async(minio_key, data, content_type=ctype)

    for idx, item in enumerate(targets, start=1):
        ekey = str(item["externalKey"])
        source_id = str(item["sourceId"])
        book_dir = Path(str(item["file_path"])).parent
        manifest_path = book_dir / "figures_manifest.json"
        if not manifest_path.exists():
            stats["books_empty"] += 1
            continue

        try:
            raw_m = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_figs = raw_m.get("figures") or []
            if not raw_figs:
                stats["books_empty"] += 1
                continue

            safe_book_key = re.sub(r"[^a-zA-Z0-9._-]+", "_", ekey).strip("_")[:120] or "book"
            upload_tasks = []
            fig_inputs: list[FigureInput] = []

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
                upload_tasks.append(_upload_one(minio_key, data, ctype))
                fig_inputs.append(
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

            if not fig_inputs:
                stats["books_empty"] += 1
                continue

            await asyncio.gather(*upload_tasks)
            async with factory() as session:
                inserted = await repo.replace_source_figures(
                    session,
                    owner_id=PUBLIC_LIBRARY_OWNER_ID,
                    source_id=source_id,
                    figures=fig_inputs,
                )
            stats["books_synced"] += 1
            stats["figures_uploaded"] += inserted
            if idx % 20 == 0 or idx == len(targets):
                print(
                    f"[{idx}/{len(targets)}] synced_books={stats['books_synced']} figures_uploaded={stats['figures_uploaded']} failed={stats['failed']}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            print(f"[ERROR] {ekey}: {type(exc).__name__}: {exc}", file=sys.stderr)

    await dispose_engine()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Figures-only fast MinIO + rag.source_figures sync")
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    res = asyncio.run(sync_figures_from_targets(args.targets, concurrency=args.concurrency))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
