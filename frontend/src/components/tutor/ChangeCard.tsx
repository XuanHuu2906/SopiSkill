"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  confirmTutorAction,
  declineTutorAction,
  fetchTutorAction,
  type TutorAction,
} from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

/**
 * Sopi `ChangeCard` for `regenerate_unit` confirmation workflow:
 *   pending -> confirm -> preparing (poll 5s) -> ready | failed
 *   pending -> decline -> declined
 */
export default function ChangeCard({
  courseId,
  initialAction,
  onReady,
}: {
  courseId: string;
  initialAction: TutorAction;
  onReady?: () => void;
}) {
  const actionId = initialAction.actionId || initialAction.id || "";
  const [action, setAction] = useState<TutorAction>(initialAction);
  const [err, setErr] = useState<string | null>(null);

  const pollQuery = useQuery({
    queryKey: ["tutor-action", courseId, actionId],
    enabled: Boolean(actionId) && action.status === "preparing",
    queryFn: () => fetchTutorAction(courseId, actionId),
    refetchInterval: (q) => (q.state.data?.status === "preparing" ? 5000 : false),
  });

  useEffect(() => {
    if (pollQuery.data && pollQuery.data.status !== action.status) {
      setAction(pollQuery.data);
      if (pollQuery.data.status === "ready") {
        onReady?.();
      }
    }
  }, [pollQuery.data, action.status, onReady]);

  const confirmMut = useMutation({
    mutationFn: () => confirmTutorAction(courseId, actionId),
    onSuccess: (updated) => {
      setErr(null);
      setAction(updated);
      if (updated.status === "ready") onReady?.();
    },
    onError: (e) => setErr(e instanceof Error ? e.message : "Không thể xác nhận viết lại."),
  });

  const declineMut = useMutation({
    mutationFn: () => declineTutorAction(courseId, actionId),
    onSuccess: (updated) => {
      setErr(null);
      setAction(updated);
    },
    onError: (e) => setErr(e instanceof Error ? e.message : "Không thể từ chối đề xuất."),
  });

  const preview = action.preview ?? {};
  const busy = confirmMut.isPending || declineMut.isPending;

  return (
    <div
      className="change-card"
      data-action-id={actionId}
      data-action-status={action.status}
      style={{
        marginTop: 10,
        padding: 14,
        borderRadius: "var(--radius-md)",
        border: "1px solid var(--ember)",
        background: "var(--wash-soft)",
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 14, color: "var(--ink)" }}>
          Đề xuất viết lại chương{preview.unitTitle ? `: ${preview.unitTitle}` : ""}
        </strong>
        <Badge
          tone={
            action.status === "ready"
              ? "success"
              : action.status === "failed"
                ? "danger"
                : "muted"
          }
        >
          {action.status === "pending"
            ? "Chờ xác nhận"
            : action.status === "preparing"
              ? "Đang viết lại…"
              : action.status === "ready"
                ? "Đã cập nhật"
                : action.status === "declined"
                  ? "Đã từ chối"
                  : action.status}
        </Badge>
      </div>

      {preview.summary && (
        <p style={{ margin: 0, fontSize: 13.5, color: "var(--ink-2)", lineHeight: 1.5 }}>
          {preview.summary}
        </p>
      )}

      {Array.isArray(preview.changes) && preview.changes.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "var(--ink-2)", display: "grid", gap: 4 }}>
          {preview.changes.map((c, idx) => (
            <li key={idx}>{c}</li>
          ))}
        </ul>
      )}

      {err && (
        <div className="error-box" role="alert" style={{ fontSize: 13 }}>
          {err}
        </div>
      )}

      {action.status === "pending" && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button size="sm" disabled={busy} onClick={() => confirmMut.mutate()}>
            {confirmMut.isPending ? "Đang gửi…" : "Xác nhận viết lại"}
          </Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => declineMut.mutate()}>
            Từ chối
          </Button>
        </div>
      )}

      {action.status === "preparing" && (
        <p className="caption" style={{ margin: 0 }}>
          Hệ thống đang tạo lại các bài trong chương (tự cập nhật mỗi 5 giây)…
        </p>
      )}
    </div>
  );
}
