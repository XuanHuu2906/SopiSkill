"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { fetchCourses, fetchMeStats } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../providers";
import { ButtonLink } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { ProgressRing } from "@/components/ui/Progress";
import { Skeleton, SkeletonStack } from "@/components/ui/Skeleton";

function formatJoined(iso: string | null | undefined): string {
  if (!iso) return "Thành viên SopiSkill";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Thành viên SopiSkill";
  return `Tham gia tháng ${d.getMonth() + 1}/${d.getFullYear()}`;
}

export default function ProfilePage() {
  const { user, isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const statsKey = useSessionQueryKey("me-stats");
  const coursesKey = useSessionQueryKey("courses", { limit: 20 });

  const stats = useQuery({
    queryKey: statsKey,
    enabled: isAuthenticated,
    queryFn: fetchMeStats,
  });

  const courses = useQuery({
    queryKey: coursesKey,
    enabled: isAuthenticated,
    queryFn: () => fetchCourses(20, 0),
  });

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const name = stats.data?.displayName ?? user?.displayName ?? "Người học";
  const initial = (name.trim()[0] ?? "S").toUpperCase();

  return (
    <div className="profile-page">
      <header className="profile-header">
        <div className="profile-identity">
          <div className="profile-avatar" aria-hidden="true">
            {initial}
          </div>
          <div>
            <h1 className="page-title">{name}</h1>
            <p className="caption" style={{ marginTop: 4 }}>
              {formatJoined(stats.data?.createdAt)}
              {stats.data ? ` · ${stats.data.coursesTotal} khóa học` : ""}
            </p>
          </div>
        </div>
        <ButtonLink href="/settings" variant="secondary" size="md">
          <Icon name="settings" size={18} />
          Cài đặt
        </ButtonLink>
      </header>

      {stats.isLoading && (
        <div className="profile-stats-grid">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="profile-stat-tile">
              <Skeleton height={34} width={34} />
              <Skeleton height={30} width={72} />
              <Skeleton height={16} width={110} />
            </div>
          ))}
        </div>
      )}

      {stats.isError && (
        <div className="error-box" role="alert">
          Không tải được thống kê hồ sơ: {stats.error.message}
        </div>
      )}

      {stats.data && (
        <section className="profile-stats-grid" aria-label="Tổng quan học tập">
          <div className="profile-stat-tile">
            <span className="profile-stat-icon" aria-hidden="true">
              <Icon name="flame" size={18} />
            </span>
            <span className="profile-stat-value">{stats.data.streakDays}</span>
            <span className="profile-stat-label">Chuỗi ngày liên tiếp</span>
          </div>
          <div className="profile-stat-tile">
            <span className="profile-stat-icon" aria-hidden="true">
              <Icon name="bolt" size={18} />
            </span>
            <span className="profile-stat-value">{stats.data.xp.toLocaleString("vi-VN")}</span>
            <span className="profile-stat-label">Tổng XP tích lũy</span>
          </div>
          <div className="profile-stat-tile">
            <span className="profile-stat-icon" aria-hidden="true">
              <Icon name="checkCircle" size={18} />
            </span>
            <span className="profile-stat-value">
              {stats.data.lessonsCompleted}/{stats.data.lessonsTotal}
            </span>
            <span className="profile-stat-label">Bài học hoàn thành</span>
          </div>
          <div className="profile-stat-tile">
            <span className="profile-stat-icon" aria-hidden="true">
              <Icon name="learn" size={18} />
            </span>
            <span className="profile-stat-value">
              {stats.data.coursesReady}/{stats.data.coursesTotal}
            </span>
            <span className="profile-stat-label">Khóa học sẵn sàng</span>
          </div>
        </section>
      )}

      <section aria-labelledby="profile-courses-heading">
        <div className="section-head">
          <h2 id="profile-courses-heading" className="section-title">
            Tiến độ khóa học
          </h2>
          <Link href="/new" className="link" style={{ fontSize: 15, fontWeight: 600 }}>
            Khóa học mới
          </Link>
        </div>

        {courses.isLoading && <SkeletonStack rows={3} />}
        {courses.data && courses.data.items.length === 0 && (
          <p className="muted">Bạn chưa có khóa học nào. Bắt đầu tạo khóa đầu tiên nhé.</p>
        )}
        {courses.data && courses.data.items.length > 0 && (
          <div className="course-grid">
            {courses.data.items.map((course) => (
              <Link key={course.id} href={`/course/${course.id}`} className="course-card">
                <ProgressRing
                  percent={course.progress.percent}
                  size={52}
                  thickness={4}
                  label={`${course.progress.percent}%`}
                />
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span className="course-card-title" style={{ display: "block" }}>
                    {course.topic}
                  </span>
                  <span className="course-card-meta" style={{ display: "block" }}>
                    {course.progress.completed}/{course.progress.total} bài ·{" "}
                    {course.progress.percent}%
                  </span>
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="list-group" aria-label="Lối tắt tài khoản">
        <span className="list-group-title">Quản lý học tập</span>
        <div className="list-group-card">
          <Link href="/review" className="list-group-row">
            <Icon name="sparkle" size={20} />
            <span style={{ flex: 1 }}>Ôn tập ngắt quãng</span>
            {stats.data && stats.data.reviewsDue > 0 && (
              <span className="caption" style={{ color: "var(--ember-deep)", fontWeight: 600 }}>
                {stats.data.reviewsDue} đến hạn
              </span>
            )}
            <Icon name="arrowRight" size={18} />
          </Link>
          <Link href="/sources" className="list-group-row">
            <Icon name="book" size={20} />
            <span style={{ flex: 1 }}>Thư viện tài liệu nguồn</span>
            <Icon name="arrowRight" size={18} />
          </Link>
          <Link href="/settings" className="list-group-row">
            <Icon name="settings" size={20} />
            <span style={{ flex: 1 }}>Cài đặt tài khoản & giao diện</span>
            <Icon name="arrowRight" size={18} />
          </Link>
        </div>
      </section>
    </div>
  );
}
