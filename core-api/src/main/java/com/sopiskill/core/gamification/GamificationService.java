package com.sopiskill.core.gamification;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Core gamification engine (Phase 6):
 * - Configurable standardized lesson XP (`XP_LESSON_BASE=80`, `XP_PERFECT_BONUS=20`).
 * - Timezone-aware Streak + auto Streak Freeze (+1 every 7 days, max 2; auto-consumed on 1 missed day).
 * - Hearts (max 5, timed refill + immediate +1 refill on FSRS review grade, optional 409 enforcement).
 * - 7 Milestone Groups + 9 Ladder Milestones unlocked atomically inside the attempt transaction.
 * - 7-day daily activity tracking for `WeekRecapCard` and `WeekChart`.
 */
@Service
public class GamificationService {

    public static final int MAX_STREAK_FREEZES = 2;

    public record MilestoneDef(String code, String category, String title, String description, boolean ladder) {}

    /** 7 core milestone groups + 9 ladder milestones = 16 deterministic badges. */
    public static final List<MilestoneDef> MILESTONE_CATALOG = List.of(
            // 7 Core Milestone Groups
            new MilestoneDef("first_lesson", "lesson", "Bước chân đầu tiên", "Hoàn thành bài học đầu tiên trên SopiSkill.", false),
            new MilestoneDef("perfect_lesson", "mastery", "Hoàn hảo 100%", "Đạt điểm tuyệt đối trong một bài học.", false),
            new MilestoneDef("streak_3", "streak", "Giữ lửa 3 ngày", "Duy trì chuỗi học tập 3 ngày liên tiếp.", false),
            new MilestoneDef("streak_7", "streak", "Chiến binh 7 ngày", "Duy trì chuỗi học tập 7 ngày và nhận đóng băng chuỗi.", false),
            new MilestoneDef("course_started", "course", "Nhà thám hiểm", "Tạo và bắt đầu khóa học đầu tiên.", false),
            new MilestoneDef("course_completed", "course", "Chinh phục khóa học", "Hoàn thành toàn bộ bài học của một khóa học.", false),
            new MilestoneDef("review_champion", "review", "Bậc thầy ôn tập", "Hoàn thành ít nhất 3 thẻ ôn tập FSRS để ghi nhớ dài hạn.", false),
            // 9 Ladder Milestones
            new MilestoneDef("ladder_xp_100", "ladder_xp", "Cột mốc 100 XP", "Tích lũy 100 XP học tập.", true),
            new MilestoneDef("ladder_xp_500", "ladder_xp", "Cột mốc 500 XP", "Tích lũy 500 XP học tập.", true),
            new MilestoneDef("ladder_xp_1000", "ladder_xp", "Cột mốc 1.000 XP", "Tích lũy 1.000 XP học tập.", true),
            new MilestoneDef("ladder_xp_2500", "ladder_xp", "Cột mốc 2.500 XP", "Tích lũy 2.500 XP học tập.", true),
            new MilestoneDef("ladder_lessons_3", "ladder_lessons", "3 bài hoàn thành", "Hoàn thành 3 bài học khác nhau.", true),
            new MilestoneDef("ladder_lessons_10", "ladder_lessons", "10 bài hoàn thành", "Hoàn thành 10 bài học khác nhau.", true),
            new MilestoneDef("ladder_lessons_25", "ladder_lessons", "25 bài hoàn thành", "Hoàn thành 25 bài học khác nhau.", true),
            new MilestoneDef("ladder_streak_14", "ladder_streak", "Chuỗi 14 ngày", "Duy trì chuỗi học tập 14 ngày liên tiếp.", true),
            new MilestoneDef("ladder_streak_30", "ladder_streak", "Chuỗi 30 ngày", "Duy trì chuỗi học tập 30 ngày liên tiếp.", true)
    );

    public record StreakResult(
            int streakDays,
            int bestStreakDays,
            int streakFreezes,
            LocalDate lastActiveDay,
            boolean freezeConsumed,
            boolean freezeEarned
    ) {}

    public record HeartsState(int hearts, int heartsMax, Instant heartsRefillAt) {}

