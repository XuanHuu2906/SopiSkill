"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchCourses, type CourseListItem } from "@/lib/api";
import { useAuth, useSessionQueryKey } from "./providers";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ProgressRing } from "@/components/ui/Progress";
import { Skeleton, SkeletonStack } from "@/components/ui/Skeleton";
import LandingPage from "@/components/landing/LandingPage";

const WEEKDAY = ["Chủ nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 11) return "Chào buổi sáng";
  if (hour < 14) return "Chào buổi trưa";
  if (hour < 18) return "Chào buổi chiều";
  return "Chào buổi tối";
}

function firstName(displayName: string): string {
  const trimmed = displayName.trim();
  if (!trimmed) return "bạn";
  const parts = trimmed.split(/\s+/);
  return parts[parts.length - 1];
}

function CourseCard({ course }: { course: CourseListItem }) {
  const statusLabel =
    course.status === "ready"
      ? course.progress.completed === 0
        ? "mới"
        : `${course.progress.percent}%`
      : course.status;
  return (
    <Link href={`/course/${course.id}`} className="course-card">
      <ProgressRing
        percent={course.progress.percent}
        size={52}
        thickness={4}
        label={`Đã học ${course.progress.percent}%`}
      />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="course-card-title" style={{ display: "block" }}>
          {course.topic}
        </span>
        <span className="course-card-meta" style={{ display: "block" }}>
          {course.progress.completed}/{course.progress.total} bài · {statusLabel}
        </span>
        {course.resumeLessonTitle && (
          <span className="course-card-next" style={{ display: "block", marginTop: 4 }}>
            {course.resumeLessonTitle}
          </span>
        )}
      </span>
    </Link>
  );
}

export default function HomePage() {
  const { data: user, isLoading } = useAuth();
  const listKey = useSessionQueryKey("courses", { limit: 5 });
  const courses = useQuery({
    queryKey: listKey,
    queryFn: () => fetchCourses(5, 0),
    enabled: !!user,
    retry: false,
  });

  const today = WEEKDAY[new Date().getDay()];
  const nextCourse = courses.data?.items.find((c) => c.resumeLessonId) ?? courses.data?.items[0];
  const totalXp = user?.xp ?? 0;

  if (isLoading) {
    return <div aria-hidden="true" style={{ minHeight: "60vh" }} />;
  }

  if (!user) {
    return <LandingPage />;
  }

  return (
    <div>
      <span className="eyebrow" style={{ color: "var(--ink-3)" }}>
        {today}
      </span>
      <h1 className="display-xl" style={{ margin: "4px 0 24px" }}>
        {`${greeting()}, ${firstName(user.displayName)}.`}
      </h1>

      {courses.isLoading && (
        <div className="hero-card" style={{ alignItems: "stretch" }}>
          <div style={{ flex: 1 }}>
            <Skeleton height={20} width={220} />
            <div style={{ height: 12 }} />
            <Skeleton height={36} width={340} />
          </div>
        </div>
      )}

      {nextCourse && (
        <section className="hero-card" aria-label="Học tiếp">
          <div style={{ minWidth: 0 }}>
            <span className="hero-kicker">{nextCourse.topic}</span>
            <span className="hero-step" style={{ display: "block", marginTop: 2 }}>
              {nextCourse.progress.completed}/{nextCourse.progress.total} bài ·{" "}
              {nextCourse.progress.percent}%
            </span>
            <p className="hero-lesson">{nextCourse.resumeLessonTitle ?? "Bài kế tiếp"}</p>
          </div>
          {nextCourse.resumeLessonId ? (
            <ButtonLink
              href={`/lesson/${nextCourse.resumeLessonId}`}
              variant="light"
              size="lg"
              data-testid="resume-continue"
            >
              Tiếp tục
            </ButtonLink>
          ) : (
            <ButtonLink href={`/course/${nextCourse.id}`} variant="light" size="lg">
              Mở khóa học
            </ButtonLink>
          )}
        </section>
      )}

      <section aria-labelledby="my-courses">
        <div className="section-head">
          <h2 id="my-courses" className="section-title">
            Khóa học của bạn
          </h2>
          <Link className="link" href="/new" style={{ fontSize: 15 }}>
            Tạo mới
          </Link>
        </div>

        {courses.isPending && (
          <Card>
            <SkeletonStack rows={3} />
          </Card>
        )}

        {courses.isError && (
          <div className="error-box" role="alert">
            Không tải được khóa học: {courses.error.message}
            <div style={{ marginTop: 8 }}>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => courses.refetch()}>
                Thử lại
              </button>
            </div>
          </div>
        )}

        {courses.data && courses.data.items.length === 0 && (
          <Card variant="dashed">
            <h3 className="section-title" style={{ fontSize: 19, marginBottom: 8 }}>
              Chưa có khóa học nào
            </h3>
            <p className="muted" style={{ marginBottom: 16 }}>
              Chọn một chủ đề bạn tò mò, hệ thống sẽ phỏng vấn nhanh rồi soạn lộ trình.
            </p>
            <ButtonLink href="/new" size="md">
              Tạo khóa học đầu tiên
            </ButtonLink>
          </Card>
        )}

        {courses.data && courses.data.items.length > 0 && (
          <div className="course-grid">
            {courses.data.items.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        )}

        {courses.data && courses.data.total > courses.data.items.length && (
          <p className="muted" style={{ marginTop: 12 }}>
            Hiển thị {courses.data.items.length}/{courses.data.total} khóa học
          </p>
        )}
      </section>

      <section aria-labelledby="how-it-works" style={{ marginTop: 40 }}>
        <h2 id="how-it-works" className="section-title" style={{ marginBottom: 12 }}>
          Cách hoạt động
        </h2>
        <Card>
          <ol style={{ margin: 0, paddingLeft: 20 }} className="muted">
            <li>Nhập chủ đề bạn muốn học</li>
            <li>Trả lời 5 câu phỏng vấn ngắn để hệ thống hiểu mục tiêu</li>
            <li>Duyệt đề xuất khóa học</li>
            <li>Chờ hệ thống soạn bài học</li>
            <li>Học, làm quiz — điểm được chấm và lưu phía máy chủ</li>
          </ol>
          <div style={{ display: "flex", gap: 12, marginTop: 16, flexWrap: "wrap", alignItems: "center" }}>
            <Badge tone="muted">{totalXp} XP</Badge>
            <Link href="/sources" className="link" style={{ fontSize: 15 }}>
              Tài liệu của tôi (PDF)
            </Link>
            <Link href="/review" className="link" style={{ fontSize: 15 }}>
              Ôn tập
            </Link>
          </div>
        </Card>
      </section>
    </div>
  );
}
