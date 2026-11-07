import type { HTMLAttributes, ReactNode } from "react";

export type CardVariant =
  | "default"
  | "tint"
  | "accent"
  | "hero"
  | "dashed"
  | "correct"
  | "wrong";

const VARIANT_CLASS: Record<CardVariant, string> = {
  default: "",
  tint: "card-tint",
  accent: "card-accent",
  hero: "card-hero",
  dashed: "card-dashed",
  correct: "card-correct",
  wrong: "card-wrong",
};

export function Card({
  variant = "default",
  children,
  className,
  ...rest
}: { variant?: CardVariant; children: ReactNode; className?: string } & HTMLAttributes<HTMLDivElement>) {
  const cls = ["card", VARIANT_CLASS[variant], className ?? ""].filter(Boolean).join(" ");
  return (
    <div className={cls} {...rest}>
      {children}
    </div>
  );
}
