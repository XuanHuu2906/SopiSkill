"use client";

import { useMemo, useState } from "react";
import { CodeBlockCard, FormulaMath } from "./MathText";

export interface FigureNode {
  id?: string;
  label: string;
  sublabel?: string;
}

export interface FigureEdge {
  from?: string;
  to?: string;
  source?: string;
  target?: string;
  label?: string;
}

export interface TableCellObj {
  text: string;
  tone?: "moss" | "clay" | "neutral";
}

export interface TableRowSpec {
  tone?: "moss" | "clay" | "neutral";
  cells: (string | TableCellObj)[];
}

export interface PlotFunctionSpec {
  expr: string;
  label?: string;
  color?: string;
}

export interface PlotPointSpec {
  x: number;
  y: number;
  label?: string;
}

export interface PlotParamSpec {
  name: string;
  label?: string;
  min: number;
  max: number;
  step?: number;
  value: number;
}

export interface LessonFigure {
  kind?: "formula" | "table" | "visual" | "diagram" | "code" | "plot";
  type?: "formula" | "table" | "visual" | "diagram" | "code" | "plot";
  layout?: "flow" | "timeline" | "branch" | "cycle" | "stack" | "split" | "hub";
  title?: string;
  caption?: string;
  latex?: string;
  // Code figure fields
  code?: string;
  language?: string;
  highlightLines?: number[];
  // Plot figure fields
  xRange?: [number, number];
  yRange?: [number, number];
  xLabel?: string;
  yLabel?: string;
  functions?: PlotFunctionSpec[];
  points?: PlotPointSpec[];
  params?: PlotParamSpec[];
  // Table & diagram fields
  headers?: string[];
  rows?: (TableRowSpec | (string | TableCellObj)[])[];
  nodes?: (FigureNode | string)[];
  edges?: FigureEdge[];
  items?: (FigureNode | string)[];
  left?: (FigureNode | string)[];
  right?: (FigureNode | string)[];
  center?: FigureNode | string;
  spokes?: (FigureNode | string)[];
}

function normalizeNodes(raw?: (FigureNode | string)[]): FigureNode[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item, idx) =>
    typeof item === "string"
      ? { id: `n${idx}`, label: item }
      : { id: item.id ?? `n${idx}`, label: item.label ?? "", sublabel: item.sublabel }
  );
}

