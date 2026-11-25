package com.sopiskill.core.gamification;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * Phase 6 gamification endpoints:
 * - `GET /v1/home` (WeekRecapCard, streak/freezes, hearts, daily goal, reviewsDue)
 * - `GET /v1/me/profile` (WeekChart 7 days, accuracy, milestones, hearts, streaks)
 * - `PATCH /v1/me/preferences` (timezone, goalLessons 1|2|3)
 * - `GET /v1/league` & `GET /v1/league/last` (guarded by `LEAGUES_ENABLED`)
 */
@RestController
public class GamificationController {

    private final JdbcClient jdbc;
    private final SopiProperties props;
    private final GamificationService gamification;
    private final LeagueService leagueService;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;

    public GamificationController(
            JdbcClient jdbc,
            SopiProperties props,
            GamificationService gamification,
            LeagueService leagueService,
            CsrfValidator csrf,
            RateLimiterService rateLimiter
    ) {
        this.jdbc = jdbc;
        this.props = props;
        this.gamification = gamification;
        this.leagueService = leagueService;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
    }

    public record UpdatePreferencesRequest(String timezone, Integer goalLessons) {}

    @GetMapping("/v1/home")
    public Map<String, Object> home(@AuthenticationPrincipal AuthPrincipal principal) {
        UUID uid = principal.userId();
        Instant now = Instant.now();
        Map<String, Object> user = loadUserGamificationRow(uid);
        ZoneId zone = GamificationService.resolveZone(String.valueOf(user.get("timezone")));
        var hearts = gamification.computeEffectiveHearts(
                ((Number) user.get("hearts")).intValue(),
                (Instant) user.get("heartsRefillAt"),
                now
        );
        List<Map<String, Object>> weekChart = gamification.buildWeekChart(uid, zone, now);
        int lessonsThisWeek = weekChart.stream().mapToInt(d -> ((Number) d.get("lessonsCompleted")).intValue()).sum();
        int xpThisWeek = weekChart.stream().mapToInt(d -> ((Number) d.get("xpEarned")).intValue()).sum();
        int activeDaysThisWeek = (int) weekChart.stream()
                .filter(d -> ((Number) d.get("attemptsCount")).intValue() > 0 || ((Number) d.get("lessonsCompleted")).intValue() > 0)
                .count();
        int todayLessons = weekChart.isEmpty() ? 0 : ((Number) weekChart.getLast().get("lessonsCompleted")).intValue();
        int goalLessons = ((Number) user.get("goalLessons")).intValue();

        int reviewsDue = jdbc.sql("SELECT COUNT(*) FROM core.review_cards WHERE user_id = :uid AND due_at <= now()")
                .param("uid", uid).query(Integer.class).single();

        Map<String, Object> weekRecap = new LinkedHashMap<>();
        weekRecap.put("days", weekChart);
        weekRecap.put("lessonsThisWeek", lessonsThisWeek);
        weekRecap.put("xpThisWeek", xpThisWeek);
        weekRecap.put("activeDaysThisWeek", activeDaysThisWeek);
        weekRecap.put("todayLessons", todayLessons);
        weekRecap.put("goalLessons", goalLessons);
        weekRecap.put("goalReachedToday", todayLessons >= goalLessons);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("userId", IdCodec.format("usr", uid));
        out.put("displayName", user.get("displayName"));
        out.put("timezone", zone.getId());
        out.put("xp", user.get("xp"));
        out.put("streakDays", user.get("streakDays"));
        out.put("bestStreakDays", user.get("bestStreakDays"));
        out.put("streakFreezes", user.get("streakFreezes"));
        out.put("hearts", hearts.hearts());
        out.put("heartsMax", hearts.heartsMax());
        out.put("heartsRefillAt", hearts.heartsRefillAt() == null ? null : hearts.heartsRefillAt().toString());
        out.put("heartsEnforcementEnabled", props.heartsEnforcementEnabled());
        out.put("leaguesEnabled", props.leaguesEnabled());
        out.put("reviewsDue", reviewsDue);
        out.put("weekRecap", weekRecap);
        return out;
    }

