"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Button, IconButton } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";

interface InterviewOut {
  questions: string[];
  completedCount: number;
}

function InterviewInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const interviewKey = useSessionQueryKey("interview", courseId);

  const [answers, setAnswers] = useState<string[]>(["", "", "", "", ""]);
  const [current, setCurrent] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answered, setAnswered] = useState<string[]>([]);

  const interview = useQuery({
    queryKey: interviewKey,
    queryFn: () => api<InterviewOut>(`/v1/courses/${courseId}/interview`),
    enabled: !!courseId && isAuthenticated,
  });

  useEffect(() => {
    if (interview.data) {
      const done = Math.min(interview.data.completedCount, 5);
      setAnswers((prev) => {
        const merged = [...prev];
        for (let i = 0; i < done; i++) {
          if (!merged[i]?.trim()) merged[i] = "✓ đã trả lời";
        }
        return merged;
      });
      if (done >= 5) {
        router.replace(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
        return;
      }
      setCurrent(done);
      setAnswers((prev) => prev.map((a, i) => (i === done ? "" : a)));
    }
  }, [interview.data, courseId, router]);

  const questions = interview.data?.questions ?? [];
  const completedCount = Math.min(interview.data?.completedCount ?? 0, 5);
  const redirecting = completedCount >= 5;
  const percent = (Math.min(current, 5) / 5) * 100;

  async function submitAnswer() {
    if (!courseId || current >= 5) return;
    const value = answers[current].trim();
    if (!value) return;
    setSubmitting(true);
    setError(null);
    try {
      await api<InterviewOut>(`/v1/courses/${courseId}/interview/answer`, {
        method: "POST",
        body: { position: current, answer: value },
      });
      setAnswered((prev) => [...prev, value]);
      if (current === 4) {
        router.push(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
      } else {
        setCurrent(current + 1);
        setAnswers((prev) => prev.map((a, i) => (i === current + 1 ? "" : a)));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setSubmitting(false);
    }
  }

  if (!courseId)
    return (
      <div style={{ maxWidth: 680, margin: "0 auto", paddingTop: 40, textAlign: "center" }}>
        <h1 className="section-title" style={{ marginBottom: 8 }}>
          Chưa chọn khóa học
        </h1>
        <p className="lede">Hãy bắt đầu từ trang tạo khóa học để có câu hỏi phỏng vấn.</p>
        <Button variant="secondary" onClick={() => router.push("/new")}>
          Về trang tạo khóa học
        </Button>
      </div>
    );
  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;
  if (redirecting) {
    return (
      <div style={{ maxWidth: 680, margin: "0 auto", paddingTop: 40, textAlign: "center" }}>
        <h1 className="eyebrow" style={{ margin: 0 }}>
          Phỏng vấn đã xong
        </h1>
        <p className="lede" style={{ marginTop: 8 }}>
          Đang mở kế hoạch học của bạn…
        </p>
      </div>
    );
  }

  if (interview.isError)
    return (
      <div>
        <div className="error-box" role="alert">
          Không tải được phỏng vấn: {interview.error.message}
        </div>
        <Button variant="secondary" onClick={() => interview.refetch()}>
          Thử lại
        </Button>
      </div>
    );

  return (
    <div style={{ maxWidth: 680, margin: "0 auto" }}>
      <div className="flow-header">
        <IconButton
          aria-label="Quay lại chủ đề"
          onClick={() => router.push("/new")}
        >
          <Icon name="arrowLeft" size={20} />
        </IconButton>
        <div style={{ flex: 1, textAlign: "center" }}>
          <h1 className="flow-header-title">Phỏng vấn ngắn</h1>
          <div className="flow-header-meta">Câu {current + 1}/5</div>
        </div>
        <span style={{ width: 40 }} aria-hidden="true" />
      </div>

      <ProgressBar percent={percent} label="Tiến độ trả lời" thin />

      <div className="transcript">
        {answered.map((answer, i) => (
          <div key={`a-${i}`} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div className="bubble bubble-question">
              <span className="bubble-label">Câu {i + 1}</span>
              {questions[i] ?? "…"}
            </div>
            <div className="bubble bubble-answer">
              <span className="bubble-label">Bạn</span>
              {answer}
            </div>
          </div>
        ))}

        {feedbackForCompleted(completedCount, questions, answered)}

        <div className="bubble bubble-question">
          <span className="bubble-label">Câu {current + 1}</span>
          {questions[current] ?? "Đang tải câu hỏi..."}
        </div>
      </div>

      {questions[current] && (
        <>
          <label htmlFor="interview-answer" className="sr-only">
            Câu trả lời
          </label>
          <textarea
            id="interview-answer"
            value={answers[current]}
            onChange={(e) =>
              setAnswers((prev) => prev.map((a, i) => (i === current ? e.target.value : a)))
            }
            placeholder="Câu trả lời của bạn..."
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                e.preventDefault();
                void submitAnswer();
              }
            }}
          />
          <p className="field-hint" style={{ margin: "8px 0 12px" }}>
            Ctrl+Enter để gửi
          </p>
        </>
      )}

      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      <Button
        size="lg"
        block
        onClick={() => void submitAnswer()}
        disabled={submitting || !answers[current]?.trim()}
      >
        {submitting
          ? "Đang gửi..."
          : current === 4
            ? "Gửi câu trả lời cuối"
            : "Câu tiếp theo"}
      </Button>
    </div>
  );
}

function feedbackForCompleted(
  completedCount: number,
  questions: string[],
  answered: string[]
) {
  if (!completedCount || answered.length >= completedCount) return null;
  const rows = [];
  for (let i = answered.length; i < Math.min(completedCount, 5); i++) {
    rows.push(
      <div key={`c-${i}`} className="bubble bubble-question">
        <span className="bubble-label">Câu {i + 1} · đã trả lời</span>
        {questions[i] ?? "…"}
      </div>
    );
  }
  return rows;
}

export default function InterviewPage() {
  return (
    <Suspense fallback={<p className="muted">Đang tải...</p>}>
      <InterviewInner />
    </Suspense>
  );
}
