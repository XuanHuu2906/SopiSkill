const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function getCsrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = getCsrfToken();
  }

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    credentials: "include",
    cache: "no-store",
  });

  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.detail?.code) {
        code = data.detail.code;
        message = data.detail.message ?? message;
      }
    } catch {
      // ignore json parse errors
    }
    throw new ApiError(res.status, code, message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function newClientId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
}

// ---------- Auth ----------

export interface AuthUser {
  id: string;
  email: string | null;
  displayName: string;
  xp: number;
}

export async function fetchMe(): Promise<AuthUser | null> {
  try {
    return await api<AuthUser>("/v1/auth/me");
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 503)) {
      return null;
    }
    throw err;
  }
}

export async function loginRequest(
  email: string,
  password: string
): Promise<AuthUser> {
  return api<AuthUser>("/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export async function registerRequest(
  email: string,
  password: string
): Promise<AuthUser> {
  return api<AuthUser>("/v1/auth/register", {
    method: "POST",
    body: { email, password },
  });
}

export async function logoutRequest(): Promise<void> {
  await api<void>("/v1/auth/logout", { method: "POST" });
}
