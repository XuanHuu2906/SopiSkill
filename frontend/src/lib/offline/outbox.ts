import { api, ApiError } from "@/lib/api";
import {
  idbDelete,
  idbGetAll,
  idbPut,
  notifyOfflineChange,
  type OutboxAttemptRecord,
} from "./db";

export interface SyncedAttemptEvent {
  lessonId: string;
  clientAttemptId: string;
  response: Record<string, unknown>;
}

/** Exact exponential backoff: min(5s * 2^(attempts-1), 300s). */
export function computeBackoffMs(attempts: number): number {
  const exp = Math.max(0, attempts - 1);
  return Math.min(5_000 * Math.pow(2, exp), 300_000);
}

export function isLikelyNetworkError(err: unknown): boolean {
  if (err instanceof ApiError) return false;
  if (typeof navigator !== "undefined" && !navigator.onLine) return true;
  if (err instanceof TypeError) return true;
  if (err instanceof Error && /network|fetch|offline|failed to fetch/i.test(err.message)) {
    return true;
  }
  return false;
}

export async function enqueueOfflineAttempt(params: {
  owner: string;
  clientAttemptId: string;
  lessonId: string;
  courseId: string | null;
  lessonTitle: string;
  contentVersion: number;
  answers: { index: number; answer: unknown }[];
}): Promise<OutboxAttemptRecord> {
  const now = Date.now();
  const record: OutboxAttemptRecord = {
    clientAttemptId: params.clientAttemptId,
    owner: params.owner,
    lessonId: params.lessonId,
    courseId: params.courseId,
    lessonTitle: params.lessonTitle,
    contentVersion: params.contentVersion,
    answers: params.answers,
    attempts: 0,
    nextRetryAt: now,
    createdAt: now,
    lastError: null,
  };
  await idbPut("outbox_attempts", record);
  notifyOfflineChange();
  return record;
}

export async function listPendingOutboxForOwner(ownerId: string): Promise<OutboxAttemptRecord[]> {
  const all = await idbGetAll<OutboxAttemptRecord>("outbox_attempts");
  return all
    .filter((entry) => entry.owner === ownerId)
    .sort((a, b) => a.createdAt - b.createdAt);
}

let flushInFlight = false;

/**
 * Drains `outbox_attempts` FIFO exclusively for `currentUserId`.
 * - Drops any foreign-owner record (isolation invariant).
 * - Drops unrecoverable 4xx errors (except 401 which pauses flush until re-authenticated).
 * - Retries 5xx / network failures with `min(5s * 2^(attempts-1), 300s)` backoff.
 */
export async function flushOutboxAttempts(
  currentUserId: string,
  options: { force?: boolean } = {},
): Promise<{ synced: SyncedAttemptEvent[]; dropped4xx: number; remaining: number }> {
  if (!currentUserId || flushInFlight) {
    return { synced: [], dropped4xx: 0, remaining: 0 };
  }
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    const pending = await listPendingOutboxForOwner(currentUserId);
    return { synced: [], dropped4xx: 0, remaining: pending.length };
  }

  flushInFlight = true;
  const synced: SyncedAttemptEvent[] = [];
  let dropped4xx = 0;

  try {
    const all = await idbGetAll<OutboxAttemptRecord>("outbox_attempts");
    // Enforce strict owner isolation: purge any record not owned by currentUserId
    const owned: OutboxAttemptRecord[] = [];
    for (const item of all) {
      if (item.owner !== currentUserId) {
        await idbDelete("outbox_attempts", item.clientAttemptId);
      } else {
        owned.push(item);
      }
    }
    owned.sort((a, b) => a.createdAt - b.createdAt);

    const now = Date.now();
    for (const item of owned) {
      if (!options.force && item.nextRetryAt > now) {
        continue;
      }
      try {
        const response = await api<Record<string, unknown>>(
          `/v1/lessons/${item.lessonId}/attempts`,
          {
            method: "POST",
            body: {
              clientAttemptId: item.clientAttemptId,
              contentVersion: item.contentVersion,
              answers: item.answers,
            },
          },
        );
        await idbDelete("outbox_attempts", item.clientAttemptId);

        // Upgrade `/complete` sessionStorage snapshot so an open /complete screen refreshes live
        if (typeof window !== "undefined") {
          try {
            const storageKey = `sopiskill:complete:${item.lessonId}`;
            const prevRaw = window.sessionStorage.getItem(storageKey);
            const prev = prevRaw ? (JSON.parse(prevRaw) as Record<string, unknown>) : {};
            const upgraded = {
              ...prev,
              ...response,
              lessonTitle: item.lessonTitle || prev.lessonTitle || "",
              courseId: item.courseId ?? prev.courseId ?? null,
              pendingSync: false,
            };
            window.sessionStorage.setItem(storageKey, JSON.stringify(upgraded));
          } catch {
            // ignore storage errors
          }
          window.dispatchEvent(
            new CustomEvent("sopiskill:attempt-synced", {
              detail: { lessonId: item.lessonId, clientAttemptId: item.clientAttemptId, response },
            }),
          );
        }
        synced.push({
          lessonId: item.lessonId,
          clientAttemptId: item.clientAttemptId,
          response,
        });
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 401) {
            // Session expired — stop flushing without deleting
            break;
          }
          if (err.status >= 400 && err.status < 500) {
            // Unrecoverable 4xx (409 CONTENT_VERSION_STALE, 404, 422) -> drop cleanly
            await idbDelete("outbox_attempts", item.clientAttemptId);
            dropped4xx += 1;
            continue;
          }
        }
        // Network error or 5xx -> exponential backoff and halt FIFO queue
        const nextAttempts = item.attempts + 1;
        await idbPut<OutboxAttemptRecord>("outbox_attempts", {
          ...item,
          attempts: nextAttempts,
          nextRetryAt: Date.now() + computeBackoffMs(nextAttempts),
          lastError: err instanceof Error ? err.message : "Network error",
        });
        break;
      }
    }

    const remainingList = await listPendingOutboxForOwner(currentUserId);
    notifyOfflineChange();
    return { synced, dropped4xx, remaining: remainingList.length };
  } finally {
    flushInFlight = false;
  }
}
