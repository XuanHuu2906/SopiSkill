"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchCourses,
  fetchMeStats,
  fetchNotificationInbox,
  type CourseListItem,
} from "@/lib/api";
import { useAuth, useLogout, useSessionQueryKey } from "@/app/providers";
import { useI18n } from "@/components/i18n/I18nProvider";
import type { I18nKey } from "@/components/i18n/dictionaries";
import { AvatarBadge } from "@/components/auth/AvatarSheet";
import NotificationCenter from "@/components/notifications/NotificationCenter";
import OfflineBar from "@/components/offline/OfflineBar";
import Icon, { type IconName } from "../ui/Icon";
import { ProgressRing } from "../ui/Progress";
import { useTheme } from "./ThemeProvider";
import { SopiContext } from "./SopiContext";
import GlobalSopiSheet from "../tutor/GlobalSopiSheet";
import TabBar from "./TabBar";

const NAV: { href: string; labelKey: I18nKey; icon: IconName; match: (p: string) => boolean }[] = [
  { href: "/", labelKey: "nav.home", icon: "home", match: (p) => p === "/" },
  { href: "/new", labelKey: "nav.new", icon: "plus", match: (p) => p.startsWith("/new") },
  { href: "/sources", labelKey: "nav.sources", icon: "book", match: (p) => p.startsWith("/sources") },
  { href: "/review", labelKey: "nav.review", icon: "sparkle", match: (p) => p.startsWith("/review") },
  { href: "/profile", labelKey: "nav.profile", icon: "person", match: (p) => p.startsWith("/profile") },
];

function courseIsActive(pathname: string, courseId: string) {
  return pathname === `/course/${courseId}` || pathname.startsWith(`/course/${courseId}/`);
}

