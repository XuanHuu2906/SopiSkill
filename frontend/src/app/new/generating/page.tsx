"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { api } from "@/lib/api";

interface GenerationOut {
  jobId: string;
  status: string;
  stage: string | null;
  lessonsDone: number;
  lessonsTotal: number | null;
  error: { code: string; message: string } | null;
}

const STAGE_LABELS: Record<string, string> = {
  reading_answers: "Đọc câu trả lời của bạn",
  background: "Bổ sung kiến thức nền còn thiếu",
  outline: "Phác thảo lộ trình",
  lessons: "Soạn bài học",
  done: "Hoàn tất",
};

function GeneratingInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";

  const gen = useQuery({
    queryKey: ["generation", courseId],
    queryFn: () => api<GenerationOut>(`/v1/courses/${courseId}/generation`),
    enabled: !!courseId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "ready" || status === "failed" ? false : 2000;
    },
  });

  useEffect(() => {
    if (gen.data?.status === "ready") {
      router.push(`/course/${encodeURIComponent(courseId)}`);
    }
  }, [gen.data?.status, courseId, router]);

  if (!courseId) return <div className="container">Thiếu courseId.</div>;

  return (
    <div className="container">
      <h1>Đang sinh khóa học...</h1>
      <div className="card">
        <p>
          Trạng thái: <strong>{gen.data?.status ?? "đang tải"}</strong>
        </p>
        {gen.data?.stage && <p>{STAGE_LABELS[gen.data.stage] ?? gen.data.stage}</p>}
        {gen.data?.lessonsTotal != null && (
          <p>
            Tiến độ: {gen.data.lessonsDone}/{gen.data.lessonsTotal} bài học
          </p>
        )}
        {gen.data?.error && (
          <div className="error-box">
            Lỗi: {gen.data.error.message}
            <br />
            <button
              style={{ marginTop: 8 }}
              onClick={() => api(`/v1/courses/${courseId}/retry`, { method: "POST" })}
            >
              Thử lại
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function GeneratingPage() {
  return (
    <Suspense fallback={<div className="container">Đang tải...</div>}>
      <GeneratingInner />
    </Suspense>
  );
}
