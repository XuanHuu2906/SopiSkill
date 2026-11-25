"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  fetchMeProfile,
  type MilestoneItem,
  type UnitBreakdownItem,
} from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../../../providers";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";

interface CompleteAttemptSnapshot {
  attemptId: string;
  duplicate: boolean;
  lessonTitle: string;
  courseId: string | null;
  score: { correct: number; total: number };
  rewards: {
    xp: number;
    xpEarned: number;
    streakDays?: number;
    bestStreakDays?: number;
    streakFreezes?: number;
    freezeConsumed?: boolean;
    freezeEarned?: boolean;
    hearts?: number;
    heartsMax?: number;
    heartLost?: boolean;
  };
  unitBreakdown?: UnitBreakdownItem[];
  newlyEarnedMilestones?: MilestoneItem[];
  reviewCardCreated?: boolean;
  results?: {
    index: number;
    type: string;
    label?: string;
    prompt?: string;
    correct: boolean;
    solutionText?: string | null;
  }[];
}

const CONFETTI_PIECES = [
  { left: "10%", delay: "0ms", color: "#6746d9" },
  { left: "22%", delay: "120ms", color: "#2d7a4f" },
  { left: "36%", delay: "60ms", color: "#d97706" },
  { left: "50%", delay: "180ms", color: "#6746d9" },
  { left: "64%", delay: "90ms", color: "#2d7a4f" },
  { left: "78%", delay: "150ms", color: "#d97706" },
  { left: "90%", delay: "30ms", color: "#6746d9" },
];

