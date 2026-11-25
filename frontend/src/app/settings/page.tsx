"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { deleteMe, fetchMeStats, updateMe } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../providers";
import { Button } from "@/components/ui/Button";
import ThemeToggle from "@/components/layout/ThemeToggle";

export default function SettingsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const statsKey = useSessionQueryKey("me-stats");

  const stats = useQuery({
    queryKey: statsKey,
    enabled: isAuthenticated,
    queryFn: fetchMeStats,
  });

  const [displayName, setDisplayName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.displayName) {
      setDisplayName(user.displayName);
    }
  }, [user?.displayName]);

  async function onSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      await updateMe(displayName);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      await queryClient.invalidateQueries({ queryKey: statsKey });
      setSaveSuccess("Đã cập nhật tên hiển thị.");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Không cập nhật được hồ sơ.");
    } finally {
      setSaving(false);
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

  return (
    <div style={{ maxWidth: 680, margin: "0 auto", display: "grid", gap: 24 }}>
      <div>
        <span className="eyebrow">Tài khoản</span>
        <h1 className="page-title" style={{ marginTop: 4 }}>
          Hồ sơ & Cài đặt
        </h1>
      </div>

      <section className="list-group" aria-label="Thống kê học tập">
        <span className="list-group-title">Thống kê học tập</span>
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

      <section className="list-group" aria-label="Tên hiển thị">
        <span className="list-group-title">Thông tin hiển thị</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          <form onSubmit={(e) => void onSaveProfile(e)} style={{ display: "grid", gap: 14 }}>
            <div className="field">
              <label htmlFor="settings-email">Email</label>
              <input id="settings-email" type="email" value={user?.email ?? "—"} disabled />
            </div>
            <div className="field">
              <label htmlFor="settings-display-name">Tên hiển thị</label>
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
                {saving ? "Đang lưu…" : "Lưu thay đổi"}
              </Button>
            </div>
          </form>
        </div>
        <span className="list-group-footer">
          Hiển thị ở lời chào trang chủ và trang hồ sơ của bạn.
        </span>
      </section>

      <section className="list-group" aria-label="Giao diện hiển thị">
        <span className="list-group-title">Giao diện</span>
        <div className="list-group-card" style={{ padding: 16 }}>
          <ThemeToggle />
        </div>
      </section>

      <section className="list-group" aria-label="Xóa tài khoản">
        <span className="list-group-title">Khu vực nguy hiểm</span>
        <div className="list-group-card" style={{ padding: 20 }}>
          <h2 className="section-title" style={{ fontSize: 18, marginBottom: 8 }}>
            Xóa tài khoản
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
    </div>
  );
}
