"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/app/providers";
import { ensureOfflineOwner } from "@/lib/offline/db";
import {
  flushOutboxAttempts,
  listPendingOutboxForOwner,
} from "@/lib/offline/outbox";

interface OfflineContextValue {
  isOnline: boolean;
  pendingCount: number;
  syncing: boolean;
  syncNow: () => Promise<void>;
}

const OfflineContext = createContext<OfflineContextValue>({
  isOnline: true,
  pendingCount: 0,
  syncing: false,
  syncNow: async () => {},
});

export function OfflineProvider({ children }: { children: React.ReactNode }) {
  const { data: user } = useAuth();
  const queryClient = useQueryClient();
  const [isOnline, setIsOnline] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);
  const [syncing, setSyncing] = useState(false);

  const refreshPendingCount = useCallback(async () => {
    if (!user?.id) {
      setPendingCount(0);
      return;
    }
    const items = await listPendingOutboxForOwner(user.id);
    setPendingCount(items.length);
  }, [user?.id]);

  const syncNow = useCallback(
    async (force = true) => {
      if (!user?.id) return;
      if (typeof navigator !== "undefined" && !navigator.onLine) return;
      setSyncing(true);
      try {
        const res = await flushOutboxAttempts(user.id, { force });
        setPendingCount(res.remaining);
        if (res.synced.length > 0) {
          await queryClient.invalidateQueries({ queryKey: ["me"] });
          await queryClient.invalidateQueries({ queryKey: ["session"] });
        }
      } finally {
        setSyncing(false);
      }
    },
    [user?.id, queryClient],
  );

  // Register offline/push Service Worker cleanly once on client mount
  useEffect(() => {
    if (typeof window !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
  }, []);

  // Enforce IndexedDB owner isolation whenever user logs in or switches accounts
  useEffect(() => {
    if (!user?.id) {
      setPendingCount(0);
      return;
    }
    void ensureOfflineOwner(user.id).then(async () => {
      await refreshPendingCount();
      if (typeof navigator === "undefined" || navigator.onLine) {
        await syncNow(true);
      }
    });
  }, [user?.id, refreshPendingCount, syncNow]);

  // Monitor browser online/offline transitions + custom offline-change events
  useEffect(() => {
    if (typeof window === "undefined") return;
    setIsOnline(navigator.onLine);

    const handleOnline = () => {
      setIsOnline(true);
      void syncNow(true);
    };
    const handleOffline = () => {
      setIsOnline(false);
    };
    const handleOfflineChange = () => {
      void refreshPendingCount();
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    window.addEventListener("sopiskill:offline-change", handleOfflineChange);

    // Periodic backoff retry timer (every 10s when online with pending outbox)
    const timer = window.setInterval(() => {
      if (navigator.onLine && user?.id) {
        void listPendingOutboxForOwner(user.id).then((items) => {
          setPendingCount(items.length);
          if (items.length > 0) {
            void syncNow(false);
          }
        });
      }
    }, 10_000);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("sopiskill:offline-change", handleOfflineChange);
      window.clearInterval(timer);
    };
  }, [user?.id, syncNow, refreshPendingCount]);

  const value = useMemo(
    () => ({
      isOnline,
      pendingCount,
      syncing,
      syncNow: () => syncNow(true),
    }),
    [isOnline, pendingCount, syncing, syncNow],
  );

  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}

export function useOffline() {
  return useContext(OfflineContext);
}
