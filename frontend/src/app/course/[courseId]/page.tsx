"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  api,
  fetchCourseSources,
  isVerifiedStatus,
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
