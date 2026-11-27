package com.sopiskill.core.lesson;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.gamification.GamificationService;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import com.sopiskill.core.sources.CitationLinkResolver;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Lesson retrieval (0 answer keys), single-transaction Attempt + XP + Streak + Mastery + FSRS,
 * and Wave 4 per-block grading + bounded AI short-answer dispute.
 */
@RestController
@RequestMapping("/v1/lessons")
public class LessonController {

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final PublicBlockProjector projector;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final AiEngineClient aiEngine;
    private final GamificationService gamification;
    private final SopiProperties props;

    public LessonController(
            JdbcClient jdbc,
            JsonHelper json,
            PublicBlockProjector projector,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            AiEngineClient aiEngine,
            GamificationService gamification,
            SopiProperties props
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.projector = projector;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.aiEngine = aiEngine;
        this.gamification = gamification;
        this.props = props;
    }

    public record AnswerItem(@NotNull Integer index, Object answer) {}

    public record AttemptRequest(
            @NotBlank String clientAttemptId,
            @NotNull Integer contentVersion,
            @NotNull List<AnswerItem> answers
    ) {}

    public record BlockGradeRequest(
            @NotNull Integer contentVersion,
            Object answer,
            Boolean dispute,
            String disputeReason
    ) {}

    public record DisputeGradeRequest(String reason) {}

