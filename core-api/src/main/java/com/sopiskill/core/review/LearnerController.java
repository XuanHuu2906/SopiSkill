package com.sopiskill.core.review;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.gamification.GamificationService;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Learner profile, BKT/EWMA mastery, adaptive learning path, recommendation exposure logging,
 * and FSRS spaced repetition reviews (`/v1/reviews/*`).
 */
@RestController
public class LearnerController {

    private final JdbcClient jdbc;
    private final SopiProperties props;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final GamificationService gamification;

    public LearnerController(
            JdbcClient jdbc,
            SopiProperties props,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            GamificationService gamification
    ) {
        this.jdbc = jdbc;
        this.props = props;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.gamification = gamification;
    }

    public record ReviewGradeRequest(
            @NotNull @Min(1) @Max(4) Integer rating,
            @NotBlank String clientReviewId,
            Integer durationMs
    ) {}

    public record RecommendationEventRequest(@NotBlank String recommendationToken) {}

    @GetMapping("/v1/courses/{courseId}/mastery")
    public Map<String, Object> courseMastery(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        requireP50Enabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        List<Map<String, Object>> items = jdbc.sql("""
                SELECT s.id, s.title, s.bloom_level,
                       COALESCE(sm.mastery_score, 0.0) AS mastery_score,
                       COALESCE(sm.method, 'bkt_ewma') AS method,
                       COALESCE(sm.attempts, 0) AS attempts,
                       COALESCE(sm.correct, 0) AS correct,
                       COALESCE(sm.total, 0) AS total,
                       COALESCE(sm.pass_threshold, 0.7) AS pass_threshold,
                       sm.last_attempt_at
                FROM core.skills s
                LEFT JOIN core.skill_mastery sm ON sm.skill_id = s.id AND sm.user_id = :uid
                WHERE s.course_id = :cid
                ORDER BY s.skill_key ASC
                """)
                .param("uid", principal.userId())
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("skillId", IdCodec.format("skl", rs.getObject("id", UUID.class)));
                    m.put("title", rs.getString("title"));
                    m.put("bloomLevel", rs.getString("bloom_level"));
                    m.put("masteryScore", rs.getDouble("mastery_score"));
                    m.put("method", rs.getString("method"));
                    m.put("attempts", rs.getInt("attempts"));
                    m.put("correct", rs.getInt("correct"));
                    m.put("total", rs.getInt("total"));
                    var la = rs.getTimestamp("last_attempt_at");
                    m.put("lastAttemptAt", la == null ? null : la.toInstant().toString());
                    m.put("passThreshold", rs.getDouble("pass_threshold"));
                    return m;
                })
                .list();

        double avg = items.isEmpty()
                ? 0.0
                : items.stream().mapToDouble(i -> ((Number) i.get("masteryScore")).doubleValue()).average().orElse(0.0);
        int dueCount = jdbc.sql("SELECT COUNT(*) FROM core.review_cards WHERE user_id = :uid AND course_id = :cid AND due_at <= now()")
                .param("uid", principal.userId()).param("cid", cid).query(Integer.class).single();

        return Map.of(
                "items", items,
                "coursePercent", (int) Math.round(avg * 100),
                "reviewDueCount", dueCount
        );
    }

    @GetMapping("/v1/courses/{courseId}/learning-path")
    public Map<String, Object> learningPath(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        requireP50Enabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        var nextOpt = jdbc.sql("""
                SELECT l.id, l.title
                FROM core.lessons l
                JOIN core.units u ON u.id = l.unit_id
                WHERE l.course_id = :cid AND l.status = 'ready'
                  AND NOT EXISTS (
                      SELECT 1 FROM core.lesson_attempts la
                      WHERE la.lesson_id = l.id AND la.user_id = :uid
                        AND la.content_version = l.content_version AND la.completed = TRUE
                  )
                ORDER BY u.order_index ASC, l.order_index ASC
                LIMIT 1
                """)
                .param("cid", cid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "lessonId", IdCodec.format("lsn", rs.getObject("id", UUID.class)),
                        "title", rs.getString("title"),
                        "reason", Map.of("code", "NEXT_UNFINISHED", "message", "Bài tiếp theo trong lộ trình")
                ))
                .optional();

        int dueCount = jdbc.sql("SELECT COUNT(*) FROM core.review_cards WHERE user_id = :uid AND course_id = :cid AND due_at <= now()")
                .param("uid", principal.userId()).param("cid", cid).query(Integer.class).single();

        List<Map<String, Object>> nodes = jdbc.sql("SELECT id, title, bloom_level FROM core.skills WHERE course_id = :cid ORDER BY skill_key ASC")
                .param("cid", cid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", IdCodec.format("skl", rs.getObject("id", UUID.class)),
                        "title", rs.getString("title"),
                        "bloomLevel", rs.getString("bloom_level")
                ))
                .list();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("nextLesson", nextOpt.orElse(null));
        out.put("reviewLessonId", null);
        out.put("reviewDueCount", dueCount);
        out.put("blockedBy", List.of());
        out.put("prerequisitesDag", Map.of("nodes", nodes, "edges", List.of()));
        out.put("recommendationToken", null);
        return out;
    }

    @PostMapping("/v1/courses/{courseId}/recommendation-events")
    @Transactional
    public Map<String, Object> recordRecommendation(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody RecommendationEventRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        String tokenHash;
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            tokenHash = HexFormat.of().formatHex(md.digest(body.recommendationToken().getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }

        UUID eventId = UUID.randomUUID();
        int inserted = jdbc.sql("""
                INSERT INTO core.recommendation_events (id, user_id, course_id, token_hash)
                VALUES (:id, :uid, :cid, :hash)
                ON CONFLICT (user_id, course_id, token_hash) DO NOTHING
                """)
                .param("id", eventId)
                .param("uid", principal.userId())
                .param("cid", cid)
                .param("hash", tokenHash)
                .update();

        return Map.of(
                "recorded", inserted > 0,
                "duplicate", inserted == 0,
                "exposureId", IdCodec.format("exp", eventId),
                "reason", inserted > 0 ? "recorded" : "duplicate"
        );
    }

    @GetMapping("/v1/reviews/due")
    public Map<String, Object> dueReviews(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(required = false) String courseId,
            @RequestParam(defaultValue = "20") int limit
    ) {
        requireP50Enabled();
        int safeLimit = Math.max(1, Math.min(limit, 50));
        UUID cid = (courseId != null && !courseId.isBlank()) ? IdCodec.parse(courseId, "crs") : null;

        String sql = cid == null
                ? """
                  SELECT rc.id, rc.lesson_id, l.title AS lesson_title, rc.due_at, rc.state
                  FROM core.review_cards rc
                  JOIN core.lessons l ON l.id = rc.lesson_id
                  WHERE rc.user_id = :uid AND rc.due_at <= now()
                  ORDER BY rc.due_at ASC
                  LIMIT :limit
                  """
                : """
                  SELECT rc.id, rc.lesson_id, l.title AS lesson_title, rc.due_at, rc.state
                  FROM core.review_cards rc
                  JOIN core.lessons l ON l.id = rc.lesson_id
                  WHERE rc.user_id = :uid AND rc.course_id = :cid AND rc.due_at <= now()
                  ORDER BY rc.due_at ASC
                  LIMIT :limit
                  """;

        var stmt = jdbc.sql(sql).param("uid", principal.userId()).param("limit", safeLimit);
        if (cid != null) stmt = stmt.param("cid", cid);

        Instant now = Instant.now();
        List<Map<String, Object>> items = stmt.query((rs, rowNum) -> {
            Instant dueAt = rs.getTimestamp("due_at").toInstant();
            long overdueDays = Math.max(0L, Duration.between(dueAt, now).toDays());
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("cardId", IdCodec.format("crd", rs.getObject("id", UUID.class)));
            m.put("lessonId", IdCodec.format("lsn", rs.getObject("lesson_id", UUID.class)));
            m.put("lessonTitle", rs.getString("lesson_title"));
            m.put("dueAt", dueAt.toString());
            m.put("state", rs.getInt("state"));
            m.put("overdueDays", overdueDays);
            return m;
        }).list();

        return Map.of("items", items, "total", items.size());
    }

    @PostMapping("/v1/reviews/{cardId}/grade")
    @Transactional
    public Map<String, Object> gradeReview(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String cardId,
            @Valid @RequestBody ReviewGradeRequest body,
            HttpServletRequest request
    ) {
        requireP50Enabled();
        csrf.verify(request);
        rateLimiter.check(request, "review_grade", 60, 60);

        UUID cid = IdCodec.parse(cardId, "crd");
        UUID uid = principal.userId();

        var card = jdbc.sql("""
                SELECT id, lesson_id, state, stability, difficulty, due_at, last_review_at
                FROM core.review_cards
                WHERE id = :cid AND user_id = :uid
                FOR UPDATE
                """)
                .param("cid", cid)
                .param("uid", uid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getObject("id", UUID.class));
                    m.put("lessonId", rs.getObject("lesson_id", UUID.class));
                    m.put("state", rs.getInt("state"));
                    m.put("stability", rs.getDouble("stability"));
                    m.put("difficulty", rs.getDouble("difficulty"));
                    m.put("dueAt", rs.getTimestamp("due_at").toInstant());
                    var lr = rs.getTimestamp("last_review_at");
                    m.put("lastReviewAt", lr == null ? null : lr.toInstant());
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CARD_NOT_FOUND", "Không tìm thấy thẻ ôn tập."));

        var existing = jdbc.sql("""
                SELECT id FROM core.review_events
                WHERE card_id = :cid AND user_id = :uid AND client_review_id = :crid
                """)
                .param("cid", cid)
                .param("uid", uid)
                .param("crid", body.clientReviewId().trim())
                .query(UUID.class)
                .optional();

        if (existing.isPresent()) {
            Instant due = (Instant) card.get("dueAt");
            Instant lr = (Instant) card.get("lastReviewAt");
            return Map.of(
                    "card", Map.of(
                            "cardId", IdCodec.format("crd", cid),
                            "lessonId", IdCodec.format("lsn", (UUID) card.get("lessonId")),
                            "state", card.get("state"),
                            "dueAt", due.toString(),
                            "lastReviewAt", lr == null ? "" : lr.toString()
                    ),
                    "eventId", IdCodec.format("rev", existing.get()),
                    "duplicate", true
            );
        }

        // Deterministic FSRS-inspired interval progression (1=Again, 2=Hard, 3=Good, 4=Easy)
        double stability = ((Number) card.get("stability")).doubleValue();
        double difficulty = ((Number) card.get("difficulty")).doubleValue();
        int rating = body.rating();
        int nextState;
        double nextStability;
        double nextDifficulty;
        long intervalHours;
        switch (rating) {
            case 1 -> {
                nextState = 3; // Relearning
                nextStability = Math.max(0.5, stability * 0.5);
                nextDifficulty = Math.min(10.0, difficulty + 0.8);
                intervalHours = 4;
            }
            case 2 -> {
                nextState = 2;
                nextStability = Math.max(1.0, stability * 1.2);
                nextDifficulty = Math.min(10.0, difficulty + 0.2);
                intervalHours = Math.max(12, Math.round(nextStability * 24));
            }
            case 4 -> {
                nextState = 2;
                nextStability = Math.min(365.0, stability * 2.5);
                nextDifficulty = Math.max(1.0, difficulty - 0.5);
                intervalHours = Math.max(48, Math.round(nextStability * 36));
            }
            default -> {
                nextState = 2;
                nextStability = Math.min(365.0, stability * 1.8);
                nextDifficulty = Math.max(1.0, difficulty - 0.1);
                intervalHours = Math.max(24, Math.round(nextStability * 24));
            }
        }

        Instant now = Instant.now();
        Instant nextDue = now.plusSeconds(intervalHours * 3600L);
        UUID eventId = UUID.randomUUID();

        jdbc.sql("""
                INSERT INTO core.review_events (id, card_id, user_id, client_review_id, rating, duration_ms)
                VALUES (:eid, :cid, :uid, :crid, :rating, :dur)
                """)
                .param("eid", eventId)
                .param("cid", cid)
                .param("uid", uid)
                .param("crid", body.clientReviewId().trim())
                .param("rating", rating)
                .param("dur", body.durationMs())
                .update();

        jdbc.sql("""
                UPDATE core.review_cards
                SET state = :state, stability = :stab, difficulty = :diff,
                    due_at = :due, last_review_at = :now
                WHERE id = :cid
                """)
                .param("state", nextState)
                .param("stab", nextStability)
                .param("diff", nextDifficulty)
                .param("due", Timestamp.from(nextDue))
                .param("now", Timestamp.from(now))
                .param("cid", cid)
                .update();

        Map<String, Object> heartInfo = gamification.refillHeartOnFsrsReview(uid, now);

        Map<String, Object> cardOut = new LinkedHashMap<>();
        cardOut.put("cardId", IdCodec.format("crd", cid));
        cardOut.put("lessonId", IdCodec.format("lsn", (UUID) card.get("lessonId")));
        cardOut.put("state", nextState);
        cardOut.put("dueAt", nextDue.toString());
        cardOut.put("lastReviewAt", now.toString());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("card", cardOut);
        out.put("eventId", IdCodec.format("rev", eventId));
        out.put("duplicate", false);
        out.put("hearts", heartInfo.get("hearts"));
        out.put("heartsMax", heartInfo.get("heartsMax"));
        out.put("heartsRefilled", heartInfo.get("heartsRefilled"));
        out.put("heartsRefillAt", heartInfo.get("heartsRefillAt"));
        out.put("newlyEarnedMilestones", heartInfo.get("newlyEarnedMilestones"));
        return out;
    }

    private void requireP50Enabled() {
        if (!props.p50Enabled()) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "P50_DISABLED", "Tính năng ôn tập & lộ trình chưa được bật.");
        }
    }

    private void verifyOwnedCourse(UUID userId, UUID courseId) {
        Integer found = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE id = :cid AND user_id = :uid")
                .param("cid", courseId).param("uid", userId).query(Integer.class).single();
        if (found == null || found == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học.");
        }
    }
}
