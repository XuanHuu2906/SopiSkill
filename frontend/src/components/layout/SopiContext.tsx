"use client";

import { createContext, useContext } from "react";

export interface SopiContextValue {
  open: boolean;
  openSopi: (courseId?: string | null) => void;
  closeSopi: () => void;
}

export const SopiContext = createContext<SopiContextValue>({
  open: false,
  openSopi: () => {},
  closeSopi: () => {},
});

export function useSopi() {
  return useContext(SopiContext);
}
