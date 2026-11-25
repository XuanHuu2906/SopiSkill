package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.gamification.GamificationService;
import com.sopiskill.core.gamification.LeagueService;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 6 Gate tests:
 *  1. Timezone-aware Streak boundary (UTC vs Asia/Ho_Chi_Minh), 7-day auto Streak Freeze (+1, max 2),
 *     and auto-consumption of 1 freeze on 1 missed day.
 *  2. Hearts timed regeneration + 409 OUT_OF_HEARTS enforcement + immediate +1 refill via FSRS review grade.
 *  3. Standardized XP (80 base + 20 perfect = 100), atomic Milestone unlock, WeekRecap (`/v1/home`),
 *     Profile (`/v1/me/profile`), and Preferences (`PATCH /v1/me/preferences`).
 *  4. Leagues 30-learner cohort cap (31st learner placed into cohort #2) + weekly settlement & tier promotion.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:phase6",
        "sopiskill.rate-limit-enabled=false",
        "sopiskill.hearts-enforcement-enabled=true",
        "sopiskill.leagues-enabled=true"
})
class Phase6GamificationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcClient jdbc;

    @Autowired
    private GamificationService gamification;

    @Autowired
    private LeagueService leagueService;

    private final HttpClient http = HttpClient.newHttpClient();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    void timezoneBoundaryStreakFreezeAndTimedHeartsRegen() {
        // 1. Timezone day boundary: 2026-06-10T18:30:00Z is 2026-06-10 in UTC, 2026-06-11 in Asia/Ho_Chi_Minh (+07:00)
        Instant boundaryInstant = Instant.parse("2026-06-10T18:30:00Z");
        LocalDate utcDay = boundaryInstant.atZone(ZoneId.of("UTC")).toLocalDate();
        LocalDate vnDay = boundaryInstant.atZone(ZoneId.of("Asia/Ho_Chi_Minh")).toLocalDate();
        assertThat(utcDay).isEqualTo(LocalDate.of(2026, 6, 10));
        assertThat(vnDay).isEqualTo(LocalDate.of(2026, 6, 11));

        // 2. 6-day streak advancing to day 7 auto-grants +1 freeze (capped at 2)
        var day7 = GamificationService.evaluateStreak(vnDay, vnDay.minusDays(1), 6, 6, 0);
        assertThat(day7.streakDays()).isEqualTo(7);
        assertThat(day7.bestStreakDays()).isEqualTo(7);
        assertThat(day7.streakFreezes()).isEqualTo(1);
        assertThat(day7.freezeEarned()).isTrue();

        // Cap at 2 freezes on day 14 when already at 2
        var day14Cap = GamificationService.evaluateStreak(vnDay, vnDay.minusDays(1), 13, 13, 2);
        assertThat(day14Cap.streakDays()).isEqualTo(14);
        assertThat(day14Cap.streakFreezes()).isEqualTo(2);
        assertThat(day14Cap.freezeEarned()).isFalse();

        // 3. Missed 1 day (lastActive = today - 2) with 1 freeze -> consumes 1 freeze & keeps streak alive
        var saved = GamificationService.evaluateStreak(vnDay, vnDay.minusDays(2), 7, 7, 1);
        assertThat(saved.streakDays()).isEqualTo(8);
        assertThat(saved.streakFreezes()).isEqualTo(0);
        assertThat(saved.freezeConsumed()).isTrue();

        // 4. Missed 1 day with 0 freezes -> resets streak to 1, preserves bestStreakDays
        var reset = GamificationService.evaluateStreak(vnDay, vnDay.minusDays(2), 8, 8, 0);
        assertThat(reset.streakDays()).isEqualTo(1);
        assertThat(reset.bestStreakDays()).isEqualTo(8);
        assertThat(reset.freezeConsumed()).isFalse();

        // 5. Timed hearts regeneration: 30 min per heart up to 5
        Instant t0 = Instant.parse("2026-06-10T10:00:00Z");
        var beforeRefill = gamification.computeEffectiveHearts(2, t0.plusSeconds(1800), t0.plusSeconds(600));
        assertThat(beforeRefill.hearts()).isEqualTo(2);

        var afterTwoIntervals = gamification.computeEffectiveHearts(2, t0.plusSeconds(1800), t0.plusSeconds(3600));
        assertThat(afterTwoIntervals.hearts()).isEqualTo(4);
        assertThat(afterTwoIntervals.heartsRefillAt()).isEqualTo(t0.plusSeconds(5400));

        var afterFull = gamification.computeEffectiveHearts(2, t0.plusSeconds(1800), t0.plusSeconds(7200));
        assertThat(afterFull.hearts()).isEqualTo(5);
        assertThat(afterFull.heartsRefillAt()).isNull();
    }

    @Test
    void heartsEnforcementFsrsRefillStandardizedXpMilestonesHomeAndProfile() throws Exception {
        String email = "p6-hearts-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
        var session = register(email);
        String cookie = session.get("cookie");
        String csrf = session.get("csrf");
        UUID uid = IdCodec.parse(session.get("userId"), "usr");

        try {
            // Update timezone & daily goal
            HttpResponse<String> prefResp = patchAuthed("/v1/me/preferences", cookie, csrf,
                    Map.of("timezone", "Asia/Ho_Chi_Minh", "goalLessons", 2));
            assertThat(prefResp.statusCode()).isEqualTo(200);
            assertThat(parseMap(prefResp.body())).containsEntry("timezone", "Asia/Ho_Chi_Minh")
                    .containsEntry("goalLessons", 2);

            // Invalid goal -> 422
            HttpResponse<String> badGoal = patchAuthed("/v1/me/preferences", cookie, csrf, Map.of("goalLessons", 9));
            assertThat(badGoal.statusCode()).isEqualTo(422);

            // Seed a course + unit + ready lesson directly for deterministic Hearts/XP/FSRS test
            UUID courseUuid = UUID.randomUUID();
            UUID unitUuid = UUID.randomUUID();
            UUID lessonUuid = UUID.randomUUID();
            String lessonId = IdCodec.format("lsn", lessonUuid);

            jdbc.sql("INSERT INTO core.courses (id, user_id, topic, language, status) VALUES (:cid, :uid, 'Phase 6 Gamification', 'en', 'ready')")
                    .param("cid", courseUuid).param("uid", uid).update();
            jdbc.sql("INSERT INTO core.units (id, course_id, order_index, title, blurb) VALUES (:unid, :cid, 0, 'Unit 1', 'Core')")
                    .param("unid", unitUuid).param("cid", courseUuid).update();
            jdbc.sql("""
                    INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_version, content_json)
                    VALUES (:lid, :cid, :unid, 0, 'Hearts & XP', 'ready', 1, CAST(:blocks AS jsonb))
                    """)
                    .param("lid", lessonUuid)
                    .param("cid", courseUuid)
                    .param("unid", unitUuid)
                    .param("blocks", objectMapper.writeValueAsString(List.of(
                            Map.of("type", "teach", "title", "Intro", "paragraphs", List.of("Learn hearts.")),
                            Map.of("type", "mc", "question", "2+2?", "options", List.of("4", "5"), "answerIndex", 0),
                            Map.of("type", "blank", "sentence", "____ refills 1 heart.", "answer", "FSRS")
                    )))
                    .update();

            // Set hearts = 1 (next refill 30m in future)
            jdbc.sql("UPDATE core.users SET hearts = 1, hearts_refill_at = now() + interval '30 minutes' WHERE id = :uid")
                    .param("uid", uid).update();

            // 1. Submit failed attempt (0/2) -> loses last heart -> hearts = 0
            HttpResponse<String> failAttempt = postAuthed("/v1/lessons/" + lessonId + "/attempts", cookie, csrf, Map.of(
                    "clientAttemptId", "p6-fail-1",
                    "contentVersion", 1,
                    "answers", List.of(Map.of("index", 1, "answer", 1), Map.of("index", 2, "answer", "WRONG"))
            ));
            assertThat(failAttempt.statusCode()).isEqualTo(200);
            Map<String, Object> failBody = parseMap(failAttempt.body());
            @SuppressWarnings("unchecked")
            Map<String, Object> failRewards = (Map<String, Object>) failBody.get("rewards");
            assertThat(((Number) failRewards.get("hearts")).intValue()).isEqualTo(0);
            assertThat(failRewards.get("heartLost")).isEqualTo(true);

            // 2. Next attempt with hearts == 0 -> 409 OUT_OF_HEARTS!
            HttpResponse<String> blocked = postAuthed("/v1/lessons/" + lessonId + "/attempts", cookie, csrf, Map.of(
                    "clientAttemptId", "p6-blocked-2",
                    "contentVersion", 1,
                    "answers", List.of(Map.of("index", 1, "answer", 0), Map.of("index", 2, "answer", "FSRS"))
            ));
            assertThat(blocked.statusCode()).isEqualTo(409);
            assertThat(blocked.body()).contains("OUT_OF_HEARTS");

            // 3. Make the FSRS review card due now and grade it -> immediately refills +1 heart!
            UUID cardUuid = jdbc.sql("SELECT id FROM core.review_cards WHERE user_id = :uid AND lesson_id = :lid")
                    .param("uid", uid).param("lid", lessonUuid).query(UUID.class).single();
            jdbc.sql("UPDATE core.review_cards SET due_at = now() - interval '1 hour' WHERE id = :cid")
                    .param("cid", cardUuid).update();

            HttpResponse<String> reviewResp = postAuthed(
                    "/v1/reviews/" + IdCodec.format("crd", cardUuid) + "/grade",
                    cookie, csrf,
                    Map.of("rating", 3, "clientReviewId", "p6-rev-1")
            );
            assertThat(reviewResp.statusCode()).isEqualTo(200);
            Map<String, Object> revBody = parseMap(reviewResp.body());
            assertThat(revBody.get("heartsRefilled")).isEqualTo(true);
            assertThat(((Number) revBody.get("hearts")).intValue()).isEqualTo(1);

            // 4. Now perfect attempt (2/2) succeeds -> awards 100 XP (80 base + 20 perfect), unlocks milestones!
            HttpResponse<String> passAttempt = postAuthed("/v1/lessons/" + lessonId + "/attempts", cookie, csrf, Map.of(
                    "clientAttemptId", "p6-pass-3",
                    "contentVersion", 1,
                    "answers", List.of(Map.of("index", 1, "answer", 0), Map.of("index", 2, "answer", "FSRS"))
            ));
            assertThat(passAttempt.statusCode()).isEqualTo(200);
            Map<String, Object> passBody = parseMap(passAttempt.body());
            @SuppressWarnings("unchecked")
            Map<String, Object> passRewards = (Map<String, Object>) passBody.get("rewards");
            assertThat(((Number) passRewards.get("xpEarned")).intValue()).isEqualTo(100);
            assertThat(((Number) passRewards.get("xp")).intValue()).isEqualTo(100);
            assertThat(((Number) passRewards.get("streakDays")).intValue()).isGreaterThanOrEqualTo(1);
            assertThat(passRewards.get("heartLost")).isEqualTo(false);
            assertThat(((Number) passRewards.get("hearts")).intValue()).isEqualTo(1);

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> breakdown = (List<Map<String, Object>>) passBody.get("unitBreakdown");
            assertThat(breakdown).hasSize(2);

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> newMilestones = (List<Map<String, Object>>) passBody.get("newlyEarnedMilestones");
            List<String> newCodes = newMilestones.stream().map(m -> String.valueOf(m.get("code"))).toList();
            assertThat(newCodes).contains("first_lesson", "perfect_lesson", "ladder_xp_100", "course_completed");

            // 5. Verify GET /v1/home & GET /v1/me/profile reflect WeekChart, accuracy, hearts, milestones
            HttpResponse<String> homeResp = getAuthed("/v1/home", cookie);
            assertThat(homeResp.statusCode()).isEqualTo(200);
            Map<String, Object> homeJson = parseMap(homeResp.body());
            assertThat(((Number) homeJson.get("xp")).intValue()).isEqualTo(100);
            assertThat(((Number) homeJson.get("hearts")).intValue()).isEqualTo(1);
            @SuppressWarnings("unchecked")
            Map<String, Object> weekRecap = (Map<String, Object>) homeJson.get("weekRecap");
            assertThat(((Number) weekRecap.get("xpThisWeek")).intValue()).isEqualTo(100);
            assertThat(((Number) weekRecap.get("lessonsThisWeek")).intValue()).isEqualTo(1);

            HttpResponse<String> profileResp = getAuthed("/v1/me/profile", cookie);
            assertThat(profileResp.statusCode()).isEqualTo(200);
            Map<String, Object> profileJson = parseMap(profileResp.body());
            assertThat(((Number) profileJson.get("milestonesTotal")).intValue()).isEqualTo(16);
            assertThat(((Number) profileJson.get("milestonesEarned")).intValue()).isGreaterThanOrEqualTo(4);
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> weekChart = (List<Map<String, Object>>) profileJson.get("weekChart");
            assertThat(weekChart).hasSize(7);
            assertThat(((Number) weekChart.getLast().get("xpEarned")).intValue()).isEqualTo(100);

            // 6. Verify GET /v1/league returns live cohort standings when enabled
            HttpResponse<String> leagueResp = getAuthed("/v1/league", cookie);
            assertThat(leagueResp.statusCode()).isEqualTo(200);
            Map<String, Object> leagueJson = parseMap(leagueResp.body());
            assertThat(leagueJson.get("tier")).isEqualTo("bronze");
            assertThat(((Number) leagueJson.get("myWeeklyXp")).intValue()).isEqualTo(100);
        } finally {
            jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", uid).update();
        }
    }

    @Test
    void leagueCohortCapAt30LearnersAndWeeklySettlementPromotion() {
        // Use an isolated historical Monday week so concurrent tests never collide
        Instant testWeekInstant = Instant.parse("2025-01-08T12:00:00Z"); // Wed -> Monday 2025-01-06
        LocalDate weekStart = LeagueService.currentWeekStart(testWeekInstant);
        Instant nextWeekInstant = Instant.parse("2025-01-15T12:00:00Z"); // Monday 2025-01-13

        List<UUID> testUsers = new ArrayList<>();
        Set<UUID> createdCohortIds = new HashSet<>();
        try {
            // Create 31 synthetic users and enroll them in week 2025-01-06
            List<UUID> cohortAssignments = new ArrayList<>();
            for (int i = 0; i < 31; i++) {
                UUID uid = UUID.randomUUID();
                testUsers.add(uid);
                jdbc.sql("INSERT INTO core.users (id, email, display_name, xp, streak_days) VALUES (:id, :email, :name, 0, 0)")
                        .param("id", uid)
                        .param("email", "lg-" + i + "-" + uid.toString().substring(0, 8) + "@sopi.test")
                        .param("name", "Learner " + i)
                        .update();
                // User 0 gets highest XP (3100), User 30 gets 100
                int xp = (31 - i) * 100;
                UUID cohortId = leagueService.ensureEnrolledAndAddXp(uid, xp, testWeekInstant);
                cohortAssignments.add(cohortId);
                createdCohortIds.add(cohortId);
            }

            // First 30 learners MUST be in Cohort 1; 31st learner MUST spill over into Cohort 2!
            UUID firstCohort = cohortAssignments.get(0);
            UUID secondCohort = cohortAssignments.get(30);
            assertThat(secondCohort).isNotEqualTo(firstCohort);
            for (int i = 0; i < 30; i++) {
                assertThat(cohortAssignments.get(i)).isEqualTo(firstCohort);
            }

            Integer count1 = jdbc.sql("SELECT COUNT(*) FROM core.league_memberships WHERE cohort_id = :cid")
                    .param("cid", firstCohort).query(Integer.class).single();
            Integer count2 = jdbc.sql("SELECT COUNT(*) FROM core.league_memberships WHERE cohort_id = :cid")
                    .param("cid", secondCohort).query(Integer.class).single();
            assertThat(count1).isEqualTo(30);
            assertThat(count2).isEqualTo(1);

            // Settle week -> top 20% of 30 (6 learners) promoted, rest stayed (bronze never demotes)
            int settled = leagueService.settleWeek(weekStart, testWeekInstant.plusSeconds(86400 * 5L));
            assertThat(settled).isGreaterThanOrEqualTo(2);

            Integer promotedCount = jdbc.sql("""
                    SELECT COUNT(*) FROM core.league_memberships
                    WHERE cohort_id = :cid AND outcome = 'promoted'
                    """).param("cid", firstCohort).query(Integer.class).single();
            Integer demotedCount = jdbc.sql("""
                    SELECT COUNT(*) FROM core.league_memberships
                    WHERE cohort_id = :cid AND outcome = 'demoted'
                    """).param("cid", firstCohort).query(Integer.class).single();
            assertThat(promotedCount).isEqualTo(6);
            assertThat(demotedCount).isEqualTo(0);

            // Top learner (testUsers.get(0)) enters next week -> automatically placed in SILVER tier!
            UUID nextWeekCohortId = leagueService.ensureEnrolledAndAddXp(testUsers.get(0), 100, nextWeekInstant);
            createdCohortIds.add(nextWeekCohortId);
            String nextTier = jdbc.sql("SELECT tier FROM core.league_cohorts WHERE id = :cid")
                    .param("cid", nextWeekCohortId).query(String.class).single();
            assertThat(nextTier).isEqualTo("silver");
        } finally {
            for (UUID uid : testUsers) {
                jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", uid).update();
            }
            for (UUID cid : createdCohortIds) {
                jdbc.sql("DELETE FROM core.league_cohorts WHERE id = :cid").param("cid", cid).update();
            }
        }
    }

    private Map<String, String> register(String email) throws Exception {
        HttpResponse<String> regResp = http.send(
                HttpRequest.newBuilder(URI.create(url("/v1/auth/register")))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(
                                objectMapper.writeValueAsString(Map.of("email", email, "password", "StrongPassword123!"))
                        ))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(regResp.statusCode()).isEqualTo(201);
        List<String> setCookies = regResp.headers().allValues("set-cookie");
        String access = extractCookieValue(setCookies, "access_token");
        String csrf = extractCookieValue(setCookies, "csrf_token");
        Map<String, Object> body = parseMap(regResp.body());
        return Map.of(
                "userId", String.valueOf(body.get("id")),
                "cookie", "access_token=" + access + "; csrf_token=" + csrf,
                "csrf", csrf
        );
    }

    private HttpResponse<String> getAuthed(String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path))).header("Cookie", cookie).GET().build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> postAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> patchAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .method("PATCH", HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private Map<String, Object> parseMap(String raw) throws Exception {
        return objectMapper.readValue(raw.getBytes(StandardCharsets.UTF_8), new TypeReference<>() {});
    }

    private String extractCookieValue(List<String> setCookies, String name) {
        for (String header : setCookies) {
            String firstPart = header.split(";")[0].trim();
            if (firstPart.startsWith(name + "=")) {
                return firstPart.substring((name + "=").length());
            }
        }
        return "";
    }
}
