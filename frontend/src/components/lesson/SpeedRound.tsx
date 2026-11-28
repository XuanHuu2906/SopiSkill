"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import MathText from "./MathText";

export interface SpeedItem {
  id: number;
  prompt: string;
  choices: string[];
}

/**
 * 60-second timed SpeedRound supporting touch/pointer swipe, direct buttons,
 * and WCAG 2.1 AA ArrowLeft / ArrowRight keyboard controls.
 * Submits raw choice indices for 100% server-authoritative grading.
 */
export default function SpeedRound({
  prompt,
  timeLimitSeconds = 60,
  items,
  values,
  onChange,
}: {
  prompt: string;
  timeLimitSeconds?: number;
  items: SpeedItem[];
  values: number[];
  onChange: (next: number[]) => void;
}) {
  const [cursor, setCursor] = useState(0);
  const [remaining, setRemaining] = useState(timeLimitSeconds);
  const pointerStartX = useRef<number | null>(null);

  const answers = Array.from({ length: items.length }, (_, i) =>
    typeof values[i] === "number" ? values[i] : -1
  );
  const answeredCount = answers.filter((v) => v >= 0).length;
  const allDone = answeredCount === items.length && items.length > 0;

  useEffect(() => {
    if (allDone || remaining <= 0) return;
    const timer = window.setInterval(() => {
      setRemaining((r) => (r > 0 ? r - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [allDone, remaining]);

  const activeIndex = Math.min(cursor, Math.max(0, items.length - 1));
  const activeItem = items[activeIndex];

  function choose(choiceIdx: number) {
    if (!activeItem) return;
    const next = [...answers];
    next[activeIndex] = choiceIdx;
    onChange(next);
    if (activeIndex < items.length - 1) {
      setCursor(activeIndex + 1);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (!activeItem) return;
    if (e.key === "ArrowLeft" && activeItem.choices.length >= 1) {
      e.preventDefault();
      choose(0);
    } else if (e.key === "ArrowRight" && activeItem.choices.length >= 2) {
      e.preventDefault();
      choose(1);
    }
  }

  return (
    <div
      className="speed-round"
      tabIndex={0}
      role="region"
      aria-label={`${prompt} — dùng phím mũi tên Trái hoặc Phải để chọn nhanh`}
      onKeyDown={handleKeyDown}
      onPointerDown={(e) => {
        pointerStartX.current = e.clientX;
      }}
      onPointerUp={(e) => {
        if (pointerStartX.current === null) return;
        const dx = e.clientX - pointerStartX.current;
        pointerStartX.current = null;
        if (dx <= -50) choose(0);
        else if (dx >= 50) choose(1);
      }}
      style={{ display: "grid", gap: 16 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h1 className="block-title-sm" style={{ margin: 0 }}>
          <MathText text={prompt} />
        </h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Badge tone={remaining <= 10 ? "danger" : "muted"}>
            {remaining}s
          </Badge>
          <Badge tone={allDone ? "success" : "muted"}>
            {answeredCount}/{items.length}
          </Badge>
        </div>
      </div>

      <p className="caption" style={{ margin: 0 }}>
        Chạm nút, kéo sang trái/phải hoặc nhấn phím <strong>←</strong> / <strong>→</strong> để phân loại nhanh.
      </p>

      {activeItem && (
        <div
          style={{
            padding: 20,
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--linen)",
            background: "var(--surface)",
            boxShadow: "var(--shadow-card)",
            display: "grid",
            gap: 16,
          }}
        >
          <div className="caption">Thẻ {activeIndex + 1}/{items.length}</div>
          <div style={{ fontSize: 19, fontWeight: 700, color: "var(--ink)" }}>
            <MathText text={activeItem.prompt} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
            {activeItem.choices.map((choice, cIdx) => {
              const selected = answers[activeIndex] === cIdx;
              return (
                <button
                  key={cIdx}
                  type="button"
                  className={["quiz-option", selected ? "selected" : ""].filter(Boolean).join(" ")}
                  aria-pressed={selected}
                  onClick={() => choose(cIdx)}
                  style={{ margin: 0, justifyContent: "center" }}
                >
                  <span className="option-letter">{cIdx === 0 ? "←" : "→"}</span>
                  <span>
                    <MathText text={choice} />
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }} aria-label="Danh sách thẻ tốc độ">
        {items.map((item, idx) => {
          const picked = answers[idx];
          return (
            <button
              key={item.id}
              type="button"
              className="quick-chip"
              aria-current={idx === activeIndex ? "step" : undefined}
              onClick={() => setCursor(idx)}
              style={
                idx === activeIndex
                  ? { borderColor: "var(--ember)", fontWeight: 700 }
                  : picked >= 0
                    ? { background: "var(--wash)" }
                    : undefined
              }
            >
              #{idx + 1}
              {picked >= 0 ? (
                <>
                  {" · "}
                  <MathText text={item.choices[picked]} />
                </>
              ) : (
                ""
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
