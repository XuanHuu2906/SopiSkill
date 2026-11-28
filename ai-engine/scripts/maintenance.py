"""Phase 10B Kubernetes CronJob maintenance runner (`CronJob: maintenance`).

Tasks executed cleanly without breaking domain boundaries:
  1. Calls `POST {CORE_API_URL}/internal/maintenance/run` (HMAC-signed) to settle due league cohorts,
     scan retention notifications, trim Redis streams, and fetch active `reels-audio/` object keys.
  2. Prunes orphaned `reels-audio/` objects from MinIO/S3 that are no longer referenced by `core.media_calls`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Any

_AI_ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(_AI_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AI_ENGINE_ROOT))

from app.core.callback_client import CoreApiCallbackClient
from app.core.config import Settings, get_settings
from app.rag.storage import get_source_storage

logger = logging.getLogger(__name__)


async def run_maintenance(*, settings: Settings | None = None, callback_client: CoreApiCallbackClient | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    cb = callback_client or CoreApiCallbackClient(settings=cfg)
    store = get_source_storage(cfg)

    resp = await cb.post_callback(
        "/internal/maintenance/run",
        {"source": "k8s-cronjob"},
        correlation_id=f"cor_maint_{uuid.uuid4().hex[:12]}",
    )
    active_keys = set(str(k) for k in (resp.get("activeReelObjectKeys") or []) if str(k).startswith("reels-audio/"))
    stored_keys = await store.list_prefix("reels-audio/")

    pruned = 0
    for key in stored_keys:
        if key not in active_keys:
            if await store.delete_object(key):
                pruned += 1

    summary = {
        "status": "ok",
        "settledCohorts": resp.get("settledCohorts", 0),
        "nudgesDispatched": resp.get("nudgesDispatched", 0),
        "trimmedStreams": resp.get("trimmedStreams", 0),
        "activeReelObjects": len(active_keys),
        "prunedOrphanReelObjects": pruned,
    }
    logger.info("k8s_maintenance_complete summary=%s", json.dumps(summary))
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run_maintenance())
    print(json.dumps(result, ensure_ascii=False))
