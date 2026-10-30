"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";

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

  const interview = useQuery({
    queryKey: interviewKey,
    queryFn: () => api<InterviewOut>(`/v1/courses/${courseId}/interview`),
    enabled: !!courseId && isAuthenticated,
  });

  // Đồng bộ trạng thái local với server (reload không mất câu đã trả lời)
  // Reload: server chỉ trả `completedCount` (không trả nội dung câu trả lời để
  // tránh lộ dữ liệu cũ trên máy khác). Đưa người dùng về đúng câu kế tiếp và
  // đánh dấu các câu trước là "đã trả lời" thay vì hiển thị ô trống gây hiểu nhầm.
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
        // Đã trả lời đủ 5 câu → không cho nộp lại, đi thẳng tới proposal.
        router.replace(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
        return;
      }
      setCurrent(done);
      // Xoá giá trị placeholder ở câu kế tiếp để người học nhập câu trả lời thật.
      setAnswers((prev) => prev.map((a, i) => (i === done ? "" : a)));
    }
  }, [interview.data, courseId, router]);

  const questions = interview.data?.questions ?? [];

  async function submitAnswer() {
    if (!courseId || current >= 5) return;
    setSubmitting(true);
    setError(null);
    try {
      await api<InterviewOut>(`/v1/courses/${courseId}/interview/answer`, {
        method: "POST",
        body: { position: current, answer: answers[current].trim() },
      });
      if (current === 4) {
        router.push(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
      } else {
        setCurrent(current + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setSubmitting(false);
    }
  }

  if (!courseId) return <div className="container">Thiếu courseId.</div>;
  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated) return <div className="container">Đang chuyển tới trang đăng nhập…</div>;
  if (interview.isError)
    return (
      <div className="container">
        <div className="error-box">Không tải được phỏng vấn: {interview.error.message}</div>
        <button onClick={() => interview.refetch()}>Thử lại</button>
      </div>
    );

  return (
    <div className="container">
      <h1>Phỏng vấn ({current + 1}/5)</h1>
      <div className="card">
        {questions[current] ? (
          <>
            <p style={{ fontWeight: 600 }}>{questions[current]}</p>
            <label htmlFor="interview-answer" className="sr-only">
              Câu trả lời
            </label>
            <textarea
              id="interview-answer"
              value={answers[current]}
              onChange={(e) =>
                setAnswers((prev) =>
                  prev.map((a, i) => (i === current ? e.target.value : a))
                )
              }
              placeholder="Câu trả lời của bạn..."
            />
            {error && (
              <div className="error-box" role="alert">
                {error}
              </div>
            )}
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                onClick={submitAnswer}
                disabled={submitting || !answers[current].trim()}
              >
                {current === 4 ? "Gửi câu trả lời cuối" : "Câu tiếp theo"}
              </button>
            </div>
          </>
        ) : (
          <p>Đang tải câu hỏi...</p>
        )}
      </div>
    </div>
  );
}

export default function InterviewPage() {
  return (
    <Suspense fallback={<div className="container">Đang tải...</div>}>
      <InterviewInner />
    </Suspense>
  );
}