function courseHref(course: { id: string; status?: string }) {
  if (course.status === "interviewing") {
    return `/new/interview?courseId=${encodeURIComponent(course.id)}`;
  }
  if (course.status === "proposal_ready") {
    return `/new/proposal?courseId=${encodeURIComponent(course.id)}`;
  }
  return `/course/${course.id}`;
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
      href={courseHref(course)}
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
  const { preference, toggle } = useTheme();
  const { t } = useI18n();
  const [sopiOpen, setSopiOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [sopiCourseId, setSopiCourseId] = useState<string | null>(null);
  const coursesKey = useSessionQueryKey("courses", { limit: 10 });
  const statsKey = useSessionQueryKey("me-stats");
  const inboxKey = useSessionQueryKey("notifications-inbox");

  const courses = useQuery({
    queryKey: coursesKey,
    queryFn: () => fetchCourses(10, 0),
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
  const inbox = useQuery({
    queryKey: inboxKey,
    queryFn: () => fetchNotificationInbox(10),
    enabled: !!user,
    retry: false,
    staleTime: 30_000,
  });

  const openSopi = useCallback((courseId?: string | null) => {
    setSopiCourseId(courseId ?? null);
    setSopiOpen(true);
  }, []);

  const closeSopi = useCallback(() => {
    setSopiOpen(false);
  }, []);

  useEffect(() => {
    if (pathname.startsWith("/lesson/")) {
      setSopiOpen(false);
      setNotifOpen(false);
    }
  }, [pathname]);

  if (pathname === "/login") {
    return (
      <div className="auth-shell">
        <main>{children}</main>
      </div>
    );
  }

  if (pathname === "/" && (isLoading || !user)) {
    return (
      <div className="app-shell is-marketing">
        <main className="app-content">
          <OfflineBar />
          {children}
        </main>
      </div>
    );
  }

  const activeCourseId = courses.data?.items.find((c) => courseIsActive(pathname, c.id))?.id ?? null;
  const focusMode = pathname.startsWith("/lesson/");
  const isDark = preference === "dark";
  const initial = (user?.displayName?.trim()[0] ?? "S").toUpperCase();
  const streakDays = stats.data?.streakDays ?? 0;
  const xpTotal = stats.data?.xp ?? user?.xp ?? 0;
  const unreadNotifs = inbox.data?.unreadCount ?? 0;

  return (
    <SopiContext.Provider value={{ open: sopiOpen, openSopi, closeSopi }}>
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
              const active = !sopiOpen && !notifOpen && item.match(pathname);
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
                  <span>{t(item.labelKey)}</span>
                </Link>
              );
            })}
            {user && (
              <>
                <button
                  type="button"
                  className={`nav-row${sopiOpen ? " is-active" : ""}`}
                  aria-expanded={sopiOpen}
                  onClick={() => openSopi(activeCourseId)}
                >
                  <span className="nav-glyph" aria-hidden="true">
                    <Icon name="chat" size={22} />
                  </span>
                  <span>{t("nav.askSopi")}</span>
                </button>
                <button
                  type="button"
                  className={`nav-row${notifOpen ? " is-active" : ""}`}
                  aria-expanded={notifOpen}
                  onClick={() => setNotifOpen(true)}
                >
                  <span className="nav-glyph" aria-hidden="true">
                    <Icon name="bell" size={22} />
                  </span>
                  <span style={{ flex: 1, textAlign: "left" }}>{t("nav.notifications")}</span>
                  {unreadNotifs > 0 && (
                    <span className="notif-badge" aria-label={`${unreadNotifs} thông báo mới`}>
                      {unreadNotifs}
                    </span>
                  )}
                </button>
              </>
            )}
          </div>

          {user && courses.data && courses.data.items.length > 0 && (
            <div className="side-nav-group">
              <span className="side-nav-label">{t("nav.yourCourses")}</span>
              {courses.data.items.slice(0, 5).map((course) => (
                <CourseRow key={course.id} course={course} active={course.id === activeCourseId} />
              ))}
            </div>
          )}

          <div className="nav-spacer" />

          {user && (
            <div className="side-stats-card" aria-label="Thống kê hằng ngày">
              <Link href="/profile" className="side-stats-user">
                <AvatarBadge avatar={user.avatar} initial={initial} size={30} />
                <span className="side-stats-name">{user.displayName}</span>
              </Link>
              <div className="side-stats-pills">
                <Link
                  href="/profile"
                  className="side-stat-pill"
                  aria-label={`Chuỗi ${streakDays} ngày`}
                >
                  <Icon name="flame" size={16} />
                  <span>{streakDays} ngày</span>
                </Link>
                <Link href="/profile" className="side-stat-pill" aria-label={`${xpTotal} XP`}>
                  <Icon name="bolt" size={16} />
                  <span>{xpTotal} XP</span>
                </Link>
              </div>
            </div>
          )}

          <div className="side-nav-footer">
            <button type="button" className="nav-row" onClick={toggle}>
              <span className="nav-glyph" aria-hidden="true">
                <Icon name={isDark ? "sun" : "moon"} size={22} />
              </span>
              <span>{isDark ? t("nav.lightMode") : t("nav.darkMode")}</span>
            </button>
            <Link
              href="/settings"
              className={`nav-row${pathname.startsWith("/settings") ? " is-active" : ""}`}
              aria-current={pathname.startsWith("/settings") ? "page" : undefined}
            >
              <span className="nav-glyph" aria-hidden="true">
                <Icon name="settings" size={22} />
              </span>
              <span>{t("nav.settings")}</span>
            </Link>
            {user && (
              <button type="button" className="nav-row" onClick={() => void logout(false)}>
                <span className="nav-glyph" aria-hidden="true">
                  <Icon name="logout" size={22} />
                </span>
                <span>{t("nav.logout")}</span>
              </button>
            )}
          </div>
        </nav>

        <main className="app-content">
          <OfflineBar />
          {children}
        </main>

        {!focusMode && <TabBar />}

        {user && !focusMode && (
          <>
            <GlobalSopiSheet
              open={sopiOpen}
              onClose={closeSopi}
              courses={courses.data?.items ?? []}
              initialCourseId={sopiCourseId ?? activeCourseId}
            />
            <NotificationCenter open={notifOpen} onClose={() => setNotifOpen(false)} />
          </>
        )}
      </div>
    </SopiContext.Provider>
  );
}
