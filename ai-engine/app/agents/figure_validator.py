"""Deterministic validator for rich lesson figures (6 kinds, 7 SVG diagram layouts + code + plot).

Supported figure kinds:
  1. `formula`: KaTeX display math (`latex`)
  2. `table`: structured comparison table (`headers`, `rows`, optional cell `tone` in `moss|clay|neutral`)
  3. `visual`: captioned schematic (`title`, `items` or `nodes`)
  4. `diagram`: 7 SVG layouts — `flow`, `timeline`, `branch`, `cycle`, `stack`, `split`, `hub`
  5. `code`: syntax-highlighted code snippet (`code`, optional `language`, `highlightLines`)
  6. `plot`: zero-eval interactive math function plot (`functions`, `xRange`, `yRange`, optional `points`, `params`)

Graph & safety invariants enforced deterministically:
  - No orphan nodes when edges are declared; every edge `from`/`to` must reference an existing node `id`.
  - `split`: requires even count of items (`>= 2`, `len % 2 == 0`) or explicit non-empty `left` & `right`.
  - `cycle`: requires 3..6 nodes and concise labels (`<= 48` chars each).
  - `hub`: requires `center` (or first node) and `>= 2` spokes.
  - `table`: cell/column tones restricted to `{"moss", "clay", "neutral"}`.
  - `code`: non-empty `code <= 4000` chars, safe `language` token, valid 1-based `highlightLines`.
  - `plot`: strict Python AST whitelist (only arithmetic ops, numeric literals, `x`/declared `params`, `pi`/`e`,
    and allowlisted math functions — rejects attribute access, subscripts, lambdas, imports, or arbitrary calls).
  - Mutual exclusion on `teach` block: never allow both `figure` and `image` simultaneously.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any

ALLOWED_FIGURE_KINDS = frozenset({"formula", "table", "visual", "diagram", "code", "plot"})
ALLOWED_DIAGRAM_LAYOUTS = frozenset({"flow", "timeline", "branch", "cycle", "stack", "split", "hub"})
ALLOWED_TABLE_TONES = frozenset({"moss", "clay", "neutral"})
MAX_CYCLE_LABEL_LEN = 48
MAX_CODE_CHARS = 4000
_SAFE_LANG_RE = re.compile(r"^[a-zA-Z0-9_+#.-]{1,32}$")
_SAFE_PARAM_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,15}$")

SAFE_PLOT_FUNCS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "exp",
        "ln",
        "log",
        "log10",
        "sqrt",
        "abs",
        "floor",
        "ceil",
        "min",
        "max",
        "pow",
    }
)
SAFE_PLOT_CONSTANTS = frozenset({"pi", "e"})


def validate_safe_math_expr(expr: str, allowed_vars: set[str]) -> str | None:
    """Validate a plot expression via Python AST without ever executing it. Returns error string or None."""
    cleaned = (expr or "").strip()
    if not cleaned:
        return "empty expression"
    if len(cleaned) > 160:
        return "expression exceeds 160 chars"
    py_expr = cleaned.replace("^", "**")
    try:
        tree = ast.parse(py_expr, mode="eval")
    except SyntaxError as exc:
        return f"syntax error: {exc.msg}"

    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.Expression,
                ast.Load,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.Pow,
                ast.UAdd,
                ast.USub,
            ),
        ):
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                return f"non-numeric constant {node.value!r}"
            continue
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
                return f"unsupported operator {type(node.op).__name__}"
            continue
        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.UAdd, ast.USub)):
                return f"unsupported unary operator {type(node.op).__name__}"
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return "only direct math function calls are allowed"
            fn_name = node.func.id.lower()
            if fn_name not in SAFE_PLOT_FUNCS:
                return f"disallowed function {node.func.id!r}"
            if node.keywords:
                return "keyword arguments are not allowed in plot expressions"
            continue
        if isinstance(node, ast.Name):
            low = node.id.lower()
            if low in SAFE_PLOT_FUNCS or low in SAFE_PLOT_CONSTANTS or node.id in allowed_vars or low in allowed_vars:
                continue
            return f"unknown identifier {node.id!r}"
        return f"disallowed syntax node {type(node).__name__}"
    return None


def _is_finite_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


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

    if kind == "code":
        code = str(fig.get("code") or "")
        if not code.strip():
            errors.append(f"block[{block_index}].figure (code): missing non-empty code body.")
            return errors
        if len(code) > MAX_CODE_CHARS:
            errors.append(
                f"block[{block_index}].figure (code): code exceeds {MAX_CODE_CHARS} chars ({len(code)})."
            )
        lang = fig.get("language")
        if lang is not None and str(lang).strip() and not _SAFE_LANG_RE.match(str(lang).strip()):
            errors.append(f"block[{block_index}].figure (code): invalid language token {lang!r}.")
        hl = fig.get("highlightLines")
        if hl is not None:
            line_count = len(code.replace("\r\n", "\n").rstrip("\n").split("\n"))
            if not isinstance(hl, list):
                errors.append(f"block[{block_index}].figure (code): highlightLines must be a list of ints.")
            else:
                for ln in hl:
                    if not isinstance(ln, int) or isinstance(ln, bool) or not (1 <= ln <= line_count):
                        errors.append(
                            f"block[{block_index}].figure (code): highlightLines entry {ln!r} out of range 1..{line_count}."
                        )
        return errors

    if kind == "plot":
        for axis in ("xRange", "yRange"):
            rng = fig.get(axis)
            if rng is not None:
                if (
                    not isinstance(rng, list)
                    or len(rng) != 2
                    or not _is_finite_number(rng[0])
                    or not _is_finite_number(rng[1])
                    or float(rng[0]) >= float(rng[1])
                ):
                    errors.append(
                        f"block[{block_index}].figure (plot): {axis} must be [min, max] with finite min < max."
                    )

        allowed_vars: set[str] = {"x"}
        params = fig.get("params") or []
        if not isinstance(params, list) or len(params) > 4:
            errors.append(f"block[{block_index}].figure (plot): params must be a list of at most 4 items.")
        else:
            for p_idx, p in enumerate(params):
                if not isinstance(p, dict):
                    errors.append(f"block[{block_index}].figure (plot): params[{p_idx}] must be an object.")
                    continue
                pname = str(p.get("name") or "").strip()
                if not _SAFE_PARAM_NAME_RE.match(pname) or pname.lower() in SAFE_PLOT_FUNCS:
                    errors.append(f"block[{block_index}].figure (plot): invalid param name {pname!r}.")
                    continue
                pmin, pmax, pval = p.get("min"), p.get("max"), p.get("value")
                if (
                    not _is_finite_number(pmin)
                    or not _is_finite_number(pmax)
                    or not _is_finite_number(pval)
                    or float(pmin) >= float(pmax)
                    or not (float(pmin) <= float(pval) <= float(pmax))
                ):
                    errors.append(
                        f"block[{block_index}].figure (plot): param {pname!r} requires finite min <= value <= max and min < max."
                    )
                    continue
                allowed_vars.add(pname)

        funcs = fig.get("functions") or []
        if not isinstance(funcs, list) or not (1 <= len(funcs) <= 4):
            errors.append(f"block[{block_index}].figure (plot): requires 1..4 functions.")
        else:
            for f_idx, fn in enumerate(funcs):
                if not isinstance(fn, dict):
                    errors.append(f"block[{block_index}].figure (plot): functions[{f_idx}] must be an object.")
                    continue
                expr_err = validate_safe_math_expr(str(fn.get("expr") or ""), allowed_vars)
                if expr_err:
                    errors.append(
                        f"block[{block_index}].figure (plot): functions[{f_idx}] invalid expr ({expr_err})."
                    )

        pts = fig.get("points") or []
        if not isinstance(pts, list) or len(pts) > 12:
            errors.append(f"block[{block_index}].figure (plot): points must be a list of at most 12 items.")
        else:
            for pt_idx, pt in enumerate(pts):
                if not isinstance(pt, dict) or not _is_finite_number(pt.get("x")) or not _is_finite_number(pt.get("y")):
                    errors.append(
                        f"block[{block_index}].figure (plot): points[{pt_idx}] requires finite numeric x and y."
                    )
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
