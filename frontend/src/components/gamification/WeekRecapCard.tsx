"use client";

import Link from "next/link";
import type { HomeOut } from "@/lib/api";
import Icon from "@/components/ui/Icon";
import { Badge } from "@/components/ui/Badge";
import WeekChart from "./WeekChart";

export default function WeekRecapCard({ home }: { home: HomeOut }) {
  const { weekRecap } = home;
  const lowHearts = home.hearts < home.heartsMax;

  return (
    <section
      className="week-recap-card"
      aria-labelledby="week-recap-title"
      data-testid="week-recap-card"
    >
      <div className="week-recap-head">
        <div>
          <span className="eyebrow">Nhịp học tuần này</span>
          <h2 id="week-recap-title" className="section-title" style={{ margin: "2px 0 0" }}>
            {weekRecap.lessonsThisWeek} bài · {weekRecap.xpThisWeek.toLocaleString("vi-VN")} XP
          </h2>
        </div>
        <div className="week-recap-pills">
          <span className="gamify-pill" aria-label={`Chuỗi ${home.streakDays} ngày`}>
            <Icon name="flame" size={16} />
            <strong>{home.streakDays}</strong> ngày
          </span>
          {home.streakFreezes > 0 && (
            <span className="gamify-pill is-freeze" aria-label={`${home.streakFreezes} đóng băng chuỗi`}>
              <Icon name="shield" size={16} />
              <strong>{home.streakFreezes}</strong> đóng băng
            </span>
          )}
          <span
            className={`gamify-pill${lowHearts ? " is-low-hearts" : ""}`}
            aria-label={`${home.hearts} trên ${home.heartsMax} tim`}
          >
            <Icon name="heart" size={16} />
            <strong>
              {home.hearts}/{home.heartsMax}
            </strong>{" "}
            tim
          </span>
        </div>
      </div>

      <WeekChart days={weekRecap.days} />

      <div className="week-recap-foot">
        <div className="week-recap-goal">
          <Badge tone={weekRecap.goalReachedToday ? "success" : "accent"}>
            Mục tiêu hôm nay: {weekRecap.todayLessons}/{weekRecap.goalLessons} bài
          </Badge>
          {lowHearts && (
            <Link href="/review" className="link" style={{ fontSize: 14, fontWeight: 600 }}>
              Ôn FSRS để hồi +1 tim →
            </Link>
          )}
        </div>
        <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
          <Link href="/profile" className="link" style={{ fontSize: 14, fontWeight: 600 }}>
            Huy hiệu & hồ sơ
          </Link>
          <Link href="/league" className="link" style={{ fontSize: 14, fontWeight: 600 }}>
            Bảng xếp hạng
          </Link>
        </div>
      </div>
    </section>
  );
}