/** Word-wrap Vietnamese/English node labels cleanly across up to `maxLines` lines without ugly mid-word cuts. */
function wrapSvgLabel(text: string, maxCharsPerLine: number, maxLines = 2): string[] {
  const words = (text || "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const candidate = cur ? `${cur} ${w}` : w;
    if (candidate.length <= maxCharsPerLine) {
      cur = candidate;
    } else {
      if (cur) lines.push(cur);
      cur = w.length > maxCharsPerLine ? `${w.slice(0, maxCharsPerLine - 1)}…` : w;
      if (lines.length >= maxLines - 1) break;
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  // If remaining words were omitted, append ellipsis on last line
  const joined = lines.join(" ").replace(/…$/, "");
  if (joined.length < (text || "").trim().length && lines.length === maxLines) {
    const last = lines[lines.length - 1];
    if (!last.endsWith("…")) {
      lines[lines.length - 1] =
        last.length >= maxCharsPerLine ? `${last.slice(0, maxCharsPerLine - 1)}…` : `${last}…`;
    }
  }
  return lines;
}

function WrappedSvgText({
  text,
  x,
  centerY,
  maxChars,
  maxLines = 2,
  fontSize = 12.5,
  fontWeight = 600,
  fill = "#1d1b18",
}: {
  text: string;
  x: number;
  centerY: number;
  maxChars: number;
  maxLines?: number;
  fontSize?: number;
  fontWeight?: number;
  fill?: string;
}) {
  const lines = wrapSvgLabel(text, maxChars, maxLines);
  const lineH = fontSize * 1.25;
  const startY = centerY - ((lines.length - 1) * lineH) / 2 + fontSize * 0.35;
  return (
    <text x={x} textAnchor="middle" fontSize={fontSize} fontWeight={fontWeight} fill={fill}>
      {lines.map((ln, idx) => (
        <tspan key={idx} x={x} y={startY + idx * lineH}>
          {ln}
        </tspan>
      ))}
    </text>
  );
}

const TONE_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  moss: { bg: "#ecfdf3", color: "#14532d", border: "#86efac" },
  clay: { bg: "#fff1ed", color: "#7c2d12", border: "#fdba74" },
  neutral: { bg: "#f7f5f0", color: "#1f1d1a", border: "#e2ddd3" },
};

// ---------------------------------------------------------------------------
// Zero-eval safe recursive-descent mathematical expression evaluator for `plot`
// ---------------------------------------------------------------------------
type MathToken =
  | { t: "num"; v: number }
  | { t: "id"; v: string }
  | { t: "op"; v: string }
  | { t: "lp" }
  | { t: "rp" }
  | { t: "comma" };

const SAFE_MATH_FUNCS: Record<string, (...args: number[]) => number> = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sinh: Math.sinh,
  cosh: Math.cosh,
  tanh: Math.tanh,
  exp: Math.exp,
  ln: Math.log,
  log: Math.log,
  log10: Math.log10,
  sqrt: Math.sqrt,
  abs: Math.abs,
  floor: Math.floor,
  ceil: Math.ceil,
  min: Math.min,
  max: Math.max,
  pow: Math.pow,
};

function tokenizeMathExpr(expr: string): MathToken[] | null {
  const out: MathToken[] = [];
  let i = 0;
  const s = (expr || "").replace(/\*\*/g, "^");
  while (i < s.length) {
    const ch = s[i];
    if (/\s/.test(ch)) {
      i += 1;
      continue;
    }
    if (/[0-9.]/.test(ch)) {
      let j = i;
      while (j < s.length && /[0-9.]/.test(s[j])) j += 1;
      const num = Number(s.slice(i, j));
      if (!Number.isFinite(num)) return null;
      out.push({ t: "num", v: num });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(ch)) {
      let j = i;
      while (j < s.length && /[A-Za-z0-9_]/.test(s[j])) j += 1;
      out.push({ t: "id", v: s.slice(i, j) });
      i = j;
      continue;
    }
    if ("+-*/^".includes(ch)) {
      out.push({ t: "op", v: ch });
      i += 1;
      continue;
    }
    if (ch === "(") {
      out.push({ t: "lp" });
      i += 1;
      continue;
    }
    if (ch === ")") {
      out.push({ t: "rp" });
      i += 1;
      continue;
    }
    if (ch === ",") {
      out.push({ t: "comma" });
      i += 1;
      continue;
    }
    return null;
  }
  return out;
}

