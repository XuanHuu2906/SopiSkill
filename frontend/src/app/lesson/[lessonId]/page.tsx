"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { api, citationStatusLabel, newClientId, type Citation } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";

interface IdText {
  id: number;
  text: string;
}

// Public blocks từ server — KHÔNG có answer key.
type Block =
  | { type: "teach"; title: string; paragraphs: string[] }
  | { type: "mc"; question: string; options: string[] }
  | { type: "blank"; sentence: string }
  | { type: "order"; prompt: string; items: IdText[] }
  | { type: "match"; prompt: string; lefts: IdText[]; rights: IdText[] }
  | { type: "short"; question: string };

interface LessonOut {
  id: string;
  title: string;
  orderIndex: number;
  contentVersion: number;
  status: string;
  blocks: Block[];
  grounding: "source_grounded" | "general_ai_knowledge";
  citations: Citation[];
  evidenceNotice: string | null;
}

interface AttemptResult {
  index: number;
  type: string;
  correct: boolean;
  solution: Record<string, unknown>;
}

interface AttemptOut {
  attemptId: string;
  duplicate: boolean;
  score: { correct: number; total: number };
  rewards: { xp: number; xpEarned: number };
  results: AttemptResult[];
}

type AnswerValue = number | string | number[] | Record<string, number> | null;

function buildAnswers(
  blocks: Block[],
  state: {
    mc: Record<number, number>;
    blank: Record<number, string>;
    short: Record<number, string>;
    order: Record<number, number[]>;
    match: Record<number, Record<number, number>>;
  }
): { index: number; answer: AnswerValue }[] {
  const out: { index: number; answer: AnswerValue }[] = [];
  blocks.forEach((b, i) => {
    if (b.type === "teach") return;
    if (b.type === "mc") out.push({ index: i, answer: state.mc[i] ?? -1 });
    if (b.type === "blank") out.push({ index: i, answer: state.blank[i] ?? "" });
    if (b.type === "short") out.push({ index: i, answer: state.short[i] ?? "" });
    if (b.type === "order") out.push({ index: i, answer: state.order[i] ?? [] });
    if (b.type === "match") out.push({ index: i, answer: state.match[i] ?? {} });
  });
  return out;
}

