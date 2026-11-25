"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  deleteMe,
  fetchMeStats,
  fetchMyIdentities,
  fetchNotificationPreferences,
  registerWebPush,
  unregisterWebPush,
  updateMe,
  updateNotificationPreferences,
} from "@/lib/api";
import { useLogout, useRequireAuth, useSessionQueryKey } from "../providers";
import { useI18n } from "@/components/i18n/I18nProvider";
import { LANGUAGE_OPTIONS, type SupportedLanguage } from "@/components/i18n/dictionaries";
import AvatarSheet, { AvatarBadge, type AvatarId } from "@/components/auth/AvatarSheet";
import { Button } from "@/components/ui/Button";
import ThemeToggle from "@/components/layout/ThemeToggle";

const REMINDER_SLOTS: { minutes: number; label: string }[] = Array.from({ length: 96 }, (_, i) => {
  const m = i * 15;
  const hh = String(Math.floor(m / 60)).padStart(2, "0");
  const mm = String(m % 60).padStart(2, "0");
  return { minutes: m, label: `${hh}:${mm}` };
});

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const logout = useLogout();
  const { user, isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const { t, appLanguage, setAppLanguage, lessonLanguage, setLessonLanguage } = useI18n();
  const statsKey = useSessionQueryKey("me-stats");
  const notifKey = useSessionQueryKey("notif-prefs");
  const identitiesKey = useSessionQueryKey("my-identities");

  const stats = useQuery({
    queryKey: statsKey,
    enabled: isAuthenticated,
    queryFn: fetchMeStats,
  });
  const notifPrefs = useQuery({
    queryKey: notifKey,
    enabled: isAuthenticated,
    queryFn: fetchNotificationPreferences,
  });
  const identities = useQuery({
    queryKey: identitiesKey,
    enabled: isAuthenticated,
    queryFn: fetchMyIdentities,
  });

  const [displayName, setDisplayName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [avatarOpen, setAvatarOpen] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);

  const [langSaving, setLangSaving] = useState(false);
  const [langSaved, setLangSaved] = useState<string | null>(null);

  const [dailyEnabled, setDailyEnabled] = useState(true);
  const [dailyMinutes, setDailyMinutes] = useState(1140);
  const [streakGuard, setStreakGuard] = useState(true);
  const [weeklyRecap, setWeeklyRecap] = useState(true);
  const [comebackNudge, setComebackNudge] = useState(true);
  const [notifSaving, setNotifSaving] = useState(false);
  const [notifStatus, setNotifStatus] = useState<string | null>(null);
  const [pushStatus, setPushStatus] = useState<string | null>(null);

  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.displayName) setDisplayName(user.displayName);
  }, [user?.displayName]);

  useEffect(() => {
    if (notifPrefs.data) {
      setDailyEnabled(notifPrefs.data.dailyReminderEnabled);
      setDailyMinutes(notifPrefs.data.dailyReminderMinutes);
      setStreakGuard(notifPrefs.data.streakGuardEnabled);
      setWeeklyRecap(notifPrefs.data.weeklyRecapEnabled);
      setComebackNudge(notifPrefs.data.comebackNudgeEnabled);
    }
  }, [notifPrefs.data]);

  async function onSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      await updateMe({ displayName });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: statsKey });
      setSaveSuccess(t("settings.saved"));
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Không cập nhật được hồ sơ.");
    } finally {
      setSaving(false);
    }
  }

  async function onSelectAvatar(nextAvatar: AvatarId) {
    setAvatarBusy(true);
    try {
      await updateMe({ avatar: nextAvatar });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: statsKey });
    } finally {
      setAvatarBusy(false);
      setAvatarOpen(false);
    }
  }

  async function onChangeAppLanguage(nextLang: SupportedLanguage) {
    setAppLanguage(nextLang);
    setLangSaving(true);
    setLangSaved(null);
    try {
      await updateMe({ appLanguage: nextLang });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      setLangSaved(t("settings.languageSaved"));
    } finally {
      setLangSaving(false);
    }
  }

  async function onChangeLessonLanguage(nextLang: SupportedLanguage) {
    setLessonLanguage(nextLang);
    setLangSaving(true);
    setLangSaved(null);
    try {
      await updateMe({ lessonLanguage: nextLang });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      setLangSaved(t("settings.languageSaved"));
    } finally {
      setLangSaving(false);
    }
  }

  async function onSaveNotifications(e: React.FormEvent) {
    e.preventDefault();
    setNotifSaving(true);
    setNotifStatus(null);
    try {
      await updateNotificationPreferences({
        dailyReminderEnabled: dailyEnabled,
        dailyReminderMinutes: dailyMinutes,
        streakGuardEnabled: streakGuard,
        weeklyRecapEnabled: weeklyRecap,
        comebackNudgeEnabled: comebackNudge,
      });
      await queryClient.invalidateQueries({ queryKey: notifKey });
      setNotifStatus(t("settings.notificationsSaved"));
    } catch (err) {
      setNotifStatus(err instanceof Error ? err.message : "Không lưu được cài đặt thông báo.");
    } finally {
      setNotifSaving(false);
    }
  }

  async function onToggleWebPush() {
    setPushStatus(null);
    if (notifPrefs.data?.webPushEnabled) {
      await unregisterWebPush();
      await queryClient.invalidateQueries({ queryKey: notifKey });
      setPushStatus("Đã tắt thông báo Web Push.");
      return;
    }
    try {
      if (typeof window !== "undefined" && "serviceWorker" in navigator) {
        await navigator.serviceWorker.register("/sw.js");
      }
      await registerWebPush({
        endpoint: `https://push.sopiskill.local/sub/${crypto.randomUUID()}`,
        p256dh: "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
        auth: "tBHItJI5svbpez7KI4CCXg",
      });
      await queryClient.invalidateQueries({ queryKey: notifKey });
      setPushStatus("Đã đăng ký Service Worker & Web Push.");
    } catch (err) {
      setPushStatus(err instanceof Error ? err.message : "Không thể đăng ký Web Push.");
    }
  }

  async function onDeleteAccount(e: React.FormEvent) {
    e.preventDefault();
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteMe({
        confirmText: deleteConfirm,
        password: deletePassword || undefined,
      });
      queryClient.clear();
      router.replace("/login");
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Không thể xóa tài khoản.");
      setDeleting(false);
    }
  }

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const currentAvatar = (user?.avatar as AvatarId | undefined) ?? "happy";
  const initial = (user?.displayName?.trim()[0] ?? "S").toUpperCase();

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", display: "grid", gap: 24 }}>
      <div>
        <span className="eyebrow">{t("settings.eyebrow")}</span>
        <h1 className="page-title" style={{ marginTop: 4 }} data-testid="settings-heading">
          {t("settings.title")}
        </h1>
      </div>

      <section className="list-group" aria-label={t("settings.stats")}>
        <span className="list-group-title">{t("settings.stats")}</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          {stats.isLoading && <p className="muted">Đang tải thống kê…</p>}
          {stats.isError && (
            <div className="error-box" role="alert">
              Không tải được thống kê: {stats.error.message}
            </div>
          )}
          {stats.data && (
            <div className="stat-strip" style={{ margin: 0 }}>
              <div className="stat-item">
                <div className="stat-value">{stats.data.xp}</div>
                <div className="stat-caption">Tổng XP</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">
                  {stats.data.coursesReady}/{stats.data.coursesTotal}
                </div>
                <div className="stat-caption">Khóa học sẵn sàng</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">
                  {stats.data.lessonsCompleted}/{stats.data.lessonsTotal}
                </div>
                <div className="stat-caption">Bài hoàn thành</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.data.attemptsTotal}</div>
                <div className="stat-caption">Lượt làm bài</div>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.profile")}>
        <span className="list-group-title">{t("settings.profile")}</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
            <AvatarBadge avatar={currentAvatar} initial={initial} size={48} />
            <Button variant="secondary" size="sm" onClick={() => setAvatarOpen(true)}>
              {t("settings.changeAvatar")}
            </Button>
          </div>
          <form onSubmit={(e) => void onSaveProfile(e)} style={{ display: "grid", gap: 14 }}>
            <div className="field">
              <label htmlFor="settings-email">Email</label>
              <input id="settings-email" type="email" value={user?.email ?? "—"} disabled />
            </div>
            <div className="field">
              <label htmlFor="settings-display-name">{t("settings.displayName")}</label>
              <input
                id="settings-display-name"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                maxLength={80}
                required
              />
            </div>
            {saveSuccess && <div className="success-box">{saveSuccess}</div>}
            {saveError && (
              <div className="error-box" role="alert">
                {saveError}
              </div>
            )}
            <div>
              <Button type="submit" size="md" disabled={saving || !displayName.trim()}>
                {saving ? t("settings.saving") : t("settings.saveChanges")}
              </Button>
            </div>
          </form>
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.languageSection")}>
        <span className="list-group-title">{t("settings.languageSection")}</span>
        <div className="list-group-card" style={{ padding: 20, display: "grid", gap: 14 }}>
          <div className="field">
            <label htmlFor="settings-app-language">{t("settings.appLanguage")}</label>
            <select
              id="settings-app-language"
              data-testid="app-language-select"
              value={appLanguage}
              disabled={langSaving}
              onChange={(e) => void onChangeAppLanguage(e.target.value as SupportedLanguage)}
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.code} value={opt.code}>
                  {opt.nativeLabel} ({opt.code})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="settings-lesson-language">{t("settings.lessonLanguage")}</label>
            <select
              id="settings-lesson-language"
              data-testid="lesson-language-select"
              value={lessonLanguage}
              disabled={langSaving}
              onChange={(e) => void onChangeLessonLanguage(e.target.value as SupportedLanguage)}
            >
              <option value="vi">Tiếng Việt (vi)</option>
              <option value="en">English (en)</option>
            </select>
          </div>
          <p className="caption" style={{ margin: 0 }}>
            {t("settings.languageNote")}
          </p>
          {langSaved && <div className="success-box">{langSaved}</div>}
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.notifications")}>
        <span className="list-group-title">{t("settings.notifications")}</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          <form onSubmit={(e) => void onSaveNotifications(e)} style={{ display: "grid", gap: 12 }}>
            <div className="field">
              <label htmlFor="settings-reminder-time">{t("settings.reminderTime")}</label>
              <select
                id="settings-reminder-time"
                value={dailyMinutes}
                onChange={(e) => setDailyMinutes(Number(e.target.value))}
              >
                {REMINDER_SLOTS.map((slot) => (
                  <option key={slot.minutes} value={slot.minutes}>
                    {slot.label}
                  </option>
                ))}
              </select>
            </div>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={dailyEnabled}
                onChange={(e) => setDailyEnabled(e.target.checked)}
              />
              <span>{t("settings.dailyReminder")}</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={streakGuard}
                onChange={(e) => setStreakGuard(e.target.checked)}
              />
              <span>{t("settings.streakGuard")}</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={weeklyRecap}
                onChange={(e) => setWeeklyRecap(e.target.checked)}
              />
              <span>{t("settings.weeklyRecap")}</span>
            </label>
            <label className="toggle-row">
              <input
                type="checkbox"
                checked={comebackNudge}
                onChange={(e) => setComebackNudge(e.target.checked)}
              />
              <span>{t("settings.comebackNudge")}</span>
            </label>
            <p className="caption" style={{ margin: "2px 0 0" }}>
              {t("settings.quietHours")}
            </p>
            {notifStatus && <div className="success-box">{notifStatus}</div>}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <Button type="submit" size="sm" disabled={notifSaving}>
                {t("settings.saveNotifications")}
              </Button>
              <Button type="button" variant="secondary" size="sm" onClick={() => void onToggleWebPush()}>
                {notifPrefs.data?.webPushEnabled ? "Tắt Web Push" : t("settings.webPush")}
              </Button>
            </div>
            {pushStatus && <p className="caption" style={{ margin: 0 }}>{pushStatus}</p>}
          </form>
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.identities")}>
        <span className="list-group-title">{t("settings.identities")}</span>
        <div className="list-group-card" style={{ padding: 20, display: "grid", gap: 12 }}>
          <p className="muted" style={{ margin: 0, fontSize: 14 }}>
            {identities.data && identities.data.total > 0
              ? `Đã liên kết: ${identities.data.items.map((i) => i.provider).join(", ")}`
              : "Chưa liên kết tài khoản Google/Apple."}
          </p>
          <div>
            <Button type="button" variant="secondary" size="sm" onClick={() => void logout(true)}>
              {t("settings.logoutAll")}
            </Button>
          </div>
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.appearance")}>
        <span className="list-group-title">{t("settings.appearance")}</span>
        <div className="list-group-card" style={{ padding: 16 }}>
          <ThemeToggle />
        </div>
      </section>

      <section className="list-group" aria-label={t("settings.deleteAccount")}>
        <span className="list-group-title">{t("settings.dangerZone")}</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          <h2 className="section-title" style={{ fontSize: 18, marginBottom: 8 }}>
            {t("settings.deleteAccount")}
          </h2>
          <p className="muted" style={{ marginBottom: 14, fontSize: 15 }}>
            Hành động này xóa vĩnh viễn tài khoản cùng toàn bộ khóa học, bài học, lượt làm bài,
            lịch sử trợ giảng và tài liệu bạn đã tải lên. Không thể hoàn tác.
          </p>
          <form onSubmit={(e) => void onDeleteAccount(e)} style={{ display: "grid", gap: 12 }}>
            <div className="field">
              <label htmlFor="delete-password">Mật khẩu hiện tại</label>
              <input
                id="delete-password"
                type="password"
                autoComplete="current-password"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                placeholder="Nhập mật khẩu để xác nhận"
              />
            </div>
            <div className="field">
              <label htmlFor="delete-confirm">
                Nhập chính xác <code>DELETE</code> để xác nhận
              </label>
              <input
                id="delete-confirm"
                type="text"
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                placeholder="DELETE"
                required
              />
            </div>
            {deleteError && (
              <div className="error-box" role="alert">
                {deleteError}
              </div>
            )}
            <div>
              <Button
                type="submit"
                variant="danger"
                size="md"
                disabled={deleting || deleteConfirm.trim().toUpperCase() !== "DELETE"}
              >
                {deleting ? "Đang xóa tài khoản…" : "Xóa vĩnh viễn tài khoản"}
              </Button>
            </div>
          </form>
        </div>
      </section>

      <AvatarSheet
        open={avatarOpen}
        currentAvatar={currentAvatar}
        busy={avatarBusy}
        onSelect={(av) => void onSelectAvatar(av)}
        onClose={() => setAvatarOpen(false)}
      />
    </div>
  );
}
