"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, citationStatusLabel, newClientId, type Citation } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, ButtonLink, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";
import useMediaQuery from "@/components/ui/useMediaQuery";
import TutorPanel from "./TutorPanel";

interface IdText {
  id: number;
  text: string;
}

type Block =
  | { type: "teach"; title: string; paragraphs: string[] }
  | { type: "mc"; question: string; options: string[] }
  | { type: "blank"; sentence: string }
  | { type: "order"; prompt: string; items: IdText[] }
  | { type: "match"; prompt: string; lefts: IdText[]; rights: IdText[] }
  | { type: "short"; question: string };

interface LessonOut {
  id: string;
  courseId?: string | null;
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
  reviewCardCreated?: boolean;
}

type AnswerValue = number | string | number[] | Record<string, number> | null;

interface AnswerState {
  mc: Record<number, number>;
  blank: Record<number, string>;
  short: Record<number, string>;
  order: Record<number, number[]>;
  match: Record<number, Record<number, number>>;
}

const BLOCK_EYEBROW: Record<Block["type"], string> = {
  teach: "Bài giảng",
  mc: "Chọn đáp án",
  blank: "Điền chỗ trống",
  order: "Sắp xếp",
  match: "Ghép cặp",
  short: "Trả lời ngắn",
};

const BLOCK_LABELS: Record<Block["type"], string> = {
  teach: "Bài giảng",
  mc: "Trắc nghiệm",
  blank: "Điền chỗ trống",
  order: "Sắp xếp",
  match: "Ghép cặp",
  short: "Trả lời ngắn",
};

const LETTERS = ["A", "B", "C", "D", "E", "F"];

/* The order block renders the server's shuffled sequence immediately, so that
   displayed order *is* the current answer until the learner moves an item.
   Reading only `state.order` would show a valid sequence while submitting `[]`. */
function orderAnswer(
  index: number,
  state: AnswerState,
  defaults: Record<number, IdText[]>,
): number[] {
  return state.order[index] ?? defaults[index]?.map((it) => it.id) ?? [];
}

function buildAnswers(
  blocks: Block[],
  state: AnswerState,
  defaults: Record<number, IdText[]>,
): { index: number; answer: AnswerValue }[] {
  const out: { index: number; answer: AnswerValue }[] = [];
  blocks.forEach((b, i) => {
    if (b.type === "teach") return;
    if (b.type === "mc") out.push({ index: i, answer: state.mc[i] ?? -1 });
    if (b.type === "blank") out.push({ index: i, answer: state.blank[i] ?? "" });
    if (b.type === "short") out.push({ index: i, answer: state.short[i] ?? "" });
    if (b.type === "order") out.push({ index: i, answer: orderAnswer(i, state, defaults) });
    if (b.type === "match") out.push({ index: i, answer: state.match[i] ?? {} });
  });
  return out;
}

/* Match is graded all-or-nothing on the server (every left must be paired), so
   the step is only "answered" once every row has a selection. */
function isAnswered(
  block: Block,
  index: number,
  state: AnswerState,
  defaults: Record<number, IdText[]>,
): boolean {
  switch (block.type) {
    case "teach":
      return false;
    case "mc":
      return state.mc[index] !== undefined;
    case "blank":
      return Boolean(state.blank[index]?.trim());
    case "short":
      return Boolean(state.short[index]?.trim());
    case "order":
      return orderAnswer(index, state, defaults).length > 0;
    case "match":
      return (
        Object.keys(state.match[index] ?? {}).length === block.lefts.length &&
        block.lefts.length > 0
      );
  }
}

function blockPrompt(block: Block): string {
  switch (block.type) {
    case "teach":
      return block.title;
    case "mc":
    case "short":
      return block.question;
    case "blank":
      return block.sentence;
    case "order":
    case "match":
      return block.prompt;
  }
}

