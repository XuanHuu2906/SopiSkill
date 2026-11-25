"use client";

import { Fragment } from "react";

export default function MultiBlankWordBank({
  parts,
  blankCount,
  bank,
  values,
  lockedIndices = [],
  onChange,
}: {
  parts: string[];
  blankCount: number;
  bank: string[];
  values: string[];
  lockedIndices?: number[];
  onChange: (next: string[]) => void;
}) {
  const locked = new Set(lockedIndices);
  const slots = Array.from({ length: blankCount }, (_, i) => values[i] ?? "");

  function pickWord(word: string) {
    const firstEmpty = slots.findIndex((s, i) => !s && !locked.has(i));
    if (firstEmpty === -1) return;
    const next = [...slots];
    next[firstEmpty] = word;
    onChange(next);
  }

  function clearSlot(slotIdx: number) {
    if (locked.has(slotIdx) || !slots[slotIdx]) return;
    const next = [...slots];
    next[slotIdx] = "";
    onChange(next);
  }

  // Count how many times each word is currently placed so duplicate bank words work cleanly.
  const placedCounts = new Map<string, number>();
  for (const s of slots) {
    if (s) placedCounts.set(s, (placedCounts.get(s) ?? 0) + 1);
  }
  const seenInBank = new Map<string, number>();

  return (
    <div className="multi-blank-wrap" style={{ display: "grid", gap: 18 }}>
      <p style={{ fontSize: 19, lineHeight: 1.85, color: "var(--ink)", margin: 0 }}>
        {parts.map((text, idx) => (
          <Fragment key={idx}>
            <span>{text}</span>
            {idx < blankCount && (
              <button
                type="button"
                data-blank-slot={idx}
                disabled={locked.has(idx)}
                aria-label={
                  slots[idx]
                    ? `Chỗ trống ${idx + 1}: ${slots[idx]}${locked.has(idx) ? " (đã khóa đúng)" : " — nhấn để bỏ chọn"}`
                    : `Chỗ trống ${idx + 1}: chưa điền`
                }
                onClick={() => clearSlot(idx)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 96,
                  padding: "3px 12px",
                  margin: "0 4px",
                  borderRadius: 8,
                  border: locked.has(idx)
                    ? "2px solid #15803d"
                    : slots[idx]
                      ? "2px solid var(--ember)"
                      : "2px dashed var(--ink-3)",
                  background: locked.has(idx)
                    ? "#ecfdf3"
                    : slots[idx]
                      ? "var(--wash)"
                      : "var(--surface)",
                  color: locked.has(idx) ? "#14532d" : "var(--ink)",
                  fontWeight: 700,
                  fontSize: 16,
                  cursor: locked.has(idx) ? "default" : slots[idx] ? "pointer" : "default",
                }}
              >
                {slots[idx] ? `${locked.has(idx) ? "✓ " : ""}${slots[idx]}` : `(${idx + 1})`}
              </button>
            )}
          </Fragment>
        ))}
      </p>

      <div
        role="group"
        aria-label="Ngân hàng từ gợi ý"
        style={{ display: "flex", flexWrap: "wrap", gap: 10 }}
      >
        {bank.map((word, idx) => {
          const usedCount = placedCounts.get(word) ?? 0;
          const occurrence = seenInBank.get(word) ?? 0;
          seenInBank.set(word, occurrence + 1);
          const isUsed = occurrence < usedCount;
          return (
            <button
              key={`${word}-${idx}`}
              type="button"
              className="quick-chip"
              data-bank-word={word}
              disabled={isUsed}
              onClick={() => pickWord(word)}
              style={
                isUsed
                  ? { opacity: 0.45, cursor: "not-allowed", textDecoration: "line-through" }
                  : undefined
              }
            >
              {word}
            </button>
          );
        })}
      </div>
    </div>
  );
}
