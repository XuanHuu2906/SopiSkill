"use client";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";

export interface RecapSourceStat {
  label: string;
  count?: number;
}

export default function RecapView({
  title,
  points,
  sources = [],
}: {
  title: string;
  points: string[];
  sources?: RecapSourceStat[];
}) {
  return (
    <div className="recap-view" style={{ display: "grid", gap: 18 }}>
      <h1 className="block-title">{title}</h1>
      <Card>
        <h2 style={{ fontSize: 16, fontWeight: 700, margin: "0 0 12px", color: "var(--ink)" }}>
          Điểm cốt lõi cần nhớ
        </h2>
        <ul style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 10, color: "var(--ink-2)", lineHeight: 1.6 }}>
          {points.map((pt, idx) => (
            <li key={idx}>{pt}</li>
          ))}
        </ul>
      </Card>
      {sources.length > 0 && (
        <Card variant="tint">
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8, color: "var(--ink)" }}>
            Phân bổ câu hỏi theo học phần
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {sources.map((src, idx) => (
              <Badge key={idx} tone="muted">
                {src.label}{src.count != null ? ` · ${src.count} câu` : ""}
              </Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