/* Post-submit only: the backend returns `solution` next to each graded result. */
function solutionText(block: Block, solution: Record<string, unknown>): string | null {
  switch (block.type) {
    case "mc": {
      const text = solution.answerText;
      if (typeof text !== "string" || !text) return null;
      const idx = solution.answerIndex;
      return typeof idx === "number" ? `${LETTERS[idx] ?? idx + 1}. ${text}` : text;
    }
    case "blank":
      return typeof solution.answer === "string" ? solution.answer : null;
    case "short": {
      const accepted = solution.acceptedAnswers;
      if (!Array.isArray(accepted)) return null;
      const labels = accepted.filter((v): v is string => typeof v === "string" && v.length > 0);
      return labels.length > 0 ? labels.join(" · ") : null;
    }
    case "order": {
      const ids = solution.order;
      if (!Array.isArray(ids)) return null;
      return ids
        .map((id) => block.items.find((it) => it.id === id)?.text ?? String(id))
        .join(" → ");
    }
    case "match": {
      const pairs = solution.pairs;
      if (!Array.isArray(pairs)) return null;
      const out = pairs
        .map((pair) => {
          if (!Array.isArray(pair) || pair.length < 2) return "";
          const left = block.lefts.find((it) => it.id === Number(pair[0]))?.text ?? String(pair[0]);
          const right = block.rights.find((it) => it.id === Number(pair[1]))?.text ?? String(pair[1]);
          return `${left} → ${right}`;
        })
        .filter(Boolean);
      return out.length > 0 ? out.join(" · ") : null;
    }
    default:
      return null;
  }
}

