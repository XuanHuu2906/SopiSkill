"""Phase 10B maintenance script tests: prunes orphaned `reels-audio/` objects without touching active clips."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.rag.storage import get_source_storage
from scripts.maintenance import run_maintenance


@pytest.mark.asyncio
async def test_k8s_maintenance_prunes_only_orphaned_reel_audio():
    cfg = Settings(source_storage_backend="memory")
    store = get_source_storage(cfg)
    await store.delete_prefix("reels-audio/")
    await store.put_bytes_async("reels-audio/crs_1/lsn_1/v1_sc_1.wav", b"RIFFactive")
    await store.put_bytes_async("reels-audio/crs_1/lsn_1/v0_sc_old.wav", b"RIFForphan")
    await store.put_bytes_async("sources/usr_1/doc.pdf", b"%PDF-keep")

    class StubCallback:
        async def post_callback(self, path: str, payload: dict, *, correlation_id: str):
            assert path == "/internal/maintenance/run"
            assert correlation_id.startswith("cor_maint_")
            return {
                "status": "ok",
                "settledCohorts": 1,
                "nudgesDispatched": 2,
                "trimmedStreams": 0,
                "activeReelObjectKeys": ["reels-audio/crs_1/lsn_1/v1_sc_1.wav"],
            }

    summary = await run_maintenance(settings=cfg, callback_client=StubCallback())  # type: ignore[arg-type]
    assert summary["status"] == "ok"
    assert summary["prunedOrphanReelObjects"] == 1
    assert summary["activeReelObjects"] == 1
    assert await store.get_bytes("reels-audio/crs_1/lsn_1/v1_sc_1.wav") == b"RIFFactive"
    assert await store.get_bytes("sources/usr_1/doc.pdf") == b"%PDF-keep"
    assert await store.list_prefix("reels-audio/") == ["reels-audio/crs_1/lsn_1/v1_sc_1.wav"]