function evaluateSafeMathExpr(expr: string, env: Record<string, number>): number {
  const tokens = tokenizeMathExpr(expr);
  if (!tokens || tokens.length === 0) return Number.NaN;
  let pos = 0;

  function peek(): MathToken | undefined {
    return tokens![pos];
  }

  function parseAddSub(): number {
    let left = parseMulDiv();
    while (peek()?.t === "op" && ((peek() as { v: string }).v === "+" || (peek() as { v: string }).v === "-")) {
      const op = (tokens![pos++] as { v: string }).v;
      const right = parseMulDiv();
      left = op === "+" ? left + right : left - right;
    }
    return left;
  }

  function parseMulDiv(): number {
    let left = parseUnary();
    while (peek()?.t === "op" && ((peek() as { v: string }).v === "*" || (peek() as { v: string }).v === "/")) {
      const op = (tokens![pos++] as { v: string }).v;
      const right = parseUnary();
      left = op === "*" ? left * right : left / right;
    }
    return left;
  }

  function parseUnary(): number {
    if (peek()?.t === "op" && ((peek() as { v: string }).v === "-" || (peek() as { v: string }).v === "+")) {
      const op = (tokens![pos++] as { v: string }).v;
      const val = parseUnary();
      return op === "-" ? -val : val;
    }
    return parsePow();
  }

  function parsePow(): number {
    const base = parsePrimary();
    if (peek()?.t === "op" && (peek() as { v: string }).v === "^") {
      pos += 1;
      const exp = parseUnary();
      return Math.pow(base, exp);
    }
    return base;
  }

  function parsePrimary(): number {
    const tok = peek();
    if (!tok) return Number.NaN;
    if (tok.t === "num") {
      pos += 1;
      return tok.v;
    }
    if (tok.t === "lp") {
      pos += 1;
      const v = parseAddSub();
      if (peek()?.t !== "rp") return Number.NaN;
      pos += 1;
      return v;
    }
    if (tok.t === "id") {
      pos += 1;
      const name = tok.v;
      const lower = name.toLowerCase();
      if (peek()?.t === "lp") {
        pos += 1;
        const fn = SAFE_MATH_FUNCS[lower];
        if (!fn) return Number.NaN;
        const args: number[] = [];
        if (peek()?.t !== "rp") {
          args.push(parseAddSub());
          while (peek()?.t === "comma") {
            pos += 1;
            args.push(parseAddSub());
          }
        }
        if (peek()?.t !== "rp") return Number.NaN;
        pos += 1;
        return fn(...args);
      }
      if (lower === "pi") return Math.PI;
      if (lower === "e") return Math.E;
      if (name in env) return env[name];
      if (lower in env) return env[lower];
      return Number.NaN;
    }
    return Number.NaN;
  }

  const result = parseAddSub();
  return pos === tokens.length ? result : Number.NaN;
}

const PLOT_PALETTE = ["#c85a27", "#15803d", "#2563eb", "#7c3aed"];

