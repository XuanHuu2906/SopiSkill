"use client";

import { useRef } from "react";
import { Button, IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";

export type AvatarId = "happy" | "graduate" | "curious" | "wink" | "excited";

export const AVATAR_OPTIONS: { id: AvatarId; label: string; bg: string; fg: string; glyph: string }[] = [
  { id: "happy", label: "Vui vẻ", bg: "#6746d9", fg: "#ffffff", glyph: "◡" },
  { id: "graduate", label: "Học giả", bg: "#2d7a4f", fg: "#ffffff", glyph: "★" },
  { id: "curious", label: "Tò mò", bg: "#0f766e", fg: "#ffffff", glyph: "?" },
  { id: "wink", label: "Nháy mắt", bg: "#b45309", fg: "#ffffff", glyph: "✦" },
  { id: "excited", label: "Hào hứng", bg: "#be185d", fg: "#ffffff", glyph: "!" },
];

export function AvatarBadge({
  avatar,
  initial,
  size = 44,
}: {
  avatar?: string | null;
  initial: string;
  size?: number;
}) {
  const preset = AVATAR_OPTIONS.find((a) => a.id === avatar) ?? AVATAR_OPTIONS[0];
  return (
    <span
      className="avatar-badge"
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        backgroundColor: preset.bg,
        color: preset.fg,
        fontSize: Math.round(size * 0.44),
      }}
    >
      {avatar ? preset.glyph : initial}
    </span>
  );
}

export default function AvatarSheet({
  open,
  currentAvatar,
  busy,
  onSelect,
  onClose,
}: {
  open: boolean;
  currentAvatar: AvatarId;
  busy?: boolean;
  onSelect: (avatar: AvatarId) => void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  useModalPanel({ open, onClose, panelRef });

  if (!open) return null;

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng chọn ảnh đại diện"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="modal-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-sheet-heading"
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div>
            <div id="avatar-sheet-heading" className="tutor-title">
              Chọn ảnh đại diện
            </div>
            <div className="tutor-subtitle">5 phong cách Sopi</div>
          </div>
          <IconButton aria-label="Đóng" onClick={onClose}>
            <Icon name="close" size={18} />
          </IconButton>
        </div>
        <div className="avatar-grid">
          {AVATAR_OPTIONS.map((opt) => {
            const active = opt.id === currentAvatar;
            return (
              <button
                key={opt.id}
                type="button"
                className={`avatar-option${active ? " is-active" : ""}`}
                aria-pressed={active}
                disabled={busy}
                onClick={() => onSelect(opt.id)}
              >
                <AvatarBadge avatar={opt.id} initial="S" size={48} />
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>
        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Xong
          </Button>
        </div>
      </div>
    </>
  );
}
