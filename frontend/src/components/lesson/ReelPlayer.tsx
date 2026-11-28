"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import { getCachedReelClip, putCachedReelClip } from "@/lib/offline/db";
import FigureRenderer, { FunctionPlotSvg, type LessonFigure } from "./FigureRenderer";
import MathText, { CodeBlockCard, FormulaMath } from "./MathText";

export const REEL_SPEEDS = [1, 1.25, 1.5] as const;
export type ReelSpeed = (typeof REEL_SPEEDS)[number];
export const DRIFT_TOLERANCE_MS = 80;

export interface ReelWordTiming {
  text: string;
  startMs: number;
  endMs: number;
}

export interface ReelCue {
  verb: "rise" | "draw" | "count" | "pulse";
  target: string;
}

export interface ReelBeat {
  index?: number;
  say: string;
  startMs: number;
  endMs: number;
  cues?: ReelCue[];
}

export interface ReelAudioSpec {
  clipId: string;
  url: string;
  contentType?: string;
  durationMs: number;
  provider?: string;
  voice?: string;
}

export interface ReelChartSpec {
  chartType: "bar" | "line" | "donut";
  unit?: string;
  series: { label: string; value: number }[];
}

export interface ReelCompiledPlotSpec {
  xRange: [number, number];
  yRange: [number, number];
  xLabel?: string;
  yLabel?: string;
  curves: {
    expr: string;
    label: string;
    color: string;
    segments: [number, number][][];
  }[];
  points?: { x: number; y: number; label?: string }[];
  tangents?: {
    expr?: string;
    x: number;
    y: number;
    slope: number;
    label?: string;
    segment: [[number, number], [number, number]];
  }[];
  areas?: {
    expr?: string;
    fromX: number;
    toX: number;
    label?: string;
    color?: string;
    polygon: [number, number][];
  }[];
}

export interface ReelScene {
  id: string;
  kind:
    | "title"
    | "statement"
    | "bullets"
    | "term"
    | "compare"
    | "figure"
    | "chart"
    | "code"
    | "equation"
    | "plot"
    | "ready"
    | "fallback";
  kicker?: string;
  title?: string;
  subtitle?: string;
  statement?: string;
  bullets?: string[];
  term?: string;
  definition?: string;
  leftTitle?: string;
  leftPoints?: string[];
  rightTitle?: string;
  rightPoints?: string[];
  sourceFigureId?: string;
  image?: {
    url: string;
    alt?: string;
    caption?: string;
    sourceTitle?: string;
    attribution?: string;
  };
  figure?: LessonFigure;
  chart?: ReelChartSpec;
  code?: string;
  language?: string;
  highlightLines?: number[];
  steps?: { latex: string; note?: string }[];
  plot?: ReelCompiledPlotSpec;
  ctaLabel?: string;
  durationMs: number;
  audio?: ReelAudioSpec | null;
  words?: ReelWordTiming[];
  beats?: ReelBeat[];
}

export interface ReelManifest {
  id: string;
  version: number;
  contentVersion?: number;
  styleVersion?: string;
  language?: string;
  durationMs: number;
  scenes: ReelScene[];
}

function resolveMediaUrl(url: string): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("blob:")) {
    return url;
  }
  return `${API_BASE}${url}`;
}

