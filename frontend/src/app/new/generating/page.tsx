"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

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
  llmCalls: number;
  promptTokens: number | null;
  completionTokens: number | null;
  costEstimateUsd: number | null;
  costKnown: boolean;
}

const STAGES: { key: string; label: string }[] = [
  { key: "reading_answers", label: "Đọc câu trả lời của bạn" },
  { key: "background", label: "Bổ sung kiến thức nền còn thiếu" },
  { key: "outline", label: "Phác thảo lộ trình" },
  { key: "lessons", label: "Soạn bài học" },
];

const STATUS_LABELS: Record<string, string> = {
  queued: "Trong hàng đợi",
  running: "Đang sinh",
  ready: "Hoàn tất",
  failed: "Thất bại",
};

function stageState(
  stageKey: string,
  currentStage: string | null | undefined,
  status: string | undefined
): "done" | "active" | "pending" {
  if (status === "ready") return "done";
  if (!currentStage) return "pending";
  const order = STAGES.map((s) => s.key);
  const currentIndex = order.indexOf(currentStage);
  const index = order.indexOf(stageKey);
  if (currentIndex < 0) return "pending";
  if (index < currentIndex) return "done";
  if (index === currentIndex) return "active";
  return "pending";
}

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

  if (!courseId) return <p className="muted">Thiếu courseId.</p>;
  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const status = gen.data?.status;
  const ready = status === "ready";
  const title = ready ? "Khóa học đã sẵn sàng" : "Đang soạn khóa học";

  return (
    <div style={{ maxWidth: 560, margin: "0 auto", textAlign: "center", paddingTop: 40 }}>
      <span className="eyebrow">{title}</span>
      <h1 className="page-title" style={{ margin: "8px 0 32px" }}>
        {ready ? "Xong rồi." : STATUS_LABELS[status ?? ""] ?? "Đang tải"}
      </h1>

      <ul className="stage-list" style={{ textAlign: "left" }}>
        {STAGES.map((stage) => {
          const state = stageState(stage.key, gen.data?.stage, status);
          return (
            <li key={stage.key} className={`stage-item is-${state}`}>
              <span className="stage-dot" aria-hidden="true" />
              <span>{stage.label}</span>
              {stage.key === "lessons" && gen.data?.lessonsTotal != null && (
                <span className="caption" style={{ marginLeft: "auto" }}>
                  {gen.data.lessonsDone}/{gen.data.lessonsTotal}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {status === "queued" && !gen.data?.dispatched && (
        <p className="muted">Đang chờ worker nhận việc… (hệ thống tự thử lại)</p>
      )}

      {gen.data && gen.data.llmCalls > 0 && !ready && (
        <p className="caption">
          Đã gọi AI {gen.data.llmCalls} lần · {gen.data.promptTokens ?? 0} token vào /{" "}
          {gen.data.completionTokens ?? 0} token ra
          {gen.data.costKnown && gen.data.costEstimateUsd != null
            ? ` · ~$${gen.data.costEstimateUsd.toFixed(4)}`
            : ""}
        </p>
      )}

      {gen.data?.error && (
        <div className="error-box" role="alert" style={{ textAlign: "left" }}>
          Lỗi ({gen.data.error.code}): {gen.data.error.message}
          {gen.data.error.retryable && (
            <p style={{ marginTop: 6 }}>
              Lỗi tạm thời — hệ thống đang tự thử lại (lần {gen.data.attempts}).
            </p>
          )}
          <div style={{ marginTop: 10 }}>
            <Button
              variant="secondary"
              size="md"
              onClick={() => retry.mutate()}
              disabled={retry.isPending}
            >
              {retry.isPending ? "Đang gửi..." : "Thử lại"}
            </Button>
          </div>
          {retry.isError && <p className="error-text" style={{ marginTop: 8 }}>{retry.error.message}</p>}
        </div>
      )}

      {gen.isError && (
        <div className="error-box" role="alert" style={{ textAlign: "left" }}>
          Không lấy được trạng thái: {gen.error.message}
          <div style={{ marginTop: 10 }}>
            <Button variant="secondary" size="md" onClick={() => gen.refetch()}>
              Thử lại
            </Button>
          </div>
        </div>
      )}

      {ready && (
        <ButtonLink href={`/course/${courseId}`} size="lg" block>
          Mở lộ trình
        </ButtonLink>
      )}

      {!ready && !gen.isError && (
        <Card variant="tint" style={{ marginTop: 24, textAlign: "left" }}>
          <p className="muted" style={{ margin: 0 }}>
            Bạn có thể rời trang này — quá trình soạn bài tiếp tục ở máy chủ và kết quả
            sẽ xuất hiện trong danh sách khóa học.
          </p>
        </Card>
      )}
    </div>
  );
}

export default function GeneratingPage() {
  return (
    <Suspense fallback={<p className="muted">Đang tải...</p>}>
      <GeneratingInner />
    </Suspense>
  );
}
