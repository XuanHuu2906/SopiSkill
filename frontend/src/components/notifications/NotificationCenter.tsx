"use client";

import Link from "next/link";
import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchNotificationInbox,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/lib/api";
import { useSessionQueryKey } from "@/app/providers";
import { useI18n } from "@/components/i18n/I18nProvider";
import { Button, IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import useModalPanel from "@/components/ui/useModalPanel";

export default function NotificationCenter({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const queryClient = useQueryClient();
  const inboxKey = useSessionQueryKey("notifications-inbox");

  useModalPanel({ open, onClose, panelRef });

  const inbox = useQuery({
    queryKey: inboxKey,
    enabled: open,
    queryFn: () => fetchNotificationInbox(20),
    retry: false,
  });

  const markOne = useMutation({
    mutationFn: (id: string) => markNotificationRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inboxKey }),
  });

  const markAll = useMutation({
    mutationFn: () => markAllNotificationsRead(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: inboxKey }),
  });

  if (!open) return null;

  const items = inbox.data?.items ?? [];

  return (
    <>
      <button
        type="button"
        className="tutor-backdrop"
        aria-label="Đóng thông báo"
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        className="tutor-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="notif-center-heading"
        ref={panelRef}
        tabIndex={-1}
      >
        <div className="tutor-head">
          <div>
            <div id="notif-center-heading" className="tutor-title">
              {t("notifications.title")}
            </div>
            <div className="tutor-subtitle">
              {inbox.data ? `${inbox.data.unreadCount} chưa đọc` : ""}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {items.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => markAll.mutate()}
                disabled={markAll.isPending}
              >
                {t("notifications.markAll")}
              </Button>
            )}
            <IconButton aria-label="Đóng" onClick={onClose}>
              <Icon name="close" size={18} />
            </IconButton>
          </div>
        </div>

        <div className="notif-list">
          {inbox.isLoading && <p className="muted">Đang tải…</p>}
          {!inbox.isLoading && items.length === 0 && (
            <p className="muted" style={{ padding: "16px 0" }}>
              {t("notifications.empty")}
            </p>
          )}
          {items.map((item) => (
            <div key={item.id} className={`notif-item${item.read ? "" : " is-unread"}`}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="notif-item-title">{item.title}</div>
                <p className="notif-item-body">{item.body}</p>
                <div style={{ display: "flex", gap: 12, marginTop: 6, alignItems: "center" }}>
                  {item.actionUrl && (
                    <Link
                      href={item.actionUrl}
                      className="link"
                      style={{ fontSize: 13, fontWeight: 600 }}
                      onClick={() => {
                        if (!item.read) markOne.mutate(item.id);
                        onClose();
                      }}
                    >
                      Mở →
                    </Link>
                  )}
                  {!item.read && (
                    <button
                      type="button"
                      className="link-btn"
                      style={{ fontSize: 12 }}
                      onClick={() => markOne.mutate(item.id)}
                    >
                      Đánh dấu đã đọc
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
