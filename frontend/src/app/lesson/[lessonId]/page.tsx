"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { api, newClientId } from "@/lib/api";

interface LessonOut {
  id: string;
  title: string;
  orderIndex: number;
  contentVersion: number;
  status: string;
  blocks: Block[];
}

type Block =
  | { type: "teach"; title: string; paragraphs: string[] }
  | { type: "mc"; question: string; options: string[]; answerIndex: number }
  | { type: "blank"; sentence: string; answer: string }
  | { type: "order"; prompt: string; items: string[] }
  | { type: "match"; prompt: string; pairs: [string, string][] }
  | { type: "short"; question: string; acceptedAnswers: string[] };

interface AttemptOut {
  attemptId: string;
  duplicate: boolean;
  score: { correct: number; total: number };
  rewards: { xp: number; xpEarned: number };
  results: { index: number; type: string; correct: boolean }[];
}

export default function LessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>();

  const lesson = useQuery({
    queryKey: ["lesson", lessonId],
    queryFn: () => api<LessonOut>(`/v1/lessons/${lessonId}`),
    enabled: !!lessonId,
  });

  const [mcAnswers, setMcAnswers] = useState<Record<number, number>>({});
  const [blankAnswers, setBlankAnswers] = useState<Record<number, string>>({});
  const [shortAnswers, setShortAnswers] = useState<Record<number, string>>({});
  const [orderAnswers, setOrderAnswers] = useState<Record<number, string[]>>({});
  const [matchAnswers, setMatchAnswers] = useState<Record<number, Record<string, string>>>({});
  const [result, setResult] = useState<AttemptOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Shuffle order items một lần per lesson (client-side hiển thị)
  const shuffledOrders = useMemo(() => {
    const map: Record<number, string[]> = {};
    lesson.data?.blocks.forEach((b, i) => {
      if (b.type === "order") {
        map[i] = [...b.items].sort(() => Math.random() - 0.5);
      }
    });
    return map;
  }, [lesson.data]);

  function moveItem(blockIndex: number, from: number, dir: -1 | 1) {
    setOrderAnswers((prev) => {
      const current =
        prev[blockIndex] ?? shuffledOrders[blockIndex] ?? [];
      const next = [...current];
      const to = from + dir;
      if (to < 0 || to >= next.length) return prev;
      [next[from], next[to]] = [next[to], next[from]];
      return { ...prev, [blockIndex]: next };
    });
  }

  async function submit() {
    if (!lesson.data) return;
    setSubmitting(true);
    setError(null);
    const answers: { index: number; answer: unknown }[] = [];
    lesson.data.blocks.forEach((b, i) => {
      if (b.type === "teach") return;
      if (b.type === "mc") answers.push({ index: i, answer: mcAnswers[i] ?? -1 });
      if (b.type === "blank") answers.push({ index: i, answer: blankAnswers[i] ?? "" });
      if (b.type === "short") answers.push({ index: i, answer: shortAnswers[i] ?? "" });
      if (b.type === "order")
        answers.push({
          index: i,
          answer:
            orderAnswers[i] ?? shuffledOrders[i] ?? [],
        });
      if (b.type === "match")
        answers.push({ index: i, answer: matchAnswers[i] ?? {} });
    });

    try {
      const attempt = await api<AttemptOut>(`/v1/lessons/${lessonId}/attempts`, {
        method: "POST",
        body: {
          clientAttemptId: newClientId("att"),
          contentVersion: lesson.data.contentVersion,
          answers,
        },
      });
      setResult(attempt);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lỗi không xác định");
    } finally {
      setSubmitting(false);
    }
  }

  if (!lessonId) return <div className="container">Thiếu lessonId.</div>;

  return (
    <div className="container">
      <div className="topbar">
        <h1>{lesson.data?.title ?? "Bài học"}</h1>
        <Link href="/" className="link">
          ← Trang chủ
        </Link>
      </div>

      {lesson.data?.blocks.map((b, i) => (
        <div className="card lesson-block" key={i}>
          {b.type === "teach" && (
            <>
              <h2>{b.title}</h2>
              {b.paragraphs.map((p, j) => (
                <p key={j}>{p}</p>
              ))}
            </>
          )}

          {b.type === "mc" && (
            <>
              <h3>{b.question}</h3>
              {b.options.map((opt, j) => (
                <button
                  key={j}
                  className={`quiz-option ${mcAnswers[i] === j ? "selected" : ""}`}
                  onClick={() => setMcAnswers((p) => ({ ...p, [i]: j }))}
                  disabled={!!result}
                >
                  {opt}
                </button>
              ))}
              {result && (
                <p>
                  {result.results.find((r) => r.index === i)?.correct
                    ? "✓ Đúng"
                    : "✗ Sai"}
                </p>
              )}
            </>
          )}

          {b.type === "blank" && (
            <>
              <h3>Điền vào chỗ trống</h3>
              <p>{b.sentence}</p>
              <input
                type="text"
                value={blankAnswers[i] ?? ""}
                onChange={(e) =>
                  setBlankAnswers((p) => ({ ...p, [i]: e.target.value }))
                }
                disabled={!!result}
              />
              {result && (
                <p>
                  {result.results.find((r) => r.index === i)?.correct
                    ? "✓ Đúng"
                    : `✗ Sai — đáp án: ${b.answer}`}
                </p>
              )}
            </>
          )}

          {b.type === "order" && (
            <>
              <h3>{b.prompt}</h3>
              {(orderAnswers[i] ?? shuffledOrders[i] ?? []).map((item, j, arr) => (
                <div className="order-item" key={item}>
                  <span style={{ flex: 1 }}>
                    {j + 1}. {item}
                  </span>
                  {!result && (
                    <>
                      <button
                        style={{ padding: "4px 10px" }}
                        onClick={() => moveItem(i, j, -1)}
                        disabled={j === 0}
                      >
                        ↑
                      </button>
                      <button
                        style={{ padding: "4px 10px" }}
                        onClick={() => moveItem(i, j, 1)}
                        disabled={j === arr.length - 1}
                      >
                        ↓
                      </button>
                    </>
                  )}
                </div>
              ))}
              {result && (
                <p>
                  {result.results.find((r) => r.index === i)?.correct
                    ? "✓ Đúng"
                    : "✗ Sai"}
                </p>
              )}
            </>
          )}

          {b.type === "match" && (
            <>
              <h3>{b.prompt}</h3>
              {b.pairs.map(([left]) => (
                <div className="match-row" key={left}>
                  <span style={{ flex: 1, alignSelf: "center" }}>{left}</span>
                  <select
                    value={matchAnswers[i]?.[left] ?? ""}
                    onChange={(e) =>
                      setMatchAnswers((p) => ({
                        ...p,
                        [i]: { ...p[i], [left]: e.target.value },
                      }))
                    }
                    disabled={!!result}
                  >
                    <option value="">-- chọn --</option>
                    {b.pairs.map(([, right]) => (
                      <option key={right} value={right}>
                        {right}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              {result && (
                <p>
                  {result.results.find((r) => r.index === i)?.correct
                    ? "✓ Đúng"
                    : `✗ Sai — đáp án: ${b.pairs
                        .map(([l, r]) => `${l}→${r}`)
                        .join(", ")}`}
                </p>
              )}
            </>
          )}

          {b.type === "short" && (
            <>
              <h3>{b.question}</h3>
              <input
                type="text"
                value={shortAnswers[i] ?? ""}
                onChange={(e) =>
                  setShortAnswers((p) => ({ ...p, [i]: e.target.value }))
                }
                disabled={!!result}
              />
              {result && (
                <p>
                  {result.results.find((r) => r.index === i)?.correct
                    ? "✓ Đúng"
                    : "✗ Sai"}
                </p>
              )}
            </>
          )}
        </div>
      ))}

      {error && <div className="error-box">{error}</div>}

      {!result && lesson.data && (
        <button onClick={submit} disabled={submitting}>
          {submitting ? "Đang nộp..." : "Nộp bài"}
        </button>
      )}

      {result && (
        <div className={result.score.correct === result.score.total ? "success-box" : "card"}>
          <h2>
            Kết quả: {result.score.correct}/{result.score.total}
            {result.duplicate && " (kết quả lần nộp trước — idempotent)"}
          </h2>
          <p>
            XP: +{result.rewards.xpEarned} (tổng {result.rewards.xp})
          </p>
        </div>
      )}
    </div>
  );
}
