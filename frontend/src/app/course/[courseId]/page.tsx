"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";
import {
  api,
  ApiError,
  fetchCourseMastery,
  fetchCourseSources,
  fetchLearningPath,
  isVerifiedStatus,
  recordRecommendation,
  verificationLabel,
} from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../providers";
import { Badge } from "@/components/ui/Badge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";

interface CourseDetail {
  id: string;
  topic: string;
  status: string;
  units: {
    id: string;
    orderIndex: number;
    title: string;
    blurb: string;
    lessons: {
      id: string;
      orderIndex: number;
      title: string;
      status: string;
      contentVersion: number;
      completed: boolean;
    }[];
  }[];
  progress: { completed: number; total: number; percent: number };
}

const LESSON_STATUS_LABEL: Record<string, string> = {
  ready: "Sẵn sàng",
  generating: "Đang soạn",
  queued: "Đang chờ",
  failed: "Lỗi",
};

function lessonMeta(lesson: CourseDetail["units"][number]["lessons"][number]) {
  if (lesson.completed) return "Đã học";
  if (lesson.status === "ready") return "Sẵn sàng";
  return LESSON_STATUS_LABEL[lesson.status] ?? lesson.status;
}

/* The rail glyph tells you what a row *is* at a glance — done, next, or not yet
   reachable. It never invents lock state the API does not return: a lesson is
   only drawn as locked when the learning path named it in `blockedBy`. */
