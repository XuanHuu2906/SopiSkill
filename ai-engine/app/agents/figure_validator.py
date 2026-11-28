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

_SAFE_MATH_CALLABLES: dict[str, Any] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log,
    "log10": math.log10,
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "min": min,
    "max": max,
    "pow": math.pow,
}


def evaluate_safe_math_ast(expr: str, variables: dict[str, float]) -> float | None:
    """Safely evaluate a validated math expression using pure Python AST traversal (ZERO eval/exec)."""
    allowed_vars = set(variables.keys()) | {"x"}
    if validate_safe_math_expr(expr, allowed_vars) is not None:
        return None
    py_expr = (expr or "").strip().replace("^", "**")
    try:
        tree = ast.parse(py_expr, mode="eval")
    except SyntaxError:
        return None

    def _walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            low = node.id.lower()
            if low == "pi":
                return math.pi
            if low == "e":
                return math.e
            if node.id in variables:
                return float(variables[node.id])
            if low in variables:
                return float(variables[low])
            raise ValueError(f"Unknown variable {node.id!r}")
        if isinstance(node, ast.UnaryOp):
            val = _walk(node.operand)
            if isinstance(node.op, ast.UAdd):
                return +val
            if isinstance(node.op, ast.USub):
                return -val
            raise ValueError("Unsupported unary op")
        if isinstance(node, ast.BinOp):
            left = _walk(node.left)
            right = _walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if abs(right) < 1e-12:
                    raise ZeroDivisionError("division by zero")
                return left / right
            if isinstance(node.op, ast.Pow):
                if abs(right) > 100 or (abs(left) > 1e6 and abs(right) > 4):
                    raise OverflowError("exponent too large")
                return math.pow(left, right) if left >= 0 or float(right).is_integer() else float("nan")
            raise ValueError("Unsupported binary op")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = _SAFE_MATH_CALLABLES.get(node.func.id.lower())
            if fn is None:
                raise ValueError(f"Disallowed function {node.func.id!r}")
            args = [_walk(a) for a in node.args]
            return float(fn(*args))
        raise ValueError(f"Disallowed AST node {type(node).__name__}")

    try:
        res = _walk(tree)
        if not math.isfinite(res):
            return None
        return res
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


