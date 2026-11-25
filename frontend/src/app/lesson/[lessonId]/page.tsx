"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  citationStatusLabel,
  disputeShortGrade,
  fetchCourseGlossary,
  gradeLessonBlock,
  newClientId,
  type BlockGradeResult,
  type Citation,
} from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, ButtonLink, IconButton } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";
import useMediaQuery from "@/components/ui/useMediaQuery";
import VocabSheet from "@/components/course/VocabSheet";
import CitationChip, { type InlineCite } from "@/components/lesson/CitationChip";
import FigureRenderer, { type LessonFigure } from "@/components/lesson/FigureRenderer";
import MathText, { type InlineTermSpec } from "@/components/lesson/MathText";
import MultiBlankWordBank from "@/components/lesson/MultiBlankWordBank";
import RecapView, { type RecapSourceStat } from "@/components/lesson/RecapView";
import { ScenarioQuestion, StepsQuestion } from "@/components/lesson/ScenarioAndSteps";
import SpeedRound, { type SpeedItem } from "@/components/lesson/SpeedRound";
import TutorPanel from "./TutorPanel";

const CLIENT_BLOCKS_CAPABILITIES =
  "teach,mc,blank,multi_blank,order,match,short,speed,recap,figure";

interface IdText {
  id: number;
  text: string;
}

interface TeachImage {
  url: string;
  alt?: string;
  caption?: string;
}

type Block =
  | {
      type: "teach";
      kicker?: string;
      title: string;
      paragraphs: string[];
      takeaway?: string;
      terms?: InlineTermSpec[];
      cite?: InlineCite;
      figure?: LessonFigure;
      image?: TeachImage;
    }
  | {
      type: "mc";
      format?: string;
      display?: string;
      context?: string;
      steps?: string[];
      question: string;
      options: string[];
    }
  | {
      type: "blank";
      mode?: "multi_bank";
      sentence: string;
      parts?: string[];
      blankCount?: number;
      bank?: string[];
    }
  | { type: "order"; prompt: string; items: IdText[] }
  | { type: "match"; prompt: string; lefts: IdText[]; rights: IdText[] }
  | { type: "short"; format?: string; hint?: string; question: string }
  | { type: "speed"; prompt: string; timeLimitSeconds?: number; items: SpeedItem[] }
  | { type: "recap"; title: string; points: string[]; sources?: RecapSourceStat[] };

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
  rewards: {
    xp: number;
    xpEarned: number;
    streakDays?: number;
    bestStreakDays?: number;
    streakFreezes?: number;
    freezeConsumed?: boolean;
    freezeEarned?: boolean;
    hearts?: number;
    heartsMax?: number;
    heartLost?: boolean;
  };
  results: AttemptResult[];
  unitBreakdown?: {
    type: string;
    label: string;
    correct: number;
    total: number;
    accuracyPercent: number;
  }[];
  newlyEarnedMilestones?: {
    id?: string;
    code: string;
    category: string;
    title: string;
    description: string;
    ladder: boolean;
  }[];
  reviewCardCreated?: boolean;
}

type AnswerValue = number | string | string[] | number[] | Record<string, number> | null;

interface AnswerState {
  mc: Record<number, number>;
  blank: Record<number, string>;
  multiBlank: Record<number, string[]>;
  short: Record<number, string>;
  order: Record<number, number[]>;
  match: Record<number, Record<number, number>>;
  speed: Record<number, number[]>;
}

const BLOCK_EYEBROW: Record<Block["type"], string> = {
  teach: "Bài giảng",
  mc: "Chọn đáp án",
  blank: "Điền chỗ trống",
  order: "Sắp xếp",
  match: "Ghép cặp",
  short: "Trả lời ngắn",
  speed: "Vòng tốc độ",
  recap: "Tổng kết",
};

const BLOCK_LABELS: Record<Block["type"], string> = {
  teach: "Bài giảng",
  mc: "Trắc nghiệm",
  blank: "Điền chỗ trống",
  order: "Sắp xếp",
  match: "Ghép cặp",
  short: "Trả lời ngắn",
  speed: "Vòng tốc độ",
  recap: "Tổng kết",
};

