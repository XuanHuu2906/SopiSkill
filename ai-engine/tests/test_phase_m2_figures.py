"""Phase M2 (P2) tests: Grounded Figure Registry, MinIO/memory serving, and sourceFigureId resolution."""

from __future__ import annotations

from app.agents.lesson_generator import resolve_source_figure_ids
from app.db.session import ensure_sqlite_tables, get_session_factory
from app.rag.repository import FigureInput, PUBLIC_LIBRARY_OWNER_ID, RagRepository
from app.rag.storage import get_source_storage
from tests.conftest import signed_json_request


async def test_phase_m2_figure_registry_scoping_and_retrieval():
    await ensure_sqlite_tables()
    repo = RagRepository()
    factory = get_session_factory()

    async with factory() as db:
        inserted = await repo.replace_source_figures(
            db,
            owner_id=PUBLIC_LIBRARY_OWNER_ID,
            source_id="src_pub_attn",
            figures=[
                FigureInput(
                    figure_id="fig_001",
                    minio_key="library-figures/attention/fig_001.webp",
                    content_type="image/webp",
                    section_anchor="3-model-architecture",
                    page_number=3,
                    label="Figure 1",
                    caption="The Transformer model architecture.",
                    alt_text="Encoder and decoder stacks with multi-head attention.",
                ),
                FigureInput(
                    figure_id="fig_002",
                    minio_key="library-figures/attention/fig_002.webp",
                    content_type="image/webp",
                    section_anchor="3-2-attention",
                    page_number=4,
                    label="Figure 2",
                    caption="Scaled Dot-Product Attention and Multi-Head Attention.",
                    alt_text="Q K V matrix multiply and softmax.",
                ),
            ],
        )
        assert inserted == 2

        # Tenant private figure on another user must NEVER leak to usr_other
        await repo.replace_source_figures(
            db,
            owner_id="usr_alice",
            source_id="src_alice_priv",
            figures=[
                FigureInput(
                    figure_id="fig_secret",
                    minio_key="private/alice/fig_secret.webp",
                    caption="Confidential diagram",
                )
            ],
        )

        # Public library figures are visible when source_id is authorized
        figs = await repo.list_figures_for_sources(
            db,
            owner_id="usr_bob",
            source_ids=["src_pub_attn"],
            section_anchors=["3-2-attention"],
            query="scaled dot product attention",
            limit=4,
        )
        assert len(figs) == 2
        assert figs[0]["figureId"] == "fig_002"
        assert figs[0]["url"] == "/v1/library/figures/src_pub_attn/fig_002"

        # Tenant isolation: Bob cannot fetch Alice's private figure
        assert await repo.get_figure(db, source_id="src_alice_priv", figure_id="fig_secret", owner_id="usr_bob") is None
        assert await repo.get_figure(db, source_id="src_alice_priv", figure_id="fig_secret", owner_id="usr_alice") is not None


async def test_phase_m2_internal_figure_endpoint_serves_verified_bytes(ai_client):
    await ensure_sqlite_tables()
    repo = RagRepository()
    storage = get_source_storage()
    webp_stub = b"RIFF\x20\x00\x00\x00WEBPVP8 \x10\x00\x00\x00" + b"\x00" * 16
    await storage.put_bytes_async("library-figures/test/fig_001.webp", webp_stub, content_type="image/webp")

    factory = get_session_factory()
    async with factory() as db:
        await repo.replace_source_figures(
            db,
            owner_id=PUBLIC_LIBRARY_OWNER_ID,
            source_id="src_test_fig",
            figures=[
                FigureInput(
                    figure_id="fig_001",
                    minio_key="library-figures/test/fig_001.webp",
                    content_type="image/webp",
                    label="Figure 1",
                    caption="Sample diagram",
                )
            ],
        )

    path = "/internal/library/figures/src_test_fig/fig_001"
    _, hdrs = signed_json_request("GET", path, None)
    resp = await ai_client.get(path, headers=hdrs)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/webp")
    assert resp.content == webp_stub

    missing_path = "/internal/library/figures/src_test_fig/fig_missing"
    _, hdrs_404 = signed_json_request("GET", missing_path, None)
    resp_404 = await ai_client.get(missing_path, headers=hdrs_404)
    assert resp_404.status_code == 404


def test_phase_m2_resolve_source_figure_ids_grounds_and_strips_hallucinations():
    available = {
        "src_1:fig_002": {
            "sourceId": "src_1",
            "figureId": "fig_002",
            "label": "Figure 2",
            "caption": "Scaled Dot-Product Attention",
            "alt": "Q, K, V attention diagram",
        },
        "fig_002": {
            "sourceId": "src_1",
            "figureId": "fig_002",
            "label": "Figure 2",
            "caption": "Scaled Dot-Product Attention",
            "alt": "Q, K, V attention diagram",
        },
    }
    lesson = {
        "title": "Transformer Attention",
        "blocks": [
            {
                "type": "teach",
                "title": "Valid Figure Binding",
                "paragraphs": ["See the diagram below."],
                "sourceFigureId": "src_1:fig_002",
            },
            {
                "type": "teach",
                "title": "Hallucinated Figure Stripped",
                "paragraphs": ["Should not leak bogus URL."],
                "sourceFigureId": "https://evil.example/ssrf.png",
            },
            {
                "type": "teach",
                "title": "Mutual Exclusion Preserved",
                "paragraphs": ["Has figure already."],
                "figure": {"kind": "formula", "latex": "E = mc^2"},
                "sourceFigureId": "src_1:fig_002",
            },
        ],
    }

    resolved = resolve_source_figure_ids(lesson, available)
    b0, b1, b2 = resolved["blocks"]

    assert "sourceFigureId" not in b0
    assert b0["image"]["url"] == "/v1/library/figures/src_1/fig_002"
    assert b0["image"]["caption"] == "Scaled Dot-Product Attention"

    assert "sourceFigureId" not in b1
    assert "image" not in b1

    assert "sourceFigureId" not in b2
    assert "image" not in b2
    assert b2["figure"]["kind"] == "formula"
