"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, fetchLastLeague, fetchLeague } from "@/lib/api";
import { useRequireAuth, useSessionQueryKey } from "../providers";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { SkeletonStack } from "@/components/ui/Skeleton";

const TIER_LABELS: Record<string, string> = {
  bronze: "Hạng Đồng",
  silver: "Hạng Bạc",
  gold: "Hạng Vàng",
  sapphire: "Hạng Lam Ngọc",
  ruby: "Hạng Hồng Ngọc",
};

const OUTCOME_LABELS: Record<string, string> = {
  promoted: "Thăng hạng",
  stayed: "Giữ hạng",
  demoted: "Xuống hạng",
};

export default function LeaguePage() {
  const { isAuthenticated, isLoading: authLoading } = useRequireAuth();
  const leagueKey = useSessionQueryKey("league-current");
  const lastKey = useSessionQueryKey("league-last");

  const current = useQuery({
    queryKey: leagueKey,
    enabled: isAuthenticated,
    queryFn: fetchLeague,
    retry: false,
  });

  const last = useQuery({
    queryKey: lastKey,
    enabled: isAuthenticated && !current.isError,
    queryFn: fetchLastLeague,
    retry: false,
  });

  if (authLoading) return <p className="muted">Đang kiểm tra phiên đăng nhập…</p>;
  if (!isAuthenticated) return <p className="muted">Đang chuyển tới trang đăng nhập…</p>;

  const disabled = current.error instanceof ApiError && current.error.status === 503;

  return (
    <div className="league-page" data-testid="league-page">
      <header className="section-head" style={{ marginBottom: 20 }}>
        <div>
          <span className="eyebrow">Thi đua tuần</span>
          <h1 className="page-title" style={{ margin: "4px 0 0" }}>
            Bảng xếp hạng
          </h1>
        </div>
        <ButtonLink href="/" variant="ghost" size="sm">
          ← Trang chủ
        </ButtonLink>
      </header>

      {disabled && (
        <Card variant="tint" data-testid="leagues-disabled-notice">
          <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
            <Icon name="trophy" size={24} />
            <div>
              <h2 className="section-title" style={{ margin: "0 0 6px" }}>
                Bảng xếp hạng tuần đang tạm tắt
              </h2>
              <p className="muted" style={{ margin: "0 0 14px" }}>
                Quản trị viên hiện đặt cờ <code>LEAGUES_ENABLED=false</code>. XP và chuỗi học tập
                của bạn vẫn được ghi nhận đầy đủ trong hồ sơ cá nhân.
              </p>
              <ButtonLink href="/profile" variant="secondary" size="sm">
                Xem hồ sơ & huy hiệu
              </ButtonLink>
            </div>
          </div>
        </Card>
      )}

      {!disabled && current.isLoading && (
        <Card>
          <SkeletonStack rows={5} />
        </Card>
      )}

      {!disabled && current.isError && (
        <div className="error-box" role="alert">
          Không tải được bảng xếp hạng: {current.error.message}
        </div>
      )}

      {!disabled && current.data && (
        <>
          <Card style={{ marginBottom: 20 }}>
            <div className="league-tier-bar" role="list" aria-label="Các hạng thi đua">
              {current.data.tiers.map((t) => (
                <span
                  key={t}
                  role="listitem"
                  className={`league-tier-chip${t === current.data.tier ? " is-current" : ""}`}
                >
                  {TIER_LABELS[t] ?? t}
                </span>
              ))}
            </div>
            <div style={{ marginTop: 14, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
              <div>
                <h2 className="section-title" style={{ margin: 0 }}>
                  {TIER_LABELS[current.data.tier] ?? current.data.tier}
                </h2>
                <p className="caption" style={{ margin: "4px 0 0" }}>
                  Tuần từ {current.data.weekStart} · {current.data.memberCount}/
                  {current.data.cohortMaxSize} học viên
                </p>
              </div>
              {current.data.myRank != null && (
                <Badge tone="accent">
                  Hạng #{current.data.myRank} · {current.data.myWeeklyXp} XP tuần này
                </Badge>
              )}
            </div>
          </Card>

          <Card>
            <ol className="league-standings" aria-label="Danh sách xếp hạng nhóm tuần">
              {current.data.standings.map((row) => (
                <li
                  key={row.membershipId}
                  className={`league-row${row.isMe ? " is-me" : ""}${row.zone === "promotion" ? " is-promo" : ""}${row.zone === "demotion" ? " is-demo" : ""}`}
                >
                  <span className="league-rank">#{row.rank}</span>
                  <span className="league-name">
                    {row.displayName} {row.isMe ? "(Bạn)" : ""}
                  </span>
                  <span className="league-xp">{row.weeklyXp.toLocaleString("vi-VN")} XP</span>
                </li>
              ))}
            </ol>
          </Card>

          {last.data?.hasPrevious && last.data.cohort && (
            <Card variant="tint" style={{ marginTop: 20 }}>
              <h2 className="section-title" style={{ margin: "0 0 6px" }}>
                Kết quả tuần trước ({last.data.cohort.weekStart})
              </h2>
              <p className="muted" style={{ margin: 0 }}>
                {TIER_LABELS[last.data.cohort.tier] ?? last.data.cohort.tier} · Hạng #
                {last.data.cohort.myRank ?? "-"} ·{" "}
                {last.data.cohort.myOutcome
                  ? OUTCOME_LABELS[last.data.cohort.myOutcome] ?? last.data.cohort.myOutcome
                  : "Đang tổng kết"}
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