export default function LessonPage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const router = useRouter();
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
  const [orderAnswers, setOrderAnswers] = useState<Record<number, number[]>>({});
  const [matchAnswers, setMatchAnswers] = useState<Record<number, Record<number, number>>>({});
  const [step, setStep] = useState(0);
  const [tutorOpen, setTutorOpen] = useState(false);
  const [outlineOpen, setOutlineOpen] = useState(false);
  // The reference docks the tutor rail beside the lesson rather than covering
  // it, which needs room for both a 720 px column and a 400 px rail.
  const canDock = useMediaQuery("(min-width: 1024px)");
  const tutorDocked = tutorOpen && canDock;

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

  const blocks: Block[] = lesson.data?.blocks ?? [];
  const gradableIndices = blocks
    .map((b, i) => (b.type === "teach" ? -1 : i))
    .filter((i) => i >= 0);
  const gradableCount = gradableIndices.length;
  const lastGradableIndex = gradableIndices.length > 0 ? gradableIndices[gradableIndices.length - 1] : -1;

  const safeStep = blocks.length > 0 ? Math.min(step, blocks.length - 1) : 0;
  const current: Block | undefined = blocks[safeStep];

  const answerState: AnswerState = {
    mc: mcAnswers,
    blank: blankAnswers,
    short: shortAnswers,
    order: orderAnswers,
    match: matchAnswers,
  };
  const answeredCount = blocks.filter((b, i) => isAnswered(b, i, answerState, orderCandidates)).length;
  const submitted = !!result;
  const percent = submitted
    ? 100
    : gradableCount > 0
      ? Math.round((answeredCount / gradableCount) * 100)
      : 0;

  function currentOrder(blockIndex: number): number[] {
    return orderAnswer(blockIndex, answerState, orderCandidates);
  }

  function moveItem(blockIndex: number, from: number, dir: -1 | 1) {
    setOrderAnswers((prev) => {
      const currentIds = orderAnswer(blockIndex, { ...answerState, order: prev }, orderCandidates);
      const to = from + dir;
      if (to < 0 || to >= currentIds.length) return prev;
      const next = [...currentIds];
      [next[from], next[to]] = [next[to], next[from]];
      return { ...prev, [blockIndex]: next };
    });
  }

  function submit() {
    if (!lesson.data) return;
    const answers = buildAnswers(
      lesson.data.blocks,
      { mc: mcAnswers, blank: blankAnswers, short: shortAnswers, order: orderAnswers, match: matchAnswers },
      orderCandidates,
    );
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

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [step]);

  if (!lessonId) return <p className="muted">Thiếu lessonId.</p>;
  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;
  if (lesson.isLoading) return <p className="muted">Đang tải bài học…</p>;
  if (lesson.isError)
    return (
      <div>
        <div className="error-box" role="alert">
          Không tải được bài học: {lesson.error.message}
        </div>
        <Button variant="secondary" onClick={() => lesson.refetch()}>
          Thử lại
        </Button>
      </div>
    );
  if (!lesson.data) return null;

  const backHref = lesson.data.courseId ? `/course/${lesson.data.courseId}` : "/";

  if (blocks.length === 0) {
    return (
      <div className="reading-column">
        <div className="lesson-header">
          <IconButton aria-label="Đóng bài học" onClick={() => router.push(backHref)}>
            <Icon name="close" size={20} />
          </IconButton>
          <ProgressBar percent={0} label="Tiến độ bài học" />
        </div>
        <p className="muted">Bài học này chưa có nội dung.</p>
      </div>
    );
  }

  const isLastStep = safeStep === blocks.length - 1;
  const submitHere = !submitted && (lastGradableIndex === safeStep || (isLastStep && lastGradableIndex >= 0));
  const answeredCurrent = current ? isAnswered(current, safeStep, answerState, orderCandidates) : false;
  const isQuestionStep = current ? current.type !== "teach" : false;

  function goNext() {
    setStep((s) => Math.min(s + 1, blocks.length - 1));
  }

  function goPrev() {
    setStep((s) => Math.max(s - 1, 0));
  }

  function primaryAction() {
    if (gradableCount === 0) {
      if (isLastStep) router.push(backHref);
      else goNext();
      return;
    }
    if (submitHere) {
      submit();
      return;
    }
    goNext();
  }

  const primaryLabel = submitted
    ? "Về khóa học"
    : submitHere
      ? gradableCount === 0
        ? "Hoàn tất"
        : submitMutation.isPending
          ? "Đang nộp…"
          : "Kiểm tra"
      : isLastStep && gradableCount === 0
        ? "Hoàn tất"
        : "Tiếp tục";

  const primaryDisabled = submitted ? false : submitMutation.isPending || (isQuestionStep && !answeredCurrent);
  const isPerfect = !!result && result.score.total > 0 && result.score.correct === result.score.total;

  return (
    <div className={`reading-column lesson-page${tutorDocked ? " is-docked" : ""}`}>
      <div className="lesson-header">
        <IconButton aria-label="Đóng bài học" onClick={() => router.push(backHref)}>
          <Icon name="close" size={20} />
        </IconButton>
        <ProgressBar percent={percent} label="Tiến độ bài học" />
        <span className="lesson-counter" aria-live="polite">
          {safeStep + 1}/{blocks.length}
        </span>
        <IconButton aria-label="Mục lục bài học" onClick={() => setOutlineOpen(true)}>
          <Icon name="book" size={18} />
        </IconButton>
      </div>

      {submitted && result ? (
        <ResultView result={result} blocks={blocks} lessonTitle={lesson.data.title} />
      ) : (
        <section
          key={safeStep}
          className="lesson-step-panel"
          aria-label={`${BLOCK_EYEBROW[current!.type]} — bước ${safeStep + 1} trên ${blocks.length}`}
        >
          <span className="block-eyebrow">{BLOCK_EYEBROW[current!.type]}</span>

          {current!.type === "teach" && (
            <>
              <h1 className="block-title">{current!.title}</h1>
              {safeStep === 0 && lesson.data.grounding === "general_ai_knowledge" && (
                <div className="notice-box">
                  <Badge tone="muted">Chưa xác minh</Badge>{" "}
                  {lesson.data.evidenceNotice ??
                    "Bài học dựa trên kiến thức chung của AI, chưa có nguồn tài liệu được xác minh."}
                </div>
              )}
              <div className="prose">
                {current!.paragraphs.map((p, j) => (
                  <p key={j}>{p}</p>
                ))}
              </div>

              {safeStep === 0 && lesson.data.citations.length > 0 && (
                <Card className="lesson-citations">
                  <h2 className="lesson-citations-title">Nguồn của bài học</h2>
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
                          <span className="caption"> · phiên bản {citation.sourceVersion}</span>
                        )}
                        {citation.pageNumber != null && (
                          <span className="caption"> · trang {citation.pageNumber}</span>
                        )}{" "}
                        <Badge tone="muted">{citationStatusLabel(citation.validationStatus)}</Badge>
                        {citation.evidenceText && (
                          <blockquote className="evidence-quote">{citation.evidenceText}</blockquote>
                        )}
                      </li>
                    ))}
                  </ul>
                  <p className="caption" style={{ marginTop: 8 }}>
                    Trạng thái citation phản ánh mức kiểm tra vị trí/bằng chứng, không phải kết
                    luận nội dung bài học luôn đúng.
                  </p>
                </Card>
              )}
            </>
          )}

          {current!.type === "mc" && (
            <>
              <h1 className="block-title-sm">{current!.question}</h1>
              <div role="radiogroup" aria-label={current!.question}>
                {current!.options.map((opt, j) => {
                  const selected = mcAnswers[safeStep] === j;
                  return (
                    <button
                      key={j}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      className={["quiz-option", selected ? "selected" : ""].filter(Boolean).join(" ")}
                      onClick={() => setMcAnswers((p) => ({ ...p, [safeStep]: j }))}
                    >
                      <span className="option-letter">{LETTERS[j] ?? j + 1}</span>
                      <span>{opt}</span>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {current!.type === "blank" && (
            <>
              <h1 className="block-title-sm">{current!.sentence}</h1>
              <label className="blank-label" htmlFor={`blank-${safeStep}`}>
                Điền từ còn thiếu
              </label>
              <input
                type="text"
                id={`blank-${safeStep}`}
                value={blankAnswers[safeStep] ?? ""}
                onChange={(e) => setBlankAnswers((p) => ({ ...p, [safeStep]: e.target.value }))}
                autoComplete="off"
              />
            </>
          )}

          {current!.type === "short" && (
            <>
              <h1 className="block-title-sm">{current!.question}</h1>
              <label className="blank-label" htmlFor={`short-${safeStep}`}>
                Câu trả lời ngắn
              </label>
              <input
                type="text"
                id={`short-${safeStep}`}
                value={shortAnswers[safeStep] ?? ""}
                onChange={(e) => setShortAnswers((p) => ({ ...p, [safeStep]: e.target.value }))}
                autoComplete="off"
              />
            </>
          )}

          {current!.type === "order" && (
            <>
              <h1 className="block-title-sm">{current!.prompt}</h1>
              <p className="caption" style={{ marginBottom: 12 }}>
                Dùng nút mũi tên để đổi thứ tự.
              </p>
              {currentOrder(safeStep).map((itemId, j, arr) => {
                const text = current!.items.find((it) => it.id === itemId)?.text ?? "";
                return (
                  <div className="order-item" key={itemId}>
                    <span className="summary-index">{j + 1}</span>
                    <span style={{ flex: 1 }}>{text}</span>
                    <IconButton
                      aria-label={`Đưa "${text}" lên`}
                      onClick={() => moveItem(safeStep, j, -1)}
                      disabled={j === 0}
                    >
                      ↑
                    </IconButton>
                    <IconButton
                      aria-label={`Đưa "${text}" xuống`}
                      onClick={() => moveItem(safeStep, j, 1)}
                      disabled={j === arr.length - 1}
                    >
                      ↓
                    </IconButton>
                  </div>
                );
              })}
            </>
          )}

          {current!.type === "match" && (
            <>
              <h1 className="block-title-sm">{current!.prompt}</h1>
              {current!.lefts.map((left) => (
                <div className="match-row" key={left.id}>
                  <span style={{ flex: 1, fontSize: 15 }}>{left.text}</span>
                  <label className="sr-only" htmlFor={`match-${safeStep}-${left.id}`}>
                    Ghép cho {left.text}
                  </label>
                  <select
                    id={`match-${safeStep}-${left.id}`}
                    value={matchAnswers[safeStep]?.[left.id] ?? ""}
                    onChange={(e) =>
                      setMatchAnswers((p) => ({
                        ...p,
                        [safeStep]: { ...p[safeStep], [left.id]: Number(e.target.value) },
                      }))
                    }
                  >
                    <option value="">-- chọn --</option>
                    {current!.rights.map((right) => (
                      <option key={right.id} value={right.id}>
                        {right.text}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </>
          )}

          <p className="citation-line">{lesson.data.title}</p>
        </section>
      )}

      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      <div className={`lesson-bar${isPerfect ? " is-perfect" : ""}`}>
        <div className="lesson-bar-inner">
          {safeStep > 0 && !submitted && (
            <IconButton className="lesson-bar-prev" aria-label="Bước trước" onClick={goPrev}>
              <Icon name="arrowLeft" size={18} />
            </IconButton>
          )}
          <span className="lesson-bar-spacer" />

          {submitted ? (
            <ButtonLink
              href="/"
              variant="secondary"
              size="lg"
              className="lesson-bar-secondary"
              aria-label="Về trang chủ"
            >
              <span className="lesson-bar-glyph" aria-hidden="true">
                <Icon name="home" size={20} />
              </span>
              <span className="lesson-bar-label">Trang chủ</span>
            </ButtonLink>
          ) : (
            <Button
              variant="secondary"
              size="lg"
              className="lesson-bar-secondary"
              onClick={() => setTutorOpen(true)}
              aria-label="Hỏi trợ giảng"
            >
              <span className="lesson-bar-glyph" aria-hidden="true">
                <Icon name="chat" size={20} />
              </span>
              <span className="lesson-bar-label">Hỏi trợ giảng</span>
            </Button>
          )}

          <Button
            size="lg"
            variant={submitted ? "success" : "primary"}
            className="lesson-bar-primary"
            onClick={() => (submitted ? router.push(backHref) : primaryAction())}
            disabled={primaryDisabled}
          >
            {primaryLabel}
          </Button>
        </div>
      </div>

      <OutlineSheet
        open={outlineOpen}
        blocks={blocks}
        activeIndex={safeStep}
        onClose={() => setOutlineOpen(false)}
        onSelect={(index) => {
          setStep(index);
          setOutlineOpen(false);
        }}
      />

      {lesson.data.courseId && (
        <TutorPanel
          courseId={lesson.data.courseId}
          lessonId={lesson.data.id}
          activeBlockIndex={safeStep}
          blockLabel={current ? BLOCK_LABELS[current.type] : undefined}
          open={tutorOpen}
          onClose={() => setTutorOpen(false)}
          docked={tutorDocked}
        />
      )}
    </div>
  );
}

/* The reference keeps a book control in the header that opens the lesson's own
   structure. It lists only block type and public prompt — the same fields the
   lesson body already renders — so it cannot leak a solution. */
function OutlineSheet({
  open,
  blocks,
  activeIndex,
  onClose,
  onSelect,
}: {
  open: boolean;
  blocks: Block[];
  activeIndex: number;
  onClose: () => void;
  onSelect: (index: number) => void;
}) {
  const sheetRef = useRef<HTMLDivElement | null>(null);
  // Land on the active step so a keyboard user continues from where they are
  // rather than from step 1.
  useModalPanel({
    open,
    onClose,
    panelRef: sheetRef,
    initialFocusSelector: ".outline-item.is-active",
  });

  if (!open) return null;

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng mục lục"
        tabIndex={-1}
        onClick={onClose}
      />
      {/* `aside` has an implicit `complementary` role; ARIA forbids overriding it
          with `dialog` (axe: aria-allowed-role). `div` is the valid host. */}
      <div
        className="tutor-sheet outline-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="outline-heading"
        ref={sheetRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div>
            <div id="outline-heading" className="tutor-title">
              Mục lục bài học
            </div>
            <div className="tutor-subtitle">{blocks.length} bước</div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>
        <ol className="outline-list">
          {blocks.map((block, index) => (
            <li key={index}>
              <button
                type="button"
                className={`outline-item${index === activeIndex ? " is-active" : ""}`}
                aria-current={index === activeIndex ? "step" : undefined}
                onClick={() => onSelect(index)}
              >
                <span className="outline-index">{index + 1}</span>
                <span className="outline-body">
                  <span className="outline-label">{BLOCK_LABELS[block.type]}</span>
                  <span className="outline-prompt">{blockPrompt(block)}</span>
                </span>
              </button>
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}

function ResultView({
  result,
  blocks,
  lessonTitle,
}: {
  result: AttemptOut;
  blocks: Block[];
  lessonTitle: string;
}) {
  const perfect = result.score.correct === result.score.total && result.score.total > 0;
  return (
    <section className="lesson-result" aria-label="Kết quả bài kiểm tra">
      <span className="block-eyebrow">{perfect ? "Hoàn hảo" : "Kết quả"}</span>
      <h1 className="block-title-sm">
        {result.score.correct}/{result.score.total} câu đúng
      </h1>
      <p className="lesson-result-xp">
        XP: +{result.rewards.xpEarned} (tổng {result.rewards.xp})
        {result.duplicate && " · lần nộp trước (idempotent)"}
        {result.rewards.xpEarned === 0 &&
          !result.duplicate &&
          (result.score.correct > 0
            ? " — bài này đã được cộng XP tối đa"
            : " — chưa có câu đúng nên chưa cộng XP")}
      </p>
      {result.reviewCardCreated && (
        <p className="caption">Đã thêm bài này vào lịch ôn tập.</p>
      )}

      <ol className="lesson-result-list">
        {blocks.map((block, index) => {
          if (block.type === "teach") return null;
          const graded = result.results.find((x) => x.index === index);
          const solution = graded ? solutionText(block, graded.solution) : null;
          return (
            <li
              key={index}
              className={`lesson-result-row ${graded?.correct ? "is-correct" : "is-wrong"}`}
            >
              <span className="lesson-result-mark" aria-hidden="true">
                {graded?.correct ? "✓" : "✗"}
              </span>
              <div className="lesson-result-body">
                <p className="lesson-result-label">
                  {BLOCK_LABELS[block.type]} · {graded?.correct ? "Đúng" : "Sai"}
                </p>
                <p className="lesson-result-prompt">{blockPrompt(block)}</p>
                <p className="lesson-result-solution">
                  {solution ? `Đáp án: ${solution}` : "Không có đáp án mẫu."}
                </p>
              </div>
            </li>
          );
        })}
      </ol>

      <p className="caption">{lessonTitle}</p>
      <p className="caption">
        Nội dung bài học do AI sinh. Đáp án chỉ được trả về sau khi nộp bài và được chấm trên
        máy chủ. Kiến thức chưa được đối chiếu với nguồn trừ khi bài học ghi rõ trạng thái đã xác
        minh.
      </p>
    </section>
  );
}
