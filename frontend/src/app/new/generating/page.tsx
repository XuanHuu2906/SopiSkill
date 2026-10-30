"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";

interface GenerationOut {
  jobId: string;
  status: string;
  stage: string | null;
  lessonsDone: number;
  lessonsTotal: number | null;
  error: { code: string; message: string; retryable?: boolean } | null;
  attempts: number;
  dispatched: boolean;
  lastErrorCode: string | null;
}

const STAGE_LABELS: Record<string, string> = {
  reading_answers: "Đọc câu trả lời của bạn",
  background: "Bổ sung kiến thức nền còn thiếu",
  outline: "Phác thảo lộ trình",
  lessons: "Soạn bài học",
  done: "Hoàn tất",
};

const STATUS_LABELS: Record<string, string> = {
  queued: "Trong hàng đợi",
  running: "Đang sinh",
  ready: "Hoàn tất",
  failed: "Thất bại",
};

function GeneratingInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const generationKey = useSessionQueryKey("generation", courseId);

  const gen = useQuery({
    queryKey: generationKey,
    queryFn: () => api<GenerationOut>(`/v1/courses/${courseId}/generation`),
    enabled: !!courseId && isAuthenticated,
    retry: 2,
    // Dừng polling ở mọi trạng thái terminal; lỗi mạng tạm thời vẫn poll lại.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "ready" || status === "failed") return false;
      return query.state.status === "error" ? 5000 : 2000;
    },
  });

  const retry = useMutation({
    mutationFn: () => api(`/v1/courses/${courseId}/retry`, { method: "POST" }),
    onSuccess: () => gen.refetch(),
  });

  useEffect(() => {
    if (gen.data?.status === "ready") {
      router.push(`/course/${encodeURIComponent(courseId)}`);
    }
  }, [gen.data?.status, courseId, router]);

  if (!courseId) return <div className="container">Thiếu courseId.</div>;
  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated) return <div className="container">Đang chuyển tới trang đăng nhập…</div>;

  return (
    <div className="container">
      <h1>Đang sinh khóa học...</h1>
      <div className="card">
        <p>
          Trạng thái:{" "}
          <strong>
            {(gen.data?.status && STATUS_LABELS[gen.data.status]) ?? "đang tải"}
          </strong>
        </p>
        {gen.data?.stage && <p>{STAGE_LABELS[gen.data.stage] ?? gen.data.stage}</p>}
        {gen.data?.lessonsTotal != null && (
          <p>
            Tiến độ: {gen.data.lessonsDone}/{gen.data.lessonsTotal} bài học
          </p>
        )}
        {gen.data?.status === "queued" && !gen.data.dispatched && (
          <p>
            Đang chờ worker nhận việc… (hệ thống sẽ tự thử lại, không cần thao tác)
          </p>
        )}

        {gen.data?.error && (
          <div className="error-box">
            Lỗi ({gen.data.error.code}): {gen.data.error.message}
            {gen.data.error.retryable && (
              <p>Lỗi tạm thời — hệ thống đang tự thử lại (lần {gen.data.attempts}).</p>
            )}
            <button
              style={{ marginTop: 8 }}
              type="button"
              onClick={() => retry.mutate()}
              disabled={retry.isPending}
            >
              {retry.isPending ? "Đang gửi..." : "Thử lại"}
            </button>
            {retry.isError && <p>{retry.error.message}</p>}
          </div>
        )}

        {gen.isError && (
          <div className="error-box">
            Không lấy được trạng thái: {gen.error.message}
            <button style={{ marginTop: 8 }} onClick={() => gen.refetch()}>
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
