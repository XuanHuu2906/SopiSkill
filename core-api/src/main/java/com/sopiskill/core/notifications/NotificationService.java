package com.sopiskill.core.notifications;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.gamification.GamificationService;
import java.net.URI;
import java.sql.Timestamp;
import java.time.DayOfWeek;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Notification preferences (15-min step, quiet hours 22:00-08:00), Web Push subscriptions,
 * In-App Notification Center, and 7-kind retention scanner:
 * `course.ready`, `course.failed`, `league.settled`, `daily.reminder`,
 * `streak.guard`, `weekly.recap`, `comeback.nudge` (days 2, 4, 8, 15).
 */
@Service
public class NotificationService {

    public static final Set<Long> COMEBACK_DAYS = Set.of(2L, 4L, 8L, 15L);
    public static final Set<String> VALID_KINDS = Set.of(
            "course.ready",
            "course.failed",
            "league.settled",
            "daily.reminder",
            "streak.guard",
            "weekly.recap",
            "comeback.nudge"
    );

    private final JdbcClient jdbc;
    private final SopiProperties props;

    public NotificationService(JdbcClient jdbc, SopiProperties props) {
        this.jdbc = jdbc;
        this.props = props;
    }

    /**
     * Checks whether `localTime` falls inside `[quietStartMinutes, quietEndMinutes)`.
     * Handles overnight wrap-around such as `22:00 (1320) -> 08:00 (480)` accurately.
     */
    public static boolean isInQuietHours(LocalTime localTime, int quietStartMinutes, int quietEndMinutes) {
        int current = localTime.getHour() * 60 + localTime.getMinute();
        if (quietStartMinutes == quietEndMinutes) {
            return false;
        }
        if (quietStartMinutes > quietEndMinutes) {
            // Overnight window e.g. 22:00..08:00 -> quiet when >= 22:00 OR < 08:00
            return current >= quietStartMinutes || current < quietEndMinutes;
        }
        return current >= quietStartMinutes && current < quietEndMinutes;
    }

