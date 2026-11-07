import type { ReactNode } from "react";

export type BadgeTone = "accent" | "muted" | "success" | "danger" | "lock";

const TONE_CLASS: Record<BadgeTone, string> = {
  accent: "",
  muted: "badge-muted",
  success: "badge-success",
  danger: "badge-danger",
  lock: "badge-lock",
};

export function Badge({
  tone = "accent",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  const cls = ["badge", TONE_CLASS[tone], className ?? ""].filter(Boolean).join(" ");
  return <span className={cls}>{children}</span>;
}
