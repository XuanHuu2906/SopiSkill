"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { deleteMe, fetchMeStats, updateMe } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../providers";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

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
    <div style={{ maxWidth: 680, margin: "0 auto", display: "grid", gap: 18 }}>
      <div>
        <span className="eyebrow">Tài khoản</span>
        <h1 className="section-title" style={{ marginTop: 4 }}>
          Hồ sơ & Cài đặt
        </h1>
      </div>

      <Card>
        <h2 className="section-title" style={{ fontSize: 18, marginBottom: 12 }}>
          Thống kê học tập
        </h2>
        {stats.isLoading && <p className="muted">Đang tải thống kê…</p>}
        {stats.isError && (
          <div className="error-box" role="alert">
            Không tải được thống kê: {stats.error.message}
          </div>
        )}
        {stats.data && (
          <div className="stat-strip">
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
      </Card>

      <Card>
        <h2 className="section-title" style={{ fontSize: 18, marginBottom: 12 }}>
          Thông tin hiển thị
        </h2>
        <form onSubmit={(e) => void onSaveProfile(e)} style={{ display: "grid", gap: 12 }}>
          <div>
            <label htmlFor="settings-email" className="caption">
              Email
            </label>
            <input id="settings-email" value={user?.email ?? "—"} disabled />
          </div>
          <div>
            <label htmlFor="settings-display-name" className="caption">
              Tên hiển thị
            </label>
            <input
              id="settings-display-name"
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
            <Button type="submit" disabled={saving || !displayName.trim()}>
              {saving ? "Đang lưu…" : "Lưu thay đổi"}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <h2 className="section-title" style={{ fontSize: 18, marginBottom: 8 }}>
          Xóa tài khoản
        </h2>
        <p className="muted" style={{ marginBottom: 12 }}>
          Hành động này xóa vĩnh viễn tài khoản cùng toàn bộ khóa học, bài học, lượt làm bài,
          lịch sử trợ giảng và tài liệu bạn đã tải lên. Không thể hoàn tác.
        </p>
        <form onSubmit={(e) => void onDeleteAccount(e)} style={{ display: "grid", gap: 12 }}>
          <div>
            <label htmlFor="delete-password" className="caption">
              Mật khẩu hiện tại
            </label>
            <input
              id="delete-password"
              type="password"
              autoComplete="current-password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              placeholder="Nhập mật khẩu để xác nhận"
            />
          </div>
          <div>
            <label htmlFor="delete-confirm" className="caption">
              Nhập chính xác <code>DELETE</code> để xác nhận
            </label>
            <input
              id="delete-confirm"
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
              variant="secondary"
              disabled={deleting || deleteConfirm.trim().toUpperCase() !== "DELETE"}
            >
              {deleting ? "Đang xóa tài khoản…" : "Xóa vĩnh viễn tài khoản"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
