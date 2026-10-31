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
    // 401 ở bất kỳ call nào nghĩa là phiên đã hết — các trang có guard UX sẽ
    // điều hướng sang /login; không cache/giữ dữ liệu cũ của user trước đó.
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

export interface CourseListItem {
  id: string;
  topic: string;
  status: string;
  createdAt: string | null;
  updatedAt: string | null;
  progress: { completed: number; total: number; percent: number };
  resumeLessonId: string | null;
  resumeLessonTitle: string | null;
  lastCompletedLessonTitle: string | null;
}
export interface CourseList {
  items: CourseListItem[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}

export function fetchCourses(limit = 20, offset = 0): Promise<CourseList> {
  return api<CourseList>(`/v1/courses?limit=${limit}&offset=${offset}`);
}

// ---------- Source Registry (P3.0) ----------

export interface SourceOut {
  id: string;
  sourceType: string;
  title: string;
  canonicalUrl: string | null;
  author: string | null;
  publisher: string | null;
  publicationDate: string | null;
  sourceUpdatedAt: string | null;
  retrievedAt: string | null;
  language: string | null;
  version: string | null;
  visibility: string;
  licenseInfo: string | null;
  contentHash: string | null;
  verificationStatus: string;
  ownerId: string | null;
  createdAt: string | null;
}

export interface CourseSourceList {
  items: { courseId: string; source: SourceOut; evaluation: unknown; linkedAt: string | null }[];
  total: number;
  groundingAvailable: boolean;
  contentIngested: boolean;
  notice: string | null;
}

export interface Citation {
  citationId: string;
  sourceId: string;
  sourceVersion: string | null;
  chunkId: string | null;
  pageNumber: number | null;
  sectionAnchor: string | null;
  evidenceText: string | null;
  validationStatus: string;
  sourceTitle: string | null;
  sourceUrl: string | null;
  sourceVerificationStatus: string | null;
}

export function fetchCourseSources(courseId: string): Promise<CourseSourceList> {
  return api<CourseSourceList>(`/v1/courses/${courseId}/sources`);
}

const VERIFICATION_LABEL: Record<string, string> = {
  unverified: "Chưa xác minh",
  pending_review: "Chờ review",
  metadata_verified: "Metadata đã kiểm tra",
  locator_verified: "Vị trí trích dẫn đã kiểm tra",
  evidence_supported: "Có bằng chứng hỗ trợ",
  corroborated: "Được nguồn khác xác nhận",
  rejected: "Bị từ chối",
};

const VALIDATION_LABEL: Record<string, string> = {
  unverified: "Chưa kiểm chứng",
  locator_verified: "Đã kiểm tra vị trí",
  evidence_supported: "Có bằng chứng",
  unavailable: "Không có nội dung để kiểm tra",
  source_changed: "Nguồn đã đổi phiên bản",
  rejected: "Không hợp lệ",
};

export function verificationLabel(status: string): string {
  return VERIFICATION_LABEL[status] ?? status;
}

export function citationStatusLabel(status: string): string {
  return VALIDATION_LABEL[status] ?? status;
}

/** Nhãn "đã xác minh" chỉ đúng khi nguồn đã qua kiểm tra metadata/vị trí. */
export function isVerifiedStatus(status: string): boolean {
  return ["metadata_verified", "locator_verified", "evidence_supported", "corroborated"].includes(
    status
  );
}

export async function logoutRequest(): Promise<void> {
  await api<void>("/v1/auth/logout", { method: "POST" });
}

// ---------- AI Tutor (P3.0) ----------

export interface TutorCitation {
  chunkId: string;
  sourceId: string;
  documentId?: string | null;
  pageNumber?: number | null;
  charStart?: number | null;
  charEnd?: number | null;
  sectionAnchor?: string | null;
  textHash?: string | null;
  sourceTitle?: string | null;
  sourceVersion?: string | null;
  evidenceText?: string | null;
  validationStatus: string;
  /** P4.1 LUÔN false: locator_verified chỉ xác minh vị trí, không xác minh claim. */
  evidenceSupported: boolean;
}

export interface TutorMessage {
  id: string;
  role: "user" | "assistant";
  status: string;
  content: string;
  contextRef: Record<string, unknown> | null;
  errorCode: string | null;
  finishReason: string | null;
  citations: TutorCitation[];
  createdAt: string | null;
}

export interface TutorThread {
  id: string;
  courseId: string;
  lessonId: string;
  title: string;
  messageCount: number;
  createdAt: string | null;
  updatedAt: string | null;
  messages: TutorMessage[];
  replaySupported: boolean;
  notice: string | null;
}

export interface TutorThreadSummary {
  id: string;
  courseId: string;
  lessonId: string;
  title: string;
  messageCount: number;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface TutorThreadList {
  items: TutorThreadSummary[];
  total: number;
}

export function fetchTutorThreads(courseId: string): Promise<TutorThreadList> {
  return api<TutorThreadList>(`/v1/courses/${courseId}/tutor/threads`);
}

export function fetchTutorThread(
  courseId: string,
  threadId: string
): Promise<TutorThread> {
  return api<TutorThread>(
    `/v1/courses/${courseId}/tutor/threads/${threadId}`
  );
}

export interface TutorStreamEvent {
  event:
    | "delta"
    | "done"
    | "error"
    | "heartbeat"
    | "cancelled"
    | "tool"
    | "citations";
  data: {
    streamId?: string;
    messageId?: string;
    seq?: number;
    text?: string;
    code?: string;
    message?: string;
    retryable?: boolean;
    finishReason?: string;
    replayed?: boolean;
    reason?: string;
    partial?: boolean;
    name?: string;
    status?: "ok" | "failed";
    summary?: string;
    durationMs?: number;
    // Frame `citations` (P4.1): chỉ chứa id đã verify server-side.
    citations?: TutorCitation[];
    unverified?: Array<{
      chunkId: string;
      sourceId: string;
      sourceTitle?: string | null;
      pageNumber?: number | null;
      sectionAnchor?: string | null;
      validationStatus: string;
    }>;
    insufficientEvidence?: boolean;
    usage?: {
      promptTokens: number | null;
      completionTokens: number | null;
      known: boolean;
    } | null;
  };
}

export interface TutorUsage {
  courseId: string;
  windowSeconds: number;
  used: { messages: number; tokens: number };
  limits: { messagesPerDay: number; tokensPerDay: number; maxConcurrentStreams: number };
  remaining: { messages: number | null; tokens: number | null };
  runningStreams: number;
  tokensKnown: boolean;
}

export interface TutorStopResult {
  messageId: string;
  status: string;
  providerStopGuaranteed: boolean;
  notice: string | null;
}

export function fetchTutorUsage(courseId: string): Promise<TutorUsage> {
  return api<TutorUsage>(`/v1/courses/${courseId}/tutor/usage`);
}

/**
 * Yêu cầu server dừng một câu trả lời đang stream (P3.1).
 *
 * Đây là dừng **best-effort**: server ngừng vòng stream của chính nó ở lần kiểm
 * tra kế tiếp, nhưng KHÔNG hoàn chi phí/token provider đã sinh. Client vẫn nên
 * abort `fetch` để giải phóng kết nối.
 */
export async function stopTutorMessage(
  courseId: string,
  messageId: string
): Promise<TutorStopResult> {
  const res = await fetch(
    `${API_URL}/v1/courses/${courseId}/tutor/messages/${messageId}/stop`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": getCsrfToken() },
      credentials: "include",
      cache: "no-store",
    }
  );
  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = res.statusText;
    try {
      const data = await res.json();
      if (data.detail?.code) {
        code = data.detail.code;
        message = data.detail.message ?? message;
      }
    } catch {
      // ignore
    }
    throw new TutorStreamError(res.status, code, message);
  }
  return (await res.json()) as TutorStopResult;
}