    public record AttemptGamificationResult(
            int newXp,
            int xpEarned,
            StreakResult streak,
            HeartsState hearts,
            boolean heartLost,
            List<Map<String, Object>> newlyEarnedMilestones
    ) {}

    private final JdbcClient jdbc;
    private final SopiProperties props;
    private final LeagueService leagueService;

    public GamificationService(JdbcClient jdbc, SopiProperties props, LeagueService leagueService) {
        this.jdbc = jdbc;
        this.props = props;
        this.leagueService = leagueService;
    }

    public static ZoneId resolveZone(String timezone) {
        if (timezone == null || timezone.isBlank()) {
            return ZoneOffset.UTC;
        }
        try {
            return ZoneId.of(timezone.trim());
        } catch (Exception ex) {
            return ZoneOffset.UTC;
        }
    }

    /**
     * Standardized lesson XP computation:
     * - Completed lesson (`completed == true`): `XP_LESSON_BASE` (80) + `XP_PERFECT_BONUS` (20) when perfect.
     * - Partial non-completed attempt (`correct > 0`): proportional partial XP (`< XP_LESSON_BASE`),
     *   so completing later tops up the exact remaining delta without ever exceeding `base + bonus`.
     */
    public int computeRawLessonXp(int correct, int total, boolean completed) {
        int base = Math.max(10, props.xpLessonBase());
        int perfectBonus = Math.max(0, props.xpPerfectBonus());
        if (completed) {
            boolean perfect = total > 0 && correct == total;
            return base + (perfect ? perfectBonus : 0);
        }
        if (total <= 0 || correct <= 0) {
            return 0;
        }
        return Math.min(base - 10, Math.max(10, (int) Math.round(base * ((double) correct / total) * 0.5)));
    }

    /**
     * Pure timezone-aware streak + freeze state machine:
     * - Same local day: keep streak & freezes.
     * - Next local day (+1): streak++, +1 freeze every 7-day multiple (cap 2).
     * - Missed 1 day (+2): if freezes > 0, consume 1 freeze & increment streak; else reset to 1.
     * - Missed >= 2 days or first activity: streak = 1.
     */
    public static StreakResult evaluateStreak(
            LocalDate localToday,
            LocalDate lastActiveDay,
            int currentStreak,
            int bestStreak,
            int currentFreezes
    ) {
        int safeFreezes = Math.max(0, Math.min(MAX_STREAK_FREEZES, currentFreezes));
        int safeStreak = Math.max(0, currentStreak);
        int safeBest = Math.max(bestStreak, safeStreak);
        boolean freezeConsumed = false;
        boolean freezeEarned = false;

        int nextStreak;
        int nextFreezes = safeFreezes;

        if (lastActiveDay == null) {
            nextStreak = 1;
        } else if (lastActiveDay.equals(localToday)) {
            nextStreak = Math.max(1, safeStreak);
        } else if (lastActiveDay.equals(localToday.minusDays(1))) {
            nextStreak = safeStreak + 1;
            if (nextStreak % 7 == 0 && nextFreezes < MAX_STREAK_FREEZES) {
                nextFreezes++;
                freezeEarned = true;
            }
        } else if (lastActiveDay.equals(localToday.minusDays(2))) {
            if (nextFreezes > 0) {
                nextFreezes--;
                freezeConsumed = true;
                nextStreak = safeStreak + 1;
                if (nextStreak % 7 == 0 && nextFreezes < MAX_STREAK_FREEZES) {
                    nextFreezes++;
                    freezeEarned = true;
                }
            } else {
                nextStreak = 1;
            }
        } else if (lastActiveDay.isAfter(localToday)) {
            // Timezone shifted westward slightly: keep existing streak without breaking it
            nextStreak = Math.max(1, safeStreak);
        } else {
            nextStreak = 1;
        }

        int nextBest = Math.max(safeBest, nextStreak);
        return new StreakResult(nextStreak, nextBest, nextFreezes, localToday, freezeConsumed, freezeEarned);
    }

