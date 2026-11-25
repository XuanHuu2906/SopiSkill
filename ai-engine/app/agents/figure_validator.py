"""Deterministic validator for Phase 4 rich lesson figures (4 kinds, 7 SVG diagram layouts).

Supported figure kinds:
  1. `formula`: KaTeX display math (`latex`)
  2. `table`: structured comparison table (`headers`, `rows`, optional cell `tone` in `moss|clay|neutral`)
  3. `visual`: captioned schematic (`title`, `items` or `nodes`)
  4. `diagram`: 7 SVG layouts — `flow`, `timeline`, `branch`, `cycle`, `stack`, `split`, `hub`

Graph invariants enforced deterministically:
  - No orphan nodes when edges are declared; every edge `from`/`to` must reference an existing node `id`.
  - `split`: requires even count of items (`>= 2`, `len % 2 == 0`) or explicit non-empty `left` & `right`.
  - `cycle`: requires 3..6 nodes and concise labels (`<= 48` chars each).
  - `hub`: requires `center` (or first node) and `>= 2` spokes.
  - `table`: cell/column tones restricted to `{"moss", "clay", "neutral"}`.
  - Mutual exclusion on `teach` block: never allow both `figure` and `image` simultaneously.
"""

from __future__ import annotations

from typing import Any

ALLOWED_FIGURE_KINDS = frozenset({"formula", "table", "visual", "diagram"})
ALLOWED_DIAGRAM_LAYOUTS = frozenset({"flow", "timeline", "branch", "cycle", "stack", "split", "hub"})
ALLOWED_TABLE_TONES = frozenset({"moss", "clay", "neutral"})
MAX_CYCLE_LABEL_LEN = 48


def validate_teach_media_and_figure(block: dict[str, Any], block_index: int) -> list[str]:
    """Validate `teach` block media mutual exclusion and figure schema/graph invariants."""
    errors: list[str] = []
    has_figure = isinstance(block.get("figure"), dict) and bool(block.get("figure"))
    has_image = isinstance(block.get("image"), dict) and bool(block.get("image"))
    if has_figure and has_image:
        errors.append(
            f"block[{block_index}] (teach): figure and image are mutually exclusive — provide only one."
        )
    if not has_figure:
        return errors

    fig: dict[str, Any] = block["figure"]
    kind = str(fig.get("kind") or fig.get("type") or "").strip().lower()
    if kind not in ALLOWED_FIGURE_KINDS:
        errors.append(
            f"block[{block_index}].figure: unsupported kind {kind!r} (allowed: {sorted(ALLOWED_FIGURE_KINDS)})."
        )
        return errors

    if kind == "formula":
        latex = str(fig.get("latex") or "").strip()
        if not latex:
            errors.append(f"block[{block_index}].figure (formula): missing non-empty latex expression.")
        return errors

    if kind == "table":
        headers = fig.get("headers") or []
        rows = fig.get("rows") or []
        if not isinstance(headers, list) or len(headers) < 2:
            errors.append(f"block[{block_index}].figure (table): requires at least 2 headers.")
        if not isinstance(rows, list) or not rows:
            errors.append(f"block[{block_index}].figure (table): requires at least 1 row.")
        for r_idx, row in enumerate(rows if isinstance(rows, list) else []):
            cells = row.get("cells") if isinstance(row, dict) else row
            if isinstance(row, dict) and row.get("tone"):
                tone = str(row["tone"]).strip().lower()
                if tone not in ALLOWED_TABLE_TONES:
                    errors.append(
                        f"block[{block_index}].figure (table): row[{r_idx}] invalid tone {tone!r}."
                    )
            if isinstance(cells, list):
                for c_idx, cell in enumerate(cells):
                    if isinstance(cell, dict) and cell.get("tone"):
                        tone = str(cell["tone"]).strip().lower()
                        if tone not in ALLOWED_TABLE_TONES:
                            errors.append(
                                f"block[{block_index}].figure (table): row[{r_idx}].cell[{c_idx}] invalid tone {tone!r}."
                            )
        return errors

    if kind == "visual":
        items = fig.get("items") or fig.get("nodes") or []
        if not isinstance(items, list) or not items:
            errors.append(f"block[{block_index}].figure (visual): requires non-empty items or nodes.")
        return errors

    # kind == "diagram"
    layout = str(fig.get("layout") or "").strip().lower()
    if layout not in ALLOWED_DIAGRAM_LAYOUTS:
        errors.append(
            f"block[{block_index}].figure (diagram): unsupported layout {layout!r} "
            f"(allowed: {sorted(ALLOWED_DIAGRAM_LAYOUTS)})."
        )
        return errors

    nodes = fig.get("nodes") or []
    edges = fig.get("edges") or []

    if layout == "split":
        left = fig.get("left")
        right = fig.get("right")
        if isinstance(left, list) and isinstance(right, list):
            if not left or not right:
                errors.append(f"block[{block_index}].figure (split): left and right columns must be non-empty.")
        else:
            items = fig.get("items") if isinstance(fig.get("items"), list) else nodes
            if not isinstance(items, list) or len(items) < 2 or len(items) % 2 != 0:
                errors.append(
                    f"block[{block_index}].figure (split): requires an even number of items (>= 2), got {len(items) if isinstance(items, list) else 0}."
                )
        return errors

    if layout == "hub":
        center = fig.get("center")
        spokes = fig.get("spokes") or (nodes[1:] if len(nodes) > 1 else [])
        if not center and not nodes:
            errors.append(f"block[{block_index}].figure (hub): requires center node.")
        if not isinstance(spokes, list) or len(spokes) < 2:
            errors.append(f"block[{block_index}].figure (hub): requires at least 2 spokes.")
        return errors

    if not isinstance(nodes, list) or len(nodes) < 2:
        errors.append(f"block[{block_index}].figure ({layout}): requires at least 2 nodes.")
        return errors

    node_ids: set[str] = set()
    for n_idx, node in enumerate(nodes):
        if isinstance(node, dict):
            nid = str(node.get("id") or f"n{n_idx}")
            label = str(node.get("label") or "").strip()
        else:
            nid = f"n{n_idx}"
            label = str(node).strip()
        node_ids.add(nid)
        if not label:
            errors.append(f"block[{block_index}].figure ({layout}): node[{n_idx}] has empty label.")
        if layout == "cycle" and len(label) > MAX_CYCLE_LABEL_LEN:
            errors.append(
                f"block[{block_index}].figure (cycle): node '{nid}' label exceeds {MAX_CYCLE_LABEL_LEN} chars ({len(label)})."
            )

    if layout == "cycle" and not (3 <= len(nodes) <= 6):
        errors.append(f"block[{block_index}].figure (cycle): requires 3..6 nodes, got {len(nodes)}.")

    # Graph connectivity check: if edges are explicitly provided, forbid dangling edges and orphan nodes.
    if isinstance(edges, list) and edges:
        connected: set[str] = set()
        for e_idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"block[{block_index}].figure ({layout}): edge[{e_idx}] must be an object.")
                continue
            src = str(edge.get("from") or edge.get("source") or "").strip()
            dst = str(edge.get("to") or edge.get("target") or "").strip()
            if src not in node_ids or dst not in node_ids:
                errors.append(
                    f"block[{block_index}].figure ({layout}): edge[{e_idx}] references unknown node ({src!r} -> {dst!r})."
                )
            else:
                connected.add(src)
                connected.add(dst)
        orphans = sorted(node_ids - connected)
        if orphans:
            errors.append(
                f"block[{block_index}].figure ({layout}): orphan nodes detected without edges: {orphans}."
            )

    return errors
