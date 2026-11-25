"use client";

import { useRef, useState } from "react";
import { ApiError, confirmAccountLink } from "@/lib/api";
import { Button, IconButton } from "@/components/ui/Button";
import { TextInput } from "@/components/ui/Field";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";

export default function LinkAccountSheet({
  open,
  provider,
  email,
  linkTicket,
  onLinked,
  onClose,
}: {
  open: boolean;
  provider: string;
  email: string;
  linkTicket: string;
  onLinked: () => Promise<void> | void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useModalPanel({ open, onClose, panelRef });

  if (!open) return null;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await confirmAccountLink(linkTicket, password);
      await onLinked();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không thể liên kết tài khoản.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng hộp thoại liên kết"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="modal-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-account-heading"
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div>
            <div id="link-account-heading" className="tutor-title">
              Xác nhận liên kết tài khoản
            </div>
            <div className="tutor-subtitle">
              {email} · {provider}
            </div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>
        <p className="muted" style={{ marginTop: 12, fontSize: 14 }}>
          Email <strong>{email}</strong> đã tồn tại trên SopiSkill. Để chống chiếm quyền tài khoản,
          hãy nhập mật khẩu hiện tại để xác nhận liên kết với {provider}.
        </p>
        <form onSubmit={(e) => void onSubmit(e)} style={{ display: "grid", gap: 12, marginTop: 12 }}>
          <TextInput
            id="link-account-password"
            label="Mật khẩu tài khoản hiện có"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          {error && (
            <div className="error-box" role="alert">
              {error}
            </div>
          )}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <Button type="button" variant="secondary" size="sm" onClick={onClose}>
              Hủy
            </Button>
            <Button type="submit" size="sm" disabled={busy || !password}>
              {busy ? "Đang xác nhận…" : "Xác nhận liên kết"}
            </Button>
          </div>
        </form>
      </div>
    </>
  );
}
