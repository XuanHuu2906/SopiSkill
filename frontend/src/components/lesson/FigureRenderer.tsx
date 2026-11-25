"use client";

import { FormulaMath } from "./MathText";

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

export interface LessonFigure {
  kind?: "formula" | "table" | "visual" | "diagram";
  type?: "formula" | "table" | "visual" | "diagram";
  layout?: "flow" | "timeline" | "branch" | "cycle" | "stack" | "split" | "hub";
  title?: string;
  caption?: string;
  latex?: string;
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

const TONE_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  moss: { bg: "#ecfdf3", color: "#14532d", border: "#86efac" },
  clay: { bg: "#fff1ed", color: "#7c2d12", border: "#fdba74" },
  neutral: { bg: "#f7f5f0", color: "#1f1d1a", border: "#e2ddd3" },
};

function DiagramSvg({ figure }: { figure: LessonFigure }) {
  const layout = figure.layout ?? "flow";
  const nodes = normalizeNodes(figure.nodes ?? figure.items);
  const label = figure.title ?? `Biểu đồ ${layout}`;

  if (layout === "flow" || layout === "timeline") {
    const count = Math.max(1, nodes.length);
    const boxW = 148;
    const gap = 36;
    const width = Math.max(360, count * boxW + (count - 1) * gap + 40);
    const height = layout === "timeline" ? 132 : 108;
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
          const y = layout === "timeline" ? 56 : 24;
          return (
            <g key={node.id ?? i}>
              {layout === "timeline" && (
                <circle cx={x + boxW / 2} cy={34} r={9} fill="#c85a27" />
              )}
              <rect
                x={x}
                y={y}
                width={boxW}
                height={56}
                rx={12}
                fill="#ffffff"
                stroke="#c85a27"
                strokeWidth={1.75}
              />
              <text
                x={x + boxW / 2}
                y={y + 33}
                textAnchor="middle"
                fontSize={13}
                fontWeight={600}
                fill="#1d1b18"
              >
                {node.label.slice(0, 22)}
              </text>
              {layout === "flow" && i < nodes.length - 1 && (
                <g>
                  <line
                    x1={x + boxW + 4}
                    y1={y + 28}
                    x2={x + boxW + gap - 8}
                    y2={y + 28}
                    stroke="#8c4020"
                    strokeWidth={2}
                  />
                  <polygon
                    points={`${x + boxW + gap - 10},${y + 22} ${x + boxW + gap - 2},${y + 28} ${x + boxW + gap - 10},${y + 34}`}
                    fill="#8c4020"
                  />
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
    const width = 460;
    const height = count * 56 + 24;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {nodes.map((node, i) => {
          const y = 12 + i * 54;
          return (
            <g key={node.id ?? i}>
              <rect x={24} y={y} width={width - 48} height={44} rx={10} fill={i === 0 ? "#fff5ef" : "#ffffff"} stroke="#c85a27" strokeWidth={1.6} />
              <text x={width / 2} y={y + 27} textAnchor="middle" fontSize={13.5} fontWeight={600} fill="#1d1b18">
                {node.label.slice(0, 44)}
              </text>
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
    const width = 520;
    const height = rows * 58 + 28;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <line x1={width / 2} y1={14} x2={width / 2} y2={height - 14} stroke="#d4cec4" strokeDasharray="4 4" strokeWidth={1.5} />
        {Array.from({ length: rows }).map((_, i) => {
          const y = 16 + i * 56;
          const l = leftNodes[i];
          const r = rightNodes[i];
          return (
            <g key={i}>
              {l && (
                <>
                  <rect x={16} y={y} width={220} height={44} rx={10} fill="#ecfdf3" stroke="#15803d" strokeWidth={1.4} />
                  <text x={126} y={y + 27} textAnchor="middle" fontSize={13} fontWeight={600} fill="#14532d">
                    {l.label.slice(0, 28)}
                  </text>
                </>
              )}
              {r && (
                <>
                  <rect x={284} y={y} width={220} height={44} rx={10} fill="#fff1ed" stroke="#c85a27" strokeWidth={1.4} />
                  <text x={394} y={y + 27} textAnchor="middle" fontSize={13} fontWeight={600} fill="#7c2d12">
                    {r.label.slice(0, 28)}
                  </text>
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
    const width = Math.max(460, leafCount * 160 + 40);
    const height = 186;
    const rootCx = width / 2;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <rect x={rootCx - 85} y={16} width={170} height={46} rx={12} fill="#fff5ef" stroke="#c85a27" strokeWidth={2} />
        <text x={rootCx} y={44} textAnchor="middle" fontSize={13.5} fontWeight={700} fill="#1d1b18">
          {root.label.slice(0, 24)}
        </text>
        {leaves.map((leaf, i) => {
          const cx = ((i + 0.5) * width) / leafCount;
          return (
            <g key={leaf.id ?? i}>
              <path d={`M ${rootCx} 62 C ${rootCx} 92, ${cx} 86, ${cx} 116`} fill="none" stroke="#8c4020" strokeWidth={1.8} />
              <rect x={cx - 72} y={116} width={144} height={48} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.6} />
              <text x={cx} y={145} textAnchor="middle" fontSize={12.5} fontWeight={600} fill="#1d1b18">
                {leaf.label.slice(0, 20)}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  if (layout === "cycle") {
    const count = Math.max(3, nodes.length);
    const width = 460;
    const height = 260;
    const cx = width / 2;
    const cy = height / 2;
    const rx = 148;
    const ry = 88;
    return (
      <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
        <ellipse cx={cx} cy={cy} rx={rx} ry={ry} fill="none" stroke="#d4cec4" strokeWidth={2} strokeDasharray="5 4" />
        {nodes.map((node, i) => {
          const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
          const x = cx + Math.cos(angle) * rx;
          const y = cy + Math.sin(angle) * ry;
          return (
            <g key={node.id ?? i}>
              <rect x={x - 62} y={y - 20} width={124} height={40} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.7} />
              <text x={x} y={y + 5} textAnchor="middle" fontSize={12.5} fontWeight={600} fill="#1d1b18">
                {node.label.slice(0, 18)}
              </text>
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
  const width = 480;
  const height = 260;
  const cx = width / 2;
  const cy = height / 2;
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }}>
      {spokes.map((spoke, i) => {
        const angle = (i / spokeCount) * Math.PI * 2 - Math.PI / 2;
        const x = cx + Math.cos(angle) * 155;
        const y = cy + Math.sin(angle) * 90;
        return (
          <g key={spoke.id ?? i}>
            <line x1={cx} y1={cy} x2={x} y2={y} stroke="#8c4020" strokeWidth={1.6} />
            <rect x={x - 60} y={y - 19} width={120} height={38} rx={10} fill="#ffffff" stroke="#c85a27" strokeWidth={1.5} />
            <text x={x} y={y + 5} textAnchor="middle" fontSize={12} fontWeight={600} fill="#1d1b18">
              {spoke.label.slice(0, 18)}
            </text>
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r={44} fill="#fff5ef" stroke="#c85a27" strokeWidth={2.2} />
      <text x={cx} y={cy + 5} textAnchor="middle" fontSize={13} fontWeight={700} fill="#1d1b18">
        {centerNode.label.slice(0, 14)}
      </text>
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
