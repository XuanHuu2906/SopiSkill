"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchCourseGlossary, type CourseGlossary } from "@/lib/api";
import { useAuth, useSessionQueryKey } from "@/app/providers";
import { getCachedGlossary, putCachedGlossary } from "@/lib/offline/db";
import { isLikelyNetworkError } from "@/lib/offline/outbox";
import { Badge } from "@/components/ui/Badge";
import { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";

export default function VocabSheet({
  courseId,
  lessonId,
  initialQuery,
  open,
  onClose,
}: {
  courseId: string;
  lessonId?: string;
  initialQuery?: string;
  open: boolean;
  onClose: () => void;
}) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  const { data: user } = useAuth();
  const [search, setSearch] = useState(initialQuery ?? "");
  const [scopeLessonOnly, setScopeLessonOnly] = useState(Boolean(lessonId));

  useEffect(() => {
    if (open) {
      setSearch(initialQuery ?? "");
    }
  }, [open, initialQuery]);
  const activeLessonId = scopeLessonOnly ? lessonId : undefined;
  const glossaryKey = useSessionQueryKey("course-glossary", courseId, activeLessonId ?? "all");

  useModalPanel({
    open,
    onClose,
    panelRef: sheetRef,
    initialFocusSelector: "#vocab-search-input",
  });

  const glossary = useQuery({
    queryKey: glossaryKey,
    networkMode: "always",
    enabled: open && Boolean(courseId),
    queryFn: async () => {
      if (user?.id && typeof navigator !== "undefined" && !navigator.onLine) {
        const cached = await getCachedGlossary<CourseGlossary>(
          courseId,
          activeLessonId,
          user.id,
        );
        if (cached) return cached;
      }
      try {
        const fresh = await fetchCourseGlossary(courseId, activeLessonId);
        if (user?.id) {
          void putCachedGlossary(courseId, activeLessonId, user.id, fresh).catch(() => {});
        }
        return fresh;
      } catch (err) {
        if (user?.id && isLikelyNetworkError(err)) {
          const cached = await getCachedGlossary<CourseGlossary>(
            courseId,
            activeLessonId,
            user.id,
          );
          if (cached) return cached;
        }
        throw err;
      }
    },
  });

  if (!open) return null;

  const q = search.trim().toLowerCase();
  const filtered = (glossary.data?.items ?? []).filter(
    (item) =>
      !q ||
      item.term.toLowerCase().includes(q) ||
      item.definition.toLowerCase().includes(q) ||
      (item.lessonTitle ?? "").toLowerCase().includes(q)
  );

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng bảng thuật ngữ"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="tutor-sheet outline-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vocab-heading"
        ref={sheetRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div>
            <div id="vocab-heading" className="tutor-title">
              Bảng thuật ngữ
            </div>
            <div className="tutor-subtitle">
              {glossary.data ? `${glossary.data.total} thuật ngữ` : "Đang tải…"}
            </div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>

        <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--linen)" }}>
          <label className="sr-only" htmlFor="vocab-search-input">
            Tìm thuật ngữ
          </label>
          <input
            id="vocab-search-input"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm thuật ngữ hoặc định nghĩa…"
          />
          {lessonId && (
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button
                type="button"
                className={`btn btn-sm ${scopeLessonOnly ? "" : "btn-secondary"}`}
                onClick={() => setScopeLessonOnly(true)}
              >
                Bài này
              </button>
              <button
                type="button"
                className={`btn btn-sm ${!scopeLessonOnly ? "" : "btn-secondary"}`}
                onClick={() => setScopeLessonOnly(false)}
              >
                Cả khóa học
              </button>
            </div>
          )}
        </div>

        <div
          tabIndex={0}
          aria-label="Danh sách thuật ngữ"
          style={{ padding: "14px 20px", overflowY: "auto", flex: 1 }}
        >
          {glossary.isLoading && <p className="muted">Đang tải thuật ngữ…</p>}
          {glossary.isError && (
            <div className="error-box" role="alert">
              Không tải được thuật ngữ: {glossary.error.message}
            </div>
          )}
          {!glossary.isLoading && !glossary.isError && filtered.length === 0 && (
            <p className="muted">Chưa có thuật ngữ phù hợp.</p>
          )}
          <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 12 }}>
            {filtered.map((item) => (
              <li
                key={item.id}
                style={{
                  border: "1px solid var(--linen)",
                  borderRadius: "var(--radius-md)",
                  padding: "14px 16px",
                  background: "var(--surface)",
                  boxShadow: "var(--shadow-card)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "baseline" }}>
                  <strong style={{ fontSize: 15 }}>{item.term}</strong>
                  {item.lessonTitle && <Badge tone="muted">{item.lessonTitle}</Badge>}
                </div>
                <p className="muted" style={{ marginTop: 6, fontSize: 14, lineHeight: 1.5 }}>
                  {item.definition}
                </p>
                {item.example && (
                  <p className="caption" style={{ marginTop: 6 }}>
                    Ví dụ: {item.example}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