def compile_plot_scene_spec(
    plot_spec: dict[str, Any],
    *,
    samples: int = 80,
) -> dict[str, Any]:
    """Deterministically compile a Phase 10A `plot` scene (`expr` -> SVG `segments`, `tangents`, `areas`).

    Reuses `validate_safe_math_expr` and `evaluate_safe_math_ast` with ZERO `eval()`.
    """
    raw_xr = plot_spec.get("xRange")
    raw_yr = plot_spec.get("yRange")
    x_min, x_max = (-5.0, 5.0)
    y_min, y_max = (-5.0, 5.0)
    if (
        isinstance(raw_xr, list)
        and len(raw_xr) == 2
        and _is_finite_number(raw_xr[0])
        and _is_finite_number(raw_xr[1])
        and float(raw_xr[0]) < float(raw_xr[1])
    ):
        x_min, x_max = float(raw_xr[0]), float(raw_xr[1])
    if (
        isinstance(raw_yr, list)
        and len(raw_yr) == 2
        and _is_finite_number(raw_yr[0])
        and _is_finite_number(raw_yr[1])
        and float(raw_yr[0]) < float(raw_yr[1])
    ):
        y_min, y_max = float(raw_yr[0]), float(raw_yr[1])

    palette = ["#c85a27", "#2d6a4f", "#1d4ed8", "#7c3aed"]
    y_span = max(1e-6, y_max - y_min)
    clamp_margin = y_span * 1.5
    safe_samples = max(20, min(int(samples), 200))

    raw_funcs = plot_spec.get("functions") or plot_spec.get("curves") or []
    compiled_curves: list[dict[str, Any]] = []
    primary_expr: str | None = None

    for idx, fn in enumerate(raw_funcs[:4] if isinstance(raw_funcs, list) else []):
        if not isinstance(fn, dict):
            continue
        expr = str(fn.get("expr") or "").strip()
        if validate_safe_math_expr(expr, {"x"}) is not None:
            continue
        if primary_expr is None:
            primary_expr = expr
        segments: list[list[list[float]]] = []
        current_seg: list[list[float]] = []
        prev_y: float | None = None
        for step in range(safe_samples + 1):
            x = x_min + (x_max - x_min) * (step / safe_samples)
            y = evaluate_safe_math_ast(expr, {"x": x})
            if (
                y is None
                or y < y_min - clamp_margin
                or y > y_max + clamp_margin
                or (prev_y is not None and abs(y - prev_y) > y_span * 1.25)
            ):
                if len(current_seg) >= 2:
                    segments.append(current_seg)
                current_seg = []
                prev_y = None
                continue
            current_seg.append([round(x, 4), round(y, 4)])
            prev_y = y
        if len(current_seg) >= 2:
            segments.append(current_seg)

        compiled_curves.append(
            {
                "expr": expr,
                "label": str(fn.get("label") or f"f(x) = {expr}")[:64],
                "color": str(fn.get("color") or palette[idx % len(palette)]),
                "segments": segments,
            }
        )

    # Compile explicit points
    compiled_points: list[dict[str, Any]] = []
    for pt in (plot_spec.get("points") or [])[:12]:
        if not isinstance(pt, dict):
            continue
        if _is_finite_number(pt.get("x")) and _is_finite_number(pt.get("y")):
            compiled_points.append(
                {
                    "x": round(float(pt["x"]), 4),
                    "y": round(float(pt["y"]), 4),
                    "label": str(pt.get("label") or "")[:40],
                }
            )

    # Compile tangent lines via symmetric finite difference on safe AST
    compiled_tangents: list[dict[str, Any]] = []
    h = max(1e-4, (x_max - x_min) * 1e-4)
    for tan_spec in (plot_spec.get("tangents") or [])[:4]:
        if not isinstance(tan_spec, dict) or not _is_finite_number(tan_spec.get("x")):
            continue
        expr = str(tan_spec.get("expr") or primary_expr or "").strip()
        if not expr or validate_safe_math_expr(expr, {"x"}) is not None:
            continue
        x0 = float(tan_spec["x"])
        y0 = evaluate_safe_math_ast(expr, {"x": x0})
        y_plus = evaluate_safe_math_ast(expr, {"x": x0 + h})
        y_minus = evaluate_safe_math_ast(expr, {"x": x0 - h})
        if y0 is None or y_plus is None or y_minus is None:
            continue
        slope = (y_plus - y_minus) / (2.0 * h)
        if not math.isfinite(slope):
            continue
        span = (x_max - x_min) * 0.25
        x1, x2 = max(x_min, x0 - span), min(x_max, x0 + span)
        y1 = y0 + slope * (x1 - x0)
        y2 = y0 + slope * (x2 - x0)
        compiled_tangents.append(
            {
                "expr": expr,
                "x": round(x0, 4),
                "y": round(y0, 4),
                "slope": round(slope, 4),
                "label": str(tan_spec.get("label") or f"m = {slope:.2f}")[:40],
                "segment": [[round(x1, 4), round(y1, 4)], [round(x2, 4), round(y2, 4)]],
            }
        )

    # Compile shaded definite integral / area polygons under a curve
    compiled_areas: list[dict[str, Any]] = []
    for area_spec in (plot_spec.get("areas") or [])[:3]:
        if not isinstance(area_spec, dict):
            continue
        if not (_is_finite_number(area_spec.get("fromX")) and _is_finite_number(area_spec.get("toX"))):
            continue
        expr = str(area_spec.get("expr") or primary_expr or "").strip()
        if not expr or validate_safe_math_expr(expr, {"x"}) is not None:
            continue
        a_x = max(x_min, min(x_max, float(area_spec["fromX"])))
        b_x = max(x_min, min(x_max, float(area_spec["toX"])))
        if a_x >= b_x:
            continue
        baseline = float(area_spec["baseline"]) if _is_finite_number(area_spec.get("baseline")) else 0.0
        poly: list[list[float]] = [[round(a_x, 4), round(baseline, 4)]]
        steps = 36
        for step in range(steps + 1):
            x = a_x + (b_x - a_x) * (step / steps)
            y = evaluate_safe_math_ast(expr, {"x": x})
            if y is not None:
                clamped_y = max(y_min, min(y_max, y))
                poly.append([round(x, 4), round(clamped_y, 4)])
        poly.append([round(b_x, 4), round(baseline, 4)])
        if len(poly) >= 4:
            compiled_areas.append(
                {
                    "expr": expr,
                    "fromX": round(a_x, 4),
                    "toX": round(b_x, 4),
                    "label": str(area_spec.get("label") or "")[:40],
                    "color": str(area_spec.get("color") or "rgba(200, 90, 39, 0.18)"),
                    "polygon": poly,
                }
            )

    return {
        "xRange": [x_min, x_max],
        "yRange": [y_min, y_max],
        "xLabel": str(plot_spec.get("xLabel") or "x")[:24],
        "yLabel": str(plot_spec.get("yLabel") or "y")[:24],
        "curves": compiled_curves,
        "points": compiled_points,
        "tangents": compiled_tangents,
        "areas": compiled_areas,
    }


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
