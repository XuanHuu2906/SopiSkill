"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { Button, ButtonLink } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";

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
    return (
      <div className="container">
        <div style={{ display: "grid", gap: 16 }}>
          <Skeleton height={28} width="40%" />
          <Skeleton height={96} />
          <Skeleton height={96} />
        </div>
      </div>
    );
  }
  if (!isAuthenticated) {
    return <div className="container">Đang chuyển tới trang đăng nhập…</div>;
  }

  const remaining = items.length;

  return (
    <div className="container">
      <header
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 20,
        }}
      >
        <div>
          <span className="eyebrow">Ôn tập giãn cách</span>
          <h1 className="page-title" style={{ margin: "4px 0 0" }}>
            Ôn tập
          </h1>
        </div>
        <ButtonLink href="/" variant="ghost" size="sm">
          ← Trang chủ
        </ButtonLink>
      </header>

      {disabled && (
        <Card variant="tint">
          <p className="muted" style={{ margin: 0 }}>
            Tính năng ôn tập chưa được bật trên hệ thống này.
          </p>
        </Card>
      )}

      {!disabled && due.isLoading && (
        <div style={{ display: "grid", gap: 12 }}>
          <Skeleton height={96} />
          <Skeleton height={96} />
        </div>
      )}

      {!disabled && due.isError && !(due.error instanceof ApiError && due.error.status === 503) && (
        <div className="error-box" role="alert">
          Không tải được thẻ ôn tập: {due.error.message}
          <div style={{ marginTop: 8 }}>
            <Button variant="secondary" size="sm" onClick={() => due.refetch()}>
              Thử lại
            </Button>
          </div>
        </div>
      )}

      {!disabled && due.data && items.length === 0 && (
        <Card variant="tint">
          <p className="muted" style={{ margin: 0 }}>
            {reviewedCount > 0
              ? `Đã ôn ${reviewedCount} thẻ. Hiện không còn thẻ nào đến hạn.`
              : "Hôm nay không có thẻ nào đến hạn. Hãy học thêm bài để tạo lịch ôn."}
          </p>
        </Card>
      )}

      {!disabled && remaining > 0 && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 12,
            flexWrap: "wrap",
          }}
        >
          <Badge tone="accent">{remaining} thẻ đến hạn</Badge>
          {reviewedCount > 0 && <Badge tone="success">đã ôn {reviewedCount}</Badge>}
        </div>
      )}

      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}

      {!disabled &&
        items.map((card) => (
          <Card key={card.cardId}>
            <h2 className="section-title" style={{ margin: 0 }}>
              {card.lessonTitle}
            </h2>
            <p className="caption" style={{ margin: "4px 0 14px" }}>
              {reviewStateLabel(card.state)}
              {card.overdueDays > 0 ? ` · trễ ${card.overdueDays} ngày` : ""}
            </p>

            {!revealed[card.cardId] ? (
              <Button
                variant="secondary"
                size="md"
                onClick={() =>
                  setRevealed((prev) => ({ ...prev, [card.cardId]: true }))
                }
              >
                Hiện đáp án
              </Button>
            ) : (
              <>
                <p className="muted" style={{ marginTop: 0 }}>
                  Hãy tự nhớ lại nội dung chính của bài trên trước khi tự đánh giá mức
                  độ nhớ.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {RATINGS.map((rating) => (
                    <Button
                      key={rating.value}
                      variant={
                        rating.value <= 2 ? "danger" : rating.value === 3 ? "secondary" : "success"
                      }
                      size="sm"
                      onClick={() => startGrade(card.cardId, rating.value)}
                      disabled={grade.isPending}
                      aria-label={`${rating.label}: ${rating.hint}`}
                      title={rating.hint}
                    >
                      {rating.label}
                    </Button>
                  ))}
                </div>
              </>
            )}
          </Card>
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