    /**
     * Computes effective hearts after timed regeneration (`heartsRefillMinutes` per heart, max `heartsMax`).
     */
    public HeartsState computeEffectiveHearts(int storedHearts, Instant refillAt, Instant now) {
        int max = Math.max(1, props.heartsMax());
        int refillMins = Math.max(1, props.heartsRefillMinutes());
        int hearts = Math.max(0, Math.min(max, storedHearts));
        if (hearts >= max) {
            return new HeartsState(max, max, null);
        }
        if (refillAt == null) {
            return new HeartsState(hearts, max, now.plusSeconds(refillMins * 60L));
        }
        if (now.isBefore(refillAt)) {
            return new HeartsState(hearts, max, refillAt);
        }
        long extraSeconds = Math.max(0L, Duration.between(refillAt, now).getSeconds());
        long intervalSec = refillMins * 60L;
        int gained = (int) (1L + extraSeconds / intervalSec);
        int nextHearts = Math.min(max, hearts + gained);
        if (nextHearts >= max) {
            return new HeartsState(max, max, null);
        }
        Instant nextRefillAt = refillAt.plusSeconds(gained * intervalSec);
        return new HeartsState(nextHearts, max, nextRefillAt);
    }

    public void checkHeartsAvailableOrThrow(int storedHearts, Instant refillAt, Instant now) {
        HeartsState effective = computeEffectiveHearts(storedHearts, refillAt, now);
        if (props.heartsEnforcementEnabled() && effective.hearts() <= 0) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "OUT_OF_HEARTS",
                    "Bạn đã hết tim! Hãy chờ hồi tim hoặc hoàn thành 1 thẻ ôn tập FSRS tại /review để hồi ngay +1 tim.",
                    Map.of(
                            "hearts", 0,
                            "heartsMax", effective.heartsMax(),
                            "heartsRefillAt", effective.heartsRefillAt() == null ? "" : effective.heartsRefillAt().toString()
                    )
            );
        }
    }

    /**
     * Executes XP, Streak/Freeze, Hearts, Daily Activity, Milestones, and League XP update
     * inside the caller's single ACID `@Transactional` block (user row already locked `FOR UPDATE`).
     */
    public AttemptGamificationResult applyAttemptRewards(
            UUID userId,
            UUID courseId,
            UUID lessonId,
            Map<String, Object> lockedUserRow,
            int correct,
            int total,
            boolean completed,
            int xpEarned,
            Instant now
    ) {
        int currentXp = ((Number) lockedUserRow.get("xp")).intValue();
        int newXp = currentXp + Math.max(0, xpEarned);
        String timezone = String.valueOf(lockedUserRow.getOrDefault("timezone", "UTC"));
        ZoneId zone = resolveZone(timezone);
        LocalDate localToday = now.atZone(zone).toLocalDate();

        LocalDate lastActiveDay = (LocalDate) lockedUserRow.get("lastActiveDay");
        int currentStreak = ((Number) lockedUserRow.get("streakDays")).intValue();
        int bestStreak = ((Number) lockedUserRow.get("bestStreakDays")).intValue();
        int currentFreezes = ((Number) lockedUserRow.get("streakFreezes")).intValue();

        StreakResult streak = evaluateStreak(localToday, lastActiveDay, currentStreak, bestStreak, currentFreezes);

        int storedHearts = ((Number) lockedUserRow.get("hearts")).intValue();
        Instant storedRefillAt = (Instant) lockedUserRow.get("heartsRefillAt");
        HeartsState effectiveHearts = computeEffectiveHearts(storedHearts, storedRefillAt, now);

        boolean heartLost = total > 0 && !completed;
        int nextHearts = effectiveHearts.hearts();
        Instant nextRefillAt = effectiveHearts.heartsRefillAt();
        if (heartLost && nextHearts > 0) {
            nextHearts = nextHearts - 1;
            if (nextRefillAt == null) {
                nextRefillAt = now.plusSeconds(Math.max(1, props.heartsRefillMinutes()) * 60L);
            }
        }
        HeartsState finalHearts = new HeartsState(nextHearts, effectiveHearts.heartsMax(), nextHearts >= effectiveHearts.heartsMax() ? null : nextRefillAt);

        jdbc.sql("""
                UPDATE core.users
                SET xp = :xp,
                    streak_days = :streak,
                    best_streak_days = :best,
                    last_active_date = :today,
                    last_active_day = :today,
                    streak_freezes = :freezes,
                    hearts = :hearts,
                    hearts_refill_at = :refillAt,
                    updated_at = now()
                WHERE id = :uid
                """)
                .param("xp", newXp)
                .param("streak", streak.streakDays())
                .param("best", streak.bestStreakDays())
                .param("today", localToday)
                .param("freezes", streak.streakFreezes())
                .param("hearts", finalHearts.hearts())
                .param("refillAt", finalHearts.heartsRefillAt() == null ? null : Timestamp.from(finalHearts.heartsRefillAt()))
                .param("uid", userId)
                .update();

        // Upsert daily activity for localToday
        jdbc.sql("""
                INSERT INTO core.user_daily_activity (
                    user_id, activity_day, lessons_completed, xp_earned, attempts_count, correct_count, total_count, updated_at
                ) VALUES (
                    :uid, :day, :lc, :xp, 1, :correct, :total, now()
                )
                ON CONFLICT (user_id, activity_day) DO UPDATE SET
                    lessons_completed = core.user_daily_activity.lessons_completed + EXCLUDED.lessons_completed,
                    xp_earned = core.user_daily_activity.xp_earned + EXCLUDED.xp_earned,
                    attempts_count = core.user_daily_activity.attempts_count + 1,
                    correct_count = core.user_daily_activity.correct_count + EXCLUDED.correct_count,
                    total_count = core.user_daily_activity.total_count + EXCLUDED.total_count,
                    updated_at = now()
                """)
                .param("uid", userId)
                .param("day", localToday)
                .param("lc", completed ? 1 : 0)
                .param("xp", Math.max(0, xpEarned))
                .param("correct", correct)
                .param("total", total)
                .update();

        // Evaluate & unlock milestones atomically
        List<Map<String, Object>> newlyEarned = evaluateAndUnlockMilestones(
                userId, courseId, newXp, streak.streakDays(), completed, total > 0 && correct == total
        );

        // Update weekly League XP atomically when leagues are enabled
        if (props.leaguesEnabled() && xpEarned > 0) {
            leagueService.ensureEnrolledAndAddXp(userId, xpEarned, now);
        }

        return new AttemptGamificationResult(newXp, xpEarned, streak, finalHearts, heartLost, newlyEarned);
    }

    /**
     * FSRS Review Refill hook: completing a due review card immediately adds `+1` heart (up to `HEARTS_MAX`)
     * inside the caller's transaction.
     */
    public Map<String, Object> refillHeartOnFsrsReview(UUID userId, Instant now) {
        var row = jdbc.sql("""
                SELECT hearts, hearts_refill_at, xp, streak_days
                FROM core.users
                WHERE id = :uid
                FOR UPDATE
                """)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("hearts", rs.getInt("hearts"));
                    var ra = rs.getTimestamp("hearts_refill_at");
                    m.put("heartsRefillAt", ra == null ? null : ra.toInstant());
                    m.put("xp", rs.getInt("xp"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    return m;
                })
                .single();

        HeartsState effective = computeEffectiveHearts(
                ((Number) row.get("hearts")).intValue(),
                (Instant) row.get("heartsRefillAt"),
                now
        );
        boolean refilled = effective.hearts() < effective.heartsMax();
        int nextHearts = Math.min(effective.heartsMax(), effective.hearts() + (refilled ? 1 : 0));
        Instant nextRefillAt = nextHearts >= effective.heartsMax() ? null : effective.heartsRefillAt();

        jdbc.sql("""
                UPDATE core.users
                SET hearts = :hearts, hearts_refill_at = :refillAt, updated_at = now()
                WHERE id = :uid
                """)
                .param("hearts", nextHearts)
                .param("refillAt", nextRefillAt == null ? null : Timestamp.from(nextRefillAt))
                .param("uid", userId)
                .update();

        List<Map<String, Object>> newlyEarned = evaluateAndUnlockMilestones(
                userId, null, ((Number) row.get("xp")).intValue(), ((Number) row.get("streakDays")).intValue(), false, false
        );

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("hearts", nextHearts);
        out.put("heartsMax", effective.heartsMax());
        out.put("heartsRefilled", refilled);
        out.put("heartsRefillAt", nextRefillAt == null ? null : nextRefillAt.toString());
        out.put("newlyEarnedMilestones", newlyEarned);
        return out;
    }

    public List<Map<String, Object>> evaluateAndUnlockMilestones(
            UUID userId,
            UUID activeCourseId,
            int totalXp,
            int streakDays,
            boolean lessonCompletedNow,
            boolean perfectNow
    ) {
        int distinctLessonsCompleted = jdbc.sql("""
                SELECT COUNT(DISTINCT lesson_id)
                FROM core.lesson_attempts
                WHERE user_id = :uid AND completed = TRUE
                """).param("uid", userId).query(Integer.class).single();

        int coursesTotal = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid")
                .param("uid", userId).query(Integer.class).single();

        int reviewEventsCount = jdbc.sql("SELECT COUNT(*) FROM core.review_events WHERE user_id = :uid")
                .param("uid", userId).query(Integer.class).single();

        boolean courseCompleted = false;
        if (activeCourseId != null) {
            int totalCourseLessons = jdbc.sql("SELECT COUNT(*) FROM core.lessons WHERE course_id = :cid")
                    .param("cid", activeCourseId).query(Integer.class).single();
            int completedCourseLessons = jdbc.sql("""
                    SELECT COUNT(DISTINCT la.lesson_id)
                    FROM core.lesson_attempts la
                    JOIN core.lessons l ON l.id = la.lesson_id
                    WHERE la.user_id = :uid AND l.course_id = :cid AND la.completed = TRUE
                    """).param("uid", userId).param("cid", activeCourseId).query(Integer.class).single();
            courseCompleted = totalCourseLessons > 0 && completedCourseLessons >= totalCourseLessons;
        }

        List<MilestoneDef> qualified = new ArrayList<>();
        for (MilestoneDef def : MILESTONE_CATALOG) {
            boolean earned = switch (def.code()) {
                case "first_lesson" -> lessonCompletedNow || distinctLessonsCompleted >= 1;
                case "perfect_lesson" -> perfectNow;
                case "streak_3" -> streakDays >= 3;
                case "streak_7" -> streakDays >= 7;
                case "course_started" -> coursesTotal >= 1;
                case "course_completed" -> courseCompleted;
                case "review_champion" -> reviewEventsCount >= 3;
                case "ladder_xp_100" -> totalXp >= 100;
                case "ladder_xp_500" -> totalXp >= 500;
                case "ladder_xp_1000" -> totalXp >= 1000;
                case "ladder_xp_2500" -> totalXp >= 2500;
                case "ladder_lessons_3" -> distinctLessonsCompleted >= 3;
                case "ladder_lessons_10" -> distinctLessonsCompleted >= 10;
                case "ladder_lessons_25" -> distinctLessonsCompleted >= 25;
                case "ladder_streak_14" -> streakDays >= 14;
                case "ladder_streak_30" -> streakDays >= 30;
                default -> false;
            };
            if (earned) {
                qualified.add(def);
            }
        }

        List<Map<String, Object>> newlyEarned = new ArrayList<>();
        for (MilestoneDef def : qualified) {
            UUID mid = UUID.randomUUID();
            int inserted = jdbc.sql("""
                    INSERT INTO core.user_milestones (id, user_id, code, category, title, description)
                    VALUES (:id, :uid, :code, :cat, :title, :desc)
                    ON CONFLICT (user_id, code) DO NOTHING
                    """)
                    .param("id", mid)
                    .param("uid", userId)
                    .param("code", def.code())
                    .param("cat", def.category())
                    .param("title", def.title())
                    .param("desc", def.description())
                    .update();
            if (inserted > 0) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", IdCodec.format("mst", mid));
                m.put("code", def.code());
                m.put("category", def.category());
                m.put("title", def.title());
                m.put("description", def.description());
                m.put("ladder", def.ladder());
                newlyEarned.add(m);
            }
        }
        return newlyEarned;
    }

    public List<Map<String, Object>> buildWeekChart(UUID userId, ZoneId zone, Instant now) {
        LocalDate today = now.atZone(zone).toLocalDate();
        LocalDate start = today.minusDays(6);

        Map<LocalDate, Map<String, Object>> byDay = new LinkedHashMap<>();
        jdbc.sql("""
                SELECT activity_day, lessons_completed, xp_earned, attempts_count, correct_count, total_count
                FROM core.user_daily_activity
                WHERE user_id = :uid AND activity_day >= :start AND activity_day <= :end
                """)
                .param("uid", userId)
                .param("start", start)
                .param("end", today)
                .query((rs, rowNum) -> {
                    LocalDate day = rs.getDate("activity_day").toLocalDate();
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("lessonsCompleted", rs.getInt("lessons_completed"));
                    m.put("xpEarned", rs.getInt("xp_earned"));
                    m.put("attemptsCount", rs.getInt("attempts_count"));
                    m.put("correctCount", rs.getInt("correct_count"));
                    m.put("totalCount", rs.getInt("total_count"));
                    byDay.put(day, m);
                    return m;
                })
                .list();

        List<Map<String, Object>> days = new ArrayList<>(7);
        for (int i = 0; i < 7; i++) {
            LocalDate d = start.plusDays(i);
            Map<String, Object> rec = byDay.get(d);
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("date", d.toString());
            item.put("dayOfWeek", d.getDayOfWeek().getValue()); // 1=Mon .. 7=Sun
            item.put("isToday", d.equals(today));
            item.put("lessonsCompleted", rec == null ? 0 : rec.get("lessonsCompleted"));
            item.put("xpEarned", rec == null ? 0 : rec.get("xpEarned"));
            item.put("attemptsCount", rec == null ? 0 : rec.get("attemptsCount"));
            days.add(item);
        }
        return days;
    }

    public List<Map<String, Object>> listAllMilestonesWithStatus(UUID userId) {
        Map<String, String> earnedAtByCode = jdbc.sql("""
                SELECT code, earned_at
                FROM core.user_milestones
                WHERE user_id = :uid
                """)
                .param("uid", userId)
                .query((rs, rowNum) -> Map.entry(
                        rs.getString("code"),
                        rs.getTimestamp("earned_at").toInstant().toString()
                ))
                .list()
                .stream()
                .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue, (a, b) -> a));

        List<Map<String, Object>> out = new ArrayList<>(MILESTONE_CATALOG.size());
        for (MilestoneDef def : MILESTONE_CATALOG) {
            String earnedAt = earnedAtByCode.get(def.code());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("code", def.code());
            m.put("category", def.category());
            m.put("title", def.title());
            m.put("description", def.description());
            m.put("ladder", def.ladder());
            m.put("earned", earnedAt != null);
            m.put("earnedAt", earnedAt);
            out.add(m);
        }
        return out;
    }

    public static List<Map<String, Object>> buildUnitBreakdown(List<Map<String, Object>> results) {
        Map<String, int[]> agg = new LinkedHashMap<>();
        for (Map<String, Object> r : results) {
            String type = String.valueOf(r.getOrDefault("type", "other"));
            int[] counts = agg.computeIfAbsent(type, k -> new int[2]);
            if (Boolean.TRUE.equals(r.get("correct"))) counts[0]++;
            counts[1]++;
        }
        List<Map<String, Object>> breakdown = new ArrayList<>();
        for (Map.Entry<String, int[]> e : agg.entrySet()) {
            String label = switch (e.getKey()) {
                case "mc" -> "Trắc nghiệm";
                case "blank" -> "Điền chỗ trống";
                case "order" -> "Sắp xếp";
                case "match" -> "Ghép cặp";
                case "short" -> "Trả lời ngắn";
                case "speed" -> "Vòng tốc độ";
                default -> e.getKey();
            };
            int ok = e.getValue()[0];
            int tot = e.getValue()[1];
            breakdown.add(Map.of(
                    "type", e.getKey(),
                    "label", label,
                    "correct", ok,
                    "total", tot,
                    "accuracyPercent", tot == 0 ? 100 : (int) Math.round((ok * 100.0) / tot)
            ));
        }
        return breakdown;
    }

    public static final Set<Integer> ALLOWED_GOAL_LESSONS = Set.of(1, 2, 3);
}
