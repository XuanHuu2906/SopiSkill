"use client";

import { useTheme } from "./ThemeProvider";
import Icon from "../ui/Icon";

export default function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference, toggle } = useTheme();

  if (compact) {
    return (
      <button
        type="button"
        className="nav-row"
        onClick={toggle}
        aria-label="Chế độ tối"
      >
        <span className="nav-glyph" aria-hidden="true">
          <Icon name={preference === "dark" ? "sun" : "moon"} size={22} />
        </span>
        <span>{preference === "dark" ? "Chế độ sáng" : "Chế độ tối"}</span>
      </button>
    );
  }

  return (
    <div className="theme-toggle" role="group" aria-label="Giao diện">
      {(["light", "system", "dark"] as const).map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={preference === value}
          onClick={() => setPreference(value)}
        >
          {value === "light" ? "Sáng" : value === "dark" ? "Tối" : "Hệ thống"}
        </button>
      ))}
    </div>
  );
}