    public Map<String, Object> getPreferences(UUID userId) {
        var rowOpt = jdbc.sql("""
                SELECT daily_reminder_enabled, daily_reminder_minutes, streak_guard_enabled,
                       weekly_recap_enabled, comeback_nudge_enabled, course_ready_enabled,
                       league_settled_enabled, quiet_start_minutes, quiet_end_minutes, web_push_enabled
                FROM core.notification_preferences
                WHERE user_id = :uid
                """)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("dailyReminderEnabled", rs.getBoolean("daily_reminder_enabled"));
                    m.put("dailyReminderMinutes", rs.getInt("daily_reminder_minutes"));
                    m.put("streakGuardEnabled", rs.getBoolean("streak_guard_enabled"));
                    m.put("weeklyRecapEnabled", rs.getBoolean("weekly_recap_enabled"));
                    m.put("comebackNudgeEnabled", rs.getBoolean("comeback_nudge_enabled"));
                    m.put("courseReadyEnabled", rs.getBoolean("course_ready_enabled"));
                    m.put("leagueSettledEnabled", rs.getBoolean("league_settled_enabled"));
                    m.put("quietStartMinutes", rs.getInt("quiet_start_minutes"));
                    m.put("quietEndMinutes", rs.getInt("quiet_end_minutes"));
                    m.put("webPushEnabled", rs.getBoolean("web_push_enabled"));
                    return m;
                })
                .optional();

        Map<String, Object> prefs = rowOpt.orElseGet(() -> {
            Map<String, Object> def = new LinkedHashMap<>();
            def.put("dailyReminderEnabled", true);
            def.put("dailyReminderMinutes", 1140); // 19:00
            def.put("streakGuardEnabled", true);
            def.put("weeklyRecapEnabled", true);
            def.put("comebackNudgeEnabled", true);
            def.put("courseReadyEnabled", true);
            def.put("leagueSettledEnabled", true);
            def.put("quietStartMinutes", 1320); // 22:00
            def.put("quietEndMinutes", 480); // 08:00
            def.put("webPushEnabled", false);
            return def;
        });

        Integer pushCount = jdbc.sql("SELECT COUNT(*) FROM core.push_subscriptions WHERE user_id = :uid")
                .param("uid", userId).query(Integer.class).single();
        prefs.put("pushSubscriptionCount", pushCount == null ? 0 : pushCount);
        prefs.put("vapidPublicKey", props.vapidPublicKey() == null ? "" : props.vapidPublicKey());
        return prefs;
    }

    @Transactional
    public Map<String, Object> updatePreferences(UUID userId, Map<String, Object> patch) {
        Map<String, Object> current = getPreferences(userId);
        boolean dailyEnabled = getBool(patch, "dailyReminderEnabled", (Boolean) current.get("dailyReminderEnabled"));
        int dailyMinutes = getInt(patch, "dailyReminderMinutes", (Integer) current.get("dailyReminderMinutes"));
        boolean streakGuard = getBool(patch, "streakGuardEnabled", (Boolean) current.get("streakGuardEnabled"));
        boolean weeklyRecap = getBool(patch, "weeklyRecapEnabled", (Boolean) current.get("weeklyRecapEnabled"));
        boolean comeback = getBool(patch, "comebackNudgeEnabled", (Boolean) current.get("comebackNudgeEnabled"));
        boolean courseReady = getBool(patch, "courseReadyEnabled", (Boolean) current.get("courseReadyEnabled"));
        boolean leagueSettled = getBool(patch, "leagueSettledEnabled", (Boolean) current.get("leagueSettledEnabled"));
        int quietStart = getInt(patch, "quietStartMinutes", (Integer) current.get("quietStartMinutes"));
        int quietEnd = getInt(patch, "quietEndMinutes", (Integer) current.get("quietEndMinutes"));
        boolean webPush = getBool(patch, "webPushEnabled", (Boolean) current.get("webPushEnabled"));

        if (dailyMinutes < 0 || dailyMinutes > 1425 || (dailyMinutes % 15) != 0) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "INVALID_REMINDER_STEP",
                    "Giờ nhắc học hằng ngày phải nằm trong 00:00-23:45 theo bước 15 phút."
            );
        }
        if (quietStart < 0 || quietStart > 1439 || quietEnd < 0 || quietEnd > 1439) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "INVALID_QUIET_HOURS",
                    "Khung giờ yên lặng không hợp lệ."
            );
        }

        jdbc.sql("""
                INSERT INTO core.notification_preferences (
                    user_id, daily_reminder_enabled, daily_reminder_minutes, streak_guard_enabled,
                    weekly_recap_enabled, comeback_nudge_enabled, course_ready_enabled,
                    league_settled_enabled, quiet_start_minutes, quiet_end_minutes, web_push_enabled, updated_at
                ) VALUES (
                    :uid, :de, :dm, :sg, :wr, :cn, :cr, :ls, :qs, :qe, :wp, now()
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    daily_reminder_enabled = EXCLUDED.daily_reminder_enabled,
                    daily_reminder_minutes = EXCLUDED.daily_reminder_minutes,
                    streak_guard_enabled = EXCLUDED.streak_guard_enabled,
                    weekly_recap_enabled = EXCLUDED.weekly_recap_enabled,
                    comeback_nudge_enabled = EXCLUDED.comeback_nudge_enabled,
                    course_ready_enabled = EXCLUDED.course_ready_enabled,
                    league_settled_enabled = EXCLUDED.league_settled_enabled,
                    quiet_start_minutes = EXCLUDED.quiet_start_minutes,
                    quiet_end_minutes = EXCLUDED.quiet_end_minutes,
                    web_push_enabled = EXCLUDED.web_push_enabled,
                    updated_at = now()
                """)
                .param("uid", userId)
                .param("de", dailyEnabled)
                .param("dm", dailyMinutes)
                .param("sg", streakGuard)
                .param("wr", weeklyRecap)
                .param("cn", comeback)
                .param("cr", courseReady)
                .param("ls", leagueSettled)
                .param("qs", quietStart)
                .param("qe", quietEnd)
                .param("wp", webPush)
                .update();

        return getPreferences(userId);
    }

    @Transactional
    public Map<String, Object> registerPushSubscription(
            UUID userId,
            String endpoint,
            String p256dh,
            String auth,
            String userAgent
    ) {
        validatePushEndpoint(endpoint);
        if (p256dh == null || p256dh.isBlank() || auth == null || auth.isBlank()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_PUSH_KEYS", "Thiếu khóa mã hóa Web Push (p256dh/auth).");
        }
        String ua = userAgent != null && userAgent.length() > 250 ? userAgent.substring(0, 250) : userAgent;
        UUID pid = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.push_subscriptions (id, user_id, endpoint, p256dh, auth, user_agent)
                VALUES (:id, :uid, :ep, :p256, :auth, :ua)
                ON CONFLICT (endpoint) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    p256dh = EXCLUDED.p256dh,
                    auth = EXCLUDED.auth,
                    user_agent = EXCLUDED.user_agent
                """)
                .param("id", pid)
                .param("uid", userId)
                .param("ep", endpoint.trim())
                .param("p256", p256dh.trim())
                .param("auth", auth.trim())
                .param("ua", ua)
                .update();

        // Enable web_push_enabled flag cleanly
        jdbc.sql("""
                INSERT INTO core.notification_preferences (user_id, web_push_enabled)
                VALUES (:uid, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET web_push_enabled = TRUE, updated_at = now()
                """).param("uid", userId).update();

        return Map.of("subscriptionId", IdCodec.format("psh", pid), "registered", true);
    }

    @Transactional
    public Map<String, Object> unregisterPushSubscription(UUID userId, String endpoint) {
        int deleted;
        if (endpoint != null && !endpoint.isBlank()) {
            deleted = jdbc.sql("DELETE FROM core.push_subscriptions WHERE user_id = :uid AND endpoint = :ep")
                    .param("uid", userId).param("ep", endpoint.trim()).update();
        } else {
            deleted = jdbc.sql("DELETE FROM core.push_subscriptions WHERE user_id = :uid")
                    .param("uid", userId).update();
        }
        Integer rem = jdbc.sql("SELECT COUNT(*) FROM core.push_subscriptions WHERE user_id = :uid")
                .param("uid", userId).query(Integer.class).single();
        if (rem == null || rem == 0) {
            jdbc.sql("UPDATE core.notification_preferences SET web_push_enabled = FALSE, updated_at = now() WHERE user_id = :uid")
                    .param("uid", userId).update();
        }
        return Map.of("removed", deleted);
    }

    public boolean enqueueNotification(
            UUID userId,
            String kind,
            String title,
            String body,
            String actionUrl,
            String dedupeKey
    ) {
        if (!VALID_KINDS.contains(kind)) {
            throw new IllegalArgumentException("Unsupported notification kind: " + kind);
        }
        int inserted = jdbc.sql("""
                INSERT INTO core.in_app_notifications (id, user_id, kind, title, body, action_url, dedupe_key)
                VALUES (:id, :uid, :kind, :title, :body, :url, :dk)
                ON CONFLICT (user_id, dedupe_key) DO NOTHING
                """)
                .param("id", UUID.randomUUID())
                .param("uid", userId)
                .param("kind", kind)
                .param("title", title)
                .param("body", body)
                .param("url", actionUrl)
                .param("dk", dedupeKey)
                .update();
        return inserted > 0;
    }

    /**
     * Scans a single user across all 7 retention/lifecycle notification kinds at `now`,
     * strictly suppressing scheduled notifications during the user's local quiet hours (default 22:00-08:00).
     */
    @Transactional
    public List<String> scanUserNotifications(UUID userId, Instant now) {
        var userOpt = jdbc.sql("""
                SELECT id, timezone, streak_days, last_active_day, last_active_date
                FROM core.users
                WHERE id = :uid
                """)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("timezone", rs.getString("timezone"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    var lad = rs.getDate("last_active_day");
                    if (lad == null) lad = rs.getDate("last_active_date");
                    m.put("lastActiveDay", lad == null ? null : lad.toLocalDate());
                    return m;
                })
                .optional();
        if (userOpt.isEmpty()) return List.of();

        Map<String, Object> user = userOpt.get();
        Map<String, Object> prefs = getPreferences(userId);
        ZoneId zone = GamificationService.resolveZone(String.valueOf(user.get("timezone")));
        ZonedDateTime localNow = now.atZone(zone);
        LocalDate localToday = localNow.toLocalDate();
        LocalTime localTime = localNow.toLocalTime();
        int quietStart = ((Number) prefs.get("quietStartMinutes")).intValue();
        int quietEnd = ((Number) prefs.get("quietEndMinutes")).intValue();

        // Hard quiet-hours guard (default 22:00-08:00 local time): suppress all proactive nudges!
        if (isInQuietHours(localTime, quietStart, quietEnd)) {
            return List.of();
        }

        List<String> dispatched = new ArrayList<>();
        int currentMinutes = localTime.getHour() * 60 + localTime.getMinute();
        LocalDate lastActive = (LocalDate) user.get("lastActiveDay");
        int streakDays = ((Number) user.get("streakDays")).intValue();

        // 1. course.ready & 2. course.failed (recent 24h)
        if (Boolean.TRUE.equals(prefs.get("courseReadyEnabled"))) {
            List<Map<String, Object>> recentCourses = jdbc.sql("""
                    SELECT id, topic, status
                    FROM core.courses
                    WHERE user_id = :uid AND status IN ('ready', 'failed')
                      AND updated_at >= :since
                    """)
                    .param("uid", userId)
                    .param("since", Timestamp.from(now.minusSeconds(86400)))
                    .query((rs, rowNum) -> Map.<String, Object>of(
                            "id", rs.getObject("id", UUID.class),
                            "topic", rs.getString("topic"),
                            "status", rs.getString("status")
                    ))
                    .list();
            for (Map<String, Object> c : recentCourses) {
                String cid = IdCodec.format("crs", (UUID) c.get("id"));
                String st = String.valueOf(c.get("status"));
                String kind = "ready".equals(st) ? "course.ready" : "course.failed";
                String title = "ready".equals(st) ? "Khóa học đã sẵn sàng!" : "Tạo khóa học gặp sự cố";
                String body = "ready".equals(st)
                        ? "Khóa học \"" + c.get("topic") + "\" đã sẵn sàng để bạn bắt đầu."
                        : "Không thể hoàn tất tạo khóa học \"" + c.get("topic") + "\". Bạn có thể thử lại.";
                if (enqueueNotification(userId, kind, title, body, "/course/" + cid, kind + ":" + cid)) {
                    dispatched.add(kind);
                }
            }
        }

        // 3. league.settled (recent 7 days)
        if (Boolean.TRUE.equals(prefs.get("leagueSettledEnabled"))) {
            var settledOpt = jdbc.sql("""
                    SELECT lc.id, lc.tier, lm.rank, lm.outcome
                    FROM core.league_memberships lm
                    JOIN core.league_cohorts lc ON lc.id = lm.cohort_id
                    WHERE lm.user_id = :uid AND lc.settled = TRUE AND lc.settled_at >= :since
                    ORDER BY lc.settled_at DESC
                    LIMIT 1
                    """)
                    .param("uid", userId)
                    .param("since", Timestamp.from(now.minusSeconds(7L * 86400)))
                    .query((rs, rowNum) -> Map.<String, Object>of(
                            "cohortId", IdCodec.format("lgc", rs.getObject("id", UUID.class)),
                            "tier", rs.getString("tier"),
                            "rank", rs.getObject("rank") == null ? 0 : rs.getInt("rank"),
                            "outcome", rs.getString("outcome") == null ? "stayed" : rs.getString("outcome")
                    ))
                    .optional();
            if (settledOpt.isPresent()) {
                Map<String, Object> s = settledOpt.get();
                String dk = "league.settled:" + s.get("cohortId");
                if (enqueueNotification(
                        userId,
                        "league.settled",
                        "Đã chốt bảng xếp hạng tuần!",
                        "Bạn đạt hạng #" + s.get("rank") + " ở hạng " + s.get("tier") + " (" + s.get("outcome") + ").",
                        "/league",
                        dk
                )) {
                    dispatched.add("league.settled");
                }
            }
        }

        // 4. daily.reminder (when local time is within [reminderMin, reminderMin + 15) and user hasn't studied today)
        if (Boolean.TRUE.equals(prefs.get("dailyReminderEnabled"))) {
            int remMin = ((Number) prefs.get("dailyReminderMinutes")).intValue();
            boolean studiedToday = lastActive != null && lastActive.equals(localToday);
            if (!studiedToday && currentMinutes >= remMin && currentMinutes < remMin + 15) {
                if (enqueueNotification(
                        userId,
                        "daily.reminder",
                        "Đến giờ học 5 phút hôm nay!",
                        "Hoàn thành một bài học ngắn để giữ đà tiến bộ trên SopiSkill.",
                        "/",
                        "daily.reminder:" + localToday
                )) {
                    dispatched.add("daily.reminder");
                }
            }
        }

        // 5. streak.guard (active streak >= 1, not yet studied today, evening 19:00..21:59)
        if (Boolean.TRUE.equals(prefs.get("streakGuardEnabled")) && streakDays >= 1) {
            boolean studiedToday = lastActive != null && lastActive.equals(localToday);
            if (!studiedToday && currentMinutes >= 1140) {
                if (enqueueNotification(
                        userId,
                        "streak.guard",
                        "Đừng để đứt chuỗi " + streakDays + " ngày!",
                        "Chỉ cần 1 bài học ngắn trước nửa đêm để bảo vệ chuỗi học tập của bạn.",
                        "/",
                        "streak.guard:" + localToday
                )) {
                    dispatched.add("streak.guard");
                }
            }
        }

        // 6. weekly.recap (Sunday evening / daytime outside quiet hours)
        if (Boolean.TRUE.equals(prefs.get("weeklyRecapEnabled")) && localToday.getDayOfWeek() == DayOfWeek.SUNDAY) {
            if (enqueueNotification(
                    userId,
                    "weekly.recap",
                    "Tổng kết tuần học tập của bạn",
                    "Xem lại biểu đồ 7 ngày, độ chính xác và các huy hiệu vừa mở khóa trên hồ sơ.",
                    "/profile",
                    "weekly.recap:" + localToday
            )) {
                dispatched.add("weekly.recap");
            }
        }

        // 7. comeback.nudge (exact inactive day milestones: 2, 4, 8, 15)
        if (Boolean.TRUE.equals(prefs.get("comebackNudgeEnabled")) && lastActive != null) {
            long inactiveDays = ChronoUnit.DAYS.between(lastActive, localToday);
            if (COMEBACK_DAYS.contains(inactiveDays)) {
                if (enqueueNotification(
                        userId,
                        "comeback.nudge",
                        "SopiSkill nhớ bạn sau " + inactiveDays + " ngày!",
                        "Quay lại ôn tập nhanh 1 thẻ FSRS hoặc học tiếp bài đang dở nhé.",
                        "/review",
                        "comeback.nudge:" + localToday + ":d" + inactiveDays
                )) {
                    dispatched.add("comeback.nudge");
                }
            }
        }

        return dispatched;
    }

    public Map<String, Object> listInbox(UUID userId, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 50));
        List<Map<String, Object>> items = jdbc.sql("""
                SELECT id, kind, title, body, action_url, read_at, created_at
                FROM core.in_app_notifications
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit
                """)
                .param("uid", userId)
                .param("limit", safeLimit)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("ntf", rs.getObject("id", UUID.class)));
                    m.put("kind", rs.getString("kind"));
                    m.put("title", rs.getString("title"));
                    m.put("body", rs.getString("body"));
                    m.put("actionUrl", rs.getString("action_url"));
                    var ra = rs.getTimestamp("read_at");
                    m.put("readAt", ra == null ? null : ra.toInstant().toString());
                    m.put("read", ra != null);
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .list();

        Integer unreadCount = jdbc.sql("SELECT COUNT(*) FROM core.in_app_notifications WHERE user_id = :uid AND read_at IS NULL")
                .param("uid", userId).query(Integer.class).single();

        return Map.of(
                "items", items,
                "unreadCount", unreadCount == null ? 0 : unreadCount
        );
    }

    @Transactional
    public void markRead(UUID userId, UUID notificationId) {
        jdbc.sql("UPDATE core.in_app_notifications SET read_at = COALESCE(read_at, now()) WHERE id = :nid AND user_id = :uid")
                .param("nid", notificationId).param("uid", userId).update();
    }

    @Transactional
    public void markAllRead(UUID userId) {
        jdbc.sql("UPDATE core.in_app_notifications SET read_at = now() WHERE user_id = :uid AND read_at IS NULL")
                .param("uid", userId).update();
    }

    private static void validatePushEndpoint(String endpoint) {
        if (endpoint == null || endpoint.isBlank() || endpoint.length() > 1000) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_PUSH_ENDPOINT", "Endpoint Web Push không hợp lệ.");
        }
        try {
            URI uri = URI.create(endpoint.trim());
            String scheme = uri.getScheme();
            String host = uri.getHost();
            boolean okHttps = "https".equalsIgnoreCase(scheme) && host != null && !host.isBlank();
            boolean okLocal = "http".equalsIgnoreCase(scheme) && ("localhost".equalsIgnoreCase(host) || "127.0.0.1".equals(host));
            if (!okHttps && !okLocal) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_PUSH_ENDPOINT", "Endpoint Web Push phải dùng HTTPS.");
            }
        } catch (ApiException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_PUSH_ENDPOINT", "URL Endpoint Web Push không hợp lệ.");
        }
    }

    private static boolean getBool(Map<String, Object> map, String key, boolean fallback) {
        Object val = map.get(key);
        return val instanceof Boolean b ? b : fallback;
    }

    private static int getInt(Map<String, Object> map, String key, int fallback) {
        Object val = map.get(key);
        return val instanceof Number n ? n.intValue() : fallback;
    }
}
