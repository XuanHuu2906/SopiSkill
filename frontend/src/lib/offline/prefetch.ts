import {
  API_BASE,
  api,
  fetchCourseGlossary,
  type CoursePathOut,
} from "@/lib/api";
import {
  invalidateStaleCachedLesson,
  putCachedCourse,
  putCachedGlossary,
  putCachedLesson,
  putCachedReelClip,
} from "./db";

const CLIENT_BLOCKS_CAPABILITIES =
  "teach,mc,blank,multi_blank,order,match,short,speed,recap,figure,reel";

interface NavigatorConnectionLike {
  saveData?: boolean;
  effectiveType?: string;
}

/**
 * Determines how many upcoming `ready` lessons to prefetch in the background:
 * - 3 lessons on Wi-Fi / fast connections
 * - 1 lesson when `saveData` is enabled or on slow cellular (`slow-2g | 2g | 3g`)
 */
export function computePrefetchBudget(): number {
  if (typeof navigator === "undefined") return 1;
  const conn = (navigator as Navigator & { connection?: NavigatorConnectionLike }).connection;
  if (!conn) return 3;
  if (conn.saveData) return 1;
  if (conn.effectiveType && ["slow-2g", "2g", "3g"].includes(conn.effectiveType)) {
    return 1;
  }
  return 3;
}

/**
 * Smart Background Prefetch for a course:
 *  1. Caches `CoursePathOut` in `cached_courses`.
 *  2. Evicts any cached lesson whose server `contentVersion` increased.
 *  3. Caches course `glossary` in `cached_glossary`.
 *  4. Prefetches next 3 `ready` lessons on Wi-Fi (or 1 on saveData/slow cellular),
 *     skipping any unit/lesson marked `paywalled: true`.
 */
export async function prefetchCourseOffline(
  course: CoursePathOut,
  ownerId: string,
): Promise<void> {
  if (!ownerId || !course?.id) return;
  if (typeof navigator !== "undefined" && !navigator.onLine) return;

  try {
    await putCachedCourse(course.id, ownerId, course);
  } catch {
    // ignore storage errors
  }

  // Evict stale lessons whose server contentVersion bumped & collect eligible ready lessons
  const candidates: { id: string; contentVersion: number; completed: boolean }[] = [];
  for (const unit of course.units ?? []) {
    const unitPaywalled = Boolean((unit as unknown as { paywalled?: boolean }).paywalled);
    if (unitPaywalled) continue;
    for (const lesson of unit.lessons ?? []) {
      const lessonPaywalled = Boolean((lesson as unknown as { paywalled?: boolean }).paywalled);
      await invalidateStaleCachedLesson(lesson.id, lesson.contentVersion).catch(() => {});
      if (!lessonPaywalled && lesson.status === "ready") {
        candidates.push({
          id: lesson.id,
          contentVersion: lesson.contentVersion,
          completed: Boolean(lesson.completed),
        });
      }
    }
  }

  // Prefetch course glossary for offline VocabSheet
  try {
    const glossary = await fetchCourseGlossary(course.id);
    await putCachedGlossary(course.id, undefined, ownerId, glossary);
  } catch {
    // ignore background prefetch failures
  }

  // Prioritize upcoming uncompleted ready lessons, then remaining ready lessons up to budget
  const ordered = [
    ...candidates.filter((c) => !c.completed),
    ...candidates.filter((c) => c.completed),
  ].slice(0, computePrefetchBudget());

  for (const item of ordered) {
    if (typeof navigator !== "undefined" && !navigator.onLine) break;
    try {
      const lessonData = await api<Record<string, unknown>>(
        `/v1/lessons/${item.id}?prefetch=1`,
        { headers: { "X-Client-Blocks": CLIENT_BLOCKS_CAPABILITIES } },
      );
      const ver =
        typeof lessonData.contentVersion === "number"
          ? lessonData.contentVersion
          : item.contentVersion;
      await putCachedLesson(item.id, course.id, ownerId, ver, lessonData);

      // Warm up first 2 Reel audio clips into bounded IndexedDB `cached_reel_clips`
      const reelObj = lessonData.reel as
        | { scenes?: { audio?: { clipId?: string; url?: string; contentType?: string } | null }[] }
        | null
        | undefined;
      if (reelObj && Array.isArray(reelObj.scenes)) {
        const audioScenes = reelObj.scenes
          .filter((sc) => sc?.audio?.clipId && sc?.audio?.url)
          .slice(0, 2);
        for (const sc of audioScenes) {
          if (typeof navigator !== "undefined" && !navigator.onLine) break;
          try {
            const audioUrl = sc.audio!.url!.startsWith("http")
              ? sc.audio!.url!
              : `${API_BASE}${sc.audio!.url!}`;
            const resp = await fetch(audioUrl, { credentials: "include" });
            if (resp.ok) {
              const buf = await resp.arrayBuffer();
              await putCachedReelClip(
                `${item.id}:${sc.audio!.clipId!}`,
                ownerId,
                item.id,
                sc.audio!.contentType || resp.headers.get("content-type") || "audio/wav",
                buf,
              );
            }
          } catch {
            // ignore individual audio prefetch failure
          }
        }
      }

      // Warm same-origin HTML & Next.js RSC route shell in Service Worker cache (never touches /v1/*)
      if (typeof window !== "undefined") {
        void fetch(`/lesson/${item.id}`, { credentials: "same-origin" }).catch(() => {});
        void fetch(`/lesson/${item.id}`, {
          credentials: "same-origin",
          headers: { RSC: "1" },
        }).catch(() => {});
        void fetch(`/lesson/${item.id}/complete`, { credentials: "same-origin" }).catch(() => {});
        void fetch(`/lesson/${item.id}/complete`, {
          credentials: "same-origin",
          headers: { RSC: "1" },
        }).catch(() => {});
      }
    } catch {
      // ignore individual background prefetch failures
    }
  }
}
