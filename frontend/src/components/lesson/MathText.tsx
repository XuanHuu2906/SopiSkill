"use client";

import katex from "katex";
import { Fragment } from "react";

export interface InlineTermSpec {
  term: string;
  termKey?: string;
  definition?: string;
}

const TOKEN_RE = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\{[a-zA-Z0-9_-]{2,40}\})/g;

function renderLatex(expr: string, displayMode: boolean): string {
  try {
    return katex.renderToString(expr.trim(), {
      displayMode,
      throwOnError: false,
      strict: false,
      output: "htmlAndMathml",
    });
  } catch {
    return expr;
  }
}

export function FormulaMath({ latex, display = true }: { latex: string; display?: boolean }) {
  const html = renderLatex(latex, display);
  return (
    <span
      className={display ? "math-display" : "math-inline"}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/**
 * Renders rich prose containing:
 *  - Display KaTeX (`$$...$$`) and inline KaTeX (`$...$`) using self-hosted `.woff2` fonts
 *  - Inline `{termKey}` chips that open `VocabSheet` directly on click
 */
export default function MathText({
  text,
  terms = [],
  onTermClick,
}: {
  text: string;
  terms?: InlineTermSpec[];
  onTermClick?: (termKey: string, label: string) => void;
}) {
  if (!text) return null;
  const termByKey = new Map<string, InlineTermSpec>();
  for (const t of terms) {
    if (t.termKey) termByKey.set(t.termKey, t);
  }

  const parts = text.split(TOKEN_RE);
  return (
    <>
      {parts.map((part, idx) => {
        if (!part) return null;
        if (part.startsWith("$$") && part.endsWith("$$") && part.length > 4) {
          return (
            <span
              key={idx}
              className="math-display"
              style={{ display: "block", margin: "12px 0", overflowX: "auto" }}
              dangerouslySetInnerHTML={{ __html: renderLatex(part.slice(2, -2), true) }}
            />
          );
        }
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          return (
            <span
              key={idx}
              className="math-inline"
              dangerouslySetInnerHTML={{ __html: renderLatex(part.slice(1, -1), false) }}
            />
          );
        }
        if (part.startsWith("{") && part.endsWith("}")) {
          const key = part.slice(1, -1);
          const spec = termByKey.get(key);
          const label = spec?.term ?? key.replace(/[_-]+/g, " ");
          return (
            <button
              key={idx}
              type="button"
              className="inline-term-chip"
              onClick={() => onTermClick?.(key, label)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "1px 8px",
                margin: "0 2px",
                borderRadius: 999,
                border: "1px solid var(--ember)",
                background: "var(--wash)",
                color: "var(--ember-deep)",
                fontWeight: 600,
                fontSize: "0.92em",
                cursor: "pointer",
                verticalAlign: "baseline",
              }}
            >
              {label}
            </button>
          );
        }
        return <Fragment key={idx}>{part}</Fragment>;
      })}
    </>
  );
}