function isNonGradable(block: Block): boolean {
  return block.type === "teach" || block.type === "recap";
}

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
    if (isNonGradable(b)) return;
    if (b.type === "mc") out.push({ index: i, answer: state.mc[i] ?? -1 });
    if (b.type === "blank") {
      if (b.mode === "multi_bank" && b.blankCount) {
        const slots = state.multiBlank[i] ?? [];
        out.push({
          index: i,
          answer: Array.from({ length: b.blankCount }, (_, idx) => slots[idx] ?? ""),
        });
      } else {
        out.push({ index: i, answer: state.blank[i] ?? "" });
      }
    }
    if (b.type === "short") out.push({ index: i, answer: state.short[i] ?? "" });
    if (b.type === "order") out.push({ index: i, answer: orderAnswer(i, state, defaults) });
    if (b.type === "match") out.push({ index: i, answer: state.match[i] ?? {} });
    if (b.type === "speed") out.push({ index: i, answer: state.speed[i] ?? [] });
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
    case "recap":
      return false;
    case "mc":
      return state.mc[index] !== undefined;
    case "blank":
      if (block.mode === "multi_bank" && block.blankCount) {
        const slots = state.multiBlank[index] ?? [];
        return (
          slots.length >= block.blankCount &&
          Array.from({ length: block.blankCount }, (_, i) => slots[i]?.trim()).every(Boolean)
        );
      }
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
    case "speed": {
      const vals = state.speed[index] ?? [];
      return (
        block.items.length > 0 &&
        vals.length === block.items.length &&
        vals.every((v) => typeof v === "number" && v >= 0)
      );
    }
  }
}

