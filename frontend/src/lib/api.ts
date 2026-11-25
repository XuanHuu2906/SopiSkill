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
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {}
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { ...(options.headers ?? {}) };
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

export type CourseLanguage = "vi" | "en";

export interface CourseListItem {
  id: string;
  topic: string;
  status: string;
  language?: CourseLanguage;
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

export interface SourceBriefSection {
  anchor: string;
  heading: string;
  gist: string;
}

export interface SourceBrief {
  what: string;
  claims: string[];
  notation: string[];
  assumes: string[];
  sections: SourceBriefSection[];
}

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
  brief?: SourceBrief | null;
  wordCount?: number | null;
  durationMinutes?: number | null;
  suggestedTopic?: string | null;
  rejectReason?: string | null;
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
  lessonId: string | null;
  kind?: "course" | "anchor" | "task";
  anchorKey?: string | null;
  title: string;
  messageCount: number;
  createdAt: string | null;
  updatedAt: string | null;
  messages: TutorMessage[];
  actions?: TutorAction[];
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

export type TutorEntryPoint =
  | "tab"
  | "wrong_answer"
  | "teach_block"
  | "term"
  | "path_harder"
  | "proposal";

export interface TutorAction {
  actionId: string;
  id?: string;
  messageId?: string;
  toolName: string;
  status: "pending" | "confirmed" | "declined" | "preparing" | "ready" | "failed" | "unavailable";
  payload?: { unitId?: string; unitTitle?: string };
  preview?: { unitTitle?: string; direction?: string; summary?: string; changes?: string[] };
  jobId?: string | null;
}

export interface GlobalTutorSession {
  id: string;
  courseId: string;
  lessonId: string | null;
  courseTopic: string;
  kind: "course" | "anchor" | "task";
  anchorKey: string | null;
  title: string;
  sealed: boolean;
  messageCount: number;
  createdAt: string | null;
  updatedAt: string | null;
}

export interface GlobalTutorSessionList {
  items: GlobalTutorSession[];
  thisWeek: GlobalTutorSession[];
  earlier: GlobalTutorSession[];
  total: number;
}

export function fetchGlobalTutorSessions(limit = 30): Promise<GlobalTutorSessionList> {
  return api<GlobalTutorSessionList>(`/v1/tutor/sessions?limit=${limit}`);
}

export function fetchTutorAction(courseId: string, actionId: string): Promise<TutorAction> {
  return api<TutorAction>(`/v1/courses/${courseId}/tutor/actions/${actionId}`);
}

export function confirmTutorAction(courseId: string, actionId: string): Promise<TutorAction> {
  return api<TutorAction>(`/v1/courses/${courseId}/tutor/actions/${actionId}/confirm`, {
    method: "POST",
  });
}

export function declineTutorAction(courseId: string, actionId: string): Promise<TutorAction> {
  return api<TutorAction>(`/v1/courses/${courseId}/tutor/actions/${actionId}/decline`, {
    method: "POST",
  });
}

export interface TutorStreamEvent {
  id?: string;
  event:
    | "delta"
    | "done"
    | "error"
    | "heartbeat"
    | "cancelled"
    | "tool"
    | "citations"
    | "confirm"
    | "proposal_revised"
    | "restarted";
  data: {
    streamId?: string;
    messageId?: string;
    threadId?: string;
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
    status?: string;
    summary?: string;
    durationMs?: number;
    // Phase 5 confirm / proposal_revised / restarted payloads
    actionId?: string;
    toolName?: string;
    payload?: Record<string, unknown>;
    preview?: { unitTitle?: string; direction?: string; summary?: string; changes?: string[] };
    version?: number;
    approved?: boolean;
    content?: string;
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
async function consumeSseBody(
  body: ReadableStream<Uint8Array>,
  handlers: {
    onEventId?: (eventId: string) => void;
    onEvent: (event: TutorStreamEvent) => void;
  }
): Promise<void> {
  const reader = body.getReader();
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
      let eventId: string | undefined;
      const dataLines: string[] = [];
      for (const line of rawFrame.split("\n")) {
        if (line.startsWith("id:")) eventId = line.slice(3).trim();
        else if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (eventId) handlers.onEventId?.(eventId);
      if (dataLines.length === 0) continue;
      let parsed: unknown;
      try {
        parsed = JSON.parse(dataLines.join("\n"));
      } catch {
        continue; // frame hỏng: bỏ qua, không làm crash UI
      }
      handlers.onEvent({
        id: eventId,
        event: eventName as TutorStreamEvent["event"],
        data: parsed as TutorStreamEvent["data"],
      });
    }
  }
}

export async function streamTutorMessage(
  courseId: string,
  body: {
    clientMessageId: string;
    threadId: string | null;
    text: string;
    contextRef?: { lessonId: string; blockIndex: number } | null;
    entryPoint?: TutorEntryPoint;
    contextLabel?: string;
    threadKind?: "course" | "anchor" | "task";
    anchorKey?: string;
  },
  handlers: {
    signal?: AbortSignal;
    onThreadId?: (threadId: string) => void;
    onMessageId?: (messageId: string) => void;
    onEventId?: (eventId: string) => void;
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

  await consumeSseBody(res.body, handlers);
}

export async function resumeTutorStream(
  courseId: string,
  messageId: string,
  lastEventId: string,
  handlers: {
    signal?: AbortSignal;
    onEventId?: (eventId: string) => void;
    onEvent: (event: TutorStreamEvent) => void;
  }
): Promise<void> {
  const res = await fetch(
    `${API_URL}/v1/courses/${courseId}/tutor/messages/${messageId}/stream?lastEventId=${encodeURIComponent(lastEventId)}`,
    {
      method: "GET",
      headers: {
        Accept: "text/event-stream",
        "Last-Event-ID": lastEventId,
      },
      credentials: "include",
      cache: "no-store",
      signal: handlers.signal,
    }
  );
  if (!res.ok || !res.body) {
    throw new TutorStreamError(res.status, "RESUME_FAILED", "Không thể nối lại luồng Sopi.");
  }
  await consumeSseBody(res.body, handlers);
}

// ---------- Source Ingestion (P4.0) ----------

export interface SourceDocument {
  id: string;
  sourceId: string;
  status: "queued" | "extracting" | "ready" | "no_text" | "failed";
  /** P4.2 — nguồn gốc nội dung: PDF upload, fetch URL, hay arXiv. */
  origin?: "upload" | "web" | "arxiv";
  /** URL thật của tài liệu web/arXiv; null với PDF upload. */
  originUrl?: string | null;
  mime: string;
  byteSize: number;
  pageCount: number | null;
  pipelineVersion: string;
  originalFilename: string | null;
  chunkCount: number;
  preview: string | null;
  error: { code?: string; message?: string } | null;
  attempts: number;
  /** P4.2 — đã xác nhận quyền sử dụng nguồn hay chưa (audit). */
  rightsConfirmed?: boolean;
  /** P4.3 — text đến từ đâu: text layer PDF, OCR, hay cả hai. null = document cũ. */
  textSource?: "native" | "ocr" | "mixed" | null;
  /** Số trang phải OCR (máy đọc ảnh). Chỉ để truy vết, không phải độ tin cậy. */
  ocrPages?: number;
  ocrEngine?: string | null;
  ocrVersion?: string | null;
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
  /** P4.2 — URL ingest có bật + allowlist có host. False ⇒ ẩn form URL. */
  webEnabled?: boolean;
  webAllowedHostCount?: number;
  webMaxFetchBytes?: number;
  webRespectRobots?: boolean;
  arxivEnabled?: boolean;
  /** P4.3 — OCR cho PDF scan. false ⇒ scan vẫn "không có lớp text". */
  ocrEnabled?: boolean;
  ocrConfigured?: boolean;
  ocrEngine?: string;
  ocrVersion?: string;
  ocrMaxPages?: number;
  ocrDpi?: number;
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

/**
 * Ingest nội dung từ URL hoặc arXiv (P4.2).
 *
 * `userConfirmedRights` BẮT BUỘC — server trả 422 nếu thiếu. Đây là xác nhận có
 * quyền sử dụng nguồn, không phải checkbox trang trí.
 */
export function ingestWebDocument(
  sourceId: string,
  body: { url?: string; arxivId?: string; userConfirmedRights: boolean }
): Promise<SourceDocument> {
  return api<SourceDocument>(`/v1/sources/${sourceId}/web-document`, {
    method: "POST",
    body,
  });
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

// ---------- Learner profile / mastery / spaced repetition (P5.0) ----------

export interface SkillMastery {
  skillId: string;
  title: string;
  bloomLevel: string;
  masteryScore: number;
  method: string;
  attempts: number;
  correct: number;
  total: number;
  lastAttemptAt: string | null;
  passThreshold: number;
}

export interface CourseMastery {
  items: SkillMastery[];
  coursePercent: number;
  reviewDueCount: number;
}

export interface LearningPathReason {
  code: string;
  message: string;
}

export interface LearningPath {
  nextLesson: { lessonId: string; title: string; reason: LearningPathReason } | null;
  reviewLessonId: string | null;
  reviewDueCount: number;
  blockedBy: {
    lessonId: string;
    title: string;
    prerequisites: { skillId: string; title: string; masteryScore: number; met: boolean }[];
    reason: LearningPathReason;
  }[];
  prerequisitesDag: {
    nodes: { id: string; title: string; bloomLevel: string }[];
    edges: string[][];
  };
  // P5.2b — token server ký để báo exposure. null khi cờ tắt hoặc không có arm.
  recommendationToken?: string | null;
}

export interface RecommendationEventResult {
  recorded: boolean;
  duplicate: boolean;
  exposureId: string | null;
  reason: string | null;
}

export interface DueReview {
  cardId: string;
  lessonId: string;
  lessonTitle: string;
  dueAt: string;
  state: number;
  overdueDays: number;
}

export interface DueReviewList {
  items: DueReview[];
  total: number;
}

export interface ReviewGradeResult {
  card: {
    cardId: string;
    lessonId: string;
    state: number;
    dueAt: string;
    lastReviewAt: string | null;
  };
  eventId: string;
  duplicate: boolean;
}

export function fetchCourseMastery(courseId: string): Promise<CourseMastery> {
  return api<CourseMastery>(`/v1/courses/${courseId}/mastery`);
}

export function fetchLearningPath(courseId: string): Promise<LearningPath> {
  return api<LearningPath>(`/v1/courses/${courseId}/learning-path`);
}

/**
 * Báo exposure cho gợi ý vừa hiển thị. Server tự verify token + tính lại arm;
 * client không gửi arm/propensity. Lỗi bị nuốt ở caller (hành vi ẩn, không UI).
 */
export function recordRecommendation(
  courseId: string,
  recommendationToken: string
): Promise<RecommendationEventResult> {
  return api<RecommendationEventResult>(
    `/v1/courses/${courseId}/recommendation-events`,
    { method: "POST", body: { recommendationToken } }
  );
}

export function fetchDueReviews(
  courseId?: string,
  limit = 20
): Promise<DueReviewList> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (courseId) params.set("courseId", courseId);
  return api<DueReviewList>(`/v1/reviews/due?${params.toString()}`);
}

export function gradeReview(
  cardId: string,
  body: { rating: number; clientReviewId: string; durationMs?: number }
): Promise<ReviewGradeResult> {
  return api<ReviewGradeResult>(`/v1/reviews/${cardId}/grade`, {
    method: "POST",
    body,
  });
}

export function reviewStateLabel(state: number): string {
  switch (state) {
    case 1:
      return "Đang học";
    case 2:
      return "Ôn tập";
    case 3:
      return "Học lại";
    default:
      return "Không rõ";
  }
}

// ---------- Wave 4: Proposal Edit, Glossary, Per-block Grading, Me Surface ----------

export interface ProposalUpdatePayload {
  expectedVersion: number;
  name: string;
  objective: string;
  units: { title: string; blurb: string; lessonTitles: string[] }[];
  outcomes: string[];
}

export function updateProposal<T = unknown>(
  courseId: string,
  body: ProposalUpdatePayload
): Promise<T> {
  return api<T>(`/v1/courses/${courseId}/proposal`, {
    method: "PATCH",
    body,
  });
}

export interface GlossaryTerm {
  id: string;
  termKey: string;
  term: string;
  definition: string;
  example: string | null;
  lessonId: string | null;
  lessonTitle: string | null;
}

export interface CourseGlossary {
  courseId: string;
  total: number;
  items: GlossaryTerm[];
}

export function fetchCourseGlossary(
  courseId: string,
  lessonId?: string
): Promise<CourseGlossary> {
  const query = lessonId ? `?lessonId=${encodeURIComponent(lessonId)}` : "";
  return api<CourseGlossary>(`/v1/courses/${courseId}/glossary${query}`);
}

export interface BlockGradeResult {
  blockIndex: number;
  type: string;
  correct: boolean;
  grader: "deterministic" | "semantic_rubric" | "llm_rubric";
  feedback: string;
  solution: Record<string, unknown> | null;
  disputeAllowed: boolean;
  verdict?: "got_it" | "almost" | "not_yet";
  gradeId?: string;
  keyPoints?: string[];
  correctIndices?: number[];
  outcome?: string;
  disputed?: boolean;
}

export function gradeLessonBlock(
  lessonId: string,
  blockIndex: number,
  body: {
    contentVersion: number;
    answer: unknown;
    dispute?: boolean;
    disputeReason?: string;
  }
): Promise<BlockGradeResult> {
  return api<BlockGradeResult>(`/v1/lessons/${lessonId}/blocks/${blockIndex}/grade`, {
    method: "POST",
    body,
  });
}

export function disputeShortGrade(
  lessonId: string,
  gradeId: string,
  reason?: string
): Promise<BlockGradeResult> {
  return api<BlockGradeResult>(`/v1/lessons/${lessonId}/grades/${gradeId}/dispute`, {
    method: "POST",
    body: reason ? { reason } : {},
  });
}

export interface MeStats {
  userId: string;
  email: string | null;
  displayName: string;
  xp: number;
  streakDays: number;
  lastActiveDate: string | null;
  coursesTotal: number;
  coursesReady: number;
  lessonsCompleted: number;
  lessonsTotal: number;
  attemptsTotal: number;
  reviewsDue: number;
  createdAt: string | null;
}

export function fetchMeStats(): Promise<MeStats> {
  return api<MeStats>("/v1/me/stats");
}

export function updateMe(displayName: string): Promise<AuthUser> {
  return api<AuthUser>("/v1/me", {
    method: "PATCH",
    body: { displayName },
  });
}

export function deleteMe(body: { confirmText: string; password?: string }): Promise<void> {
  return api<void>("/v1/me", {
    method: "DELETE",
    body,
  });
}

// ---------- Phase 3: Presigned PDF Ingest, Course Path, Lifecycle ----------

export interface PresignUploadResult {
  sourceId: string;
  documentId: string;
  storageKey: string;
  uploadUrl: string;
  method: "PUT";
  expiresInSeconds: number;
}

export interface TriggerIngestResult {
  sourceId: string;
  documentId: string;
  status: string;
}

export function presignSourceUpload(body: {
  filename: string;
  contentType: string;
  byteSize: number;
  title?: string;
}): Promise<PresignUploadResult> {
  return api<PresignUploadResult>("/v1/sources/upload", {
    method: "POST",
    body,
  });
}

export async function putPresignedFile(uploadUrl: string, file: File): Promise<void> {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    body: file,
  });
  if (!res.ok) {
    throw new ApiError(res.status, "STORAGE_UPLOAD_FAILED", `Tải tệp lên kho lưu trữ thất bại (${res.status}).`);
  }
}

export function triggerSourceIngest(
  sourceId: string,
  body?: { documentId?: string; rawText?: string; ocrEnabled?: boolean }
): Promise<TriggerIngestResult> {
  return api<TriggerIngestResult>(`/v1/sources/${sourceId}/ingest`, {
    method: "POST",
    body: body ?? {},
  });
}

export function fetchSource(sourceId: string): Promise<SourceOut> {
  return api<SourceOut>(`/v1/sources/${sourceId}`);
}

export interface CoursePathLesson {
  id: string;
  orderIndex: number;
  title: string;
  status: string;
  state: "done" | "next" | "open" | "preparing" | "failed";
  contentVersion: number;
  estimatedMinutes?: number;
  kind?: string;
  format?: string;
  completed: boolean;
}

export interface CoursePathUnit {
  id: string;
  orderIndex: number;
  kicker?: string | null;
  title: string;
  blurb: string;
  tone?: string | null;
  lessons: CoursePathLesson[];
}

export interface CoursePathOut {
  id: string;
  topic: string;
  status: string;
  language?: CourseLanguage;
  units: CoursePathUnit[];
  progress: { completed: number; total: number; percent: number };
  hasPreparingLessons?: boolean;
}

export function fetchCoursePath(courseId: string): Promise<CoursePathOut> {
  return api<CoursePathOut>(`/v1/courses/${courseId}/path`);
}

export function deleteCourse(courseId: string): Promise<void> {
  return api<void>(`/v1/courses/${courseId}`, { method: "DELETE" });
}

export function retryLesson(lessonId: string): Promise<{ lessonId: string; jobId: string; status: string }> {
  return api<{ lessonId: string; jobId: string; status: string }>(`/v1/lessons/${lessonId}/retry`, {
    method: "POST",
  });
}

export function prefetchLesson(lessonId: string): Promise<unknown> {
  return api<unknown>(`/v1/lessons/${lessonId}?prefetch=1`);
}
