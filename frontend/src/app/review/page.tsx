"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useRef, useState } from "react";
import {
  ApiError,
  fetchDueReviews,
  gradeReview,
  newClientId,
  reviewStateLabel,
  type DueReview,
} from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../providers";

const RATINGS: { value: number; label: string; hint: string }[] = [
  { value: 1, label: "Quên", hint: "Không nhớ được nội dung" },
  { value: 2, label: "Khó", hint: "Nhớ mang máng, cần xem lại" },
  { value: 3, label: "Được", hint: "Nhớ được sau khi nghĩ" },
  { value: 4, label: "Dễ", hint: "Nhớ ngay, không cần nghĩ" },
];

function ReviewQueue() {
  const params = useSearchParams();
  const courseId = params.get("courseId") ?? undefined;
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const queryClient = useQueryClient();

  const dueKey = useSessionQueryKey("reviews-due", courseId ?? "all");
  const sessionPrefix = useSessionQueryKey();
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [reviewedCount, setReviewedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const reviewKeyRef = useRef<Record<string, string>>({});

  const due = useQuery({
    queryKey: dueKey,
    enabled: isAuthenticated,
    queryFn: () => fetchDueReviews(courseId, 20),
    retry: false,
  });

  const grade = useMutation({
    mutationFn: ({
      cardId,
      rating,
    }: {
      cardId: string;
      rating: number;
    }) =>
      gradeReview(cardId, {
        rating,
        clientReviewId:
          reviewKeyRef.current[cardId] ?? newClientId("rv"),
      }),
    onSuccess: (_data, variables) => {
      // Một clientReviewId cho mỗi thẻ đang được chấm; xoá sau khi xong để lượt
      // sau (khác ngày) có id mới.
      delete reviewKeyRef.current[variables.cardId];
      setReviewedCount((n) => n + 1);
      setError(null);
      // Invalidate cả nhóm session để course page cập nhật reviewDueCount /
      // mastery / learning-path sau khi chấm thẻ.
      queryClient.invalidateQueries({ queryKey: sessionPrefix });
      queryClient.invalidateQueries({ queryKey: dueKey });
    },
    onError: (err) => {
      setError(
        err instanceof ApiError
          ? err.message
          : "Không gửi được kết quả ôn tập, vui lòng thử lại."
      );
    },
  });

  const startGrade = (cardId: string, rating: number) => {
    if (!reviewKeyRef.current[cardId]) {
      reviewKeyRef.current[cardId] = newClientId("rv");
    }
    grade.mutate({ cardId, rating });
  };

  const disabled =
    due.error instanceof ApiError && due.error.status === 503;

  const items = useMemo<DueReview[]>(() => due.data?.items ?? [], [due.data]);

  if (authLoading) {
    return <div className="container">Đang kiểm tra phiên đăng nhập…</div>;
  }
  if (!isAuthenticated) {
    return <div className="container">Đang chuyển tới trang đăng nhập…</div>;
  }

  return (
    <div className="container">
      <div className="topbar">
        <h1>Ôn tập</h1>
        <Link className="link" href="/">
          ← Trang chủ
        </Link>
      </div>

      {disabled && (
        <div className="card">
          Tính năng ôn tập chưa được bật trên hệ thống này.
        </div>
      )}

      {!disabled && due.isLoading && <div className="card">Đang tải thẻ ôn tập…</div>}

      {!disabled && due.isError && !(due.error instanceof ApiError && due.error.status === 503) && (
        <div className="error-box">
          Không tải được thẻ ôn tập: {due.error.message}
          <br />
          <button style={{ marginTop: 8 }} onClick={() => due.refetch()}>
            Thử lại
          </button>
        </div>
      )}

      {!disabled && due.data && items.length === 0 && (
        <div className="card">
          {reviewedCount > 0
            ? `Đã ôn ${reviewedCount} thẻ. Hiện không còn thẻ nào đến hạn.`
            : "Hôm nay không có thẻ nào đến hạn. Hãy học thêm bài để tạo lịch ôn."}
        </div>
      )}

      {!disabled && items.length > 0 && (
        <p className="muted">
          Còn {items.length} thẻ đến hạn
          {reviewedCount > 0 ? ` · đã ôn ${reviewedCount}` : ""}
        </p>
      )}

      {error && <div className="error-box">{error}</div>}

      {!disabled &&
        items.map((card) => (
          <div className="card" key={card.cardId}>
            <h2>{card.lessonTitle}</h2>
            <p className="muted">
              {reviewStateLabel(card.state)}
              {card.overdueDays > 0 ? ` · trễ ${card.overdueDays} ngày` : ""}
            </p>

            {!revealed[card.cardId] ? (
              <button
                onClick={() =>
                  setRevealed((prev) => ({ ...prev, [card.cardId]: true }))
                }
              >
                Hiện đáp án
              </button>
            ) : (
              <>
                <p>
                  Hãy tự nhớ lại nội dung chính của bài trên trước khi tự đánh giá mức
                  độ nhớ.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {RATINGS.map((rating) => (
                    <button
                      key={rating.value}
                      onClick={() => startGrade(card.cardId, rating.value)}
                      disabled={grade.isPending}
                      aria-label={`${rating.label}: ${rating.hint}`}
                      title={rating.hint}
                    >
                      {rating.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        ))}
    </div>
  );
}

export default function ReviewPage() {
  return (
    <Suspense fallback={<div className="container">Đang tải…</div>}>
      <ReviewQueue />
    </Suspense>
  );
}