export default function LessonCompletePage() {
  const { lessonId } = useParams<{ lessonId: string }>();
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const profileKey = useSessionQueryKey("me-profile");

  const [snapshot, setSnapshot] = useState<CompleteAttemptSnapshot | null>(null);
  const [allowConfetti, setAllowConfetti] = useState(false);

  const profile = useQuery({
    queryKey: profileKey,
    enabled: isAuthenticated,
    queryFn: fetchMeProfile,
    retry: false,
  });

  useEffect(() => {
    if (!lessonId || typeof window === "undefined") return;
    try {
      const raw = window.sessionStorage.getItem(`sopiskill:complete:${lessonId}`);
      if (raw) {
        setSnapshot(JSON.parse(raw) as CompleteAttemptSnapshot);
      }
    } catch {
      // ignore storage errors
    }
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ?? false;
    setAllowConfetti(!reduced);
  }, [lessonId]);

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const score = snapshot?.score ?? { correct: 0, total: 0 };
  const perfect = score.total > 0 && score.correct === score.total;
  const accuracy =
    score.total > 0 ? Math.round((score.correct / score.total) * 100) : profile.data?.accuracyPercent ?? 100;
  const xpEarned = snapshot?.rewards.xpEarned ?? 0;
  const totalXp = snapshot?.rewards.xp ?? profile.data?.xp ?? 0;
  const streakDays = snapshot?.rewards.streakDays ?? profile.data?.streakDays ?? 0;
  const streakFreezes = snapshot?.rewards.streakFreezes ?? profile.data?.streakFreezes ?? 0;
  const hearts = snapshot?.rewards.hearts ?? profile.data?.hearts ?? 5;
  const heartsMax = snapshot?.rewards.heartsMax ?? profile.data?.heartsMax ?? 5;
  const breakdown = snapshot?.unitBreakdown ?? [];
  const newlyEarned = snapshot?.newlyEarnedMilestones ?? [];
  const courseHref = snapshot?.courseId ? `/course/${snapshot.courseId}` : "/";

  return (
    <div className="reading-column complete-page" data-testid="lesson-complete-page">
      {allowConfetti && (perfect || xpEarned > 0) && (
        <div className="complete-confetti" aria-hidden="true">
          {CONFETTI_PIECES.map((p, idx) => (
            <span
              key={idx}
              className="complete-confetti-piece"
              style={{ left: p.left, animationDelay: p.delay, backgroundColor: p.color }}
            />
          ))}
        </div>
      )}

      <section className={`complete-hero${perfect ? " is-perfect" : ""}`} aria-label="Tổng kết bài học">
        <div className="complete-medal" aria-hidden="true">
          <Icon name={perfect ? "trophy" : "checkCircle"} size={34} />
        </div>
        <span className="block-eyebrow" style={{ display: "block" }}>
          {perfect ? "Hoàn hảo 100%!" : "Hoàn thành bài học"}
        </span>
        <h1 className="block-title-sm" style={{ marginTop: 6 }}>
          {snapshot ? `${score.correct}/${score.total} câu đúng` : "Đã lưu kết quả bài học"}
        </h1>
        {snapshot?.lessonTitle && (
          <p className="caption" style={{ marginTop: 4 }}>
            {snapshot.lessonTitle}
          </p>
        )}

        <div className="complete-stats">
          <div className="complete-stat">
            <div className="complete-stat-val">{accuracy}%</div>
            <div className="complete-stat-label">Độ chính xác</div>
          </div>
          <div className="complete-stat">
            <div className="complete-stat-val">+{xpEarned}</div>
            <div className="complete-stat-label">XP nhận được</div>
          </div>
          <div className="complete-stat">
            <div className="complete-stat-val">{streakDays} ngày</div>
            <div className="complete-stat-label">Chuỗi học tập</div>
          </div>
          <div className="complete-stat">
            <div className="complete-stat-val">
              {hearts}/{heartsMax}
            </div>
            <div className="complete-stat-label">Tim hiện có</div>
          </div>
        </div>

        <p className="caption" style={{ marginTop: 14 }}>
          Tổng XP: <strong>{totalXp.toLocaleString("vi-VN")}</strong>
          {streakFreezes > 0 ? ` · ${streakFreezes} đóng băng chuỗi` : ""}
          {snapshot?.rewards.freezeEarned ? " · Nhận mới +1 đóng băng chuỗi!" : ""}
          {snapshot?.rewards.freezeConsumed ? " · Đã tự dùng đóng băng giữ chuỗi!" : ""}
          {snapshot?.duplicate ? " · Lần nộp trước (idempotent)" : ""}
        </p>
      </section>

      {newlyEarned.length > 0 && (
        <section aria-labelledby="new-milestones-heading" style={{ marginTop: 24 }}>
          <h2 id="new-milestones-heading" className="section-title" style={{ marginBottom: 12 }}>
            Huy hiệu vừa mở khóa
          </h2>
          <div className="milestones-grid" data-testid="new-milestones">
            {newlyEarned.map((m) => (
              <div key={m.code} className="milestone-card is-earned">
                <div className="milestone-icon" aria-hidden="true">
                  <Icon name="trophy" size={20} />
                </div>
                <div>
                  <div className="milestone-title">{m.title}</div>
                  <div className="milestone-desc">{m.description}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {breakdown.length > 0 && (
        <section aria-labelledby="unit-breakdown-heading" style={{ marginTop: 24 }}>
          <h2 id="unit-breakdown-heading" className="section-title" style={{ marginBottom: 12 }}>
            Phân tích theo dạng câu hỏi
          </h2>
          <Card>
            <ul className="unit-breakdown-list" data-testid="unit-breakdown">
              {breakdown.map((item) => (
                <li key={item.type} className="unit-breakdown-row">
                  <span style={{ fontWeight: 600 }}>{item.label}</span>
                  <div className="unit-breakdown-right">
                    <span className="caption">
                      {item.correct}/{item.total} đúng
                    </span>
                    <Badge tone={item.accuracyPercent >= 70 ? "success" : "muted"}>
                      {item.accuracyPercent}%
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      )}

      {(hearts < heartsMax || snapshot?.reviewCardCreated) && (
        <Card variant="tint" style={{ marginTop: 20 }}>
          <div className="complete-review-prompt">
            <div>
              <strong style={{ display: "block", marginBottom: 4 }}>
                {hearts < heartsMax
                  ? "Cần hồi tim nhanh?"
                  : "Đã thêm vào lịch ôn tập ngắt quãng FSRS"}
              </strong>
              <p className="muted" style={{ margin: 0, fontSize: 14 }}>
                {hearts < heartsMax
                  ? "Hoàn thành 1 thẻ ôn tập FSRS tại trang Ôn tập để nhận ngay +1 tim và củng cố trí nhớ."
                  : "Hệ thống đã tạo thẻ ôn tập cho bài này để nhắc bạn ôn đúng điểm quên."}
              </p>
            </div>
            <ButtonLink href="/review" variant="secondary" size="md">
              Đi tới Ôn tập
            </ButtonLink>
          </div>
        </Card>
      )}

      {snapshot?.results && snapshot.results.length > 0 && (
        <section aria-labelledby="complete-answers-heading" style={{ marginTop: 24 }}>
          <h2 id="complete-answers-heading" className="section-title" style={{ marginBottom: 12 }}>
            Chi tiết từng câu
          </h2>
          <ol className="lesson-result-list">
            {snapshot.results.map((r) => (
              <li
                key={r.index}
                className={`lesson-result-row ${r.correct ? "is-correct" : "is-wrong"}`}
              >
                <span className="lesson-result-mark" aria-hidden="true">
                  {r.correct ? "✓" : "✗"}
                </span>
                <div className="lesson-result-body">
                  <p className="lesson-result-label">
                    {r.label ?? r.type} · {r.correct ? "Đúng" : "Sai"}
                  </p>
                  {r.prompt && <p className="lesson-result-prompt">{r.prompt}</p>}
                  <p className="lesson-result-solution">
                    {r.solutionText ? `Đáp án: ${r.solutionText}` : "Đã chấm trên máy chủ."}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <div className="complete-actions" style={{ marginTop: 28, display: "flex", gap: 12, flexWrap: "wrap" }}>
        {snapshot?.courseId && (
          <ButtonLink href={courseHref} size="lg">
            Về khóa học
          </ButtonLink>
        )}
        <ButtonLink href="/" variant={snapshot?.courseId ? "secondary" : "primary"} size="lg">
          Về trang chủ
        </ButtonLink>
        <ButtonLink href="/profile" variant="ghost" size="lg">
          Xem hồ sơ & huy hiệu
        </ButtonLink>
      </div>
    </div>
  );
}