function blockPrompt(block: Block): string {
  switch (block.type) {
    case "teach":
    case "recap":
      return block.title;
    case "mc":
    case "short":
      return block.question;
    case "blank":
      return block.sentence;
    case "order":
    case "match":
    case "speed":
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
      if (Array.isArray(solution.answers)) {
        return solution.answers.map(String).join(" · ");
      }
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
        .map((id) =>
          typeof id === "number"
            ? (block.items.find((it) => it.id === id)?.text ?? String(id))
            : String(id),
        )
        .join(" → ");
    }
    case "match": {
      const pairs = solution.pairs;
      if (!Array.isArray(pairs)) return null;
      const out = pairs
        .map((pair) => {
          if (!Array.isArray(pair) || pair.length < 2) return "";
          const left =
            typeof pair[0] === "number"
              ? (block.lefts.find((it) => it.id === pair[0])?.text ?? String(pair[0]))
              : String(pair[0]);
          const right =
            typeof pair[1] === "number"
              ? (block.rights.find((it) => it.id === pair[1])?.text ?? String(pair[1]))
              : String(pair[1]);
          return `${left} → ${right}`;
        })
        .filter(Boolean);
      return out.length > 0 ? out.join(" · ") : null;
    }
    case "speed": {
      const idxs = solution.answerIndices;
      if (!Array.isArray(idxs)) return null;
      return idxs
        .map((choiceIdx, itemIdx) => {
          const item = block.items[itemIdx];
          if (!item || typeof choiceIdx !== "number") return "";
          return `#${itemIdx + 1}: ${item.choices[choiceIdx] ?? choiceIdx}`;
        })
        .filter(Boolean)
        .join(" · ");
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
    queryFn: () =>
      api<LessonOut>(`/v1/lessons/${lessonId}`, {
        headers: { "X-Client-Blocks": CLIENT_BLOCKS_CAPABILITIES },
      }),
    enabled: !!lessonId && isAuthenticated,
  });

  const [mcAnswers, setMcAnswers] = useState<Record<number, number>>({});
  const [blankAnswers, setBlankAnswers] = useState<Record<number, string>>({});
  const [multiBlankAnswers, setMultiBlankAnswers] = useState<Record<number, string[]>>({});
  const [shortAnswers, setShortAnswers] = useState<Record<number, string>>({});
  const [orderAnswers, setOrderAnswers] = useState<Record<number, number[]>>({});
  const [matchAnswers, setMatchAnswers] = useState<Record<number, Record<number, number>>>({});
  const [speedAnswers, setSpeedAnswers] = useState<Record<number, number[]>>({});
  const [step, setStep] = useState(0);
  const [tutorOpen, setTutorOpen] = useState(false);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [vocabOpen, setVocabOpen] = useState(false);
  const [vocabInitialQuery, setVocabInitialQuery] = useState("");
  const [blockChecks, setBlockChecks] = useState<Record<number, BlockGradeResult>>({});
  const [checkingBlock, setCheckingBlock] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [matchSelectedLeft, setMatchSelectedLeft] = useState<number | null>(null);
  const lessonGlossaryKey = useSessionQueryKey(
    "course-glossary",
    lesson.data?.courseId ?? "none",
    lessonId
  );
  const lessonGlossary = useQuery({
    queryKey: lessonGlossaryKey,
    enabled: Boolean(lesson.data?.courseId && lessonId && isAuthenticated),
    queryFn: () => fetchCourseGlossary(lesson.data!.courseId!, lessonId),
    retry: false,
  });
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
    onSuccess: (data) => {
      attemptKeyRef.current = null;
      queryClient.invalidateQueries({ queryKey: ["session"] });
      queryClient.invalidateQueries({ queryKey: ["me"] });
      if (typeof window !== "undefined" && lesson.data) {
        try {
          const snapshot = {
            attemptId: data.attemptId,
            duplicate: data.duplicate,
            lessonTitle: lesson.data.title,
            courseId: lesson.data.courseId ?? null,
            score: data.score,
            rewards: data.rewards,
            unitBreakdown: data.unitBreakdown ?? [],
            newlyEarnedMilestones: data.newlyEarnedMilestones ?? [],
            reviewCardCreated: data.reviewCardCreated ?? false,
            results: data.results.map((r) => {
              const blk = lesson.data.blocks[r.index];
              return {
                index: r.index,
                type: r.type,
                label: blk ? BLOCK_LABELS[blk.type] : r.type,
                prompt: blk ? blockPrompt(blk) : "",
                correct: r.correct,
                solutionText: blk ? solutionText(blk, r.solution) : null,
              };
            }),
          };
          window.sessionStorage.setItem(
            `sopiskill:complete:${lessonId}`,
            JSON.stringify(snapshot),
          );
        } catch {
          // ignore storage quota errors
        }
      }
      router.push(`/lesson/${lessonId}/complete`);
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
    .map((b, i) => (isNonGradable(b) ? -1 : i))
    .filter((i) => i >= 0);
  const gradableCount = gradableIndices.length;
  const lastGradableIndex = gradableIndices.length > 0 ? gradableIndices[gradableIndices.length - 1] : -1;

  const safeStep = blocks.length > 0 ? Math.min(step, blocks.length - 1) : 0;
  const current: Block | undefined = blocks[safeStep];

  const answerState: AnswerState = {
    mc: mcAnswers,
    blank: blankAnswers,
    multiBlank: multiBlankAnswers,
    short: shortAnswers,
    order: orderAnswers,
    match: matchAnswers,
    speed: speedAnswers,
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
      {
        mc: mcAnswers,
        blank: blankAnswers,
        multiBlank: multiBlankAnswers,
        short: shortAnswers,
        order: orderAnswers,
        match: matchAnswers,
        speed: speedAnswers,
      },
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
    setMatchSelectedLeft(null);
    setCheckError(null);
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
  const submitHere = !submitted && isLastStep && lastGradableIndex >= 0;
  const answeredCurrent = current ? isAnswered(current, safeStep, answerState, orderCandidates) : false;
  const isQuestionStep = current ? !isNonGradable(current) : false;

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
        {lesson.data.courseId && (
          <IconButton aria-label="Bảng thuật ngữ" onClick={() => setVocabOpen(true)}>
            <Icon name="learn" size={18} />
          </IconButton>
        )}
      </div>

      {submitted && result ? (
        <ResultView result={result} blocks={blocks} lessonTitle={lesson.data.title} />
      ) : (
        <section
          key={safeStep}
          className="lesson-step-panel"
          aria-label={`${BLOCK_EYEBROW[current!.type]} — bước ${safeStep + 1} trên ${blocks.length}`}
        >
          <span className="block-eyebrow">
            {current!.type === "teach" && current!.kicker ? current!.kicker : BLOCK_EYEBROW[current!.type]}
          </span>

          {current!.type === "teach" && (
            <>
              <h1 className="block-title">{current!.title}</h1>
              {current!.cite && (
                <div style={{ marginBottom: 12 }}>
                  <CitationChip cite={current!.cite} />
                </div>
              )}
              {safeStep === 0 && lesson.data.grounding === "general_ai_knowledge" && (
                <div className="notice-box">
                  <Badge tone="muted">Chưa xác minh</Badge>{" "}
                  {lesson.data.evidenceNotice ??
                    "Bài học dựa trên kiến thức chung của AI, chưa có nguồn tài liệu được xác minh."}
                </div>
              )}
              <div className="prose">
                {current!.paragraphs.map((p, j) => (
                  <p key={j}>
                    <MathText
                      text={p}
                      terms={current!.terms}
                      onTermClick={(_termKey, label) => {
                        setVocabInitialQuery(label);
                        setVocabOpen(true);
                      }}
                    />
                  </p>
                ))}
              </div>

              {current!.figure && <FigureRenderer figure={current!.figure} />}
              {!current!.figure && current!.image && (
                <figure style={{ margin: "18px 0" }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={current!.image.url}
                    alt={current!.image.alt ?? current!.title}
                    style={{ maxWidth: "100%", borderRadius: "var(--radius-md)" }}
                  />
                  {current!.image.caption && (
                    <figcaption className="caption" style={{ marginTop: 8 }}>
                      {current!.image.caption}
                    </figcaption>
                  )}
                </figure>
              )}

              {current!.takeaway && (
                <div
                  className="notice-box"
                  style={{ marginTop: 14, borderLeft: "3px solid var(--ember)", paddingLeft: 14 }}
                >
                  <strong>Ghi nhớ nhanh:</strong> <MathText text={current!.takeaway} />
                </div>
              )}

              {lessonGlossary.data && lessonGlossary.data.items.length > 0 && (
                <div className="teach-terms-row" aria-label="Thuật ngữ chính trong bài">
                  {lessonGlossary.data.items.slice(0, 6).map((term) => (
                    <button
                      key={term.id}
                      type="button"
                      className="term-pill"
                      onClick={() => {
                        setVocabInitialQuery(term.term);
                        setVocabOpen(true);
                      }}
                    >
                      {term.term}
                    </button>
                  ))}
                </div>
              )}

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

          {current!.type === "mc" && current!.display === "steps" && current!.steps ? (
            <StepsQuestion
              question={current!.question}
              steps={current!.steps}
              options={current!.options}
              selectedIndex={mcAnswers[safeStep]}
              onSelect={(j) => setMcAnswers((p) => ({ ...p, [safeStep]: j }))}
            />
          ) : current!.type === "mc" && current!.format === "scenario" ? (
            <ScenarioQuestion
              context={current!.context}
              question={current!.question}
              options={current!.options}
              selectedIndex={mcAnswers[safeStep]}
              outcome={blockChecks[safeStep]?.outcome}
              onSelect={(j) => setMcAnswers((p) => ({ ...p, [safeStep]: j }))}
            />
          ) : current!.type === "mc" ? (
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
          ) : null}

          {current!.type === "blank" &&
          current!.mode === "multi_bank" &&
          current!.parts &&
          current!.bank &&
          current!.blankCount ? (
            <>
              <h1 className="block-title-sm">Chọn từ thích hợp điền vào từng chỗ trống</h1>
              <MultiBlankWordBank
                parts={current!.parts}
                blankCount={current!.blankCount}
                bank={current!.bank}
                values={multiBlankAnswers[safeStep] ?? []}
                lockedIndices={blockChecks[safeStep]?.correctIndices ?? []}
                onChange={(next) => setMultiBlankAnswers((p) => ({ ...p, [safeStep]: next }))}
              />
            </>
          ) : current!.type === "blank" ? (
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
          ) : null}

          {current!.type === "speed" && (
            <SpeedRound
              prompt={current!.prompt}
              timeLimitSeconds={current!.timeLimitSeconds}
              items={current!.items}
              values={speedAnswers[safeStep] ?? []}
              onChange={(next) => setSpeedAnswers((p) => ({ ...p, [safeStep]: next }))}
            />
          )}

          {current!.type === "recap" && (
            <RecapView
              title={current!.title}
              points={current!.points}
              sources={current!.sources}
            />
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
              <p className="caption" style={{ marginBottom: 8 }}>
                Chọn một mục bên trái rồi chạm vào mục tương ứng bên phải để ghép cặp.
              </p>
              <div className="match-board">
                <div className="match-col">
                  <span className="match-col-head">Cột trái</span>
                  {current!.lefts.map((left, idx) => {
                    const pairedRightId = matchAnswers[safeStep]?.[left.id];
                    const isSelected = matchSelectedLeft === left.id;
                    const isPaired = pairedRightId !== undefined;
                    return (
                      <button
                        key={left.id}
                        type="button"
                        className={[
                          "match-tile",
                          isSelected ? "is-selected" : "",
                          isPaired && !isSelected ? "is-paired" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        aria-pressed={isSelected}
                        onClick={() =>
                          setMatchSelectedLeft((cur) => (cur === left.id ? null : left.id))
                        }
                      >
                        <span>{left.text}</span>
                        {isPaired && <span className="match-pair-tag">{idx + 1}</span>}
                      </button>
                    );
                  })}
                </div>
                <div className="match-col">
                  <span className="match-col-head">Cột phải</span>
                  {current!.rights.map((right) => {
                    const pairedLeftIdx = current!.lefts.findIndex(
                      (l) => matchAnswers[safeStep]?.[l.id] === right.id
                    );
                    const isPaired = pairedLeftIdx >= 0;
                    return (
                      <button
                        key={right.id}
                        type="button"
                        className={["match-tile", isPaired ? "is-paired" : ""]
                          .filter(Boolean)
                          .join(" ")}
                        onClick={() => {
                          if (matchSelectedLeft === null) return;
                          setMatchAnswers((p) => {
                            const nextMap = { ...(p[safeStep] ?? {}) };
                            for (const [k, v] of Object.entries(nextMap)) {
                              if (v === right.id) delete nextMap[Number(k)];
                            }
                            nextMap[matchSelectedLeft] = right.id;
                            return { ...p, [safeStep]: nextMap };
                          });
                          setMatchSelectedLeft(null);
                        }}
                      >
                        <span>{right.text}</span>
                        {isPaired && <span className="match-pair-tag">{pairedLeftIdx + 1}</span>}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="sr-only">
                {current!.lefts.map((left) => (
                  <div key={left.id}>
                    <label htmlFor={`match-${safeStep}-${left.id}`}>
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
              </div>
            </>
          )}

          {checkError && (
            <div className="error-box" role="alert" style={{ marginTop: 14 }}>
              {checkError}
            </div>
          )}

          <p className="citation-line">{lesson.data.title}</p>
        </section>
      )}

      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      {(() => {
        const activeCheck = !submitted ? blockChecks[safeStep] : undefined;
        const barTone = activeCheck
          ? activeCheck.correct
            ? " is-correct"
            : " is-wrong"
          : isPerfect
            ? " is-perfect"
            : "";
        const primaryVariant = submitted
          ? "success"
          : activeCheck
            ? activeCheck.correct
              ? "success"
              : "wrong"
            : "primary";

        async function runBlockCheck(dispute = false) {
          if (!lesson.data) return;
          const single = buildAnswers(blocks, answerState, orderCandidates).find(
            (a) => a.index === safeStep
          );
          if (!single) return;
          setCheckingBlock(true);
          setCheckError(null);
          try {
            const existingGradeId = blockChecks[safeStep]?.gradeId;
            const res =
              dispute && existingGradeId
                ? await disputeShortGrade(lessonId, existingGradeId)
                : await gradeLessonBlock(lessonId, safeStep, {
                    contentVersion: lesson.data.contentVersion,
                    answer: single.answer,
                    ...(dispute ? { dispute: true } : {}),
                  });
            setBlockChecks((prev) => ({ ...prev, [safeStep]: res }));
          } catch (e) {
            setCheckError(
              e instanceof Error
                ? e.message
                : dispute
                  ? "Không thể chấm lại."
                  : "Không kiểm tra được câu này."
            );
          } finally {
            setCheckingBlock(false);
          }
        }

        return (
          <div className={`lesson-bar${barTone}`}>
            {activeCheck && (
              <div className="lesson-feedback-band" role="status">
                <div>
                  <span className="lesson-feedback-title">
                    <Icon name={activeCheck.correct ? "checkCircle" : "close"} size={18} />
                    {activeCheck.correct ? "Quá chuẩn!" : "Chưa chính xác"}
                  </span>
                  <p className="lesson-feedback-text">{activeCheck.feedback}</p>
                  {activeCheck.solution &&
                    current &&
                    solutionText(current, activeCheck.solution) && (
                      <p className="lesson-feedback-solution">
                        Đáp án: {solutionText(current, activeCheck.solution)}
                      </p>
                    )}
                </div>
                {activeCheck.disputeAllowed && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={checkingBlock}
                    onClick={() => void runBlockCheck(true)}
                  >
                    Yêu cầu chấm lại
                  </Button>
                )}
              </div>
            )}

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
                <>
                  <Button
                    variant="secondary"
                    size="lg"
                    className="lesson-bar-secondary"
                    onClick={() => setTutorOpen(true)}
                    aria-label="Hỏi Sopi"
                  >
                    <span className="lesson-bar-glyph" aria-hidden="true">
                      <Icon name="chat" size={20} />
                    </span>
                    <span className="lesson-bar-label">Hỏi Sopi</span>
                  </Button>
                  {isQuestionStep && (
                    <Button
                      variant="ghost"
                      size="lg"
                      disabled={!answeredCurrent || checkingBlock}
                      onClick={() => void runBlockCheck(false)}
                    >
                      {checkingBlock ? "Đang kiểm tra…" : "Kiểm tra câu này"}
                    </Button>
                  )}
                </>
              )}

              <Button
                size="lg"
                variant={primaryVariant}
                className="lesson-bar-primary"
                onClick={() => (submitted ? router.push(backHref) : primaryAction())}
                disabled={primaryDisabled}
              >
                {primaryLabel}
              </Button>
            </div>
          </div>
        );
      })()}

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
        <VocabSheet
          courseId={lesson.data.courseId}
          lessonId={lesson.data.id}
          initialQuery={vocabInitialQuery}
          open={vocabOpen}
          onClose={() => {
            setVocabOpen(false);
            setVocabInitialQuery("");
          }}
        />
      )}

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
  const accuracy =
    result.score.total > 0 ? Math.round((result.score.correct / result.score.total) * 100) : 100;
  return (
    <section className="lesson-result" aria-label="Kết quả bài kiểm tra">
      <div className={`complete-hero${perfect ? " is-perfect" : ""}`}>
        <div className="complete-medal" aria-hidden="true">
          <Icon name={perfect ? "trophy" : "checkCircle"} size={32} />
        </div>
        <span className="block-eyebrow" style={{ display: "block" }}>
          {perfect ? "Hoàn hảo!" : "Hoàn thành bài học"}
        </span>
        <h1 className="block-title-sm" style={{ marginTop: 6 }}>
          {result.score.correct}/{result.score.total} câu đúng
        </h1>
        <div className="complete-stats">
          <div className="complete-stat">
            <div className="complete-stat-val">{accuracy}%</div>
            <div className="complete-stat-label">Độ chính xác</div>
          </div>
          <div className="complete-stat">
            <div className="complete-stat-val">+{result.rewards.xpEarned}</div>
            <div className="complete-stat-label">XP nhận được</div>
          </div>
          <div className="complete-stat">
            <div className="complete-stat-val">{result.rewards.xp}</div>
            <div className="complete-stat-label">Tổng XP</div>
          </div>
        </div>
        <p className="caption" style={{ marginTop: 14 }}>
          {result.duplicate && "Lần nộp trước (idempotent) · "}
          {result.rewards.xpEarned === 0 &&
            !result.duplicate &&
            (result.score.correct > 0
              ? "Bài này đã được cộng XP tối đa · "
              : "Chưa có câu đúng nên chưa cộng XP · ")}
          {result.reviewCardCreated ? "Đã thêm vào lịch ôn tập ngắt quãng." : lessonTitle}
        </p>
      </div>

      <ol className="lesson-result-list">
        {blocks.map((block, index) => {
          if (isNonGradable(block)) return null;
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
