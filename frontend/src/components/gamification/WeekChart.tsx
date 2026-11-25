"use client";

import type { WeekDayStat } from "@/lib/api";

const DAY_LABELS: Record<number, string> = {
  1: "T2",
  2: "T3",
  3: "T4",
  4: "T5",
  5: "T6",
  6: "T7",
  7: "CN",
};

export default function WeekChart({
  days,
  title = "Hoạt động 7 ngày qua",
}: {
  days: WeekDayStat[];
  title?: string;
}) {
  const maxXp = Math.max(100, ...days.map((d) => d.xpEarned));

  return (
    <div className="week-chart" role="region" aria-label={title} data-testid="week-chart">
      <div className="week-chart-bars">
        {days.map((day) => {
          const active = day.xpEarned > 0 || day.lessonsCompleted > 0 || day.attemptsCount > 0;
          const heightPct = active
            ? Math.max(18, Math.round((Math.max(day.xpEarned, 20) / maxXp) * 100))
            : 8;
          const label = DAY_LABELS[day.dayOfWeek] ?? day.date.slice(5);
          return (
            <div
              key={day.date}
              className={`week-chart-col${day.isToday ? " is-today" : ""}${active ? " is-active" : ""}`}
              aria-label={`${label} (${day.date}): ${day.lessonsCompleted} bài, ${day.xpEarned} XP`}
            >
              <span className="week-chart-xp" aria-hidden="true">
                {day.xpEarned > 0 ? `+${day.xpEarned}` : ""}
              </span>
              <div className="week-chart-track">
                <div
                  className="week-chart-fill"
                  style={{ height: `${heightPct}%` }}
                  data-active={active ? "true" : "false"}
                />
              </div>
              <span className="week-chart-day">{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