export class TutorStreamError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

/**
 * Mở một lượt hỏi tutor và đọc SSE thật của SopiSkill.
 *
 * - Không dùng EventSource: cần POST + CSRF header + cookie session.
 * - `signal` để client hủy stream (server ghi `cancelled`, KHÔNG cam kết dừng
 *   tính phí phía provider).
 * - `onThreadId` nhận thread id từ response header trước delta đầu tiên.
 * - Parse đúng chuẩn frame (`id:`, `event:`, `data:`) và xử lý data nhiều dòng.
 */
export async function streamTutorMessage(
  courseId: string,
  body: {
    clientMessageId: string;
    threadId: string | null;
    text: string;
    contextRef: { lessonId: string; blockIndex: number };
  },
  handlers: {
    signal?: AbortSignal;
    onThreadId?: (threadId: string) => void;
    onMessageId?: (messageId: string) => void;
    onEvent: (event: TutorStreamEvent) => void;
  }
): Promise<void> {
  const res = await fetch(`${API_URL}/v1/courses/${courseId}/tutor/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      "X-CSRF-Token": getCsrfToken(),
    },
    body: JSON.stringify(body),
    credentials: "include",
    cache: "no-store",
    signal: handlers.signal,
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
      // ignore
    }
    throw new TutorStreamError(res.status, code, message);
  }

  const threadId = res.headers.get("x-tutor-thread-id");
  if (threadId) handlers.onThreadId?.(threadId);
  const messageId = res.headers.get("x-tutor-message-id");
  if (messageId) handlers.onMessageId?.(messageId);
  if (!res.body) throw new TutorStreamError(500, "NO_STREAM", "Server không trả stream.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const rawFrame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");

      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of rawFrame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (dataLines.length === 0) continue;
      let parsed: unknown;
      try {
        parsed = JSON.parse(dataLines.join("\n"));
      } catch {
        continue; // frame hỏng: bỏ qua, không làm crash UI
      }
      handlers.onEvent({
        event: eventName as TutorStreamEvent["event"],
        data: parsed as TutorStreamEvent["data"],
      });
    }
  }
}

// ---------- Source Ingestion (P4.0) ----------

export interface SourceDocument {
  id: string;
  sourceId: string;
  status: "queued" | "extracting" | "ready" | "no_text" | "failed";
  mime: string;
  byteSize: number;
  pageCount: number | null;
  pipelineVersion: string;
  originalFilename: string | null;
  chunkCount: number;
  preview: string | null;
  error: { code?: string; message?: string } | null;
  attempts: number;
  ingestedAt: string | null;
  createdAt: string | null;
}

export interface SourceDocumentList {
  sourceId: string;
  items: SourceDocument[];
  total: number;
  contentIngested: boolean;
  notice: string | null;
}

export interface SourceIngestConfig {
  ingestEnabled: boolean;
  storageConfigured: boolean;
  maxPdfBytes: number;
  maxPdfPages: number;
  pipelineVersion: string;
  /** P4.1 — nếu false, tìm kiếm tài liệu KHÔNG chạy (không được giả vờ có RAG). */
  embeddingEnabled: boolean;
  embeddingConfigured: boolean;
  embeddingProvider: string;
  embeddingModel: string;
  embeddingDimension: number;
  ragEnabled: boolean;
}

export interface RagChunk {
  chunkId: string;
  sourceId: string;
  documentId: string;
  pageNumber: number;
  charStart: number;
  charEnd: number;
  sectionAnchor: string | null;
  textHash: string;
  sourceTitle: string;
  sourceVersion: string | null;
  snippet: string;
  lexicalRank: number | null;
  vectorRank: number | null;
  similarity: number | null;
  rrfScore: number;
}

export interface RagSearchResult {
  query: string;
  embeddingSpec: string;
  items: RagChunk[];
  total: number;
  insufficientEvidence: boolean;
  notice: string | null;
}

export function searchCourseSources(
  courseId: string,
  query: string,
  sourceIds: string[] = []
): Promise<RagSearchResult> {
  return api<RagSearchResult>(`/v1/courses/${courseId}/sources/search`, {
    method: "POST",
    body: { query, sourceIds },
  });
}

export interface SourceList {
  items: SourceOut[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
}

const DOCUMENT_STATUS_LABEL: Record<string, string> = {
  queued: "Đang chờ xử lý",
  extracting: "Đang trích xuất",
  ready: "Sẵn sàng",
  no_text: "Không có lớp text",
  failed: "Thất bại",
};

export function documentStatusLabel(status: string): string {
  return DOCUMENT_STATUS_LABEL[status] ?? status;
}

export function fetchSources(limit = 50, offset = 0): Promise<SourceList> {
  return api<SourceList>(`/v1/sources?limit=${limit}&offset=${offset}`);
}

export function createPrivateSource(body: {
  title: string;
  author?: string;
  publisher?: string;
  language?: string;
  version?: string;
}): Promise<SourceOut> {
  return api<SourceOut>("/v1/sources", {
    method: "POST",
    body: { sourceType: "user_document", visibility: "private", ...body },
  });
}

export function deleteSource(sourceId: string): Promise<void> {
  return api<void>(`/v1/sources/${sourceId}`, { method: "DELETE" });
}

export function fetchSourceDocuments(sourceId: string): Promise<SourceDocumentList> {
  return api<SourceDocumentList>(`/v1/sources/${sourceId}/documents`);
}

export function fetchSourceIngestConfig(): Promise<SourceIngestConfig> {
  return api<SourceIngestConfig>("/v1/sources/ingest-config");
}

export function deleteSourceDocument(sourceId: string, documentId: string): Promise<void> {
  return api<void>(`/v1/sources/${sourceId}/documents/${documentId}`, { method: "DELETE" });
}

function getCsrfTokenForUpload(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * Upload PDF qua multipart. Không dùng `api()` vì body là FormData: browser tự
 * đặt Content-Type kèm boundary, ta chỉ thêm CSRF header.
 */
export async function uploadSourceDocument(
  sourceId: string,
  file: File
): Promise<SourceDocument> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/v1/sources/${sourceId}/document`, {
    method: "POST",
    headers: { "X-CSRF-Token": getCsrfTokenForUpload() },
    body: form,
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) {
    let code = "HTTP_ERROR";
    let message = res.statusText;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (data.detail?.code) {
        code = data.detail.code;
        message = data.detail.message ?? message;
      }
    } catch {
      // ignore non-JSON error body
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as SourceDocument;
}
