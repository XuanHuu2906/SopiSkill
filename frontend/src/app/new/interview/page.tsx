"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Button, IconButton } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";

interface StructuredQuestion {
  index: number;
  prompt: string;
  kind: "single" | "multi" | "freeform";
  choices: string[];
}

interface InterviewOut {
  questions: string[];
  structuredQuestions?: StructuredQuestion[];
  answers?: string[];
  completedCount: number;
}

const TOTAL_QUESTIONS = 5;

function hydrateSelections(
  savedAnswers: string[],
  structuredQuestions: StructuredQuestion[]
): {
  selectedChoices: string[][];
  otherActive: boolean[];
  otherDrafts: string[];
} {
  const selectedChoices: string[][] = Array.from({ length: TOTAL_QUESTIONS }, () => []);
  const otherActive: boolean[] = Array(TOTAL_QUESTIONS).fill(false);
  const otherDrafts: string[] = Array(TOTAL_QUESTIONS).fill("");

  for (let i = 0; i < TOTAL_QUESTIONS; i++) {
    const raw = (savedAnswers[i] ?? "").trim();
    if (!raw) continue;
    const sq = structuredQuestions[i];
    const choices = sq?.choices ?? [];
    const kind = sq?.kind ?? "freeform";

    if (choices.length === 0 || kind === "freeform") {
      otherActive[i] = true;
      otherDrafts[i] = raw;
      continue;
    }

    if (kind === "single") {
      if (choices.includes(raw)) {
        selectedChoices[i] = [raw];
      } else {
        otherActive[i] = true;
        otherDrafts[i] = raw;
      }
      continue;
    }

    const parts = raw
      .split(",")
      .map((p) => p.trim())
      .filter(Boolean);
    const matched: string[] = [];
    const remainder: string[] = [];
    for (const part of parts) {
      if (choices.includes(part) && !matched.includes(part)) {
        matched.push(part);
      } else {
        remainder.push(part);
      }
    }
    selectedChoices[i] = matched;
    if (remainder.length > 0) {
      otherActive[i] = true;
      otherDrafts[i] = remainder.join(", ");
    }
  }

  return { selectedChoices, otherActive, otherDrafts };
}

function composeAnswer(
  index: number,
  structuredQuestions: StructuredQuestion[],
  selectedChoices: string[][],
  otherActive: boolean[],
  otherDrafts: string[]
): string {
  const sq = structuredQuestions[index];
  const choices = sq?.choices ?? [];
  const kind = sq?.kind ?? "freeform";
  const custom = (otherDrafts[index] ?? "").trim();

  if (choices.length === 0 || kind === "freeform") {
    return custom;
  }
  if (kind === "multi") {
    const parts = [...(selectedChoices[index] ?? [])];
    if (otherActive[index] && custom) {
      parts.push(custom);
    }
    return parts.join(", ");
  }
  if (otherActive[index]) {
    return custom;
  }
  return selectedChoices[index]?.[0] ?? "";
}

