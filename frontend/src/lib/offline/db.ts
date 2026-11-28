/**
 * Phase 8 Offline-First IndexedDB (`sopiskill_offline_v1`) with exactly 6 stores:
 *  1. `cached_courses`
 *  2. `cached_lessons` (ONLY public blocks — strictly 0 answer keys; auto-evicts on contentVersion bump)
 *  3. `cached_glossary`
 *  4. `outbox_attempts` (raw learner answers locked to `owner = user.id`)
 *  5. `cached_reel_clips`
 *  6. `local_prefs`
 */

export const OFFLINE_DB_NAME = "sopiskill_offline_v1";
export const OFFLINE_DB_VERSION = 1;

export const OFFLINE_STORES = [
  "cached_courses",
  "cached_lessons",
  "cached_glossary",
  "outbox_attempts",
  "cached_reel_clips",
  "local_prefs",
] as const;

export type OfflineStoreName = (typeof OFFLINE_STORES)[number];

export interface CachedCourseRecord {
  courseId: string;
  ownerId: string;
  data: unknown;
  updatedAt: number;
}

export interface CachedLessonRecord {
  lessonId: string;
  courseId: string | null;
  ownerId: string;
  contentVersion: number;
  data: unknown;
  updatedAt: number;
}

export interface CachedGlossaryRecord {
  cacheKey: string; // `${courseId}:${lessonId ?? "all"}`
  courseId: string;
  ownerId: string;
  data: unknown;
  updatedAt: number;
}

export interface OutboxAttemptRecord {
  clientAttemptId: string;
  owner: string;
  lessonId: string;
  courseId: string | null;
  lessonTitle: string;
  contentVersion: number;
  answers: { index: number; answer: unknown }[];
  attempts: number;
  nextRetryAt: number;
  createdAt: number;
  lastError: string | null;
}

export interface CachedReelClipRecord {
  clipId: string;
  ownerId: string;
  lessonId?: string;
  contentType?: string;
  data: unknown;
  updatedAt: number;
}

export interface LocalPrefRecord {
  key: string;
  value: unknown;
  updatedAt: number;
}

const FORBIDDEN_ANSWER_KEYS = new Set([
  "answerIndex",
  "answerIndices",
  "answer",
  "answers",
  "acceptedAnswers",
  "answer_key",
  "solution",
  "outcomes",
  "keyPoints",
  "pairs",
]);

/** Defensive client-side strip so IndexedDB NEVER stores any server answer-key field. */
export function stripForbiddenKeys<T>(input: T): T {
  if (Array.isArray(input)) {
    return input.map((item) => stripForbiddenKeys(item)) as unknown as T;
  }
  if (input && typeof input === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(input as Record<string, unknown>)) {
      if (FORBIDDEN_ANSWER_KEYS.has(k)) continue;
      out[k] = stripForbiddenKeys(v);
    }
    return out as T;
  }
  return input;
}

function isIndexedDbAvailable(): boolean {
  return typeof window !== "undefined" && typeof window.indexedDB !== "undefined";
}

let dbPromise: Promise<IDBDatabase | null> | null = null;

