"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";

interface InterviewOut {
  questions: string[];
  completedCount: number;
}

function InterviewInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";

  const [answers, setAnswers] = useState<string[]>(["", "", "", "", ""]);
  const [current, setCurrent] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const interview = useQuery({
    queryKey: ["interview", courseId],
    queryFn: () => api<InterviewOut>(`/v1/courses/${courseId}/interview`),
    enabled: !!courseId,
  });

  // Đồng bộ trạng thái local với server (reload không mất câu đã trả lời)
  useEffect(() => {
    if (interview.data) {
      setAnswers((prev) => {
        const merged = [...prev];
        for (let i = 0; i < interview.data!.completedCount; i++) {
          if (!merged[i]) merged[i] = " ";
        }
        return merged;
      });
      setCurrent(interview.data.completedCount);
    }
  }, [interview.data]);

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

  return (
    <div className="container">
      <h1>Phỏng vấn ({current + 1}/5)</h1>
      <div className="card">
        {questions[current] ? (
          <>
            <p style={{ fontWeight: 600 }}>{questions[current]}</p>
            <textarea
              value={answers[current]}
              onChange={(e) =>
                setAnswers((prev) =>
                  prev.map((a, i) => (i === current ? e.target.value : a))
                )
              }
              placeholder="Câu trả lời của bạn..."
            />
            {error && <div className="error-box">{error}</div>}
            <div style={{ marginTop: 12 }}>
              <button
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
