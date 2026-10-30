"use client";

import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { fetchMe, logoutRequest, type AuthUser } from "@/lib/api";

/**
 * Session-aware query cache.
 *
 * Vấn đề P1.3: TanStack Query cache sống theo QueryClient (một instance/browser
 * tab). Nếu user A logout rồi user B đăng nhập, các query key không phụ thuộc
 * user (`["course"]`, `["me"]`, `["lesson"]`…) sẽ trả dữ liệu của A cho B.
 *
 * Giải pháp: mọi user-scoped key đều đi qua `useSessionQueryKey`, gắn thêm
 * `user.id`. Đồng thời logout/login gọi `resetSession()` → clear toàn bộ cache
 * và bump `sessionEpoch` để invalidate mọi component đang mount.
 */

type SessionContextValue = {
  epoch: number;
  resetSession: () => void;
};

const SessionContext = createContext<SessionContextValue>({
  epoch: 0,
  resetSession: () => {},
});

export function useSession() {
  return useContext(SessionContext);
}

export function useAuth() {
  return useQuery<AuthUser | null>({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 30_000,
    retry: false,
  });
}

/**
 * Ghép session epoch + user id vào query key để cache không rò giữa user.
 * Lưu ý: chỉ dùng trong component — gọi hook ở đây là hợp lệ theo Rules of Hooks
 * vì nó luôn được gọi ở top-level của component gọi tới nó.
 */
export function useSessionQueryKey(...parts: unknown[]): unknown[] {
  const { data: user } = useAuth();
  const { epoch } = useSession();
  return ["session", epoch, user?.id ?? "anon", ...parts];
}

export function useLogout() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { resetSession } = useSession();
  return async () => {
    try {
      await logoutRequest();
    } finally {
      resetSession();
      queryClient.removeQueries();
      router.push("/login");
      router.refresh();
    }
  };
}

/** Gọi sau login/register thành công: xoá cache cũ và nạp lại user mới. */
export function useSessionRefresh() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { resetSession } = useSession();
  return async () => {
    resetSession();
    queryClient.removeQueries();
    await queryClient.fetchQuery({
      queryKey: ["me"],
      queryFn: fetchMe,
      staleTime: 0,
    });
    router.refresh();
  };
}

/** Điều hướng sau đăng nhập; chỉ chấp nhận đường dẫn nội bộ (chống open redirect). */
export function useRedirectAfterLogin() {
  const router = useRouter();
  return (next: string | null | undefined) => {
    const safe = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
    router.replace(safe);
  };
}

/**
 * Guard UX cho route cần đăng nhập. Server vẫn enforce ownership/quyền —
 * đây chỉ tránh hiển thị UI rỗng và đưa người dùng tới /login kèm `next`.
 */
export function useRequireAuth() {
  const { data: user, isLoading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const redirected = useRef(false);

  useEffect(() => {
    if (!isLoading && user === null && !redirected.current) {
      redirected.current = true;
      const next = pathname ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
  }, [isLoading, user, router, pathname]);

  return { user, isLoading, isAuthenticated: !!user };
}

function AuthBar() {
  const { data: user, isLoading } = useAuth();
  const logout = useLogout();

  if (isLoading) return <span className="badge">...</span>;
  if (!user) return null;
  return (
    <span className="badge">
      {user.displayName} · {user.xp} XP{" "}
      <button className="link-btn" onClick={logout}>
        Đăng xuất
      </button>
    </span>
  );
}

function SessionProvider({ children }: { children: React.ReactNode }) {
  const [epoch, setEpoch] = useState(0);
  const resetSession = () => setEpoch((value) => value + 1);
  return (
    <SessionContext.Provider value={{ epoch, resetSession }}>
      {children}
    </SessionContext.Provider>
  );
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // Không retry lỗi 4xx (401/403/404 là quyết định, không phải sự cố).
              const status = (error as { status?: number } | null)?.status;
              if (typeof status === "number" && status >= 400 && status < 500) {
                return false;
              }
              return failureCount < 1;
            },
          },
        },
      })
  );
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <div className="topbar-auth">
          <AuthBar />
        </div>
        {children}
      </SessionProvider>
    </QueryClientProvider>
  );
}