export function openOfflineDb(): Promise<IDBDatabase | null> {
  if (!isIndexedDbAvailable()) return Promise.resolve(null);
  if (dbPromise) return dbPromise;

  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      const req = window.indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("cached_courses")) {
          const s = db.createObjectStore("cached_courses", { keyPath: "courseId" });
          s.createIndex("ownerId", "ownerId", { unique: false });
        }
        if (!db.objectStoreNames.contains("cached_lessons")) {
          const s = db.createObjectStore("cached_lessons", { keyPath: "lessonId" });
          s.createIndex("ownerId", "ownerId", { unique: false });
          s.createIndex("courseId", "courseId", { unique: false });
        }
        if (!db.objectStoreNames.contains("cached_glossary")) {
          const s = db.createObjectStore("cached_glossary", { keyPath: "cacheKey" });
          s.createIndex("ownerId", "ownerId", { unique: false });
        }
        if (!db.objectStoreNames.contains("outbox_attempts")) {
          const s = db.createObjectStore("outbox_attempts", { keyPath: "clientAttemptId" });
          s.createIndex("owner", "owner", { unique: false });
          s.createIndex("createdAt", "createdAt", { unique: false });
        }
        if (!db.objectStoreNames.contains("cached_reel_clips")) {
          const s = db.createObjectStore("cached_reel_clips", { keyPath: "clipId" });
          s.createIndex("ownerId", "ownerId", { unique: false });
        }
        if (!db.objectStoreNames.contains("local_prefs")) {
          db.createObjectStore("local_prefs", { keyPath: "key" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => {
        dbPromise = null;
        resolve(null);
      };
    } catch {
      dbPromise = null;
      resolve(null);
    }
  });
  return dbPromise;
}

function reqToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export async function idbPut<T>(store: OfflineStoreName, value: T): Promise<void> {
  const db = await openOfflineDb();
  if (!db) return;
  const tx = db.transaction(store, "readwrite");
  tx.objectStore(store).put(value);
  await txDone(tx);
}

export async function idbGet<T>(store: OfflineStoreName, key: IDBValidKey): Promise<T | null> {
  const db = await openOfflineDb();
  if (!db) return null;
  const tx = db.transaction(store, "readonly");
  const res = await reqToPromise<T | undefined>(tx.objectStore(store).get(key));
  return res ?? null;
}

export async function idbDelete(store: OfflineStoreName, key: IDBValidKey): Promise<void> {
  const db = await openOfflineDb();
  if (!db) return;
  const tx = db.transaction(store, "readwrite");
  tx.objectStore(store).delete(key);
  await txDone(tx);
}

export async function idbGetAll<T>(store: OfflineStoreName): Promise<T[]> {
  const db = await openOfflineDb();
  if (!db) return [];
  const tx = db.transaction(store, "readonly");
  const res = await reqToPromise<T[]>(tx.objectStore(store).getAll());
  return res ?? [];
}

/** Clears all 6 stores cleanly on logout or account switch A -> B. */
export async function clearOfflineDatabase(): Promise<void> {
  const db = await openOfflineDb();
  if (!db) return;
  const tx = db.transaction([...OFFLINE_STORES], "readwrite");
  for (const store of OFFLINE_STORES) {
    tx.objectStore(store).clear();
  }
  await txDone(tx);
  notifyOfflineChange();
}

/**
 * Ensures the IndexedDB belongs exclusively to `userId`. If a different user previously used this
 * browser without logging out cleanly, wipes all 6 stores immediately so zero data or outbox
 * entries leak across accounts.
 */
export async function ensureOfflineOwner(userId: string): Promise<void> {
  if (!userId) return;
  const existing = await idbGet<LocalPrefRecord>("local_prefs", "activeOwnerId");
  if (existing && existing.value !== userId) {
    await clearOfflineDatabase();
  }
  await idbPut<LocalPrefRecord>("local_prefs", {
    key: "activeOwnerId",
    value: userId,
    updatedAt: Date.now(),
  });
}

// ---------- Typed Cache Helpers ----------

export async function putCachedCourse(courseId: string, ownerId: string, data: unknown): Promise<void> {
  await idbPut<CachedCourseRecord>("cached_courses", {
    courseId,
    ownerId,
    data,
    updatedAt: Date.now(),
  });
}

export async function getCachedCourse<T>(courseId: string, ownerId: string): Promise<T | null> {
  const rec = await idbGet<CachedCourseRecord>("cached_courses", courseId);
  if (!rec || rec.ownerId !== ownerId) return null;
  return rec.data as T;
}

