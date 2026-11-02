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

  // P5.0 — hai query này trả 503 khi cờ P50_ENABLED tắt; UI hiển thị trạng thái
  // "Chưa bật" thay vì báo lỗi, để trang không hỏng khi tính năng tắt.
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

  // P5.2b — báo exposure MỘT lần cho mỗi token mới. Hoàn toàn ẩn: không hiện
  // loading/error, không invalidate cache; lỗi bị bỏ qua có chủ đích.
  const reportedToken = useRef<string | null>(null);
  const recommendationToken = learningPath.data?.recommendationToken ?? null;
  useEffect(() => {
    if (!courseId || !recommendationToken) return;
    if (reportedToken.current === recommendationToken) return;
    reportedToken.current = recommendationToken;
    recordRecommendation(courseId, recommendationToken).catch(() => {});
  }, [courseId, recommendationToken]);

  if (!courseId) return <div className="container">Thiếu courseId.</div>;
  if (authLoading) return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  if (!isAuthenticated) return <div className="container">Đang chuyển tới trang đăng nhập…</div>;

  return (
    <div className="container">
      <div className="topbar">
        <h1>{course.data?.topic ?? "Khóa học"}</h1>
        <Link href="/" className="link">
          ← Trang chủ
        </Link>
      </div>

      {course.data && (
        <p className="badge">
          Tiến độ: {course.data.progress.completed}/{course.data.progress.total} bài (
          {course.data.progress.percent}%)
        </p>
      )}

      {course.isLoading && <div className="card">Đang tải khóa học…</div>}

      {course.isError && (
        <div className="error-box">
          Không tải được khóa học: {course.error.message}
          <br />
          <button style={{ marginTop: 8 }} onClick={() => course.refetch()}>
            Thử lại
          </button>
        </div>
      )}

      {course.data?.status === "ready" &&
        course.data.progress.total > 0 &&
        course.data.progress.completed === 0 && (
          <div className="card">Bắt đầu bài học đầu tiên để ghi nhận tiến độ.</div>
        )}

      {course.data?.status === "failed" && (
        <div className="error-box">
          Sinh khóa học thất bại.
          <br />
          <button
            style={{ marginTop: 8 }}
            onClick={() => api(`/v1/courses/${courseId}/retry`, { method: "POST" })}
          >
            Thử lại
          </button>
        </div>
      )}

      {!p50Disabled && learningPath.data && (
        <div className="card">
          <h2>Học tiếp</h2>
          {learningPath.data.nextLesson ? (
            <>
              <p>
                <Link className="link" href={`/lesson/${learningPath.data.nextLesson.lessonId}`}>
                  {learningPath.data.nextLesson.title}
                </Link>
              </p>
              <p className="muted">{learningPath.data.nextLesson.reason.message}</p>
            </>
          ) : (
            <p className="muted">
              {learningPath.data.blockedBy.length > 0
                ? "Cần đạt kỹ năng trước khi học bài kế tiếp."
                : "Bạn đã học hết các bài hiện có."}
            </p>
          )}
          {learningPath.data.blockedBy.length > 0 && (
            <ul className="muted">
              {learningPath.data.blockedBy.slice(0, 3).map((blocked) => (
                <li key={blocked.lessonId}>
                  {blocked.title} — cần:{" "}
                  {blocked.prerequisites
                    .filter((p) => !p.met)
                    .map((p) => `${p.title} (${Math.round(p.masteryScore * 100)}%)`)
                    .join(", ")}
                </li>
              ))}
            </ul>
          )}
          {learningPath.data.reviewLessonId && !learningPath.data.nextLesson && (
            <p>
              <Link className="link" href={`/lesson/${learningPath.data.reviewLessonId}`}>
                Ôn lại bài yếu nhất
              </Link>
            </p>
          )}
          <p>
            <Link className="link" href={`/review?courseId=${courseId}`}>
              Ôn tập ({learningPath.data.reviewDueCount} thẻ đến hạn)
            </Link>
          </p>
        </div>
      )}

      {!p50Disabled && mastery.data && mastery.data.items.length > 0 && (
        <div className="card">
          <h2>Mức nắm kỹ năng</h2>
          <p className="muted">
            Chỉ số tham khảo (rule-based, có trọng số thời gian) — không phải điểm số chính thức.
          </p>
          <ul className="course-list">
            {mastery.data.items.map((item) => (
              <li key={item.skillId}>
                <span>{item.title}</span>{" "}
                <span className="badge">
                  {Math.round(item.masteryScore * 100)}%
                  {item.masteryScore >= item.passThreshold ? " · đạt" : " · chưa đạt"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {sources.data && (
        <div className="card source-card">
          <h2>Nguồn tham khảo ({sources.data.total})</h2>
          {sources.data.notice && <p className="muted">{sources.data.notice}</p>}
          {sources.data.items.length === 0 && (
            <p className="muted">Khóa học này chưa gắn nguồn tài liệu nào.</p>
          )}
          <ul className="source-list">
            {sources.data.items.map(({ source }) => (
              <li key={source.id}>
                <strong>{source.title}</strong>
                {source.publisher && <span className="muted"> — {source.publisher}</span>}
                <div className="muted">
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
                  {source.version && ` · version ${source.version}`}
                </div>
                <span className={`badge ${isVerifiedStatus(source.verificationStatus) ? "" : "badge-muted"}`}>
                  {verificationLabel(source.verificationStatus)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {course.data?.status === "ready" && (
        <p className="muted">
          Nội dung bài học do AI sinh. Kiến thức chưa được đối chiếu với nguồn trừ khi bài học
          ghi rõ trạng thái đã xác minh.
        </p>
      )}

      {course.data?.units.map((unit) => (
        <div key={unit.id}>
          <h2>{unit.title}</h2>
          <div className="card">
            <p>{unit.blurb}</p>
            {unit.lessons.map((lesson) => (
              <div key={lesson.id} style={{ margin: "8px 0" }}>
                <Link className="link" href={`/lesson/${lesson.id}`}>
                  {lesson.orderIndex + 1}. {lesson.title}
                </Link>{" "}
                {lesson.completed && <span className="badge">✓ đã học</span>}
                <span className="badge">{lesson.status}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
