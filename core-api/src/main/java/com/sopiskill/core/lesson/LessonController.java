package com.sopiskill.core.lesson;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
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
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
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

    public LessonController(
            JdbcClient jdbc,
            JsonHelper json,
            PublicBlockProjector projector,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            AiEngineClient aiEngine
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.projector = projector;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.aiEngine = aiEngine;
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

    @GetMapping("/{lessonId}")
    public Map<String, Object> getLesson(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String lessonId
    ) {
        UUID lid = IdCodec.parse(lessonId, "lsn");
        var lesson = loadOwnedLesson(principal.userId(), lid);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lesson.get("blocks");
        int contentVersion = ((Number) lesson.get("contentVersion")).intValue();

        List<Map<String, Object>> citations = jdbc.sql("""
                SELECT lc.id, lc.source_id, lc.source_version, lc.chunk_id, lc.page_number,
                       lc.section_anchor, lc.evidence_text, lc.validation_status,
                       s.title AS source_title, s.canonical_url AS source_url,
                       s.verification_status AS source_verification_status
                FROM core.lesson_citations lc
                JOIN core.sources s ON s.id = lc.source_id
                WHERE lc.lesson_id = :lid
                """)
                .param("lid", lid)
                .query((rs, rowNum) -> {
                    Map<String, Object> c = new LinkedHashMap<>();
                    c.put("citationId", IdCodec.format("cit", rs.getObject("id", UUID.class)));
                    c.put("sourceId", IdCodec.format("src", rs.getObject("source_id", UUID.class)));
                    c.put("sourceVersion", rs.getString("source_version"));
                    c.put("chunkId", rs.getString("chunk_id"));
                    c.put("pageNumber", rs.getObject("page_number"));
                    c.put("sectionAnchor", rs.getString("section_anchor"));
                    c.put("evidenceText", rs.getString("evidence_text"));
                    c.put("validationStatus", rs.getString("validation_status"));
                    c.put("sourceTitle", rs.getString("source_title"));
                    c.put("sourceUrl", rs.getString("source_url"));
                    c.put("sourceVerificationStatus", rs.getString("source_verification_status"));
                    return c;
                })
                .list();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("lsn", lid));
        out.put("courseId", IdCodec.format("crs", (UUID) lesson.get("courseUuid")));
        out.put("title", lesson.get("title"));
        out.put("orderIndex", lesson.get("orderIndex"));
        out.put("contentVersion", contentVersion);
        out.put("status", lesson.get("status"));
        out.put("blocks", projector.toPublicBlocks(lid, contentVersion, privateBlocks));
        out.put("grounding", lesson.get("grounding"));
        out.put("citations", citations);
        out.put("evidenceNotice", lesson.get("evidenceNotice"));
        return out;
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

        // Lock user row (`SELECT ... FOR UPDATE`) to serialize concurrent attempt XP/streak/mastery writes!
        var userRow = jdbc.sql("""
                SELECT xp, streak_days, last_active_date
                FROM core.users
                WHERE id = :uid
                FOR UPDATE
                """)
                .param("uid", uid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("xp", rs.getInt("xp"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    var lad = rs.getDate("last_active_date");
                    m.put("lastActiveDate", lad == null ? null : lad.toLocalDate());
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
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "attemptId", IdCodec.format("att", rs.getObject("id", UUID.class)),
                        "duplicate", true,
                        "score", Map.of("correct", rs.getInt("correct"), "total", rs.getInt("total")),
                        "rewards", Map.of("xp", currentXp, "xpEarned", 0),
                        "results", json.fromJson(rs.getString("results_json"), new TypeReference<List<Map<String, Object>>>() {}),
                        "reviewCardCreated", false
                ))
                .optional();

        if (existingOpt.isPresent()) {
            return existingOpt.get();
        }

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
            if ("teach".equals(btype)) continue;
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
        int rawXp = correct * 10 + (total > 0 && correct == total ? 20 : 0);

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
        int newXp = currentXp + xpEarned;

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
                    "reviewCardCreated", false
            );
        }

        // Update XP + Streak inside the same ACID transaction
        LocalDate today = LocalDate.now(ZoneOffset.UTC);
        LocalDate lastActive = (LocalDate) userRow.get("lastActiveDate");
        int streak = ((Number) userRow.get("streakDays")).intValue();
        if (lastActive == null) {
            streak = 1;
        } else if (lastActive.equals(today.minusDays(1))) {
            streak = streak + 1;
        } else if (!lastActive.equals(today)) {
            streak = 1;
        }

        jdbc.sql("""
                UPDATE core.users
                SET xp = :xp, streak_days = :streak, last_active_date = :today, updated_at = now()
                WHERE id = :uid
                """)
                .param("xp", newXp)
                .param("streak", streak)
                .param("today", today)
                .param("uid", uid)
                .update();

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
                .param("due", java.sql.Timestamp.from(Instant.now().plusSeconds(86400)))
                .update();

        return Map.of(
                "attemptId", IdCodec.format("att", attemptId),
                "duplicate", false,
                "score", Map.of("correct", correct, "total", total),
                "rewards", Map.of("xp", newXp, "xpEarned", xpEarned),
                "results", results,
                "reviewCardCreated", createdCard > 0
        );
    }

    @PostMapping("/{lessonId}/blocks/{blockIndex}/grade")
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
        if ("teach".equals(btype)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "BLOCK_NOT_GRADABLE", "Block bài giảng không chấm điểm.");
        }

        boolean ok;
        String grader = "deterministic";
        String feedback;

        if ("short".equals(btype)) {
            boolean exactOk = projector.gradeShortExact(block, body.answer());
            if (exactOk) {
                ok = true;
                feedback = "Chính xác!";
            } else if (projector.gradeShortSemantic(block, body.answer())) {
                ok = true;
                grader = "semantic_rubric";
                feedback = "Chính xác — câu trả lời khớp với ý chính theo tiêu chí chấm.";
            } else if (Boolean.TRUE.equals(body.dispute())) {
                // Delegate bounded LLM dispute grading to `ai-api`
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
                    grader = "llm_rubric";
                    feedback = String.valueOf(aiResp.getOrDefault("feedback", "Đã chấm lại theo tiêu chí."));
                } catch (Exception ex) {
                    ok = false;
                    feedback = "Không thể gọi chấm lại AI lúc này. Hãy đối chiếu với đáp án mẫu.";
                }
            } else {
                ok = false;
                feedback = "Chưa khớp đáp án mẫu. Bạn có thể bấm 'Yêu cầu chấm lại' nếu câu trả lời đúng ý.";
            }
        } else {
            ok = projector.gradeBlock(lid, currentVersion, blockIndex, block, body.answer());
            feedback = ok ? "Chính xác!" : "Chưa chính xác. Hãy xem lại đáp án mẫu và giải thích trong bài.";
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("blockIndex", blockIndex);
        out.put("type", btype);
        out.put("correct", ok);
        out.put("grader", grader);
        out.put("feedback", feedback);
        out.put("solution", projector.solutionFor(block));
        out.put("disputeAllowed", "short".equals(btype) && !ok);
        return out;
    }

    private Map<String, Object> loadOwnedLesson(UUID userId, UUID lessonId) {
        return jdbc.sql("""
                SELECT l.id, l.course_id, l.title, l.order_index, l.status, l.content_version,
                       l.content_json, l.grounding, l.evidence_notice, c.language
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
                    m.put("language", rs.getString("language"));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "LESSON_NOT_FOUND", "Không tìm thấy bài học."));
    }
}
