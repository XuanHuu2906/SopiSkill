"use client";

import katex from "katex";
import { Fragment, useState } from "react";

export interface InlineTermSpec {
  term: string;
  termKey?: string;
  definition?: string;
}

const FENCE_BLOCK_RE = /(```[a-zA-Z0-9_+#.-]*\n[\s\S]*?```)/g;
const TOKEN_RE = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|`[^`\n]+?`|\{[a-zA-Z0-9_-]{2,40}\})/g;

const CODE_KEYWORDS = new Set([
  "def", "class", "return", "import", "from", "as", "if", "elif", "else", "for", "while", "try",
  "except", "finally", "with", "async", "await", "yield", "lambda", "pass", "break", "continue",
  "in", "not", "and", "or", "is", "None", "True", "False",
  "function", "const", "let", "var", "export", "default", "interface", "type", "enum", "extends",
  "implements", "new", "this", "super", "throw", "catch", "switch", "case", "typeof", "void",
  "null", "undefined", "true", "false",
  "public", "private", "protected", "static", "final", "abstract", "synchronized", "package",
  "fn", "pub", "mut", "match", "impl", "struct", "trait", "use", "mod", "crate", "Self", "self",
  "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "INNER", "GROUP", "BY", "ORDER", "LIMIT", "INSERT",
  "INTO", "VALUES", "UPDATE", "SET", "DELETE", "CREATE", "TABLE", "INDEX", "ON", "AS", "AND", "OR",
]);

const CODE_TOKEN_RE =
  /(\/\/[^\n]*|#[^\n]*|--[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b)/g;

function highlightCodeLine(line: string) {
  if (!line) return "\u00a0";
  const parts = line.split(CODE_TOKEN_RE);
  return parts.map((part, idx) => {
    if (!part) return null;
    if (part.startsWith("//") || part.startsWith("#") || part.startsWith("--")) {
      return (
        <span key={idx} style={{ color: "#6b7280", fontStyle: "italic" }}>
          {part}
        </span>
      );
    }
    if (
      (part.startsWith('"') && part.endsWith('"')) ||
      (part.startsWith("'") && part.endsWith("'")) ||
      (part.startsWith("`") && part.endsWith("`"))
    ) {
      return (
        <span key={idx} style={{ color: "#15803d" }}>
          {part}
        </span>
      );
    }
    if (/^\d+(?:\.\d+)?$/.test(part)) {
      return (
        <span key={idx} style={{ color: "#b45309" }}>
          {part}
        </span>
      );
    }
    if (CODE_KEYWORDS.has(part) || CODE_KEYWORDS.has(part.toUpperCase())) {
      return (
        <span key={idx} style={{ color: "#9a3412", fontWeight: 700 }}>
          {part}
        </span>
      );
    }
    return <Fragment key={idx}>{part}</Fragment>;
  });
}

export function CodeBlockCard({
  code,
  language,
  highlightLines = [],
}: {
  code: string;
  language?: string;
  highlightLines?: number[];
}) {
  const [copied, setCopied] = useState(false);
  const normalized = (code || "").replace(/\r\n/g, "\n").replace(/\n$/, "");
  const lines = normalized.split("\n");
  const highlightSet = new Set(highlightLines);
  const langLabel = (language || "code").trim().toLowerCase();

  async function handleCopy() {
    try {
      await navigator.clipboard?.writeText(normalized);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div
      className="lesson-code-card"
      data-code-lang={langLabel}
      style={{
        margin: "12px 0",
        borderRadius: 12,
        border: "1px solid var(--linen, #e2ddd3)",
        background: "#faf8f4",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "7px 12px",
          background: "#f2ede4",
          borderBottom: "1px solid var(--linen, #e2ddd3)",
          fontSize: 12,
        }}
      >
        <span
          style={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            fontWeight: 700,
            color: "#7c2d12",
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {langLabel}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          aria-label="Sao chép mã nguồn"
          style={{
            border: "1px solid #d4cec4",
            background: "#ffffff",
            color: "#1f1d1a",
            borderRadius: 6,
            padding: "2px 9px",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          {copied ? "Đã chép" : "Sao chép"}
        </button>
      </div>
      <pre
        style={{
          margin: 0,
          padding: "10px 0",
          overflowX: "auto",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
          fontSize: 13.5,
          lineHeight: 1.55,
          color: "#1d1b18",
        }}
      >
        <code>
          {lines.map((line, idx) => {
            const lineNo = idx + 1;
            const isHighlighted = highlightSet.has(lineNo);
            return (
              <div
                key={lineNo}
                style={{
                  display: "flex",
                  padding: "0 14px 0 0",
                  background: isHighlighted ? "#fff1ed" : "transparent",
                  borderLeft: isHighlighted ? "3px solid #c85a27" : "3px solid transparent",
                }}
              >
                <span
                  aria-hidden="true"
                  style={{
                    userSelect: "none",
                    minWidth: 38,
                    paddingRight: 12,
                    textAlign: "right",
                    color: "#9a948a",
                    fontSize: 12,
                  }}
                >
                  {lineNo}
                </span>
                <span style={{ whiteSpace: "pre" }}>{highlightCodeLine(line)}</span>
              </div>
            );
          })}
        </code>
      </pre>
    </div>
  );
}

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

function renderInlineTokens(
  segment: string,
  termByKey: Map<string, InlineTermSpec>,
  onTermClick?: (termKey: string, label: string) => void
) {
  const parts = segment.split(TOKEN_RE);
  return parts.map((part, idx) => {
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
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code
          key={idx}
          style={{
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
            fontSize: "0.9em",
            padding: "1px 6px",
            borderRadius: 6,
            background: "#f2ede4",
            color: "#7c2d12",
            border: "1px solid #e2ddd3",
          }}
        >
          {part.slice(1, -1)}
        </code>
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
  });
}

/**
 * Renders rich prose containing:
 *  - Fenced code blocks (` ```lang ... ``` `) with deterministic highlighting & Copy
 *  - Inline code chips (`` `code` ``)
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

  const blocks = text.split(FENCE_BLOCK_RE);
  return (
    <>
      {blocks.map((block, bIdx) => {
        if (!block) return null;
        if (block.startsWith("```") && block.endsWith("```") && block.length >= 7) {
          const firstNl = block.indexOf("\n");
          const lang = firstNl > 3 ? block.slice(3, firstNl).trim() : "code";
          const codeBody = firstNl !== -1 ? block.slice(firstNl + 1, -3) : block.slice(3, -3);
          return <CodeBlockCard key={`code-${bIdx}`} code={codeBody} language={lang} />;
        }
        return (
          <Fragment key={`seg-${bIdx}`}>
            {renderInlineTokens(block, termByKey, onTermClick)}
          </Fragment>
        );
      })}
    </>
  );
}
