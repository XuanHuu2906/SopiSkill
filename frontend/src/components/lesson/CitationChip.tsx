"use client";

export interface InlineCite {
  sourceId?: string;
  label?: string;
  sourceTitle?: string;
  url?: string | null;
  anchor?: string | null;
  pageNumber?: number | null;
  author?: string | null;
  licenseInfo?: string | null;
  attributionText?: string | null;
}

export default function CitationChip({ cite }: { cite: InlineCite }) {
  const text = cite.label || cite.sourceTitle || "Nguồn tham khảo";
  const pageSuffix = cite.pageNumber != null ? ` · tr. ${cite.pageNumber}` : "";
  const licenseBadge = cite.licenseInfo ? ` (${cite.licenseInfo})` : "";
  const titleTooltip = cite.attributionText || [cite.sourceTitle, cite.author, cite.licenseInfo].filter(Boolean).join(" · ") || undefined;
  const style = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    borderRadius: 999,
    border: "1px solid var(--linen)",
    background: "var(--surface)",
    color: "var(--ink-2)",
    fontSize: 13,
    fontWeight: 600,
    textDecoration: "none",
  } as const;

  if (cite.url) {
    return (
      <a
        href={cite.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="citation-chip"
        title={titleTooltip}
        style={style}
      >
        <span>{text}{pageSuffix}{licenseBadge}</span>
      </a>
    );
  }

  return (
    <span className="citation-chip" title={titleTooltip} style={style}>
      {text}{pageSuffix}{licenseBadge}
    </span>
  );
}
