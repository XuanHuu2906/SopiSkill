"use client";

import { useOffline } from "./OfflineProvider";
import { Button } from "@/components/ui/Button";

export default function OfflineBar() {
  const { isOnline, pendingCount, syncing, syncNow } = useOffline();

  if (isOnline && pendingCount === 0 && !syncing) {
    return null;
  }

  return (
    <div
      className={`offline-bar${!isOnline ? " is-offline" : " is-syncing"}`}
      role="status"
      aria-live="polite"
      data-testid="offline-bar"
    >
      <div className="offline-bar-text">
        {!isOnline ? (
          <>
            <strong>Đang ngoại tuyến</strong> — Bạn vẫn có thể đọc bài học đã tải, tra bảng thuật
            ngữ và lưu câu trả lời chờ đồng bộ
            {pendingCount > 0 ? ` (${pendingCount} bài chờ đồng bộ).` : "."}
          </>
        ) : syncing ? (
          <>
            <strong>Đang đồng bộ</strong> — Đang gửi {pendingCount} lượt nộp bài lên máy chủ để
            chấm điểm & cộng XP…
          </>
        ) : (
          <>
            <strong>Còn {pendingCount} bài chờ đồng bộ</strong> — Kết nối đã khôi phục.
          </>
        )}
      </div>
      {isOnline && pendingCount > 0 && !syncing && (
        <Button variant="secondary" size="sm" onClick={() => void syncNow()}>
          Đồng bộ ngay
        </Button>
      )}
    </div>
  );
}
