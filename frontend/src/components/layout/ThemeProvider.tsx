"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "sopiskill.theme";

type ThemeContextValue = {
  preference: ThemePreference;
  setPreference: (value: ThemePreference) => void;
  toggle: () => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  preference: "system",
  setPreference: () => {},
  toggle: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

function readPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // localStorage can be unavailable (private mode / blocked storage)
  }
  return "system";
}

function applyPreference(value: ThemePreference) {
  if (typeof document === "undefined") return;
  if (value === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", value);
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>("system");

  useEffect(() => {
    const stored = readPreference();
    setPreferenceState(stored);
    applyPreference(stored);
  }, []);

  const setPreference = useCallback((value: ThemePreference) => {
    setPreferenceState(value);
    applyPreference(value);
    try {
      if (value === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Persisting preference is best-effort only.
    }
  }, []);

  const toggle = useCallback(() => {
    setPreferenceState((current) => {
      const isDark =
        current === "dark" ||
        (current === "system" &&
          typeof window !== "undefined" &&
          window.matchMedia?.("(prefers-color-scheme: dark)").matches);
      const next: ThemePreference = isDark ? "light" : "dark";
      applyPreference(next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  return (
    <ThemeContext.Provider value={{ preference, setPreference, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}
