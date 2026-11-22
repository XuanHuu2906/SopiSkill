"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { fetchCourses, type CourseListItem } from "@/lib/api";
import { useAuth, useLogout, useSessionQueryKey } from "@/app/providers";
import Icon, { type IconName } from "../ui/Icon";
import { ProgressRing } from "../ui/Progress";
import ThemeToggle from "./ThemeToggle";
import TabBar from "./TabBar";

const NAV: { href: string; label: string; icon: IconName; match: (p: string) => boolean }[] = [
  { href: "/", label: "Trang chủ", icon: "home", match: (p) => p === "/" },
  { href: "/new", label: "Khóa học mới", icon: "plus", match: (p) => p.startsWith("/new") },
  { href: "/sources", label: "Tài liệu", icon: "book", match: (p) => p.startsWith("/sources") },
  { href: "/review", label: "Ôn tập", icon: "sparkle", match: (p) => p.startsWith("/review") },
];

function courseIsActive(pathname: string, courseId: string) {
  return pathname.startsWith(`/course/${courseId}`) || pathname.startsWith(`/lesson/`);
}

function CourseRow({
  course,
  active,
}: {
  course: CourseListItem;
  active: boolean;
}) {
  return (
    <Link
      href={`/course/${course.id}`}
      className={`nav-row${active ? " is-active" : ""}`}
      aria-label={`${course.topic}, đã học ${course.progress.percent}%`}
    >
      <ProgressRing
        percent={course.progress.percent}
        size={22}
        thickness={3}
        label={`${course.progress.percent}%`}
      />
      <span className="nav-course-title">{course.topic}</span>
    </Link>
  );
}

export default function AppFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const { data: user, isLoading } = useAuth();
  const logout = useLogout();
  const coursesKey = useSessionQueryKey("courses", { limit: 5 });
  const courses = useQuery({
    queryKey: coursesKey,
    queryFn: () => fetchCourses(5, 0),
    enabled: !!user,
    retry: false,
  });

  if (pathname === "/login") {
    return (
      <div className="auth-shell">
        <main>{children}</main>
      </div>
    );
  }

  // Anonymous visitors get the marketing surface on "/" — there is no sidebar
  // and no tab bar until a session exists.
  if (pathname === "/" && (isLoading || !user)) {
    return (
      <div className="app-shell is-marketing">
        <main className="app-content">{children}</main>
      </div>
    );
  }

  const activeCourseId = courses.data?.items.find((c) => courseIsActive(pathname, c.id))?.id ?? null;
  const focusMode = pathname.startsWith("/lesson/");

  return (
    <div className={`app-shell${focusMode ? " is-focus" : ""}`}>
      <nav className="side-nav" aria-label="Điều hướng chính">
        <Link href="/" className="side-nav-brand">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          SopiSkill
        </Link>

        <div className="side-nav-group">
          {NAV.map((item) => {
            const active = item.match(pathname);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-row${active ? " is-active" : ""}`}
                aria-current={active ? "page" : undefined}
              >
                <span className="nav-glyph" aria-hidden="true">
                  <Icon name={item.icon} size={22} />
                </span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>

        {user && courses.data && courses.data.items.length > 0 && (
          <div className="side-nav-group">
            <span className="side-nav-label">Khóa học của bạn</span>
            {courses.data.items.map((course) => (
              <CourseRow key={course.id} course={course} active={course.id === activeCourseId} />
            ))}
          </div>
        )}

        <div className="nav-spacer" />

        {user && (
          <div className="side-nav-group">
            <span className="side-nav-label" style={{ paddingBottom: 0 }}>
              {user.displayName}
            </span>
            <span className="side-nav-label" style={{ paddingTop: 0 }}>
              {user.xp} XP
            </span>
          </div>
        )}

        <div className="side-nav-footer">
          <ThemeToggle />
          {user && (
            <button type="button" className="nav-row" onClick={() => void logout()}>
              <span className="nav-glyph" aria-hidden="true">
                <Icon name="person" size={22} />
              </span>
              <span>Đăng xuất</span>
            </button>
          )}
        </div>
      </nav>

      <main className="app-content">{children}</main>

      {!focusMode && <TabBar />}
    </div>
  );
}
