"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type CourseListItem } from "@/lib/api";
import { useSessionQueryKey } from "@/app/providers";
import TutorPanel from "@/app/lesson/[lessonId]/TutorPanel";
import { ButtonLink, IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";

interface CourseLessonsLookup {
  id: string;
  topic: string;
  units: {
    lessons: { id: string; title: string; status: string }[];
  }[];
}

export default function GlobalSopiSheet({
  open,
  onClose,
  courses,
  initialCourseId,
}: {
  open: boolean;
  onClose: () => void;
  courses: CourseListItem[];
  initialCourseId?: string | null;
}) {
  const readyCourses = useMemo(
    () => courses.filter((c) => c.status === "ready" || Boolean(c.resumeLessonId)),
    [courses],
  );

  const defaultCourseId = useMemo(() => {
    if (initialCourseId && readyCourses.some((c) => c.id === initialCourseId)) {
      return initialCourseId;
    }
    return readyCourses.find((c) => c.resumeLessonId)?.id ?? readyCourses[0]?.id ?? null;
  }, [initialCourseId, readyCourses]);

  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(defaultCourseId);
  const prevOpenRef = useRef(false);

  useEffect(() => {
    const justOpened = open && !prevOpenRef.current;
    prevOpenRef.current = open;
    if (!open) return;

    if (justOpened) {
      if (initialCourseId && readyCourses.some((c) => c.id === initialCourseId)) {
        setSelectedCourseId(initialCourseId);
      } else {
        setSelectedCourseId(defaultCourseId);
      }
      return;
    }

    setSelectedCourseId((curr) => {
      if (curr && readyCourses.some((c) => c.id === curr)) return curr;
      return defaultCourseId;
    });
  }, [open, initialCourseId, defaultCourseId, readyCourses]);

  const activeCourse = readyCourses.find((c) => c.id === selectedCourseId) ?? null;
  const needsFallbackLesson = Boolean(open && activeCourse && !activeCourse.resumeLessonId);
  const courseLookupKey = useSessionQueryKey("sopi-course-lookup", activeCourse?.id ?? "none");

  const courseLookup = useQuery({
    queryKey: courseLookupKey,
    enabled: needsFallbackLesson,
    queryFn: () => api<CourseLessonsLookup>(`/v1/courses/${activeCourse!.id}`),
    retry: false,
  });

  const fallbackLesson = useMemo(() => {
    if (!courseLookup.data) return null;
    for (const unit of courseLookup.data.units) {
      const ready = unit.lessons.find((l) => l.status === "ready");
      if (ready) return ready;
    }
    return null;
  }, [courseLookup.data]);

  const resolvedLessonId = activeCourse?.resumeLessonId ?? fallbackLesson?.id ?? null;
  const resolvedLessonTitle = activeCourse?.resumeLessonTitle ?? fallbackLesson?.title ?? activeCourse?.topic;

  const emptySheetRef = useRef<HTMLDivElement | null>(null);
  const showEmptyState = open && (!activeCourse || (!resolvedLessonId && !courseLookup.isLoading));
  const showLoadingState = open && Boolean(activeCourse) && !resolvedLessonId && courseLookup.isLoading;

  useModalPanel({
    open: showEmptyState || showLoadingState,
    onClose,
    panelRef: emptySheetRef,
    modal: true,
  });

  if (!open) return null;

  if (activeCourse && resolvedLessonId) {
    return (
      <TutorPanel
        courseId={activeCourse.id}
        lessonId={resolvedLessonId}
        activeBlockIndex={0}
        blockLabel={resolvedLessonTitle ?? activeCourse.topic}
        open={open}
        onClose={onClose}
        docked={false}
        courseOptions={readyCourses.map((c) => ({ id: c.id, topic: c.topic }))}
        onSelectCourse={(nextId) => setSelectedCourseId(nextId)}
      />
    );
  }

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng Sopi"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="tutor-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sopi-empty-heading"
        ref={emptySheetRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="tutor-avatar" aria-hidden="true">
              S
            </span>
            <div>
              <div id="sopi-empty-heading" className="tutor-title">
                Sopi
              </div>
              <div className="tutor-subtitle">Trợ giảng AI</div>
            </div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>

        <div className="tutor-scroll" style={{ justifyContent: "center", alignItems: "flex-start" }}>
          {showLoadingState ? (
            <p className="muted" style={{ fontSize: 14 }}>
              Đang kết nối ngữ cảnh khóa học với Sopi…
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <p style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--ink)" }}>
                Chưa có bài học sẵn sàng để hỏi Sopi
              </p>
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>
                Sopi trả lời dựa trên bài học và tài liệu của khóa bạn đang học. Hãy tạo khóa học
                đầu tiên để bắt đầu trò chuyện cùng Sopi.
              </p>
              <div>
                <ButtonLink href="/new" size="md" onClick={onClose}>
                  Tạo khóa học mới
                </ButtonLink>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