function RailNode({
  state,
  index,
  tone = "muted",
}: {
  state: "done" | "next" | "open" | "blocked";
  index?: number;
  tone?: "muted" | "accent";
}) {
  const glyph =
    state === "done" ? (
      <Icon name="check" size={18} />
    ) : state === "next" ? (
      <Icon name="play" size={16} />
    ) : state === "blocked" ? (
      <span className="course-rail-lock" aria-hidden="true">
        <LockGlyph />
      </span>
    ) : (
      <span className="course-rail-num">{index}</span>
    );
  return (
    <span
      className={[
        "course-rail-node",
        `is-${state}`,
        tone === "accent" ? "is-accent" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
}

function LockGlyph() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8.5 11V7.5a3.5 3.5 0 0 1 7 0V11" />
    </svg>
  );
}

export default function CoursePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const courseKey = useSessionQueryKey("course", courseId);
  const sourcesKey = useSessionQueryKey("course-sources", courseId);

  const course = useQuery({
    queryKey: courseKey,
    enabled: !!courseId && isAuthenticated,
    queryFn: () => api<CourseDetail>(`/v1/courses/${courseId}`),
    refetchInterval: (q) =>
      q.state.data && ["ready", "failed"].includes(q.state.data.status) ? false : 2000,
  });

  const sources = useQuery({
    queryKey: sourcesKey,
    enabled: !!courseId && isAuthenticated,
    queryFn: () => fetchCourseSources(courseId),
    retry: false,
  });

  const masteryKey = useSessionQueryKey("course-mastery", courseId);
  const pathKey = useSessionQueryKey("course-learning-path", courseId);

  const mastery = useQuery({
    queryKey: masteryKey,
    enabled: !!courseId && isAuthenticated,
    queryFn: () => fetchCourseMastery(courseId),
    retry: false,
  });

  const learningPath = useQuery({
    queryKey: pathKey,
    enabled: !!courseId && isAuthenticated,
    queryFn: () => fetchLearningPath(courseId),
    retry: false,
  });

  const p50Disabled =
    (mastery.error instanceof ApiError && mastery.error.status === 503) ||
    (learningPath.error instanceof ApiError && learningPath.error.status === 503);

  const reportedToken = useRef<string | null>(null);
  const recommendationToken = learningPath.data?.recommendationToken ?? null;
  useEffect(() => {
    if (!courseId || !recommendationToken) return;
    if (reportedToken.current === recommendationToken) return;
    reportedToken.current = recommendationToken;
    recordRecommendation(courseId, recommendationToken).catch(() => {});
  }, [courseId, recommendationToken]);

  if (!courseId) return <p className="muted">Thiếu courseId.</p>;
  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const progress = course.data?.progress;
  // `nextLesson` is the backend's recommendation, but /learning-path is behind
  // a feature flag on some deployments. Falling back to the first unfinished
  // lesson keeps "Tiếp tục" honest: it is derived from course state, it does
  // not claim the recommendation or its blocking rules.
  const firstUnfinished = course.data?.units
    .flatMap((unit) => unit.lessons)
    .find((lesson) => !lesson.completed);
  const resumeLessonId =
    learningPath.data?.nextLesson?.lessonId ?? firstUnfinished?.id ?? null;
  const blockedIds = new Set(
    (learningPath.data?.blockedBy ?? []).map((blocked) => blocked.lessonId),
  );

  function nodeState(lesson: CourseDetail["units"][number]["lessons"][number]) {
    if (lesson.completed) return "done" as const;
    if (resumeLessonId === lesson.id) return "next" as const;
    if (blockedIds.has(lesson.id)) return "blocked" as const;
    return "open" as const;
  }

  return (
    <div className="course-page">
      <div className="course-head">
        <div className="course-head-main">
          <h1 className="course-topic">{course.data?.topic ?? "Đang tải…"}</h1>
          <div className="course-progress-row">
            <ProgressBar
              percent={progress?.percent ?? 0}
              label={`Hoàn thành ${progress?.percent ?? 0} phần trăm`}
            />
            <span className="course-progress-text">
              {progress
                ? `${progress.percent}% · còn ${progress.total - progress.completed}/${progress.total}`
                : "—"}
            </span>
          </div>
        </div>
        {resumeLessonId ? (
          <ButtonLink href={`/lesson/${resumeLessonId}`} size="md" className="course-resume">
            <Icon name="play" size={16} />
            Tiếp tục
          </ButtonLink>
        ) : (
          <Badge tone="muted">Đã hết bài</Badge>
        )}
      </div>

      {course.isLoading && (
        <div className="course-timeline">
          <p className="muted course-empty">Đang tải khóa học…</p>
        </div>
      )}

      {course.isError && (
        <div className="error-box" role="alert">
          Không tải được khóa học: {course.error.message}
          <div style={{ marginTop: 8 }}>
            <Button variant="secondary" size="sm" onClick={() => course.refetch()}>
              Thử lại
            </Button>
          </div>
        </div>
      )}

      {course.data?.status === "failed" && (
        <div className="error-box" role="alert">
          Sinh khóa học thất bại.
          <div style={{ marginTop: 8 }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => api(`/v1/courses/${courseId}/retry`, { method: "POST" })}
            >
              Thử lại
            </Button>
          </div>
        </div>
      )}

      {sources.data && sources.data.items.length > 0 && (
        <Link className="course-source-chip" href={`/sources?courseId=${courseId}`}>
          <span className="course-source-glyph" aria-hidden="true">
            <Icon name="file" size={18} />
          </span>
          <span className="course-source-body">
            <span className="course-source-eyebrow">Nguồn của khóa học</span>
            <span className="course-source-title">
              {sources.data.items[0].source.title}
              {sources.data.total > 1 ? ` · +${sources.data.total - 1}` : ""}
            </span>
          </span>
        </Link>
      )}

      <div className="course-timeline">
        {course.data?.units.map((unit, unitPosition) => {
          const done = unit.lessons.filter((l) => l.completed).length;
          const isLastUnit = unitPosition === course.data!.units.length - 1;
          return (
            <section
              key={unit.id}
              className={`course-unit${isLastUnit ? " is-last" : ""}`}
              aria-labelledby={`unit-${unit.id}`}
            >
              {/* The API's unit title is the chapter name, so repeating it in
                  the eyebrow would just stutter; the count is the useful bit. */}
              <span className="eyebrow course-unit-eyebrow">
                Trang {unit.orderIndex + 1} · đã xong {done}/{unit.lessons.length}
              </span>
              <h2 id={`unit-${unit.id}`} className="course-unit-title">
                {unit.title}
              </h2>
              {unit.blurb && <p className="course-unit-blurb">{unit.blurb}</p>}

              <ol className="course-lessons">
                {unit.lessons.map((lesson) => {
                  const state = nodeState(lesson);
                  const isNext = state === "next";
                  return (
                    <li key={lesson.id} className={`course-lesson is-${state}`}>
                      <span className="course-rail" aria-hidden="true">
                        <RailNode state={state} index={lesson.orderIndex + 1} />
                      </span>

                      {isNext ? (
                        <Link href={`/lesson/${lesson.id}`} className="course-next-card">
                          <span className="course-next-eyebrow">
                            Học tiếp
                            {learningPath.data?.nextLesson?.reason?.message
                              ? ` · ${learningPath.data.nextLesson.reason.message}`
                              : ""}
                          </span>
                          <span className="course-next-title">{lesson.title}</span>
                          <span className="course-next-cta">
                            <Icon name="play" size={16} />
                            Bắt đầu bài học
                          </span>
                        </Link>
                      ) : (
                        <Link
                          href={`/lesson/${lesson.id}`}
                          className="course-lesson-row"
                          aria-label={`${lesson.title} — ${lessonMeta(lesson)}`}
                        >
                          <span className="course-lesson-title">{lesson.title}</span>
                          <span className="course-lesson-meta">
                            {state === "blocked" ? "Đã khóa · " : ""}
                            {lessonMeta(lesson)}
                          </span>
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          );
        })}
      </div>

      {!p50Disabled && learningPath.data && learningPath.data.blockedBy.length > 0 && (
        <div className="course-nudge">
          <span className="course-nudge-title">Cần đạt kỹ năng trước khi mở bài kế tiếp</span>
          <ul className="course-nudge-list">
            {learningPath.data.blockedBy.slice(0, 3).map((blocked) => (
              <li key={blocked.lessonId}>
                <strong>{blocked.title}</strong> — cần:{" "}
                {blocked.prerequisites
                  .filter((p) => !p.met)
                  .map((p) => `${p.title} (${Math.round(p.masteryScore * 100)}%)`)
                  .join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      {learningPath.data && learningPath.data.reviewDueCount > 0 && (
        <Link className="course-nudge is-link" href={`/review?courseId=${courseId}`}>
          <span className="course-nudge-title">
            {learningPath.data.reviewDueCount} thẻ đến hạn ôn
          </span>
          <span className="course-nudge-sub">
            Ôn đúng lúc để điểm nắm kỹ năng không tụt
          </span>
        </Link>
      )}

      {!p50Disabled && mastery.data && mastery.data.items.length > 0 && (
        <details className="course-disclosure">
          <summary>
            <span>Mức nắm kỹ năng</span>
            <Icon name="chevronDown" size={18} />
          </summary>
          <p className="caption">
            Chỉ số tham khảo (rule-based, có trọng số thời gian) — không phải điểm số chính
            thức.
          </p>
          <ul className="course-list">
            {mastery.data.items.map((item) => (
              <li
                key={item.skillId}
                style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
              >
                <span style={{ flex: 1, fontSize: 15 }}>{item.title}</span>
                <Badge tone={item.masteryScore >= item.passThreshold ? "success" : "muted"}>
                  {Math.round(item.masteryScore * 100)}%
                  {item.masteryScore >= item.passThreshold ? " · đạt" : " · chưa đạt"}
                </Badge>
              </li>
            ))}
          </ul>
        </details>
      )}

      {sources.data && (
        <details className="course-disclosure">
          <summary>
            <span>Nguồn tham khảo ({sources.data.total})</span>
            <Icon name="chevronDown" size={18} />
          </summary>
          {sources.data.notice && <p className="caption">{sources.data.notice}</p>}
          {sources.data.items.length === 0 && (
            <p className="muted">Khóa học này chưa gắn nguồn tài liệu nào.</p>
          )}
          <ul className="source-list">
            {sources.data.items.map(({ source }) => (
              <li key={source.id}>
                <strong>{source.title}</strong>
                {source.publisher && <span className="muted"> — {source.publisher}</span>}
                <div className="caption">
                  {source.canonicalUrl && (
                    <a
                      className="link"
                      href={source.canonicalUrl}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                    >
                      {source.canonicalUrl}
                    </a>
                  )}
                  {source.sourceUpdatedAt && ` · cập nhật ${source.sourceUpdatedAt.slice(0, 10)}`}
                  {source.version && ` · phiên bản ${source.version}`}
                </div>
                <Badge tone={isVerifiedStatus(source.verificationStatus) ? "success" : "muted"}>
                  {verificationLabel(source.verificationStatus)}
                </Badge>
              </li>
            ))}
          </ul>
        </details>
      )}

      {course.data?.status === "ready" && (
        <p className="caption course-footnote">
          Nội dung bài học do AI sinh. Kiến thức chưa được đối chiếu với nguồn trừ khi bài
          học ghi rõ trạng thái đã xác minh.
        </p>
      )}
    </div>
  );
}