function ReelChartSvg({ chart, progress }: { chart: ReelChartSpec; progress: number }) {
  const series = chart.series ?? [];
  const maxVal = Math.max(1, ...series.map((s) => Math.abs(s.value)));
  const unit = chart.unit ?? "";
  const colors = ["#c85a27", "#2d6a4f", "#1d4ed8", "#7c3aed", "#b45309", "#0f766e"];
  const ease = Math.min(1, Math.max(0.25, progress));

  if (chart.chartType === "donut") {
    const total = Math.max(1e-6, series.reduce((acc, s) => acc + Math.max(0, s.value), 0));
    const r = 64;
    const circ = 2 * Math.PI * r;
    const slices = series.reduce<
      { label: string; value: number; frac: number; dashLen: number; offset: number; color: string }[]
    >((acc, s, idx) => {
      const prev = acc[acc.length - 1];
      const offset = prev ? prev.offset + prev.dashLen : 0;
      const frac = Math.max(0, s.value) / total;
      const dashLen = frac * circ * ease;
      acc.push({
        label: s.label,
        value: s.value,
        frac,
        dashLen,
        offset,
        color: colors[idx % colors.length],
      });
      return acc;
    }, []);
    return (
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <svg role="img" aria-label="Biểu đồ tỷ trọng" width={180} height={180} viewBox="0 0 180 180">
          <circle cx={90} cy={90} r={r} fill="none" stroke="#e7e2d9" strokeWidth={22} />
          {slices.map((s, idx) => (
            <circle
              key={idx}
              cx={90}
              cy={90}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth={22}
              strokeDasharray={`${s.dashLen} ${circ}`}
              strokeDashoffset={-s.offset}
              transform="rotate(-90 90 90)"
            />
          ))}
        </svg>
        <div style={{ display: "grid", gap: 6, fontSize: 13 }}>
          {slices.map((s, idx) => (
            <div key={idx} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 10, height: 10, borderRadius: 99, background: s.color, display: "inline-block" }} />
              <strong>{s.label}:</strong> {s.value}
              {unit}
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (chart.chartType === "line") {
    const w = 480;
    const h = 190;
    const padL = 44;
    const padR = 20;
    const padT = 18;
    const padB = 34;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;
    const pts = series.map((s, idx) => {
      const x = padL + (series.length <= 1 ? plotW / 2 : (idx / (series.length - 1)) * plotW);
      const y = padT + plotH - (Math.max(0, s.value) / maxVal) * plotH * ease;
      return { x, y, ...s };
    });
    const d = pts.map((p, idx) => `${idx === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
    return (
      <svg role="img" aria-label="Biểu đồ đường" viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto" }}>
        <line x1={padL} y1={padT + plotH} x2={w - padR} y2={padT + plotH} stroke="#cfc9be" strokeWidth={1.5} />
        <path d={d} fill="none" stroke="#c85a27" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
        {pts.map((p, idx) => (
          <g key={idx}>
            <circle cx={p.x} cy={p.y} r={5} fill="#c85a27" stroke="#ffffff" strokeWidth={2} />
            <text x={p.x} y={p.y - 10} textAnchor="middle" fontSize={11} fontWeight={700} fill="#1f1d1a">
              {p.value}
              {unit}
            </text>
            <text x={p.x} y={h - 10} textAnchor="middle" fontSize={11} fill="#5c564d">
              {p.label}
            </text>
          </g>
        ))}
      </svg>
    );
  }

  // Default: bar chart
  const w = 480;
  const h = 200;
  const padL = 24;
  const padR = 24;
  const padT = 26;
  const padB = 38;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const barGap = 18;
  const barW = Math.min(84, Math.max(28, (plotW - barGap * Math.max(0, series.length - 1)) / Math.max(1, series.length)));
  const totalRowW = series.length * barW + Math.max(0, series.length - 1) * barGap;
  const startX = (w - totalRowW) / 2;

  return (
    <svg role="img" aria-label="Biểu đồ cột" viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "auto" }}>
      <line x1={padL} y1={padT + plotH} x2={w - padR} y2={padT + plotH} stroke="#cfc9be" strokeWidth={1.5} />
      {series.map((s, idx) => {
        const barH = Math.max(6, (Math.max(0, s.value) / maxVal) * plotH * ease);
        const x = startX + idx * (barW + barGap);
        const y = padT + plotH - barH;
        const shownVal = Math.round(s.value * ease);
        return (
          <g key={idx}>
            <rect x={x} y={y} width={barW} height={barH} rx={8} fill={colors[idx % colors.length]} />
            <text x={x + barW / 2} y={y - 7} textAnchor="middle" fontSize={12} fontWeight={700} fill="#1f1d1a">
              {shownVal}
              {unit}
            </text>
            <text x={x + barW / 2} y={h - 12} textAnchor="middle" fontSize={11.5} fill="#5c564d">
              {s.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function ReelCompiledPlotSvg({ plot }: { plot: ReelCompiledPlotSpec }) {
  const [interactiveMode, setInteractiveMode] = useState(false);

  if (interactiveMode) {
    const figureCompat: LessonFigure = {
      kind: "plot",
      xRange: plot.xRange,
      yRange: plot.yRange,
      xLabel: plot.xLabel,
      yLabel: plot.yLabel,
      functions: plot.curves.map((c) => ({ expr: c.expr, label: c.label, color: c.color })),
      points: plot.points,
    };
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <button type="button" className="btn btn-secondary" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setInteractiveMode(false)}>
            Xem bản Reel (tiếp tuyến & tích phân)
          </button>
        </div>
        <FunctionPlotSvg figure={figureCompat} />
      </div>
    );
  }

  const [xMin, xMax] = plot.xRange ?? [-5, 5];
  const [yMin, yMax] = plot.yRange ?? [-5, 5];
  const w = 520;
  const h = 250;
  const padL = 42;
  const padR = 16;
  const padT = 16;
  const padB = 32;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const toX = (x: number) => padL + ((x - xMin) / Math.max(1e-6, xMax - xMin)) * plotW;
  const toY = (y: number) => padT + ((yMax - y) / Math.max(1e-6, yMax - yMin)) * plotH;

  const axisX = yMin <= 0 && yMax >= 0 ? toY(0) : padT + plotH;
  const axisY = xMin <= 0 && xMax >= 0 ? toX(0) : padL;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
        <button type="button" className="btn btn-secondary" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setInteractiveMode(true)}>
          Tương tác trực tiếp
        </button>
      </div>
      <svg
        role="img"
        aria-label="Đồ thị hàm số biên dịch AST"
        viewBox={`0 0 ${w} ${h}`}
        style={{ width: "100%", height: "auto", background: "#fcfbf8", borderRadius: 10, border: "1px solid var(--linen)" }}
      >
        <defs>
          <clipPath id="reel-plot-clip">
            <rect x={padL} y={padT} width={plotW} height={plotH} />
          </clipPath>
        </defs>
        <line x1={padL} y1={axisX} x2={padL + plotW} y2={axisX} stroke="#9c9487" strokeWidth={1.2} />
        <line x1={axisY} y1={padT} x2={axisY} y2={padT + plotH} stroke="#9c9487" strokeWidth={1.2} />

        <g clipPath="url(#reel-plot-clip)">
          {(plot.areas ?? []).map((area, idx) => {
            const pts = area.polygon.map(([x, y]) => `${toX(x).toFixed(1)},${toY(y).toFixed(1)}`).join(" ");
            return (
              <polygon
                key={`area-${idx}`}
                points={pts}
                fill={area.color || "rgba(200, 90, 39, 0.2)"}
                stroke="#c85a27"
                strokeOpacity={0.35}
                strokeWidth={1}
              />
            );
          })}

          {(plot.curves ?? []).map((curve, cIdx) =>
            (curve.segments ?? []).map((seg, sIdx) => {
              const d = seg
                .map(([x, y], pIdx) => `${pIdx === 0 ? "M" : "L"} ${toX(x).toFixed(1)} ${toY(y).toFixed(1)}`)
                .join(" ");
              return (
                <path
                  key={`c-${cIdx}-${sIdx}`}
                  d={d}
                  fill="none"
                  stroke={curve.color || "#c85a27"}
                  strokeWidth={2.6}
                  strokeLinecap="round"
                />
              );
            }),
          )}

          {(plot.tangents ?? []).map((tan, idx) => {
            const [[x1, y1], [x2, y2]] = tan.segment;
            return (
              <g key={`tan-${idx}`}>
                <line
                  x1={toX(x1)}
                  y1={toY(y1)}
                  x2={toX(x2)}
                  y2={toY(y2)}
                  stroke="#1d4ed8"
                  strokeWidth={2}
                  strokeDasharray="6 4"
                />
                <circle cx={toX(tan.x)} cy={toY(tan.y)} r={4.5} fill="#1d4ed8" stroke="#ffffff" strokeWidth={1.5} />
                {tan.label && (
                  <text x={toX(tan.x) + 8} y={toY(tan.y) - 8} fontSize={11} fontWeight={700} fill="#1d4ed8">
                    {tan.label}
                  </text>
                )}
              </g>
            );
          })}

          {(plot.points ?? []).map((pt, idx) => (
            <g key={`pt-${idx}`}>
              <circle cx={toX(pt.x)} cy={toY(pt.y)} r={4.5} fill="#c85a27" stroke="#ffffff" strokeWidth={1.5} />
              {pt.label && (
                <text x={toX(pt.x) + 7} y={toY(pt.y) - 6} fontSize={11} fontWeight={700} fill="#1f1d1a">
                  {pt.label}
                </text>
              )}
            </g>
          ))}
        </g>

        <text x={padL + plotW - 4} y={h - 10} textAnchor="end" fontSize={11} fill="#5c564d">
          {plot.xLabel ?? "x"}
        </text>
        <text x={padL + 8} y={padT + 14} textAnchor="start" fontSize={11} fill="#5c564d">
          {plot.yLabel ?? "y"}
        </text>
      </svg>
    </div>
  );
}

export default function ReelPlayer({
  manifest,
  lessonId,
  ownerId,
  onStartPractice,
  onClose,
}: {
  manifest: ReelManifest;
  lessonId: string;
  ownerId?: string;
  onStartPractice?: () => void;
  onClose?: () => void;
}) {
  const scenes = useMemo(() => manifest?.scenes ?? [], [manifest]);
  const [sceneIndex, setSceneIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [captionsOn, setCaptionsOn] = useState(true);
  const [speed, setSpeed] = useState<ReelSpeed>(1);
  const [sceneTimeMs, setSceneTimeMs] = useState(0);
  const [audioSrc, setAudioSrc] = useState<string | null>(null);
  const [resyncCount, setResyncCount] = useState(0);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastFrameRef = useRef<number | null>(null);
  const sceneTimeRef = useRef(0);

  const currentScene = scenes[Math.min(sceneIndex, Math.max(0, scenes.length - 1))];
  const sceneDurationMs = Math.max(1000, currentScene?.durationMs ?? 3000);

  const goToScene = useCallback(
    (nextIdx: number) => {
      const clamped = Math.max(0, Math.min(nextIdx, scenes.length - 1));
      setSceneIndex(clamped);
      sceneTimeRef.current = 0;
      setSceneTimeMs(0);
      lastFrameRef.current = null;
    },
    [scenes.length],
  );

  // Resolve scene audio clip from IndexedDB `cached_reel_clips` first, else fetch & cache cleanly
  useEffect(() => {
    let active = true;
    let createdBlobUrl: string | null = null;

    async function loadAudio() {
      const audioSpec = currentScene?.audio;
      if (!audioSpec?.url || !audioSpec?.clipId) {
        setAudioSrc(null);
        return;
      }
      const cacheKey = `${lessonId}:${audioSpec.clipId}`;
      if (ownerId) {
        const cached = await getCachedReelClip(cacheKey, ownerId).catch(() => null);
        if (cached && active) {
          createdBlobUrl = URL.createObjectURL(new Blob([cached.bytes], { type: cached.contentType }));
          setAudioSrc(createdBlobUrl);
          return;
        }
      }
      if (typeof navigator !== "undefined" && !navigator.onLine) {
        if (active) setAudioSrc(null);
        return;
      }
      try {
        const resp = await fetch(resolveMediaUrl(audioSpec.url), { credentials: "include" });
        if (!resp.ok) {
          if (active) setAudioSrc(null);
          return;
        }
        const buf = await resp.arrayBuffer();
        const ctype = audioSpec.contentType || resp.headers.get("content-type") || "audio/wav";
        if (ownerId) {
          void putCachedReelClip(cacheKey, ownerId, lessonId, ctype, buf).catch(() => {});
        }
        if (active) {
          createdBlobUrl = URL.createObjectURL(new Blob([buf], { type: ctype }));
          setAudioSrc(createdBlobUrl);
        }
      } catch {
        if (active) setAudioSrc(null);
      }
    }

    void loadAudio();
    return () => {
      active = false;
      if (createdBlobUrl) {
        URL.revokeObjectURL(createdBlobUrl);
      }
    };
  }, [currentScene, lessonId, ownerId]);

  // Synchronize HTMLAudioElement playbackRate, mute & play/pause
  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;
    el.playbackRate = speed;
    el.muted = muted;
    if (playing && audioSrc && !muted) {
      el.currentTime = Math.min(el.duration || sceneDurationMs / 1000, sceneTimeRef.current / 1000);
      void el.play().catch(() => {
        // Autoplay policy or headless silent mode -> RAF clock keeps visual reel advancing smoothly
      });
    } else {
      el.pause();
    }
  }, [playing, audioSrc, muted, speed, sceneDurationMs]);

  // Master visual clock + 80ms drift resync against <audio>
  useEffect(() => {
    if (!playing) {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      lastFrameRef.current = null;
      return;
    }

    const tick = (now: number) => {
      if (lastFrameRef.current === null) {
        lastFrameRef.current = now;
      }
      const deltaMs = (now - lastFrameRef.current) * speed;
      lastFrameRef.current = now;

      let nextMs = sceneTimeRef.current + deltaMs;
      const el = audioRef.current;
      if (el && audioSrc && !muted && !el.paused && Number.isFinite(el.currentTime)) {
        const audioMs = el.currentTime * 1000;
        if (Math.abs(nextMs - audioMs) > DRIFT_TOLERANCE_MS) {
          nextMs = audioMs;
          setResyncCount((c) => c + 1);
        }
      }

      if (nextMs >= sceneDurationMs) {
        if (sceneIndex + 1 < scenes.length) {
          goToScene(sceneIndex + 1);
        } else {
          sceneTimeRef.current = sceneDurationMs;
          setSceneTimeMs(sceneDurationMs);
          setPlaying(false);
        }
        return;
      }

      sceneTimeRef.current = nextMs;
      setSceneTimeMs(nextMs);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, speed, muted, audioSrc, sceneDurationMs, sceneIndex, scenes.length, goToScene]);

  if (!currentScene) return null;

  const progress = Math.min(1, sceneTimeMs / sceneDurationMs);
  const words = currentScene.words ?? [];
  const activeBeatIdx = Math.max(
    0,
    (currentScene.beats ?? []).findIndex((b) => sceneTimeMs >= b.startMs && sceneTimeMs <= b.endMs),
  );
  const activeCues = currentScene.beats?.[activeBeatIdx]?.cues ?? [];
  const cueVerbs = new Set(activeCues.map((c) => c.verb));

  function cycleSpeed() {
    const idx = REEL_SPEEDS.indexOf(speed);
    const next = REEL_SPEEDS[(idx + 1) % REEL_SPEEDS.length];
    setSpeed(next);
  }

  return (
    <section
      className="reel-player-card"
      data-testid="reel-player"
      data-scene-kind={currentScene.kind}
      data-scene-index={sceneIndex}
      data-speed={speed}
      data-resync-count={resyncCount}
      aria-label="Trình phát tóm tắt Reel có thuyết minh"
      style={{
        margin: "14px 0 22px",
        padding: 18,
        borderRadius: "var(--radius-lg, 16px)",
        border: "1px solid var(--linen)",
        background: "linear-gradient(180deg, #fffdf9 0%, #f9f5ee 100%)",
        boxShadow: "0 6px 24px rgba(31, 29, 26, 0.06)",
      }}
    >
      {/* Hidden native audio element for synchronized playback */}
      <audio ref={audioRef} src={audioSrc ?? undefined} preload="auto" aria-hidden="true" />

      {/* Top Segmented Story Progress Bars */}
      <div
        role="tablist"
        aria-label="Các phân cảnh Reel"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${scenes.length}, minmax(0, 1fr))`,
          gap: 5,
          marginBottom: 14,
        }}
      >
        {scenes.map((sc, idx) => {
          const fill = idx < sceneIndex ? 100 : idx === sceneIndex ? Math.round(progress * 100) : 0;
          return (
            <button
              key={sc.id || idx}
              type="button"
              role="tab"
              aria-selected={idx === sceneIndex}
              aria-label={`Phân cảnh ${idx + 1}: ${sc.title || sc.kind}`}
              onClick={() => goToScene(idx)}
              style={{
                height: 6,
                minHeight: 0,
                minWidth: 0,
                border: 0,
                padding: 0,
                borderRadius: 99,
                background: "#e5dfd5",
                overflow: "hidden",
                cursor: "pointer",
              }}
            >
              <span
                style={{
                  display: "block",
                  height: "100%",
                  width: `${fill}%`,
                  background: "#c85a27",
                  transition: idx === sceneIndex ? "none" : "width 0.2s ease",
                }}
              />
            </button>
          );
        })}
      </div>

      {/* Header bar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              color: "#9a3412",
              background: "#ffedd5",
              padding: "3px 8px",
              borderRadius: 99,
            }}
          >
            REEL · {sceneIndex + 1}/{scenes.length}
          </span>
          <span style={{ fontSize: 12, color: "#5c564d" }}>
            {currentScene.kind}
          </span>
        </div>
        {onClose && (
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: 12, padding: "4px 10px" }}
            onClick={() => {
              setPlaying(false);
              onClose();
            }}
          >
            Ẩn Reel
          </button>
        )}
      </div>

      {/* Visual Stage — supports all 11 scene kinds + fallback */}
      <div
        data-testid="reel-stage"
        style={{
          minHeight: 220,
          padding: 18,
          borderRadius: 12,
          background: "#ffffff",
          border: "1px solid var(--linen)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: 12,
          transform: cueVerbs.has("pulse") ? "scale(1.005)" : "none",
          transition: "transform 0.2s ease",
        }}
      >
        {currentScene.kicker && (
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", color: "#c85a27", textTransform: "uppercase" }}>
            {currentScene.kicker}
          </div>
        )}

        {currentScene.kind === "title" && (
          <div style={{ textAlign: "center", padding: "18px 8px" }}>
            <h2 style={{ fontSize: 24, fontWeight: 800, color: "#1d1b18", margin: "0 0 8px" }}>
              <MathText text={currentScene.title ?? ""} />
            </h2>
            {currentScene.subtitle && (
              <p style={{ fontSize: 15, color: "#5c564d", margin: 0 }}>
                <MathText text={currentScene.subtitle} />
              </p>
            )}
          </div>
        )}

        {currentScene.kind === "statement" && (
          <blockquote
            style={{
              margin: 0,
              padding: "12px 16px",
              borderLeft: "4px solid #c85a27",
              fontSize: 19,
              fontWeight: 650,
              lineHeight: 1.5,
              color: "#1d1b18",
            }}
          >
            <MathText text={currentScene.statement ?? ""} />
          </blockquote>
        )}

        {currentScene.kind === "bullets" && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 18, fontWeight: 750, margin: "0 0 12px", color: "#1d1b18" }}>
                <MathText text={currentScene.title} />
              </h3>
            )}
            <ul style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 8 }}>
              {(currentScene.bullets ?? []).map((item, idx) => (
                <li
                  key={idx}
                  style={{
                    fontSize: 15,
                    color: "#2b2824",
                    opacity: idx === 0 || progress >= idx / Math.max(1, (currentScene.bullets?.length ?? 1) + 0.5) ? 1 : 0.45,
                    transition: "opacity 0.25s ease",
                  }}
                >
                  <MathText text={item} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {currentScene.kind === "term" && (
          <div
            style={{
              padding: 16,
              borderRadius: 12,
              background: "#fff7ed",
              border: "1px solid #fed7aa",
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 700, color: "#9a3412", marginBottom: 4 }}>THUẬT NGỮ</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#1d1b18", marginBottom: 6 }}>
              <MathText text={currentScene.term ?? ""} />
            </div>
            <p style={{ margin: 0, fontSize: 14.5, color: "#3f3b35", lineHeight: 1.5 }}>
              <MathText text={currentScene.definition ?? ""} />
            </p>
          </div>
        )}

        {currentScene.kind === "compare" && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 17, fontWeight: 750, margin: "0 0 12px", color: "#1d1b18" }}>
                <MathText text={currentScene.title} />
              </h3>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
              <div style={{ padding: 12, borderRadius: 10, background: "#eef6f0", border: "1px solid #b7d8bf" }}>
                <div style={{ fontWeight: 700, color: "#1b5e20", marginBottom: 6 }}>
                  <MathText text={currentScene.leftTitle ?? ""} />
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, display: "grid", gap: 4 }}>
                  {(currentScene.leftPoints ?? []).map((p, i) => (
                    <li key={i}>
                      <MathText text={p} />
                    </li>
                  ))}
                </ul>
              </div>
              <div style={{ padding: 12, borderRadius: 10, background: "#fdf0ea", border: "1px solid #e7b9a6" }}>
                <div style={{ fontWeight: 700, color: "#9a3412", marginBottom: 6 }}>
                  <MathText text={currentScene.rightTitle ?? ""} />
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, display: "grid", gap: 4 }}>
                  {(currentScene.rightPoints ?? []).map((p, i) => (
                    <li key={i}>
                      <MathText text={p} />
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        {currentScene.kind === "figure" && (
          <div>
            {currentScene.image?.url ? (
              <figure style={{ margin: 0, textAlign: "center" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={resolveMediaUrl(currentScene.image.url)}
                  alt={currentScene.image.alt || currentScene.title || "Hình minh họa giáo trình"}
                  style={{ maxWidth: "100%", maxHeight: 260, borderRadius: 10, objectFit: "contain" }}
                />
                {(currentScene.image.caption || currentScene.image.attribution) && (
                  <figcaption style={{ marginTop: 8, fontSize: 12.5, color: "#5c564d" }}>
                    {currentScene.image.caption}
                    {currentScene.image.attribution ? ` — ${currentScene.image.attribution}` : ""}
                  </figcaption>
                )}
              </figure>
            ) : currentScene.figure ? (
              <FigureRenderer figure={currentScene.figure} />
            ) : null}
          </div>
        )}

        {currentScene.kind === "chart" && currentScene.chart && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 16.5, fontWeight: 750, margin: "0 0 10px", color: "#1d1b18" }}>
                {currentScene.title}
              </h3>
            )}
            <ReelChartSvg chart={currentScene.chart} progress={playing ? Math.max(0.4, progress) : 1} />
          </div>
        )}

        {currentScene.kind === "code" && currentScene.code && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 16.5, fontWeight: 750, margin: "0 0 8px", color: "#1d1b18" }}>
                {currentScene.title}
              </h3>
            )}
            <CodeBlockCard
              code={currentScene.code}
              language={currentScene.language}
              highlightLines={currentScene.highlightLines}
            />
          </div>
        )}

        {currentScene.kind === "equation" && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 16.5, fontWeight: 750, margin: "0 0 10px", color: "#1d1b18" }}>
                <MathText text={currentScene.title} />
              </h3>
            )}
            <div style={{ display: "grid", gap: 10 }}>
              {(currentScene.steps ?? []).map((st, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: "10px 14px",
                    borderRadius: 10,
                    background: idx === activeBeatIdx ? "#fff7ed" : "#f9f7f3",
                    border: idx === activeBeatIdx ? "1px solid #f59e0b" : "1px solid var(--linen)",
                    textAlign: "center",
                    overflowX: "auto",
                  }}
                >
                  <FormulaMath latex={st.latex} display />
                  {st.note && (
                    <div style={{ fontSize: 12.5, color: "#5c564d", marginTop: 4 }}>
                      <MathText text={st.note} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {currentScene.kind === "plot" && currentScene.plot && (
          <div>
            {currentScene.title && (
              <h3 style={{ fontSize: 16.5, fontWeight: 750, margin: "0 0 6px", color: "#1d1b18" }}>
                <MathText text={currentScene.title} />
              </h3>
            )}
            <ReelCompiledPlotSvg plot={currentScene.plot} />
          </div>
        )}

        {currentScene.kind === "ready" && (
          <div style={{ textAlign: "center", padding: "14px 8px" }}>
            <h3 style={{ fontSize: 21, fontWeight: 800, color: "#1d1b18", margin: "0 0 8px" }}>
              <MathText text={currentScene.title || "Sẵn sàng thực hành?"} />
            </h3>
            {currentScene.subtitle && (
              <p style={{ fontSize: 14.5, color: "#5c564d", margin: "0 0 14px" }}>
                <MathText text={currentScene.subtitle} />
              </p>
            )}
            {onStartPractice && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setPlaying(false);
                  onStartPractice();
                }}
              >
                {currentScene.ctaLabel || "Bắt đầu luyện tập"}
              </button>
            )}
          </div>
        )}

        {currentScene.kind === "fallback" && (() => {
          const titleText = currentScene.title || "Tóm tắt";
          const rawBody = currentScene.statement || currentScene.subtitle || "";
          const bodyText =
            rawBody && rawBody.trim() !== titleText.trim()
              ? rawBody
              : (currentScene.beats?.[0]?.say ?? "");
          return (
            <div style={{ padding: "10px 4px" }}>
              <h3 style={{ fontSize: 17, fontWeight: 700, margin: "0 0 8px" }}>
                <MathText text={titleText} />
              </h3>
              {bodyText && (
                <p style={{ margin: 0, fontSize: 15, lineHeight: 1.55, color: "#3f3b35" }}>
                  <MathText text={bodyText} />
                </p>
              )}
            </div>
          );
        })()}
      </div>

      {/* Word-by-word Karaoke Captions */}
      {captionsOn && words.length > 0 && (
        <div
          data-testid="reel-captions"
          aria-live="off"
          style={{
            marginTop: 12,
            padding: "10px 14px",
            borderRadius: 10,
            background: "#1f1d1a",
            color: "#f5f2eb",
            fontSize: 14,
            lineHeight: 1.55,
          }}
        >
          {words.map((w, idx) => {
            const isActive = sceneTimeMs >= w.startMs && sceneTimeMs < w.endMs;
            const isPast = sceneTimeMs >= w.endMs;
            return (
              <span
                key={idx}
                data-active={isActive ? "true" : undefined}
                style={{
                  color: isActive ? "#fdba74" : isPast ? "#ffffff" : "#a8a29e",
                  fontWeight: isActive ? 700 : 400,
                  marginRight: 4,
                  display: "inline-block",
                }}
              >
                {w.text}
              </span>
            );
          })}
        </div>
      )}

      {/* Playback Controls */}
      <div
        style={{
          marginTop: 12,
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            type="button"
            className="btn btn-primary"
            data-testid="reel-play-toggle"
            onClick={() => setPlaying((p) => !p)}
            aria-label={playing ? "Tạm dừng Reel" : "Phát Reel"}
            style={{ fontSize: 13, padding: "6px 14px" }}
          >
            {playing ? "Tạm dừng" : "Phát"}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="reel-prev-scene"
            disabled={sceneIndex === 0}
            onClick={() => goToScene(sceneIndex - 1)}
            aria-label="Cảnh trước"
            style={{ fontSize: 13, padding: "6px 10px" }}
          >
            ‹ Trước
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="reel-next-scene"
            disabled={sceneIndex >= scenes.length - 1}
            onClick={() => goToScene(sceneIndex + 1)}
            aria-label="Cảnh tiếp theo"
            style={{ fontSize: 13, padding: "6px 10px" }}
          >
            Tiếp ›
          </button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="reel-speed-btn"
            onClick={cycleSpeed}
            aria-label={`Tốc độ phát ${speed}×`}
            style={{ fontSize: 12.5, padding: "5px 10px", minWidth: 54 }}
          >
            {speed}×
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="reel-mute-btn"
            onClick={() => setMuted((m) => !m)}
            aria-pressed={muted}
            style={{ fontSize: 12.5, padding: "5px 10px" }}
          >
            {muted ? "Đã tắt tiếng" : "Âm thanh"}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            data-testid="reel-cc-btn"
            onClick={() => setCaptionsOn((c) => !c)}
            aria-pressed={captionsOn}
            style={{ fontSize: 12.5, padding: "5px 10px" }}
          >
            {captionsOn ? "CC: Bật" : "CC: Tắt"}
          </button>
        </div>
      </div>
    </section>
  );
}