function FunctionPlotSvg({ figure }: { figure: LessonFigure }) {
  const xMin = figure.xRange?.[0] ?? -5;
  const xMax = figure.xRange?.[1] ?? 5;
  const yMin = figure.yRange?.[0] ?? -5;
  const yMax = figure.yRange?.[1] ?? 5;
  const funcs = useMemo(() => figure.functions ?? [], [figure.functions]);
  const points = useMemo(() => figure.points ?? [], [figure.points]);
  const paramSpecs = useMemo(() => figure.params ?? [], [figure.params]);

  const [paramValues, setParamValues] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    for (const p of paramSpecs) init[p.name] = p.value;
    return init;
  });
  const [hoverX, setHoverX] = useState<number | null>(null);

  const width = 540;
  const height = 300;
  const padL = 44;
  const padR = 18;
  const padT = 16;
  const padB = 34;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const toSvgX = (x: number) => padL + ((x - xMin) / (xMax - xMin)) * plotW;
  const toSvgY = (y: number) => padT + ((yMax - y) / (yMax - yMin)) * plotH;

  const paths = useMemo(() => {
    const samples = 240;
    const spanY = Math.max(1e-6, yMax - yMin);
    return funcs.map((fn, fIdx) => {
      const segments: string[] = [];
      let curSeg: string[] = [];
      let prevY: number | null = null;
      for (let i = 0; i <= samples; i++) {
        const x = xMin + (i / samples) * (xMax - xMin);
        const y = evaluateSafeMathExpr(fn.expr, { ...paramValues, x });
        const inView = Number.isFinite(y) && y >= yMin - spanY * 0.5 && y <= yMax + spanY * 0.5;
        const jumped = prevY !== null && Math.abs(y - prevY) > spanY * 1.2;
        if (!inView || jumped) {
          if (curSeg.length >= 2) segments.push(`M ${curSeg.join(" L ")}`);
          curSeg = [];
          prevY = null;
          continue;
        }
        curSeg.push(`${toSvgX(x).toFixed(1)},${toSvgY(y).toFixed(1)}`);
        prevY = y;
      }
      if (curSeg.length >= 2) segments.push(`M ${curSeg.join(" L ")}`);
      return {
        color: fn.color || PLOT_PALETTE[fIdx % PLOT_PALETTE.length],
        label: fn.label || `f(x) = ${fn.expr}`,
        expr: fn.expr,
        d: segments.join(" "),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [funcs, xMin, xMax, yMin, yMax, paramValues]);

  const xTicks = Array.from({ length: 5 }, (_, i) => xMin + (i / 4) * (xMax - xMin));
  const yTicks = Array.from({ length: 5 }, (_, i) => yMin + (i / 4) * (yMax - yMin));
  const zeroX = xMin <= 0 && xMax >= 0 ? toSvgX(0) : null;
  const zeroY = yMin <= 0 && yMax >= 0 ? toSvgY(0) : null;
  const clipId = `plot-clip-${Math.abs(Math.round(xMin * 31 + xMax * 17 + yMax * 13))}`;

  function handleMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * width;
    if (relX < padL || relX > width - padR) {
      setHoverX(null);
      return;
    }
    const mathX = xMin + ((relX - padL) / plotW) * (xMax - xMin);
    setHoverX(mathX);
  }

  return (
    <div>
      <svg
        role="img"
        aria-label={figure.title ?? "Đồ thị hàm số"}
        viewBox={`0 0 ${width} ${height}`}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverX(null)}
        style={{ width: "100%", height: "auto", display: "block", background: "#ffffff", borderRadius: 10 }}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={padL} y={padT} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Gridlines & ticks */}
        {xTicks.map((xt, idx) => {
          const sx = toSvgX(xt);
          return (
            <g key={`xt-${idx}`}>
              <line x1={sx} y1={padT} x2={sx} y2={padT + plotH} stroke="#f0ece4" strokeWidth={1} />
              <text x={sx} y={height - 10} textAnchor="middle" fontSize={11} fill="#6b655c">
                {Number(xt.toFixed(2))}
              </text>
            </g>
          );
        })}
        {yTicks.map((yt, idx) => {
          const sy = toSvgY(yt);
          return (
            <g key={`yt-${idx}`}>
              <line x1={padL} y1={sy} x2={padL + plotW} y2={sy} stroke="#f0ece4" strokeWidth={1} />
              <text x={padL - 8} y={sy + 4} textAnchor="end" fontSize={11} fill="#6b655c">
                {Number(yt.toFixed(2))}
              </text>
            </g>
          );
        })}

        {/* Axes */}
        <rect x={padL} y={padT} width={plotW} height={plotH} fill="none" stroke="#d4cec4" strokeWidth={1} />
        {zeroX !== null && <line x1={zeroX} y1={padT} x2={zeroX} y2={padT + plotH} stroke="#8f887d" strokeWidth={1.5} />}
        {zeroY !== null && <line x1={padL} y1={zeroY} x2={padL + plotW} y2={zeroY} stroke="#8f887d" strokeWidth={1.5} />}

        {/* Curves */}
        <g clipPath={`url(#${clipId})`}>
          {paths.map((p, idx) => (
            <path key={idx} d={p.d} fill="none" stroke={p.color} strokeWidth={2.4} strokeLinecap="round" />
          ))}
          {points.map((pt, idx) => {
            const px = toSvgX(pt.x);
            const py = toSvgY(pt.y);
            return (
              <g key={`pt-${idx}`}>
                <circle cx={px} cy={py} r={4.5} fill="#c85a27" stroke="#ffffff" strokeWidth={1.5} />
                {pt.label && (
                  <text x={px + 7} y={py - 6} fontSize={11.5} fontWeight={600} fill="#1d1b18">
                    {pt.label}
                  </text>
                )}
              </g>
            );
          })}
          {hoverX !== null && (
            <g>
              <line
                x1={toSvgX(hoverX)}
                y1={padT}
                x2={toSvgX(hoverX)}
                y2={padT + plotH}
                stroke="#c85a27"
                strokeDasharray="4 4"
                strokeWidth={1.2}
              />
              {paths.map((p, idx) => {
                const y = evaluateSafeMathExpr(p.expr, { ...paramValues, x: hoverX });
                if (!Number.isFinite(y) || y < yMin || y > yMax) return null;
                return <circle key={`hv-${idx}`} cx={toSvgX(hoverX)} cy={toSvgY(y)} r={4} fill={p.color} stroke="#fff" strokeWidth={1.5} />;
              })}
            </g>
          )}
        </g>

        {figure.xLabel && (
          <text x={padL + plotW - 4} y={height - 20} textAnchor="end" fontSize={11.5} fontWeight={600} fill="#4b4740">
            {figure.xLabel}
          </text>
        )}
        {figure.yLabel && (
          <text x={padL + 8} y={padT + 14} textAnchor="start" fontSize={11.5} fontWeight={600} fill="#4b4740">
            {figure.yLabel}
          </text>
        )}
      </svg>

      {/* Legend & Hover readout */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 10, fontSize: 12.5, alignItems: "center" }}>
        {paths.map((p, idx) => {
          const hvY = hoverX !== null ? evaluateSafeMathExpr(p.expr, { ...paramValues, x: hoverX }) : null;
          return (
            <span key={idx} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#1f1d1a" }}>
              <span style={{ width: 12, height: 3, background: p.color, display: "inline-block", borderRadius: 2 }} />
              <strong>{p.label}</strong>
              {hoverX !== null && hvY !== null && Number.isFinite(hvY) && (
                <span style={{ color: "#6b655c" }}>
                  ({hoverX.toFixed(2)}, {hvY.toFixed(2)})
                </span>
              )}
            </span>
          );
        })}
      </div>

      {/* Interactive parameter sliders */}
      {paramSpecs.length > 0 && (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            borderRadius: 10,
            background: "#f7f5f0",
            display: "grid",
            gap: 8,
          }}
        >
          {paramSpecs.map((p) => (
            <label
              key={p.name}
              style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "#1f1d1a" }}
            >
              <span style={{ minWidth: 92, fontWeight: 600 }}>
                {p.label || p.name} = {(paramValues[p.name] ?? p.value).toFixed(2)}
              </span>
              <input
                type="range"
                min={p.min}
                max={p.max}
                step={p.step ?? (p.max - p.min) / 40}
                value={paramValues[p.name] ?? p.value}
                onChange={(e) =>
                  setParamValues((prev) => ({ ...prev, [p.name]: Number(e.target.value) }))
                }
                style={{ flex: 1, accentColor: "#c85a27" }}
              />
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function DiagramSvg({ figure }: { figure: LessonFigure }) {
  const layout = figure.layout ?? "flow";
  const nodes = normalizeNodes(figure.nodes ?? figure.items);
  const edges = figure.edges ?? [];
  const label = figure.title ?? `Biểu đồ ${layout}`;

  function findEdgeLabel(fromId?: string, toId?: string): string | undefined {
    if (!fromId || !toId) return undefined;
    const match = edges.find(
      (e) => (e.from ?? e.source) === fromId && (e.to ?? e.target) === toId && e.label
    );
    return match?.label;
  }

  if (layout === "flow" || layout === "timeline") {
    const count = Math.max(1, nodes.length);
    const boxW = 160;
    const gap = 46;
    const width = Math.max(380, count * boxW + (count - 1) * gap + 40);
    const height = layout === "timeline" ? 142 : 122;
    return (
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        {layout === "timeline" && (
          <line x1={28} y1={34} x2={width - 28} y2={34} stroke="#d4cec4" strokeWidth={3} strokeLinecap="round" />
        )}
        {nodes.map((node, i) => {
          const x = 20 + i * (boxW + gap);
          const y = layout === "timeline" ? 56 : 26;
          const nextNode = nodes[i + 1];
          const edgeLbl = nextNode ? findEdgeLabel(node.id, nextNode.id) : undefined;
          return (
            <g key={node.id ?? i}>
              {layout === "timeline" && <circle cx={x + boxW / 2} cy={34} r={9} fill="#c85a27" />}
              <rect
                x={x}
                y={y}
                width={boxW}
                height={66}
                rx={12}
                fill="#ffffff"
                stroke="#c85a27"
                strokeWidth={1.75}
              />
              <WrappedSvgText
                text={node.label}
                x={x + boxW / 2}
                centerY={y + 33}
                maxChars={20}
                maxLines={3}
                fontSize={12.5}
              />
              {layout === "flow" && i < nodes.length - 1 && (
                <g>
                  <line
                    x1={x + boxW + 4}
                    y1={y + 33}
                    x2={x + boxW + gap - 8}
                    y2={y + 33}
                    stroke="#8c4020"
                    strokeWidth={2}
                  />
                  <polygon
                    points={`${x + boxW + gap - 10},${y + 27} ${x + boxW + gap - 2},${y + 33} ${x + boxW + gap - 10},${y + 39}`}
                    fill="#8c4020"
                  />
                  {edgeLbl && (
                    <text
                      x={x + boxW + gap / 2}
                      y={y + 22}
                      textAnchor="middle"
                      fontSize={10.5}
                      fontWeight={600}
                      fill="#7c2d12"
                    >
                      {edgeLbl.slice(0, 14)}
                    </text>
                  )}
                </g>
              )}
            </g>
          );
        })}
      </svg>
    );
  }

  if (layout === "stack") {
    const count = Math.max(1, nodes.length);
    const width = 480;
    const height = count * 60 + 24;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {nodes.map((node, i) => {
          const y = 12 + i * 58;
          return (
            <g key={node.id ?? i}>
              <rect x={24} y={y} width={width - 48} height={48} rx={10} fill={i === 0 ? "#fff5ef" : "#ffffff"} stroke="#c85a27" strokeWidth={1.6} />
              <WrappedSvgText text={node.label} x={width / 2} centerY={y + 24} maxChars={44} maxLines={2} fontSize={13} />
            </g>
          );
        })}
      </svg>
    );
  }

  if (layout === "split") {
    const leftNodes = figure.left
      ? normalizeNodes(figure.left)
      : nodes.filter((_, idx) => idx % 2 === 0);
    const rightNodes = figure.right
      ? normalizeNodes(figure.right)
      : nodes.filter((_, idx) => idx % 2 === 1);
    const rows = Math.max(leftNodes.length, rightNodes.length, 1);
    const width = 540;
    const height = rows * 66 + 28;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <line x1={width / 2} y1={14} x2={width / 2} y2={height - 14} stroke="#d4cec4" strokeDasharray="4 4" strokeWidth={1.5} />
        {Array.from({ length: rows }).map((_, i) => {
          const y = 16 + i * 64;
          const l = leftNodes[i];
          const r = rightNodes[i];
          return (
            <g key={i}>
              {l && (
                <>
                  <rect x={16} y={y} width={232} height={52} rx={10} fill="#ecfdf3" stroke="#15803d" strokeWidth={1.4} />
                  <WrappedSvgText text={l.label} x={132} centerY={y + 26} maxChars={26} maxLines={2} fontSize={12.5} fill="#14532d" />
                </>
              )}
              {r && (
                <>
                  <rect x={292} y={y} width={232} height={52} rx={10} fill="#fff1ed" stroke="#c85a27" strokeWidth={1.4} />
                  <WrappedSvgText text={r.label} x={408} centerY={y + 26} maxChars={26} maxLines={2} fontSize={12.5} fill="#7c2d12" />
                </>
              )}
            </g>
          );
        })}
      </svg>
    );
  }

  if (layout === "branch") {
    const root = nodes[0] ?? { id: "root", label: "Root" };
    const leaves = nodes.slice(1);
    const leafCount = Math.max(1, leaves.length);
    const width = Math.max(480, leafCount * 172 + 40);
    const height = 204;
    const rootCx = width / 2;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <rect x={rootCx - 96} y={14} width={192} height={54} rx={12} fill="#fff5ef" stroke="#c85a27" strokeWidth={2} />
        <WrappedSvgText text={root.label} x={rootCx} centerY={41} maxChars={22} maxLines={2} fontSize={13} fontWeight={700} />
        {leaves.map((leaf, i) => {
          const cx = ((i + 0.5) * width) / leafCount;
          const edgeLbl = findEdgeLabel(root.id, leaf.id);
          return (
            <g key={leaf.id ?? i}>
              <path d={`M ${rootCx} 68 C ${rootCx} 98, ${cx} 92, ${cx} 124`} fill="none" stroke="#8c4020" strokeWidth={1.8} />
              {edgeLbl && (
                <text x={(rootCx + cx) / 2} y={102} textAnchor="middle" fontSize={10.5} fontWeight={600} fill="#7c2d12">
                  {edgeLbl.slice(0, 16)}
                </text>
              )}
              <rect x={cx - 78} y={124} width={156} height={60} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.6} />
              <WrappedSvgText text={leaf.label} x={cx} centerY={154} maxChars={19} maxLines={3} fontSize={12} />
            </g>
          );
        })}
      </svg>
    );
  }

  if (layout === "cycle") {
    const count = Math.max(3, nodes.length);
    const width = 500;
    const height = 280;
    const cx = width / 2;
    const cy = height / 2;
    const rx = 160;
    const ry = 94;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke="#d4cec4" strokeWidth={2} strokeDasharray="5 4" />
        {nodes.map((node, i) => {
          const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
          const x = cx + Math.cos(angle) * rx;
          const y = cy + Math.sin(angle) * ry;
          return (
            <g key={node.id ?? i}>
              <rect x={x - 70} y={y - 24} width={140} height={48} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.7} />
              <WrappedSvgText text={node.label} x={x} centerY={y} maxChars={18} maxLines={2} fontSize={12} />
            </g>
          );
        })}
      </svg>
    );
  }

  // `hub` layout
  const centerNode = figure.center
    ? normalizeNodes([figure.center])[0]
    : nodes[0] ?? { id: "center", label: "Hub" };
  const spokes = figure.spokes ? normalizeNodes(figure.spokes) : nodes.slice(1);
  const spokeCount = Math.max(2, spokes.length);
  const width = 520;
  const height = 280;
  const cx = width / 2;
  const cy = height / 2;
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {spokes.map((spoke, i) => {
        const angle = (i / spokeCount) * Math.PI * 2 - Math.PI / 2;
        const x = cx + Math.cos(angle) * 168;
        const y = cy + Math.sin(angle) * 96;
        const edgeLbl = findEdgeLabel(centerNode.id, spoke.id);
        return (
          <g key={spoke.id ?? i}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#8c4020" strokeWidth={1.6} />
            {edgeLbl && (
              <text x={(cx + x) / 2} y={(cy + y) / 2 - 4} textAnchor="middle" fontSize={10} fontWeight={600} fill="#7c2d12">
                {edgeLbl.slice(0, 14)}
              </text>
            )}
            <rect x={x - 68} y={y - 23} width={136} height={46} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.5} />
            <WrappedSvgText text={spoke.label} x={x} centerY={y} maxChars={17} maxLines={2} fontSize={11.5} />
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r={48} fill="#fff5ef" stroke="#c85a27" strokeWidth={2.2} />
      <WrappedSvgText text={centerNode.label} x={cx} centerY={cy} maxChars={12} maxLines={2} fontSize={12.5} fontWeight={700} />
    </svg>
  );
}

export default function FigureRenderer({ figure }: { figure: LessonFigure }) {
  const kind = figure.kind ?? figure.type ?? "diagram";

  return (
    <figure
      className="lesson-figure"
      data-figure-kind={kind}
      data-figure-layout={figure.layout ?? undefined}
      style={{
        margin: "18px 0",
        padding: 16,
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--linen)",
        background: "var(--surface)",
      }}
    >
      {figure.title && (
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--ink)", marginBottom: 10 }}>
          {figure.title}
        </div>
      )}

      {kind === "formula" && figure.latex && (
        <div style={{ textAlign: "center", padding: "12px 8px", overflowX: "auto" }}>
          <FormulaMath latex={figure.latex} display />
        </div>
      )}

      {kind === "code" && figure.code && (
        <CodeBlockCard
          code={figure.code}
          language={figure.language}
          highlightLines={figure.highlightLines}
        />
      )}

      {kind === "plot" && Array.isArray(figure.functions) && figure.functions.length > 0 && (
        <FunctionPlotSvg figure={figure} />
      )}

      {kind === "table" && Array.isArray(figure.headers) && Array.isArray(figure.rows) && (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "separate",
              borderSpacing: "0 6px",
              fontSize: 14,
            }}
          >
            <thead>
              <tr>
                {figure.headers.map((h, i) => (
                  <th
                    key={i}
                    scope="col"
                    style={{
                      textAlign: "left",
                      padding: "8px 12px",
                      color: "var(--ink-2)",
                      fontWeight: 700,
                      borderBottom: "1px solid var(--linen)",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {figure.rows.map((rawRow, rIdx) => {
                const rowObj: TableRowSpec = Array.isArray(rawRow)
                  ? { tone: "neutral", cells: rawRow }
                  : rawRow;
                const rowTone = TONE_STYLES[rowObj.tone ?? "neutral"] ?? TONE_STYLES.neutral;
                return (
                  <tr key={rIdx} data-tone={rowObj.tone ?? "neutral"}>
                    {rowObj.cells.map((cell, cIdx) => {
                      const cellText = typeof cell === "string" ? cell : cell.text;
                      const cellTone =
                        typeof cell === "object" && cell.tone
                          ? TONE_STYLES[cell.tone] ?? rowTone
                          : rowTone;
                      return (
                        <td
                          key={cIdx}
                          style={{
                            padding: "10px 12px",
                            background: cellTone.bg,
                            color: cellTone.color,
                            borderTop: `1px solid ${cellTone.border}`,
                            borderBottom: `1px solid ${cellTone.border}`,
                            borderLeft: cIdx === 0 ? `1px solid ${cellTone.border}` : undefined,
                            borderRight:
                              cIdx === rowObj.cells.length - 1 ? `1px solid ${cellTone.border}` : undefined,
                            borderRadius:
                              cIdx === 0
                                ? "8px 0 0 8px"
                                : cIdx === rowObj.cells.length - 1
                                  ? "0 8px 8px 0"
                                  : undefined,
                            fontWeight: cIdx === 0 ? 600 : 400,
                          }}
                        >
                          {cellText}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {kind === "visual" && (
        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
          {normalizeNodes(figure.items ?? figure.nodes).map((item, idx) => (
            <div
              key={item.id ?? idx}
              style={{
                padding: "12px 14px",
                borderRadius: 10,
                background: "var(--wash)",
                border: "1px solid var(--linen)",
                color: "var(--ink)",
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              {item.label}
            </div>
          ))}
        </div>
      )}

      {kind === "diagram" && <DiagramSvg figure={figure} />}

      {figure.caption && (
        <figcaption className="caption" style={{ marginTop: 10 }}>
          {figure.caption}
        </figcaption>
      )}
    </figure>
  );
}