    @GetMapping("/v1/me/profile")
    public Map<String, Object> profile(@AuthenticationPrincipal AuthPrincipal principal) {
        UUID uid = principal.userId();
        Instant now = Instant.now();
        Map<String, Object> user = loadUserGamificationRow(uid);
        ZoneId zone = GamificationService.resolveZone(String.valueOf(user.get("timezone")));
        var hearts = gamification.computeEffectiveHearts(
                ((Number) user.get("hearts")).intValue(),
                (Instant) user.get("heartsRefillAt"),
                now
        );

        int coursesTotal = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid")
                .param("uid", uid).query(Integer.class).single();
        int coursesReady = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid AND status = 'ready'")
                .param("uid", uid).query(Integer.class).single();
        int lessonsTotal = jdbc.sql("""
                SELECT COUNT(*) FROM core.lessons l
                JOIN core.courses c ON c.id = l.course_id
                WHERE c.user_id = :uid
                """).param("uid", uid).query(Integer.class).single();
        int lessonsCompleted = jdbc.sql("""
                SELECT COUNT(DISTINCT la.lesson_id) FROM core.lesson_attempts la
                WHERE la.user_id = :uid AND la.completed = TRUE
                """).param("uid", uid).query(Integer.class).single();
        int reviewsDue = jdbc.sql("SELECT COUNT(*) FROM core.review_cards WHERE user_id = :uid AND due_at <= now()")
                .param("uid", uid).query(Integer.class).single();

        var accRow = jdbc.sql("""
                SELECT COALESCE(SUM(correct), 0) AS c, COALESCE(SUM(total), 0) AS t
                FROM core.lesson_attempts
                WHERE user_id = :uid
                """)
                .param("uid", uid)
                .query((rs, rowNum) -> new int[] { rs.getInt("c"), rs.getInt("t") })
                .single();
        int accuracyPercent = accRow[1] == 0 ? 0 : (int) Math.round((accRow[0] * 100.0) / accRow[1]);

        List<Map<String, Object>> weekChart = gamification.buildWeekChart(uid, zone, now);
        List<Map<String, Object>> milestones = gamification.listAllMilestonesWithStatus(uid);
        int earnedCount = (int) milestones.stream().filter(m -> Boolean.TRUE.equals(m.get("earned"))).count();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("userId", IdCodec.format("usr", uid));
        out.put("email", user.get("email"));
        out.put("displayName", user.get("displayName"));
        out.put("createdAt", user.get("createdAt"));
        out.put("timezone", zone.getId());
        out.put("goalLessons", user.get("goalLessons"));
        out.put("xp", user.get("xp"));
        out.put("streakDays", user.get("streakDays"));
        out.put("bestStreakDays", user.get("bestStreakDays"));
        out.put("streakFreezes", user.get("streakFreezes"));
        out.put("hearts", hearts.hearts());
        out.put("heartsMax", hearts.heartsMax());
        out.put("heartsRefillAt", hearts.heartsRefillAt() == null ? null : hearts.heartsRefillAt().toString());
        out.put("coursesTotal", coursesTotal);
        out.put("coursesReady", coursesReady);
        out.put("lessonsCompleted", lessonsCompleted);
        out.put("lessonsTotal", lessonsTotal);
        out.put("reviewsDue", reviewsDue);
        out.put("accuracyPercent", accuracyPercent);
        out.put("weekChart", weekChart);
        out.put("milestones", milestones);
        out.put("milestonesEarned", earnedCount);
        out.put("milestonesTotal", milestones.size());
        out.put("leaguesEnabled", props.leaguesEnabled());
        return out;
    }

    @PatchMapping("/v1/me/preferences")
    @Transactional
    public Map<String, Object> updatePreferences(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestBody UpdatePreferencesRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "me_prefs", 30, 60);

        UUID uid = principal.userId();
        String nextTz = null;
        if (body.timezone() != null && !body.timezone().isBlank()) {
            try {
                nextTz = ZoneId.of(body.timezone().trim()).getId();
            } catch (Exception ex) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_TIMEZONE", "Múi giờ không hợp lệ.");
            }
        }
        Integer nextGoal = null;
        if (body.goalLessons() != null) {
            if (!GamificationService.ALLOWED_GOAL_LESSONS.contains(body.goalLessons())) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_GOAL", "Mục tiêu ngày phải là 1, 2 hoặc 3 bài.");
            }
            nextGoal = body.goalLessons();
        }

        if (nextTz != null) {
            jdbc.sql("UPDATE core.users SET timezone = :tz, updated_at = now() WHERE id = :uid")
                    .param("tz", nextTz).param("uid", uid).update();
        }
        if (nextGoal != null) {
            jdbc.sql("UPDATE core.users SET goal_lessons = :goal, updated_at = now() WHERE id = :uid")
                    .param("goal", nextGoal).param("uid", uid).update();
        }

        var user = loadUserGamificationRow(uid);
        return Map.of(
                "timezone", user.get("timezone"),
                "goalLessons", user.get("goalLessons")
        );
    }

    @GetMapping("/v1/league")
    public Map<String, Object> currentLeague(@AuthenticationPrincipal AuthPrincipal principal) {
        return leagueService.getCurrentLeague(principal.userId(), Instant.now());
    }

    @GetMapping("/v1/league/last")
    public Map<String, Object> lastLeague(@AuthenticationPrincipal AuthPrincipal principal) {
        return leagueService.getLastLeague(principal.userId(), Instant.now());
    }

    private Map<String, Object> loadUserGamificationRow(UUID uid) {
        return jdbc.sql("""
                SELECT id, email, display_name, xp, streak_days, best_streak_days,
                       streak_freezes, hearts, hearts_refill_at, timezone, goal_lessons, created_at
                FROM core.users
                WHERE id = :uid
                """)
                .param("uid", uid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("email", rs.getString("email"));
                    m.put("displayName", rs.getString("display_name"));
                    m.put("xp", rs.getInt("xp"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    m.put("bestStreakDays", rs.getInt("best_streak_days"));
                    m.put("streakFreezes", rs.getInt("streak_freezes"));
                    m.put("hearts", rs.getInt("hearts"));
                    var ra = rs.getTimestamp("hearts_refill_at");
                    m.put("heartsRefillAt", ra == null ? null : ra.toInstant());
                    m.put("timezone", rs.getString("timezone"));
                    m.put("goalLessons", rs.getInt("goal_lessons"));
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."));
    }
}