export default function LessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const queryClient = useQueryClient();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const lessonKey = useSessionQueryKey("lesson", lessonId);

  const lesson = useQuery({
    queryKey: lessonKey,
    queryFn: () => api<LessonOut>(`/v1/lessons/${lessonId}`),
    enabled: !!lessonId && isAuthenticated,
  });

  const [mcAnswers, setMcAnswers] = useState<Record<number, number>>({});
  const [blankAnswers, setBlankAnswers] = useState<Record<number, string>>({});
  const [shortAnswers, setShortAnswers] = useState<Record<number, string>>({});
  // order: danh sách index trong public `items` theo thứ tự người học sắp.
  const [orderAnswers, setOrderAnswers] = useState<Record<number, number[]>>({});
  // match: leftId -> rightId (cả hai là id public).
  const [matchAnswers, setMatchAnswers] = useState<Record<number, Record<number, number>>>({});

  // clientAttemptId ổn định cho MỘT lần nộp: giữ nguyên qua retry mạng cùng nội dung,
  // chỉ tạo mới khi người học sửa câu trả lời hoặc nộp lần tiếp theo.
  const attemptKeyRef = useRef<{ fingerprint: string; id: string } | null>(null);

  const submitMutation = useMutation({
    mutationFn: async (payload: {
      clientAttemptId: string;
      contentVersion: number;
      answers: { index: number; answer: AnswerValue }[];
    }) => {
      return api<AttemptOut>(`/v1/lessons/${lessonId}/attempts`, {
        method: "POST",
        body: payload,
      });
    },
    onSuccess: () => {
      attemptKeyRef.current = null;
      // Progress/XP nằm ở course detail + auth me → invalidate để UI cập nhật.
      queryClient.invalidateQueries({ queryKey: ["session"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const result = submitMutation.data ?? null;
  const error = submitMutation.error ? submitMutation.error.message : null;

  const orderCandidates = useMemo(() => {
    const map: Record<number, IdText[]> = {};
    lesson.data?.blocks.forEach((b, i) => {
      if (b.type === "order") map[i] = b.items;
    });
    return map;
  }, [lesson.data]);

  function currentOrder(blockIndex: number): number[] {
    return orderAnswers[blockIndex] ?? orderCandidates[blockIndex]?.map((it) => it.id) ?? [];
  }

  function moveItem(blockIndex: number, from: number, dir: -1 | 1) {
    setOrderAnswers((prev) => {
      const current = prev[blockIndex] ?? orderCandidates[blockIndex]?.map((it) => it.id) ?? [];
      const to = from + dir;
      if (to < 0 || to >= current.length) return prev;
      const next = [...current];
      [next[from], next[to]] = [next[to], next[from]];
      return { ...prev, [blockIndex]: next };
    });
  }

  function submit() {
    if (!lesson.data) return;
    const answers = buildAnswers(lesson.data.blocks, {
      mc: mcAnswers,
      blank: blankAnswers,
      short: shortAnswers,
      order: orderAnswers,
      match: matchAnswers,
    });
    const fingerprint = JSON.stringify({
      lessonId,
      contentVersion: lesson.data.contentVersion,
      answers,
    });
    if (!attemptKeyRef.current || attemptKeyRef.current.fingerprint !== fingerprint) {
      attemptKeyRef.current = { fingerprint, id: newClientId("att") };
    }
    submitMutation.mutate({
      clientAttemptId: attemptKeyRef.current.id,
      contentVersion: lesson.data.contentVersion,
      answers,
    });
  }

  if (!lessonId) return <div className="container">Thiếu lessonId.</div>;
  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated) return <div className="container">Đang chuyển tới trang đăng nhập…</div>;
  if (lesson.isLoading) return <div className="container">Đang tải bài học…</div>;
  if (lesson.isError)
    return (
      <div className="container">
        <div className="error-box">Không tải được bài học: {lesson.error.message}</div>
        <button onClick={() => lesson.refetch()}>Thử lại</button>
      </div>
    );

  const submitted = !!result;

  return (
    <div className="container">
      <div className="topbar">
        <h1>{lesson.data?.title ?? "Bài học"}</h1>
        <Link href="/" className="link">
          ← Trang chủ
        </Link>
      </div>

      {lesson.data?.grounding === "general_ai_knowledge" && (
        <div className="notice-box">
          <span className="badge badge-muted">Chưa xác minh</span>
          {lesson.data.evidenceNotice ??
            "Bài học dựa trên kiến thức chung của AI, chưa có nguồn tài liệu được xác minh."}
        </div>
      )}

      {lesson.data && lesson.data.citations.length > 0 && (
        <div className="card source-card">
          <h2>Nguồn của bài học</h2>
          <ul className="source-list">
            {lesson.data.citations.map((citation) => (
              <li key={citation.citationId}>
                {citation.sourceUrl ? (
                  <a
                    className="link"
                    href={citation.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer nofollow"
                  >
                    {citation.sourceTitle ?? citation.sourceUrl}
                  </a>
                ) : (
                  <strong>{citation.sourceTitle ?? "Nguồn không có URL"}</strong>
                )}
                {citation.sourceVersion && (
                  <span className="muted"> · version {citation.sourceVersion}</span>
                )}
                {citation.pageNumber != null && (
                  <span className="muted"> · trang {citation.pageNumber}</span>
                )}
                <span className="badge badge-muted">{citationStatusLabel(citation.validationStatus)}</span>
                {citation.evidenceText && (
                  <blockquote className="evidence-quote">{citation.evidenceText}</blockquote>
                )}
              </li>
            ))}
          </ul>
          <p className="muted">
            Trạng thái citation phản ánh mức kiểm tra vị trí/bằng chứng, không phải kết luận nội
            dung bài học luôn đúng.
          </p>
        </div>
      )}

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
                  disabled={submitted}
                >
                  {opt}
                </button>
              ))}
              {result && <ResultLine result={result} index={i} />}
            </>
          )}

          {b.type === "blank" && (
            <>
              <h3>Điền vào chỗ trống</h3>
              <p>{b.sentence}</p>
              <input
                type="text"
                value={blankAnswers[i] ?? ""}
                onChange={(e) => setBlankAnswers((p) => ({ ...p, [i]: e.target.value }))}
                disabled={submitted}
              />
              {result && <ResultLine result={result} index={i} />}
            </>
          )}

          {b.type === "order" && (
            <>
              <h3>{b.prompt}</h3>
              {currentOrder(i).map((itemId, j, arr) => {
                const text = b.items.find((it) => it.id === itemId)?.text ?? "";
                return (
                  <div className="order-item" key={itemId}>
                    <span style={{ flex: 1 }}>
                      {j + 1}. {text}
                    </span>
                    {!submitted && (
                      <>
                        <button
                          style={{ padding: "4px 10px" }}
                          aria-label={`Đưa "${text}" lên`}
                          onClick={() => moveItem(i, j, -1)}
                          disabled={j === 0}
                        >
                          ↑
                        </button>
                        <button
                          style={{ padding: "4px 10px" }}
                          aria-label={`Đưa "${text}" xuống`}
                          onClick={() => moveItem(i, j, 1)}
                          disabled={j === arr.length - 1}
                        >
                          ↓
                        </button>
                      </>
                    )}
                  </div>
                );
              })}
              {result && <ResultLine result={result} index={i} />}
            </>
          )}

          {b.type === "match" && (
            <>
              <h3>{b.prompt}</h3>
              {b.lefts.map((left) => (
                <div className="match-row" key={left.id}>
                  <span style={{ flex: 1, alignSelf: "center" }}>{left.text}</span>
                  <select
                    value={matchAnswers[i]?.[left.id] ?? ""}
                    onChange={(e) =>
                      setMatchAnswers((p) => ({
                        ...p,
                        [i]: { ...p[i], [left.id]: Number(e.target.value) },
                      }))
                    }
                    disabled={submitted}
                    aria-label={`Ghép cho ${left.text}`}
                  >
                    <option value="">-- chọn --</option>
                    {b.rights.map((right) => (
                      <option key={right.id} value={right.id}>
                        {right.text}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
              {result && <ResultLine result={result} index={i} />}
            </>
          )}

          {b.type === "short" && (
            <>
              <h3>{b.question}</h3>
              <input
                type="text"
                value={shortAnswers[i] ?? ""}
                onChange={(e) => setShortAnswers((p) => ({ ...p, [i]: e.target.value }))}
                disabled={submitted}
              />
              {result && <ResultLine result={result} index={i} />}
            </>
          )}
        </div>
      ))}

      {error && <div className="error-box">{error}</div>}

      {!submitted && lesson.data && (
        <button onClick={submit} disabled={submitMutation.isPending}>
          {submitMutation.isPending ? "Đang nộp..." : "Nộp bài"}
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
            {result.rewards.xpEarned === 0 && !result.duplicate &&
              " — bài này đã được cộng XP tối đa, nộp lại không cộng thêm"}
          </p>
        </div>
      )}
    </div>
  );
}

function ResultLine({ result, index }: { result: AttemptOut; index: number }) {
  const r = result.results.find((x) => x.index === index);
  if (!r) return null;
  return <p>{r.correct ? "✓ Đúng" : "✗ Sai"}</p>;
}
