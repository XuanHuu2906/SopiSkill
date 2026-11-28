"use client";

import MathText from "./MathText";

const LETTERS = ["A", "B", "C", "D", "E", "F"];

export function ScenarioQuestion({
  context,
  question,
  options,
  selectedIndex,
  outcome,
  onSelect,
}: {
  context?: string;
  question: string;
  options: string[];
  selectedIndex: number | undefined;
  outcome?: string | null;
  onSelect: (idx: number) => void;
}) {
  return (
    <>
      {context && (
        <div
          className="notice-box"
          style={{ marginBottom: 14, borderLeft: "3px solid var(--ember)", paddingLeft: 14 }}
        >
          <MathText text={context} />
        </div>
      )}
      <h1 className="block-title-sm">
        <MathText text={question} />
      </h1>
      <div role="radiogroup" aria-label={question}>
        {options.map((opt, j) => {
          const selected = selectedIndex === j;
          return (
            <button
              key={j}
              type="button"
              role="radio"
              aria-checked={selected}
              className={["quiz-option", selected ? "selected" : ""].filter(Boolean).join(" ")}
              onClick={() => onSelect(j)}
            >
              <span className="option-letter">{LETTERS[j] ?? j + 1}</span>
              <span>
                <MathText text={opt} />
              </span>
            </button>
          );
        })}
      </div>
      {outcome && (
        <div
          className="notice-box"
          role="note"
          data-scenario-outcome="true"
          style={{ marginTop: 14 }}
        >
          <strong>Hệ quả:</strong> <MathText text={outcome} />
        </div>
      )}
    </>
  );
}

export function StepsQuestion({
  question,
  steps,
  options,
  selectedIndex,
  onSelect,
}: {
  question: string;
  steps: string[];
  options: string[];
  selectedIndex: number | undefined;
  onSelect: (idx: number) => void;
}) {
  return (
    <>
      <h1 className="block-title-sm">
        <MathText text={question} />
      </h1>
      <ol
        className="steps-card"
        style={{
          listStyle: "none",
          padding: 16,
          margin: "0 0 16px",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--linen)",
          background: "var(--surface)",
          display: "grid",
          gap: 10,
        }}
      >
        {steps.map((s, idx) => (
          <li
            key={idx}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              background: "var(--wash)",
              color: "var(--ink)",
              fontSize: 15,
              lineHeight: 1.5,
            }}
          >
            <MathText text={s} />
          </li>
        ))}
      </ol>
      <div role="radiogroup" aria-label={question}>
        {options.map((opt, j) => {
          const selected = selectedIndex === j;
          return (
            <button
              key={j}
              type="button"
              role="radio"
              aria-checked={selected}
              className={["quiz-option", selected ? "selected" : ""].filter(Boolean).join(" ")}
              onClick={() => onSelect(j)}
            >
              <span className="option-letter">{LETTERS[j] ?? j + 1}</span>
              <span>
                <MathText text={opt} />
              </span>
            </button>
          );
        })}
      </div>
    </>
  );
}