    @GetMapping("/{lessonId}")
    public Map<String, Object> getLesson(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            @RequestParam(defaultValue = "0") int prefetch,
            @RequestHeader(value = "X-Client-Blocks", required = false) String clientBlocksHeader,
            HttpServletResponse response
    ) {
        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(principal.userId(), lid);
        if (prefetch == 1) {
            response.setHeader("Cache-Control", "private, max-age=30");
        }
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lesson.get("blocks");
        int contentVersion = ((Number) lesson.get("contentVersion")).intValue();
        var clientCaps = PublicBlockProjector.parseClientCapabilities(clientBlocksHeader);

        List<Map<String, Object>> citations = jdbc.sql("""
                SELECT lc.id, lc.source_id, lc.source_version, lc.chunk_id, lc.page_number,
                       lc.section_anchor, lc.evidence_text, lc.validation_status,
                       s.title AS source_title, s.canonical_url AS source_url,
                       s.author AS source_author, s.publisher AS source_publisher,
                       s.license_info AS source_license, s.pedagogy_tier AS source_tier,
                       s.verification_status AS source_verification_status
                FROM core.lesson_citations lc
                JOIN core.sources s ON s.id = lc.source_id
                WHERE lc.lesson_id = :lid
                """)
                .param("lid", lid)
                .query((rs, rowNum) -> {
                    String canonicalUrl = rs.getString("source_url");
                    String anchor = rs.getString("section_anchor");
                    String title = rs.getString("source_title");
                    String author = rs.getString("source_author");
                    String publisher = rs.getString("source_publisher");
                    String licenseInfo = rs.getString("source_license");
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("citationId", IdCodec.format("cit", rs.getObject("id", UUID.class)));
                    c.put("sourceId", IdCodec.format("src", rs.getObject("source_id", UUID.class)));
                    c.put("sourceVersion", rs.getString("source_version"));
                    c.put("chunkId", rs.getString("chunk_id"));
                    c.put("pageNumber", rs.getObject("page_number"));
                    c.put("sectionAnchor", anchor);
                    c.put("evidenceText", rs.getString("evidence_text"));
                    c.put("validationStatus", rs.getString("validation_status"));
                    c.put("sourceTitle", title);
                    c.put("sourceUrl", CitationLinkResolver.resolveDeepLink(canonicalUrl, anchor));
                    c.put("author", author);
                    c.put("publisher", publisher);
                    c.put("licenseInfo", licenseInfo);
                    c.put("attributionText", formatAttributionText(title, author, publisher, licenseInfo, canonicalUrl));
                    c.put("sourceVerificationStatus", rs.getString("source_verification_status"));
                    return c;
                })
                .list();

        UUID courseUuid = (UUID) lesson.get("courseUuid");
        List<Map<String, Object>> attributions = jdbc.sql("""
                SELECT DISTINCT s.id, s.title, s.author, s.publisher, s.license_info,
                       s.canonical_url, s.pedagogy_tier, s.commercial_safe
                FROM core.course_sources cs
                JOIN core.sources s ON s.id = cs.source_id
                WHERE cs.course_id = :cid
                ORDER BY s.title ASC
                """)
                .param("cid", courseUuid)
                .query((rs, rowNum) -> {
                    String title = rs.getString("title");
                    String author = rs.getString("author");
                    String publisher = rs.getString("publisher");
                    String licenseInfo = rs.getString("license_info");
                    String canonicalUrl = rs.getString("canonical_url");
                    Map<String, Object> a = new LinkedHashMap<>();
                    a.put("sourceId", IdCodec.format("src", rs.getObject("id", UUID.class)));
                    a.put("title", title);
                    a.put("author", author);
                    a.put("publisher", publisher);
                    a.put("licenseInfo", licenseInfo);
                    a.put("canonicalUrl", canonicalUrl);
                    a.put("pedagogyTier", rs.getString("pedagogy_tier"));
                    a.put("commercialSafe", rs.getBoolean("commercial_safe"));
                    a.put("attributionText", formatAttributionText(title, author, publisher, licenseInfo, canonicalUrl));
                    return a;
                })
                .list();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("lsn", lid));
        out.put("courseId", IdCodec.format("crs", courseUuid));
        out.put("title", lesson.get("title"));
        out.put("orderIndex", lesson.get("orderIndex"));
        out.put("contentVersion", contentVersion);
        out.put("status", lesson.get("status"));
        out.put("estimatedMinutes", lesson.get("estimatedMinutes"));
        out.put("kind", lesson.get("kind"));
        out.put("format", lesson.get("format"));
        out.put("blocks", projector.toPublicBlocks(lid, contentVersion, privateBlocks, clientCaps));
        out.put("reel", props.reelEnabled() ? lesson.get("reel") : null);
        out.put("reelStatus", props.reelEnabled() ? lesson.get("reelStatus") : "disabled");
        out.put("grounding", lesson.get("grounding"));
        out.put("citations", citations);
        out.put("attributions", attributions);
        out.put("evidenceNotice", lesson.get("evidenceNotice"));
        return out;
    }

    private static final java.util.regex.Pattern SAFE_REEL_CLIP_ID =
            java.util.regex.Pattern.compile("^[a-zA-Z0-9_-]{1,80}\\.(wav|mp3|ogg|webm)$");
    private static final java.util.Set<String> ALLOWED_AUDIO_MIME = java.util.Set.of(
            "audio/wav", "audio/mpeg", "audio/ogg", "audio/webm"
    );

    @GetMapping("/{lessonId}/reel/audio/{clipId}")
    public ResponseEntity<byte[]> getReelAudio(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            @PathVariable String clipId,
            HttpServletRequest request
    ) {
        if (!props.reelEnabled()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "REEL_DISABLED", "Tính năng Reel đang tắt.");
        }
        rateLimiter.check(request, "reel_audio", 240, 60);
        if (!SAFE_REEL_CLIP_ID.matcher(clipId).matches()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "INVALID_REEL_CLIP", "Mã âm thanh Reel không hợp lệ.");
        }

        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(principal.userId(), lid);
        UUID courseUuid = (UUID) lesson.get("courseUuid");

        // Verify this clip actually belongs to this owned lesson in core.media_calls (no cross-lesson traversal)
        var mediaRow = jdbc.sql("""
                        SELECT content_type
                        FROM core.media_calls
                        WHERE lesson_id = :lid AND clip_id = :clip
                        ORDER BY created_at DESC
                        LIMIT 1
                        """)
                .param("lid", lid)
                .param("clip", clipId)
                .query(String.class)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "REEL_AUDIO_NOT_FOUND", "Không tìm thấy tệp âm thanh Reel."));

        String formattedCourseId = IdCodec.format("crs", courseUuid);
        String formattedLessonId = IdCodec.format("lsn", lid);
        String internalPath = "/internal/reels/audio/" + formattedCourseId + "/" + formattedLessonId + "/" + clipId;
        var upstream = aiEngine.getBinary(internalPath, "reel_" + clipId);
        if (upstream.statusCode() == 404) {
            throw new ApiException(HttpStatus.NOT_FOUND, "REEL_AUDIO_NOT_FOUND", "Không tìm thấy tệp âm thanh Reel.");
        }
        if (upstream.statusCode() < 200 || upstream.statusCode() >= 300) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "REEL_AUDIO_UPSTREAM_ERROR", "Không thể tải âm thanh Reel.");
        }

        String rawType = upstream.headers().firstValue("content-type").orElse(mediaRow).split(";")[0].trim().toLowerCase();
        String safeType = ALLOWED_AUDIO_MIME.contains(rawType) ? rawType : "audio/wav";

        return ResponseEntity.ok()
                .header("Content-Type", safeType)
                .header("Cache-Control", "private, max-age=86400")
                .header("Accept-Ranges", "bytes")
                .header("X-Content-Type-Options", "nosniff")
                .body(upstream.body());
    }

    private static String formatAttributionText(
            String title,
            String author,
            String publisher,
            String licenseInfo,
            String canonicalUrl
    ) {
        StringBuilder sb = new StringBuilder();
        if (title != null && !title.isBlank()) sb.append(title.trim());
        if (author != null && !author.isBlank()) sb.append(" — ").append(author.trim());
        if (publisher != null && !publisher.isBlank()) sb.append(" (").append(publisher.trim()).append(")");
        if (licenseInfo != null && !licenseInfo.isBlank()) sb.append(" · ").append(licenseInfo.trim());
        if (canonicalUrl != null && canonicalUrl.toLowerCase().contains("openstax.org")) {
            sb.append(" · Access for free at openstax.org");
        }
        return sb.toString();
    }

    @PostMapping("/{lessonId}/retry")
    @Transactional
    public Map<String, Object> retryLesson(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "lesson_retry", 20, 60);
        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(principal.userId(), lid);
        UUID cid = (UUID) lesson.get("courseUuid");

        String unitTitle = jdbc.sql("""
                SELECT u.title FROM core.units u
                JOIN core.lessons l ON l.unit_id = u.id
                WHERE l.id = :lid
                """).param("lid", lid).query(String.class).single();
        String topic = jdbc.sql("SELECT topic FROM core.courses WHERE id = :cid")
                .param("cid", cid).query(String.class).single();

        jdbc.sql("UPDATE core.lessons SET status = 'queued', updated_at = now() WHERE id = :lid")
                .param("lid", lid)
                .update();

        UUID jobId = UUID.randomUUID();
        String idempKey = "retry_lsn_" + lid + "_" + jobId;
        jdbc.sql("""
                INSERT INTO core.generation_jobs (
                    id, course_id, idempotency_key, status, stage, lessons_done, lessons_total, attempts, dispatched
                ) VALUES (
                    :jid, :cid, :idem, 'queued', 'lessons', 0, 1, 1, TRUE
                )
                """)
                .param("jid", jobId)
                .param("cid", cid)
                .param("idem", idempKey)
                .update();

        aiEngine.enqueueLlmJob(Map.of(
                "jobId", IdCodec.format("job", jobId),
                "idempotencyKey", idempKey,
                "jobType", "generate_lesson",
                "ownerId", IdCodec.format("usr", principal.userId()),
                "courseId", IdCodec.format("crs", cid),
                "correlationId", "cor_" + jobId.toString().replace("-", "").substring(0, 16),
                "attempt", 1,
                "payload", Map.of(
                        "topic", topic,
                        "language", lesson.getOrDefault("language", "vi"),
                        "unitTitle", unitTitle,
                        "lessonTitle", lesson.get("title"),
                        "lessonIds", List.of(IdCodec.format("lsn", lid)),
                        "contentVersion", ((Number) lesson.get("contentVersion")).intValue(),
                        "reelEnabled", props.reelEnabled()
                )
        ));

        return Map.of(
                "lessonId", IdCodec.format("lsn", lid),
                "jobId", IdCodec.format("job", jobId),
                "status", "queued"
        );
    }

    @PostMapping("/{lessonId}/attempts")
    @Transactional
    public Map<String, Object> submitAttempt(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            @Valid @RequestBody AttemptRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "lesson_attempt", 60, 60);

        UUID uid = principal.userId();
        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(uid, lid);
        UUID courseId = (UUID) lesson.get("courseUuid");
        int currentVersion = ((Number) lesson.get("contentVersion")).intValue();

        if (!body.contentVersion().equals(currentVersion)) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "CONTENT_VERSION_STALE",
                    "Nội dung bài học đã được cập nhật, hãy tải lại trang.",
                    Map.of("currentVersion", currentVersion)
            );
        }

        // Lock user row (`SELECT ... FOR UPDATE`) to serialize concurrent attempt XP/streak/hearts/mastery/milestones/league writes!
        Instant now = Instant.now();
        var userRow = jdbc.sql("""
                SELECT xp, streak_days, best_streak_days, last_active_day, last_active_date,
                       streak_freezes, hearts, hearts_refill_at, timezone
                FROM core.users
                WHERE id = :uid
                FOR UPDATE
                """)
                .param("uid", uid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("xp", rs.getInt("xp"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    m.put("bestStreakDays", rs.getInt("best_streak_days"));
                    var lad = rs.getDate("last_active_day");
                    if (lad == null) lad = rs.getDate("last_active_date");
                    m.put("lastActiveDay", lad == null ? null : lad.toLocalDate());
                    m.put("streakFreezes", rs.getInt("streak_freezes"));
                    m.put("hearts", rs.getInt("hearts"));
                    var ra = rs.getTimestamp("hearts_refill_at");
                    m.put("heartsRefillAt", ra == null ? null : ra.toInstant());
                    m.put("timezone", rs.getString("timezone"));
                    return m;
                })
                .single();

        int currentXp = ((Number) userRow.get("xp")).intValue();

        // Idempotency check AFTER locking user row so 20 concurrent requests with same clientAttemptId never double-award XP!
        var existingOpt = jdbc.sql("""
                SELECT id, correct, total, results_json
                FROM core.lesson_attempts
                WHERE lesson_id = :lid AND user_id = :uid AND client_attempt_id = :cid
                """)
                .param("lid", lid)
                .param("uid", uid)
                .param("cid", body.clientAttemptId().trim())
                .query((rs, rowNum) -> {
                    List<Map<String, Object>> storedResults = json.fromJson(
                            rs.getString("results_json"),
                            new TypeReference<List<Map<String, Object>>>() {}
                    );
                    var effectiveHearts = gamification.computeEffectiveHearts(
                            ((Number) userRow.get("hearts")).intValue(),
                            (Instant) userRow.get("heartsRefillAt"),
                            now
                    );
                    Map<String, Object> rewards = new LinkedHashMap<>();
                    rewards.put("xp", currentXp);
                    rewards.put("xpEarned", 0);
                    rewards.put("streakDays", userRow.get("streakDays"));
                    rewards.put("bestStreakDays", userRow.get("bestStreakDays"));
                    rewards.put("streakFreezes", userRow.get("streakFreezes"));
                    rewards.put("freezeConsumed", false);
                    rewards.put("freezeEarned", false);
                    rewards.put("hearts", effectiveHearts.hearts());
                    rewards.put("heartsMax", effectiveHearts.heartsMax());
                    rewards.put("heartsRefillAt", effectiveHearts.heartsRefillAt() == null ? null : effectiveHearts.heartsRefillAt().toString());
                    rewards.put("heartLost", false);

                    Map<String, Object> dupOut = new LinkedHashMap<>();
                    dupOut.put("attemptId", IdCodec.format("att", rs.getObject("id", UUID.class)));
                    dupOut.put("duplicate", true);
                    dupOut.put("score", Map.of("correct", rs.getInt("correct"), "total", rs.getInt("total")));
                    dupOut.put("rewards", rewards);
                    dupOut.put("results", storedResults);
                    dupOut.put("unitBreakdown", GamificationService.buildUnitBreakdown(storedResults));
                    dupOut.put("newlyEarnedMilestones", List.of());
                    dupOut.put("reviewCardCreated", false);
                    return dupOut;
                })
                .optional();

        if (existingOpt.isPresent()) {
            return existingOpt.get();
        }

        // Enforce Hearts availability (409 OUT_OF_HEARTS when HEARTS_ENFORCEMENT_ENABLED=true and hearts==0)
        gamification.checkHeartsAvailableOrThrow(
                ((Number) userRow.get("hearts")).intValue(),
                (Instant) userRow.get("heartsRefillAt"),
                now
        );

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lesson.get("blocks");
        Map<Integer, Object> answersByIndex = new LinkedHashMap<>();
        for (AnswerItem item : body.answers()) {
            answersByIndex.put(item.index(), item.answer());
        }

        List<Map<String, Object>> results = new ArrayList<>();
        int correct = 0;
        int total = 0;
        for (int i = 0; i < privateBlocks.size(); i++) {
            Map<String, Object> blk = privateBlocks.get(i);
            String btype = String.valueOf(blk.getOrDefault("type", ""));
            if (!projector.isGradable(blk)) continue;
            total++;
            boolean ok = projector.gradeBlock(lid, currentVersion, i, blk, answersByIndex.get(i));
            if (ok) correct++;
            results.add(Map.of(
                    "index", i,
                    "type", btype,
                    "correct", ok,
                    "solution", projector.solutionFor(blk)
            ));
        }

        boolean completed = PublicBlockProjector.isCompleted(correct, total);
        int rawXp = gamification.computeRawLessonXp(correct, total, completed);

        Integer prevAwarded = jdbc.sql("""
                SELECT COALESCE(SUM(xp_earned), 0)
                FROM core.lesson_attempts
                WHERE user_id = :uid AND lesson_id = :lid AND content_version = :ver
                """)
                .param("uid", uid)
                .param("lid", lid)
                .param("ver", currentVersion)
                .query(Integer.class)
                .single();
        int alreadyAwarded = prevAwarded == null ? 0 : prevAwarded;
        int xpEarned = Math.max(0, rawXp - alreadyAwarded);

        UUID attemptId = UUID.randomUUID();
        try {
            jdbc.sql("""
                    INSERT INTO core.lesson_attempts (
                        id, lesson_id, user_id, client_attempt_id, content_version,
                        correct, total, completed, xp_earned, answers_json, results_json
                    ) VALUES (
                        :id, :lid, :uid, :caid, :ver, :correct, :total, :completed, :xpEarned,
                        CAST(:answers AS jsonb), CAST(:results AS jsonb)
                    )
                    """)
                    .param("id", attemptId)
                    .param("lid", lid)
                    .param("uid", uid)
                    .param("caid", body.clientAttemptId().trim())
                    .param("ver", currentVersion)
                    .param("correct", correct)
                    .param("total", total)
                    .param("completed", completed)
                    .param("xpEarned", xpEarned)
                    .param("answers", json.toJson(body.answers()))
                    .param("results", json.toJson(results))
                    .update();
        } catch (DataIntegrityViolationException dup) {
            return Map.of(
                    "attemptId", IdCodec.format("att", attemptId),
                    "duplicate", true,
                    "score", Map.of("correct", correct, "total", total),
                    "rewards", Map.of("xp", currentXp, "xpEarned", 0),
                    "results", results,
                    "unitBreakdown", GamificationService.buildUnitBreakdown(results),
                    "newlyEarnedMilestones", List.of(),
                    "reviewCardCreated", false
            );
        }

        // Update XP + Timezone Streak/Freeze + Hearts + Daily Activity + Milestones + League inside 1 ACID transaction
        var gamResult = gamification.applyAttemptRewards(
                uid, courseId, lid, userRow, correct, total, completed, xpEarned, now
        );

        if (xpEarned > 0) {
            jdbc.sql("""
                    INSERT INTO core.xp_events (id, user_id, lesson_id, attempt_id, amount, reason)
                    VALUES (:id, :uid, :lid, :aid, :amt, 'lesson_attempt')
                    """)
                    .param("id", UUID.randomUUID())
                    .param("uid", uid)
                    .param("lid", lid)
                    .param("aid", attemptId)
                    .param("amt", xpEarned)
                    .update();
        }

        // Update BKT/EWMA Skill Mastery inside the same transaction
        double accuracy = total == 0 ? 1.0 : ((double) correct / total);
        List<UUID> skillIds = jdbc.sql("SELECT skill_id FROM core.lesson_skills WHERE lesson_id = :lid")
                .param("lid", lid).query(UUID.class).list();
        for (UUID skillId : skillIds) {
            jdbc.sql("""
                    INSERT INTO core.skill_mastery (
                        id, user_id, course_id, skill_id, mastery_score, method,
                        attempts, correct, total, pass_threshold, last_attempt_at
                    ) VALUES (
                        :id, :uid, :cid, :sid, :score, 'bkt_ewma', 1, :correct, :total, 0.7, now()
                    )
                    ON CONFLICT (user_id, skill_id) DO UPDATE SET
                        mastery_score = LEAST(1.0, GREATEST(0.0, core.skill_mastery.mastery_score * 0.4 + :score * 0.6)),
                        attempts = core.skill_mastery.attempts + 1,
                        correct = core.skill_mastery.correct + :correct,
                        total = core.skill_mastery.total + :total,
                        last_attempt_at = now()
                    """)
                    .param("id", UUID.randomUUID())
                    .param("uid", uid)
                    .param("cid", courseId)
                    .param("sid", skillId)
                    .param("score", accuracy)
                    .param("correct", correct)
                    .param("total", total)
                    .update();
        }

        // Create initial FSRS review card on first attempt
        int createdCard = jdbc.sql("""
                INSERT INTO core.review_cards (id, user_id, course_id, lesson_id, state, stability, difficulty, due_at)
                VALUES (:id, :uid, :cid, :lid, 1, 1.0, 5.0, :due)
                ON CONFLICT (user_id, lesson_id) DO NOTHING
                """)
                .param("id", UUID.randomUUID())
                .param("uid", uid)
                .param("cid", courseId)
                .param("lid", lid)
                .param("due", java.sql.Timestamp.from(now.plusSeconds(86400)))
                .update();

        Map<String, Object> rewards = new LinkedHashMap<>();
        rewards.put("xp", gamResult.newXp());
        rewards.put("xpEarned", gamResult.xpEarned());
        rewards.put("streakDays", gamResult.streak().streakDays());
        rewards.put("bestStreakDays", gamResult.streak().bestStreakDays());
        rewards.put("streakFreezes", gamResult.streak().streakFreezes());
        rewards.put("freezeConsumed", gamResult.streak().freezeConsumed());
        rewards.put("freezeEarned", gamResult.streak().freezeEarned());
        rewards.put("hearts", gamResult.hearts().hearts());
        rewards.put("heartsMax", gamResult.hearts().heartsMax());
        rewards.put("heartsRefillAt", gamResult.hearts().heartsRefillAt() == null ? null : gamResult.hearts().heartsRefillAt().toString());
        rewards.put("heartLost", gamResult.heartLost());

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("attemptId", IdCodec.format("att", attemptId));
        resp.put("duplicate", false);
        resp.put("score", Map.of("correct", correct, "total", total));
        resp.put("rewards", rewards);
        resp.put("results", results);
        resp.put("unitBreakdown", GamificationService.buildUnitBreakdown(results));
        resp.put("newlyEarnedMilestones", gamResult.newlyEarnedMilestones());
        resp.put("reviewCardCreated", createdCard > 0);
        return resp;
    }

    @PostMapping("/{lessonId}/blocks/{blockIndex}/grade")
    @Transactional
    public Map<String, Object> gradeSingleBlock(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            @PathVariable int blockIndex,
            @Valid @RequestBody BlockGradeRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "block_grade", 120, 60);

        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(principal.userId(), lid);
        int currentVersion = ((Number) lesson.get("contentVersion")).intValue();
        if (!body.contentVersion().equals(currentVersion)) {
            throw new ApiException(HttpStatus.CONFLICT, "CONTENT_VERSION_STALE", "Nội dung bài học đã cập nhật.");
        }

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lesson.get("blocks");
        if (blockIndex < 0 || blockIndex >= privateBlocks.size()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "BLOCK_INDEX_INVALID", "Chỉ số block không hợp lệ.");
        }

        Map<String, Object> block = privateBlocks.get(blockIndex);
        String btype = String.valueOf(block.getOrDefault("type", ""));
        if (!projector.isGradable(block)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "BLOCK_NOT_GRADABLE", "Block bài giảng/tổng kết không chấm điểm.");
        }

        boolean ok;
        String grader = "deterministic";
        String feedback;
        String verdict = null;
        String gradeId = null;
        List<String> keyPointsOut = null;
        List<Integer> correctIndices = List.of();
        String selectedOutcome = null;

        if ("short".equals(btype)) {
            var eval = projector.evaluateShortThreeLevel(block, body.answer());
            ok = eval.correct();
            verdict = eval.verdict();
            grader = eval.grader();
            feedback = eval.feedback();
            keyPointsOut = eval.matchedKeyPoints();

            if (!ok && Boolean.TRUE.equals(body.dispute())) {
                try {
                    Map<String, Object> aiResp = aiEngine.postJson(
                            "/internal/lessons/grade-short",
                            Map.of(
                                    "lessonId", IdCodec.format("lsn", lid),
                                    "blockIndex", blockIndex,
                                    "language", lesson.getOrDefault("language", "vi"),
                                    "prompt", String.valueOf(block.getOrDefault("question", "")),
                                    "learnerAnswer", body.answer() == null ? "" : String.valueOf(body.answer()),
                                    "acceptedAnswers", block.getOrDefault("acceptedAnswers", List.of()),
                                    "dispute", true
                            ),
                            null
                    );
                    ok = Boolean.TRUE.equals(aiResp.get("correct"));
                    verdict = ok ? "got_it" : String.valueOf(aiResp.getOrDefault("verdict", verdict));
                    grader = "llm_rubric";
                    feedback = String.valueOf(aiResp.getOrDefault("feedback", "Đã chấm lại theo tiêu chí."));
                } catch (Exception ex) {
                    ok = false;
                    feedback = "Không thể gọi chấm lại AI lúc này. Hãy đối chiếu với đáp án mẫu.";
                }
            }

            UUID sagId = UUID.randomUUID();
            jdbc.sql("""
                    INSERT INTO core.short_answer_grades (
                        id, lesson_id, user_id, block_index, content_version, learner_answer,
                        verdict, correct, grader, key_points, feedback, disputed, dispute_reason
                    ) VALUES (
                        :id, :lid, :uid, :bidx, :ver, :ans,
                        :verdict, :correct, :grader, CAST(:kps AS jsonb), :fb, :disputed, :reason
                    )
                    """)
                    .param("id", sagId)
                    .param("lid", lid)
                    .param("uid", principal.userId())
                    .param("bidx", blockIndex)
                    .param("ver", currentVersion)
                    .param("ans", body.answer() == null ? "" : String.valueOf(body.answer()))
                    .param("verdict", verdict)
                    .param("correct", ok)
                    .param("grader", grader)
                    .param("kps", json.toJson(keyPointsOut))
                    .param("fb", feedback)
                    .param("disputed", Boolean.TRUE.equals(body.dispute()))
                    .param("reason", body.disputeReason())
                    .update();
            gradeId = IdCodec.format("sag", sagId);
        } else {
            ok = projector.gradeBlock(lid, currentVersion, blockIndex, block, body.answer());
            correctIndices = projector.computeCorrectIndices(lid, currentVersion, blockIndex, block, body.answer());
            selectedOutcome = projector.selectedOutcomeFor(block, body.answer());
            feedback = ok
                    ? "Chính xác!"
                    : (selectedOutcome != null
                            ? selectedOutcome
                            : (!correctIndices.isEmpty()
                                    ? "Bạn đã đúng một phần! Các vị trí đúng đã được giữ lại — hãy thử lại phần còn lại."
                                    : "Chưa chính xác. Hãy xem lại gợi ý và thử lại."));
        }

        // For multi-blank wrong answers, lock `correctIndices` and DO NOT leak remaining answers in `solution`!
        boolean hideSolutionForRetry = !ok && (projector.isMultiBlank(block) || "speed".equals(btype));

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("blockIndex", blockIndex);
        out.put("type", btype);
        out.put("correct", ok);
        out.put("grader", grader);
        out.put("feedback", feedback);
        out.put("solution", hideSolutionForRetry ? null : projector.solutionFor(block));
        out.put("disputeAllowed", "short".equals(btype) && !ok);
        if (!correctIndices.isEmpty()) out.put("correctIndices", correctIndices);
        if (selectedOutcome != null) out.put("outcome", selectedOutcome);
        if (verdict != null) out.put("verdict", verdict);
        if (gradeId != null) out.put("gradeId", gradeId);
        if (keyPointsOut != null) out.put("keyPoints", keyPointsOut);
        return out;
    }

    @PostMapping("/{lessonId}/grades/{gradeId}/dispute")
    @Transactional
    public Map<String, Object> disputeShortAnswerGrade(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId,
            @PathVariable String gradeId,
            @RequestBody(required = false) DisputeGradeRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "grade_dispute", 30, 60);

        UUID lid = IdCodec.parse(lessonId, "lsn");
        UUID gid = IdCodec.parse(gradeId, "sag");
        var lesson = loadOwnedLesson(principal.userId(), lid);

        var gradeRow = jdbc.sql("""
                SELECT id, block_index, learner_answer, verdict, correct, key_points, feedback, disputed
                FROM core.short_answer_grades
                WHERE id = :gid AND lesson_id = :lid AND user_id = :uid
                FOR UPDATE
                """)
                .param("gid", gid)
                .param("lid", lid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("blockIndex", rs.getInt("block_index"));
                    m.put("learnerAnswer", rs.getString("learner_answer"));
                    m.put("verdict", rs.getString("verdict"));
                    m.put("correct", rs.getBoolean("correct"));
                    m.put("keyPoints", json.fromJson(rs.getString("key_points"), new TypeReference<List<String>>() {}));
                    m.put("feedback", rs.getString("feedback"));
                    m.put("disputed", rs.getBoolean("disputed"));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "GRADE_NOT_FOUND", "Không tìm thấy kết quả chấm."));

        int blockIndex = ((Number) gradeRow.get("blockIndex")).intValue();
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lesson.get("blocks");
        if (blockIndex < 0 || blockIndex >= privateBlocks.size()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "BLOCK_INDEX_INVALID", "Chỉ số block không hợp lệ.");
        }
        Map<String, Object> block = privateBlocks.get(blockIndex);

        boolean ok = Boolean.TRUE.equals(gradeRow.get("correct"));
        String verdict = String.valueOf(gradeRow.get("verdict"));
        String feedback = String.valueOf(gradeRow.get("feedback"));
        String grader = "llm_rubric";
        try {
            Map<String, Object> aiResp = aiEngine.postJson(
                    "/internal/lessons/grade-short",
                    Map.of(
                            "lessonId", IdCodec.format("lsn", lid),
                            "blockIndex", blockIndex,
                            "language", lesson.getOrDefault("language", "vi"),
                            "prompt", String.valueOf(block.getOrDefault("question", "")),
                            "learnerAnswer", String.valueOf(gradeRow.get("learnerAnswer")),
                            "acceptedAnswers", block.getOrDefault("acceptedAnswers", List.of()),
                            "dispute", true
                    ),
                    null
            );
            ok = Boolean.TRUE.equals(aiResp.get("correct"));
            verdict = ok ? "got_it" : String.valueOf(aiResp.getOrDefault("verdict", verdict));
            feedback = String.valueOf(aiResp.getOrDefault("feedback", "Đã chấm lại theo tiêu chí."));
        } catch (Exception ex) {
            feedback = "Không thể gọi chấm lại AI lúc này. Hãy đối chiếu với đáp án mẫu.";
        }

        jdbc.sql("""
                UPDATE core.short_answer_grades
                SET verdict = :verdict, correct = :correct, grader = :grader,
                    feedback = :fb, disputed = TRUE, dispute_reason = :reason, updated_at = now()
                WHERE id = :gid
                """)
                .param("verdict", verdict)
                .param("correct", ok)
                .param("grader", grader)
                .param("fb", feedback)
                .param("reason", body == null ? null : body.reason())
                .param("gid", gid)
                .update();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("gradeId", IdCodec.format("sag", gid));
        out.put("blockIndex", blockIndex);
        out.put("verdict", verdict);
        out.put("correct", ok);
        out.put("grader", grader);
        out.put("feedback", feedback);
        out.put("keyPoints", gradeRow.get("keyPoints"));
        out.put("disputed", true);
        out.put("solution", projector.solutionFor(block));
        return out;
    }

    private Map<String, Object> loadOwnedLesson(UUID userId, UUID lessonId) {
        return jdbc.sql("""
                SELECT l.id, l.course_id, l.title, l.order_index, l.status, l.content_version,
                       l.content_json, l.grounding, l.evidence_notice, l.estimated_minutes,
                       l.kind, l.format, l.reel_manifest::text AS reel_manifest_text, l.reel_status,
                       c.language
                FROM core.lessons l
                JOIN core.courses c ON c.id = l.course_id
                WHERE l.id = :lid AND c.user_id = :uid
                """)
                .param("lid", lessonId)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getObject("id", UUID.class));
                    m.put("courseUuid", rs.getObject("course_id", UUID.class));
                    m.put("title", rs.getString("title"));
                    m.put("orderIndex", rs.getInt("order_index"));
                    m.put("status", rs.getString("status"));
                    m.put("contentVersion", rs.getInt("content_version"));
                    m.put("blocks", json.fromJson(rs.getString("content_json"), new TypeReference<List<Map<String, Object>>>() {}));
                    m.put("grounding", rs.getString("grounding"));
                    m.put("evidenceNotice", rs.getString("evidence_notice"));
                    m.put("estimatedMinutes", rs.getInt("estimated_minutes"));
                    m.put("kind", rs.getString("kind"));
                    m.put("format", rs.getString("format"));
                    String reelJson = rs.getString("reel_manifest_text");
                    m.put("reel", reelJson == null ? null : json.fromJson(reelJson, new TypeReference<Map<String, Object>>() {}));
                    m.put("reelStatus", rs.getString("reel_status"));
                    m.put("language", rs.getString("language"));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "LESSON_NOT_FOUND", "Không tìm thấy bài học."));
    }
}
