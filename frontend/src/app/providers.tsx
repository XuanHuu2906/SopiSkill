"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { fetchMe, logoutRequest, type AuthUser } from "@/lib/api";

export function useAuth() {
  return useQuery<AuthUser | null>({
    queryKey: ["me"],
    queryFn: fetchMe,
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogout() {
  const router = useRouter();
  return async () => {
    try {
      await logoutRequest();
    } finally {
      router.push("/login");
    }
  };
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

export default function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { refetchOnWindowFocus: false, retry: 1 },
        },
      })
  );
  return (
    <QueryClientProvider client={queryClient}>
      <div className="topbar-auth">
        <AuthBar />
      </div>
      {children}
    </QueryClientProvider>
  );
}
