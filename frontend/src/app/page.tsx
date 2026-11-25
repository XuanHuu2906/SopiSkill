"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchCourses, fetchHome, fetchMeStats, type CourseListItem } from "@/lib/api";
import { useAuth, useSessionQueryKey } from "./providers";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { ProgressRing } from "@/components/ui/Progress";
import { Skeleton, SkeletonStack } from "@/components/ui/Skeleton";
import LandingPage from "@/components/landing/LandingPage";
import WeekRecapCard from "@/components/gamification/WeekRecapCard";

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
  const remaining = Math.max(0, course.progress.total - course.progress.completed);
  const statusLabel =
    course.status === "ready"
      ? course.progress.completed === 0
        ? "Mới"
        : `${course.progress.percent}% · còn ${remaining} bài`
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
  const listKey = useSessionQueryKey("courses", { limit: 20 });
  const statsKey = useSessionQueryKey("me-stats");
  const homeKey = useSessionQueryKey("home");
  const courses = useQuery({
    queryKey: listKey,
    queryFn: () => fetchCourses(20, 0),
    enabled: !!user,
    retry: false,
  });
  const stats = useQuery({
    queryKey: statsKey,
    queryFn: fetchMeStats,
    enabled: !!user,
    retry: false,
    staleTime: 15_000,
  });
  const home = useQuery({
    queryKey: homeKey,
    queryFn: fetchHome,
    enabled: !!user,
    retry: false,
    staleTime: 15_000,
  });

  const today = WEEKDAY[new Date().getDay()];
  const allCourses = courses.data?.items ?? [];
  const activeCourses = allCourses.filter(
    (c) => !(c.progress.total > 0 && c.progress.completed >= c.progress.total)
  );
  const completedCourses = allCourses.filter(
    (c) => c.progress.total > 0 && c.progress.completed >= c.progress.total
  );
  const nextCourse =
    activeCourses.find((c) => c.resumeLessonId) ?? activeCourses[0] ?? allCourses[0];
  const reviewsDue = stats.data?.reviewsDue ?? 0;

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

      {home.data && <WeekRecapCard home={home.data} />}

      <section aria-labelledby="my-courses">
        <div className="section-head">
          <h2 id="my-courses" className="section-title">
            Khóa học của bạn
          </h2>
          <Link className="link" href="/new" style={{ fontSize: 15, fontWeight: 600 }}>
            + Tạo mới
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
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => courses.refetch()}
              >
                Thử lại
              </button>
            </div>
          </div>
        )}

        {courses.data && allCourses.length === 0 && (
          <Card variant="dashed">
            <h3 className="section-title" style={{ fontSize: 19, marginBottom: 8 }}>
              Bắt đầu khóa học đầu tiên
            </h3>
            <p className="muted" style={{ marginBottom: 16 }}>
              Nêu bất kỳ chủ đề nào hoặc tải lên tài liệu PDF — hệ thống sẽ phỏng vấn nhanh rồi
              soạn lộ trình học riêng cho bạn.
            </p>
            <ButtonLink href="/new" size="md">
              Tạo khóa học đầu tiên
            </ButtonLink>
          </Card>
        )}

        {activeCourses.length > 0 && (
          <div className="course-grid">
            {activeCourses.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        )}
      </section>

      {completedCourses.length > 0 && (
        <section aria-labelledby="completed-courses" style={{ marginTop: 36 }}>
          <div className="section-head">
            <h2 id="completed-courses" className="section-title">
              Đã hoàn thành
            </h2>
          </div>
          <div className="completed-grid">
            {completedCourses.map((course) => (
              <Link key={course.id} href={`/course/${course.id}`} className="completed-card">
                <span className="completed-badge" aria-hidden="true">
                  <Icon name="trophy" size={20} />
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span className="course-card-title" style={{ display: "block" }}>
                    {course.topic}
                  </span>
                  <span className="course-card-meta" style={{ display: "block" }}>
                    Hoàn thành {course.progress.total}/{course.progress.total} bài
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {reviewsDue > 0 && (
        <Link href="/review" className="home-review-banner">
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: "var(--ink)" }}>
              {reviewsDue} thẻ đến hạn ôn hôm nay
            </div>
            <div style={{ fontSize: 14, color: "var(--ink-2)", marginTop: 2 }}>
              Ôn tập ngắt quãng vài phút để giữ trí nhớ dài hạn và chuỗi học tập.
            </div>
          </div>
          <span className="btn btn-secondary btn-sm">Ôn ngay</span>
        </Link>
      )}
    </div>
  );
}
