const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function getUserId(): string {
  if (typeof window === "undefined") return "anonymous";
  let id = localStorage.getItem("ailp.userId");
  if (!id) {
    id = `user-${crypto.randomUUID().slice(0, 8)}`;
    localStorage.setItem("ailp.userId", id);
  }
  return id;
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {}
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": getUserId(),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
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
  return res.json() as Promise<T>;
}

export function newClientId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;
}