function InterviewInner() {
  const router = useRouter();
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? "";
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const queryClient = useQueryClient();
  const interviewKey = useSessionQueryKey("interview", courseId);

  const [selectedChoices, setSelectedChoices] = useState<string[][]>(
    Array.from({ length: TOTAL_QUESTIONS }, () => [])
  );
  const [otherActive, setOtherActive] = useState<boolean[]>(Array(TOTAL_QUESTIONS).fill(false));
  const [otherDrafts, setOtherDrafts] = useState<string[]>(Array(TOTAL_QUESTIONS).fill(""));
  const [current, setCurrent] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hydratedCourse, setHydratedCourse] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const interview = useQuery({
    queryKey: interviewKey,
    queryFn: () => api<InterviewOut>(`/v1/courses/${courseId}/interview`),
    enabled: !!courseId && isAuthenticated,
  });

  useEffect(() => {
    if (!interview.data) return;
    const done = Math.min(interview.data.completedCount, TOTAL_QUESTIONS);
    if (done >= TOTAL_QUESTIONS) {
      router.replace(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
      return;
    }
    if (hydratedCourse !== courseId) {
      const sqs = interview.data.structuredQuestions ?? [];
      const saved = interview.data.answers ?? [];
      const hydrated = hydrateSelections(saved, sqs);
      setSelectedChoices(hydrated.selectedChoices);
      setOtherActive(hydrated.otherActive);
      setOtherDrafts(hydrated.otherDrafts);
      setCurrent(done);
      setHydratedCourse(courseId);
    }
  }, [interview.data, courseId, hydratedCourse, router]);

  const questions = interview.data?.questions ?? [];
  const structuredQuestions = interview.data?.structuredQuestions ?? [];
  const serverAnswers = interview.data?.answers ?? [];
  const currentStructured = structuredQuestions[current] ?? null;
  const currentChoices = currentStructured?.choices ?? [];
  const currentKind = currentStructured?.kind ?? "freeform";
  const completedCount = Math.min(interview.data?.completedCount ?? 0, TOTAL_QUESTIONS);
  const redirecting = completedCount >= TOTAL_QUESTIONS;
  const percent = (Math.min(current, TOTAL_QUESTIONS) / TOTAL_QUESTIONS) * 100;

  const isOtherOpen = currentChoices.length === 0 || otherActive[current];
  const currentComposedValue = composeAnswer(
    current,
    structuredQuestions,
    selectedChoices,
    otherActive,
    otherDrafts
  );

  function selectPresetChoice(choice: string) {
    setSelectedChoices((prev) =>
      prev.map((items, idx) => {
        if (idx !== current) return items;
        if (currentKind === "multi") {
          return items.includes(choice)
            ? items.filter((item) => item !== choice)
            : [...items, choice];
        }
        return [choice];
      })
    );
    if (currentKind !== "multi") {
      setOtherActive((prev) => prev.map((v, idx) => (idx === current ? false : v)));
    }
  }

  function toggleOtherChoice() {
    const nextOpen = !otherActive[current];
    if (currentKind !== "multi") {
      setSelectedChoices((prev) => prev.map((items, idx) => (idx === current ? [] : items)));
      setOtherActive((prev) => prev.map((v, idx) => (idx === current ? true : v)));
    } else {
      setOtherActive((prev) => prev.map((v, idx) => (idx === current ? nextOpen : v)));
    }
    if (nextOpen || currentKind !== "multi") {
      setTimeout(() => textareaRef.current?.focus(), 0);
    }
  }

  function jumpToQuestion(targetIndex: number) {
    setError(null);
    setCurrent(Math.max(0, Math.min(targetIndex, TOTAL_QUESTIONS - 1)));
  }

  async function submitAnswer() {
    if (!courseId || current >= TOTAL_QUESTIONS) return;
    const value = currentComposedValue.trim();
    if (!value) return;
    setSubmitting(true);
    setError(null);
    try {
      const updated = await api<InterviewOut>(`/v1/courses/${courseId}/interview/answer`, {
        method: "POST",
        body: { position: current, answer: value },
      });
      queryClient.setQueryData(interviewKey, updated);
      const nextDone = Math.min(updated.completedCount, TOTAL_QUESTIONS);
      if (nextDone >= TOTAL_QUESTIONS) {
        router.push(`/new/proposal?courseId=${encodeURIComponent(courseId)}`);
      } else {
        setCurrent(Math.min(Math.max(current + 1, nextDone), TOTAL_QUESTIONS - 1));
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
        {Array.from({ length: current }, (_, i) => {
          const savedText = (serverAnswers[i] ?? "").trim() || composeAnswer(
            i,
            structuredQuestions,
            selectedChoices,
            otherActive,
            otherDrafts
          );
          if (!questions[i]) return null;
          return (
            <div key={`prev-${i}`} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div className="bubble bubble-question">
                <span className="bubble-label">Câu {i + 1}</span>
                {questions[i]}
              </div>
              <div className="bubble bubble-answer">
                <div className="interview-answer-meta">
                  <span className="bubble-label">Bạn</span>
                  <button
                    type="button"
                    className="interview-edit-btn"
                    disabled={submitting}
                    onClick={() => jumpToQuestion(i)}
                  >
                    Sửa
                  </button>
                </div>
                {savedText || "✓ đã trả lời"}
              </div>
            </div>
          );
        })}

        <div className="bubble bubble-question">
          <span className="bubble-label">Câu {current + 1}</span>
          {questions[current] ?? "Đang tải câu hỏi..."}
        </div>
      </div>

      {questions[current] && (
        <>
          {currentChoices.length > 0 && (
            <>
              <p className="interview-kind-hint">
                {currentKind === "multi"
                  ? "Có thể chọn nhiều phương án phù hợp với bạn:"
                  : "Chọn một phương án phù hợp nhất:"}
              </p>
              <div
                className="interview-choices"
                role="group"
                aria-label={currentKind === "multi" ? "Chọn nhiều phương án" : "Chọn phương án"}
              >
                {currentChoices.map((choice) => {
                  const selected = (selectedChoices[current] ?? []).includes(choice);
                  return (
                    <button
                      key={choice}
                      type="button"
                      className={`interview-choice quick-chip${selected ? " is-selected" : ""}`}
                      aria-pressed={selected}
                      disabled={submitting}
                      onClick={() => selectPresetChoice(choice)}
                    >
                      <span
                        className={`interview-choice-indicator ${
                          currentKind === "multi" ? "is-multi" : "is-single"
                        }`}
                        aria-hidden="true"
                      >
                        {selected &&
                          (currentKind === "multi" ? (
                            "✓"
                          ) : (
                            <span className="interview-choice-dot" />
                          ))}
                      </span>
                      <span>{choice}</span>
                    </button>
                  );
                })}

                <button
                  type="button"
                  className={`interview-choice interview-choice-other${
                    otherActive[current] ? " is-selected" : ""
                  }`}
                  aria-pressed={otherActive[current]}
                  disabled={submitting}
                  onClick={toggleOtherChoice}
                >
                  <span
                    className={`interview-choice-indicator ${
                      currentKind === "multi" ? "is-multi" : "is-single"
                    }`}
                    aria-hidden="true"
                  >
                    {otherActive[current] &&
                      (currentKind === "multi" ? (
                        "✓"
                      ) : (
                        <span className="interview-choice-dot" />
                      ))}
                  </span>
                  <span>Khác (tự nhập)</span>
                </button>
              </div>
            </>
          )}

          {isOtherOpen && (
            <>
              <div className="interview-composer">
                <label htmlFor="interview-answer" className="sr-only">
                  Câu trả lời của bạn
                </label>
                <textarea
                  ref={textareaRef}
                  id="interview-answer"
                  rows={2}
                  value={otherDrafts[current]}
                  onChange={(e) =>
                    setOtherDrafts((prev) =>
                      prev.map((val, idx) => (idx === current ? e.target.value : val))
                    )
                  }
                  placeholder="Nhập câu trả lời riêng của bạn..."
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                      e.preventDefault();
                      void submitAnswer();
                    }
                  }}
                />
              </div>
              <p className="field-hint" style={{ margin: "8px 0 12px" }}>
                Ctrl+Enter để gửi nhanh
              </p>
            </>
          )}
        </>
      )}

      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      <div className="interview-actions">
        {current > 0 && (
          <Button
            variant="secondary"
            size="lg"
            disabled={submitting}
            onClick={() => jumpToQuestion(current - 1)}
          >
            Câu trước
          </Button>
        )}
        <Button
          size="lg"
          block
          onClick={() => void submitAnswer()}
          disabled={submitting || !currentComposedValue.trim()}
        >
          {submitting
            ? "Đang gửi..."
            : current === TOTAL_QUESTIONS - 1
              ? "Gửi câu trả lời cuối"
              : "Câu tiếp theo"}
        </Button>
      </div>
    </div>
  );
}

export default function InterviewPage() {
  return (
    <Suspense fallback={<p className="muted">Đang tải...</p>}>
      <InterviewInner />
    </Suspense>
  );
}
