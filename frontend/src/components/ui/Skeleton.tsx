export function Skeleton({
  height = 20,
  width = "100%",
  radius,
  className,
}: {
  height?: number | string;
  width?: number | string;
  radius?: number | string;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={["skeleton", className ?? ""].filter(Boolean).join(" ")}
      style={{
        display: "block",
        height,
        width,
        borderRadius: radius,
      }}
    />
  );
}

export function SkeletonStack({ rows = 3 }: { rows?: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={i === 0 ? 32 : 18} width={i === 0 ? "55%" : "100%"} />
      ))}
    </div>
  );
}