export async function putCachedLesson(
  lessonId: string,
  courseId: string | null,
  ownerId: string,
  contentVersion: number,
  lessonData: unknown,
): Promise<void> {
  const sanitized = stripForbiddenKeys(lessonData);
  await idbPut<CachedLessonRecord>("cached_lessons", {
    lessonId,
    courseId,
    ownerId,
    contentVersion,
    data: sanitized,
    updatedAt: Date.now(),
  });
}

export async function getCachedLesson<T>(
  lessonId: string,
  ownerId: string,
  expectedMinVersion?: number,
): Promise<T | null> {
  const rec = await idbGet<CachedLessonRecord>("cached_lessons", lessonId);
  if (!rec || rec.ownerId !== ownerId) return null;
  if (typeof expectedMinVersion === "number" && rec.contentVersion < expectedMinVersion) {
    await idbDelete("cached_lessons", lessonId);
    return null;
  }
  return rec.data as T;
}

export async function invalidateStaleCachedLesson(
  lessonId: string,
  serverContentVersion: number,
): Promise<boolean> {
  const rec = await idbGet<CachedLessonRecord>("cached_lessons", lessonId);
  if (rec && rec.contentVersion < serverContentVersion) {
    await idbDelete("cached_lessons", lessonId);
    return true;
  }
  return false;
}

export async function putCachedGlossary(
  courseId: string,
  lessonId: string | undefined,
  ownerId: string,
  data: unknown,
): Promise<void> {
  const cacheKey = `${courseId}:${lessonId ?? "all"}`;
  await idbPut<CachedGlossaryRecord>("cached_glossary", {
    cacheKey,
    courseId,
    ownerId,
    data,
    updatedAt: Date.now(),
  });
}

export async function getCachedGlossary<T>(
  courseId: string,
  lessonId: string | undefined,
  ownerId: string,
): Promise<T | null> {
  const exact = await idbGet<CachedGlossaryRecord>(
    "cached_glossary",
    `${courseId}:${lessonId ?? "all"}`,
  );
  if (exact && exact.ownerId === ownerId) return exact.data as T;
  if (lessonId) {
    const courseWide = await idbGet<CachedGlossaryRecord>("cached_glossary", `${courseId}:all`);
    if (courseWide && courseWide.ownerId === ownerId) return courseWide.data as T;
  }
  return null;
}

export function notifyOfflineChange(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("sopiskill:offline-change"));
  }
}

const MAX_CACHED_REEL_CLIPS = 30;

/** Store a Reel audio clip (`ArrayBuffer`) bounded to `MAX_CACHED_REEL_CLIPS` (LRU eviction). */
export async function putCachedReelClip(
  clipId: string,
  ownerId: string,
  lessonId: string,
  contentType: string,
  bytes: ArrayBuffer,
): Promise<void> {
  if (!clipId || !ownerId || !bytes || bytes.byteLength === 0) return;
  await idbPut<CachedReelClipRecord>("cached_reel_clips", {
    clipId,
    ownerId,
    lessonId,
    contentType,
    data: bytes,
    updatedAt: Date.now(),
  });
  try {
    const all = await idbGetAll<CachedReelClipRecord>("cached_reel_clips");
    if (all.length > MAX_CACHED_REEL_CLIPS) {
      all.sort((a, b) => a.updatedAt - b.updatedAt);
      const excess = all.slice(0, all.length - MAX_CACHED_REEL_CLIPS);
      for (const old of excess) {
        await idbDelete("cached_reel_clips", old.clipId);
      }
    }
  } catch {
    // ignore background eviction error
  }
}

export async function getCachedReelClip(
  clipId: string,
  ownerId: string,
): Promise<{ bytes: ArrayBuffer; contentType: string } | null> {
  const rec = await idbGet<CachedReelClipRecord>("cached_reel_clips", clipId);
  if (!rec || rec.ownerId !== ownerId) return null;
  if (!(rec.data instanceof ArrayBuffer)) return null;
  return {
    bytes: rec.data,
    contentType: rec.contentType || "audio/wav",
  };
}
