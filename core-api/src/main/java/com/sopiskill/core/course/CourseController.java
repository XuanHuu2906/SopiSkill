package com.sopiskill.core.course;

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
import jakarta.validation.constraints.Size;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/courses")
public class CourseController {

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final AiEngineClient aiEngine;

    public CourseController(
            JdbcClient jdbc,
            JsonHelper json,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            AiEngineClient aiEngine
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.aiEngine = aiEngine;
    }

    public record CreateCourseRequest(
            @NotBlank @Size(min = 1, max = 300) String topic,
            String language,
            String sourceId
    ) {}

    public record InterviewAnswerRequest(
            @NotNull Integer position,
            @NotBlank @Size(min = 1, max = 2000) String answer
    ) {}

    public record ProposalUnitIn(
            @NotBlank String title,
            String blurb,
            @NotNull List<String> lessonTitles
    ) {}

    public record ProposalUpdateRequest(
            @NotNull Integer expectedVersion,
            @NotBlank String name,
            @NotBlank String objective,
            @NotNull List<ProposalUnitIn> units,
            @NotNull List<String> outcomes
    ) {}

    @PostMapping
    @Transactional
    public ResponseEntity<Map<String, Object>> createCourse(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody CreateCourseRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "course_create", 30, 60);
        String lang = body.language() == null ? "vi" : body.language().trim().toLowerCase();
        if (!"vi".equals(lang) && !"en".equals(lang)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_LANGUAGE", "Ngôn ngữ chỉ hỗ trợ vi hoặc en.");
        }

        String topic = body.topic().trim();
        TopicGuard.validateOrThrow(topic);

        Map<String, Object> sourceBrief = null;
        UUID linkedSourceUuid = null;
        if (body.sourceId() != null && !body.sourceId().isBlank()) {
            linkedSourceUuid = IdCodec.parse(body.sourceId(), "src");
            var briefStrOpt = jdbc.sql("SELECT brief::text FROM core.sources WHERE id = :sid AND (owner_id = :uid OR visibility = 'public')")
                    .param("sid", linkedSourceUuid)
                    .param("uid", principal.userId())
                    .query(String.class)
                    .optional();
            if (briefStrOpt.isPresent() && briefStrOpt.get() != null) {
                sourceBrief = json.fromJson(briefStrOpt.get(), new TypeReference<>() {});
            }
        }

        UUID courseId = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.courses (id, user_id, topic, language, status)
                VALUES (:id, :uid, :topic, :lang, 'interviewing')
                """)
                .param("id", courseId)
                .param("uid", principal.userId())
                .param("topic", topic)
                .param("lang", lang)
                .update();

        if (linkedSourceUuid != null) {
            jdbc.sql("""
                    INSERT INTO core.course_sources (id, course_id, source_id)
                    VALUES (:id, :cid, :sid)
                    ON CONFLICT (course_id, source_id) DO NOTHING
                    """)
                    .param("id", UUID.randomUUID())
                    .param("cid", courseId)
                    .param("sid", linkedSourceUuid)
                    .update();
        }

        List<Map<String, Object>> structuredQuestions = aiEngine.fetchStructuredInterviewQuestions(
                IdCodec.format("crs", courseId), topic, lang, sourceBrief, null
        );
        jdbc.sql("""
                INSERT INTO core.course_interviews (id, course_id, questions, answers, completed_count)
                VALUES (:id, :cid, CAST(:qs AS jsonb), '[]'::jsonb, 0)
                """)
                .param("id", UUID.randomUUID())
                .param("cid", courseId)
                .param("qs", json.toJson(structuredQuestions))
                .update();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("crs", courseId));
        out.put("courseId", IdCodec.format("crs", courseId));
        out.put("topic", topic);
        out.put("language", lang);
        out.put("status", "interviewing");
        return ResponseEntity.status(HttpStatus.CREATED).body(out);
    }

    @GetMapping
    public Map<String, Object> listCourses(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(defaultValue = "0") int offset
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 50));
        int safeOffset = Math.max(0, offset);
        UUID uid = principal.userId();

        int total = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid")
                .param("uid", uid).query(Integer.class).single();

        List<Map<String, Object>> rows = jdbc.sql("""
                SELECT id, topic, language, status, created_at, updated_at
                FROM core.courses
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """)
                .param("uid", uid)
                .param("limit", safeLimit)
                .param("offset", safeOffset)
                .query((rs, rowNum) -> {
                    UUID cid = rs.getObject("id", UUID.class);
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("id", IdCodec.format("crs", cid));
                    item.put("topic", rs.getString("topic"));
                    item.put("language", rs.getString("language"));
                    item.put("status", rs.getString("status"));
                    var ca = rs.getTimestamp("created_at");
                    var ua = rs.getTimestamp("updated_at");
                    item.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    item.put("updatedAt", ua == null ? null : ua.toInstant().toString());
                    return item;
                })
                .list();

        for (Map<String, Object> item : rows) {
            UUID cid = IdCodec.parse(String.valueOf(item.get("id")), "crs");
            populateCourseProgressSummary(uid, cid, item);
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("items", rows);
        resp.put("total", total);
        resp.put("limit", safeLimit);
        resp.put("offset", safeOffset);
        resp.put("hasMore", safeOffset + rows.size() < total);
        return resp;
    }

    @GetMapping("/{courseId}")
    public Map<String, Object> getCourseDetail(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        Map<String, Object> course = loadOwnedCourse(principal.userId(), cid);

        List<Map<String, Object>> units = jdbc.sql("""
                SELECT id, order_index, kicker, title, blurb, tone
                FROM core.units
                WHERE course_id = :cid
                ORDER BY order_index ASC
                """)
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> u = new LinkedHashMap<>();
                    u.put("id", IdCodec.format("unit", rs.getObject("id", UUID.class)));
                    u.put("orderIndex", rs.getInt("order_index"));
                    u.put("kicker", rs.getString("kicker"));
                    u.put("title", rs.getString("title"));
                    u.put("blurb", rs.getString("blurb"));
                    u.put("tone", rs.getString("tone"));
                    return u;
                })
                .list();

        int completedCount = 0;
        int totalCount = 0;
        for (Map<String, Object> u : units) {
            UUID unitUuid = IdCodec.parse(String.valueOf(u.get("id")), "unit");
            List<Map<String, Object>> lessons = jdbc.sql("""
                    SELECT l.id, l.order_index, l.title, l.status, l.content_version,
                           l.estimated_minutes, l.kind, l.format,
                           EXISTS(
                               SELECT 1 FROM core.lesson_attempts la
                               WHERE la.lesson_id = l.id
                                 AND la.user_id = :uid
                                 AND la.content_version = l.content_version
                                 AND la.completed = TRUE
                           ) AS completed
                    FROM core.lessons l
                    WHERE l.unit_id = :unitId
                    ORDER BY l.order_index ASC
                    """)
                    .param("unitId", unitUuid)
                    .param("uid", principal.userId())
                    .query((rs, rowNum) -> {
                        Map<String, Object> l = new LinkedHashMap<>();
                        String st = rs.getString("status");
                        l.put("id", IdCodec.format("lsn", rs.getObject("id", UUID.class)));
                        l.put("orderIndex", rs.getInt("order_index"));
                        l.put("title", rs.getString("title"));
                        l.put("status", st);
                        l.put("state", "queued".equals(st) || "generating".equals(st) ? "preparing" : st);
                        l.put("contentVersion", rs.getInt("content_version"));
                        l.put("estimatedMinutes", rs.getInt("estimated_minutes"));
                        l.put("kind", rs.getString("kind"));
                        l.put("format", rs.getString("format"));
                        l.put("completed", rs.getBoolean("completed"));
                        return l;
                    })
                    .list();
            for (Map<String, Object> l : lessons) {
                totalCount++;
                if (Boolean.TRUE.equals(l.get("completed"))) completedCount++;
            }
            u.put("lessons", lessons);
        }

        int percent = totalCount == 0 ? 0 : (int) Math.round((completedCount * 100.0) / totalCount);
        course.put("units", units);
        course.put("progress", Map.of("completed", completedCount, "total", totalCount, "percent", percent));
        return course;
    }

    @GetMapping("/{courseId}/path")
    @SuppressWarnings("unchecked")
    public Map<String, Object> getCoursePath(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        Map<String, Object> detail = getCourseDetail(principal, courseId);
        List<Map<String, Object>> units = (List<Map<String, Object>>) detail.get("units");
        boolean assignedNext = false;
        boolean hasPreparing = false;
        for (Map<String, Object> u : units) {
            List<Map<String, Object>> lessons = (List<Map<String, Object>>) u.get("lessons");
            for (Map<String, Object> l : lessons) {
                boolean completed = Boolean.TRUE.equals(l.get("completed"));
                String status = String.valueOf(l.get("status"));
                String state;
                if (completed) {
                    state = "done";
                } else if ("queued".equals(status) || "generating".equals(status)) {
                    state = "preparing";
                    hasPreparing = true;
                } else if ("failed".equals(status)) {
                    state = "failed";
                } else if (!assignedNext) {
                    state = "next";
                    assignedNext = true;
                } else {
                    state = "open";
                }
                l.put("state", state);
            }
        }
        detail.put("hasPreparingLessons", hasPreparing);
        return detail;
    }

    @DeleteMapping("/{courseId}")
    @Transactional
    public ResponseEntity<Void> deleteCourse(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "course_delete", 20, 60);
        UUID cid = IdCodec.parse(courseId, "crs");
        // Idempotent owner-scoped delete (never reveals existence of another user's course)
        int deleted = jdbc.sql("DELETE FROM core.courses WHERE id = :cid AND user_id = :uid")
                .param("cid", cid)
                .param("uid", principal.userId())
                .update();
        if (deleted > 0) {
            aiEngine.deleteRagResourceBestEffort("/internal/rag/courses/" + IdCodec.format("crs", cid), null);
        }
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/{courseId}/interview")
    public Map<String, Object> getInterview(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        loadOwnedCourse(principal.userId(), cid);
        return jdbc.sql("SELECT questions, completed_count FROM core.course_interviews WHERE course_id = :cid")
                .param("cid", cid)
                .query((rs, rowNum) -> buildInterviewOut(rs.getString("questions"), rs.getInt("completed_count")))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "INTERVIEW_NOT_FOUND", "Không tìm thấy phỏng vấn."));
    }

    @PostMapping("/{courseId}/interview/answer")
    @Transactional
    public Map<String, Object> submitInterviewAnswer(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody InterviewAnswerRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "interview_answer", 60, 60);
        UUID cid = IdCodec.parse(courseId, "crs");
        Map<String, Object> course = loadOwnedCourse(principal.userId(), cid);

        var row = jdbc.sql("SELECT questions, answers, completed_count FROM core.course_interviews WHERE course_id = :cid FOR UPDATE")
                .param("cid", cid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "questionsRaw", rs.getString("questions"),
                        "answers", json.fromJson(rs.getString("answers"), new TypeReference<List<String>>() {}),
                        "completed_count", rs.getInt("completed_count")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "INTERVIEW_NOT_FOUND", "Không tìm thấy phỏng vấn."));

        String questionsRaw = String.valueOf(row.get("questionsRaw"));
        List<String> questions = extractQuestionPrompts(questionsRaw);
        @SuppressWarnings("unchecked")
        List<String> answers = new ArrayList<>((List<String>) row.get("answers"));
        int pos = body.position();
        if (pos < 0 || pos >= questions.size()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_POSITION", "Vị trí câu hỏi không hợp lệ.");
        }
        while (answers.size() <= pos) {
            answers.add("");
        }
        answers.set(pos, body.answer().trim());
        int completedCount = (int) answers.stream().filter(a -> a != null && !a.isBlank()).count();

        jdbc.sql("""
                UPDATE core.course_interviews
                SET answers = CAST(:answers AS jsonb), completed_count = :done, updated_at = now()
                WHERE course_id = :cid
                """)
                .param("answers", json.toJson(answers))
                .param("done", completedCount)
                .param("cid", cid)
                .update();

        if (completedCount >= questions.size()) {
            createInitialProposalIfAbsent(cid, String.valueOf(course.get("topic")), String.valueOf(course.get("language")), questions, answers);
        }

        return buildInterviewOut(questionsRaw, completedCount);
    }

    @SuppressWarnings("unchecked")
    private List<String> extractQuestionPrompts(String questionsJson) {
        List<Object> rawList = json.fromJson(questionsJson, new TypeReference<>() {});
        List<String> prompts = new ArrayList<>(rawList.size());
        for (Object item : rawList) {
            if (item instanceof Map<?, ?> m) {
                Object p = m.get("prompt");
                prompts.add(p == null ? "" : String.valueOf(p));
            } else {
                prompts.add(String.valueOf(item));
            }
        }
        return prompts;
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> buildInterviewOut(String questionsJson, int completedCount) {
        List<Object> rawList = json.fromJson(questionsJson, new TypeReference<>() {});
        List<String> prompts = new ArrayList<>(rawList.size());
        List<Map<String, Object>> structured = new ArrayList<>(rawList.size());
        for (int i = 0; i < rawList.size(); i++) {
            Object item = rawList.get(i);
            if (item instanceof Map<?, ?> m) {
                Object p = m.get("prompt");
                String prompt = p == null ? "" : String.valueOf(p);
                prompts.add(prompt);
                Map<String, Object> q = new LinkedHashMap<>();
                q.put("index", i);
                q.put("prompt", prompt);
                Object kindVal = m.get("kind");
                q.put("kind", kindVal == null ? "freeform" : String.valueOf(kindVal));
                q.put("choices", m.get("choices") instanceof List<?> c ? c : List.of());
                structured.add(q);
            } else {
                String prompt = String.valueOf(item);
                prompts.add(prompt);
                structured.add(Map.of("index", i, "prompt", prompt, "kind", "freeform", "choices", List.of()));
            }
        }
        return Map.of(
                "questions", prompts,
                "structuredQuestions", structured,
                "completedCount", completedCount
        );
    }

    @GetMapping("/{courseId}/proposal")
    public Map<String, Object> getProposal(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        loadOwnedCourse(principal.userId(), cid);
        return loadLatestProposal(cid);
    }

    @PatchMapping("/{courseId}/proposal")
    @Transactional
    public Map<String, Object> updateProposal(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody ProposalUpdateRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "proposal_update", 30, 60);
        UUID cid = IdCodec.parse(courseId, "crs");

        // Lock course row to serialize concurrent edits
        String status = jdbc.sql("SELECT status FROM core.courses WHERE id = :cid AND user_id = :uid FOR UPDATE")
                .param("cid", cid)
                .param("uid", principal.userId())
                .query(String.class)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học."));

        if ("generating".equals(status) || "ready".equals(status)) {
            throw new ApiException(HttpStatus.CONFLICT, "PROPOSAL_LOCKED", "Đề xuất đã được duyệt và không thể chỉnh sửa.");
        }

        Map<String, Object> latest = loadLatestProposal(cid);
        int currentVersion = ((Number) latest.get("version")).intValue();
        if (Boolean.TRUE.equals(latest.get("approved"))) {
            throw new ApiException(HttpStatus.CONFLICT, "PROPOSAL_LOCKED", "Đề xuất đã được duyệt.");
        }
        if (!body.expectedVersion().equals(currentVersion)) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "PROPOSAL_VERSION_CONFLICT",
                    "Đề xuất đã thay đổi ở phiên bản mới hơn.",
                    Map.of("currentVersion", currentVersion)
            );
        }

        if (body.units().isEmpty() || body.units().stream().allMatch(u -> u.lessonTitles().isEmpty())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "PROPOSAL_INVALID", "Cần ít nhất một chương và một bài học.");
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> oldPayload = (Map<String, Object>) latest.get("payload");
        Map<String, Object> newPayload = new LinkedHashMap<>();
        newPayload.put("name", body.name().trim());
        newPayload.put("objective", body.objective().trim());
        newPayload.put("outcomes", body.outcomes().stream().map(String::trim).filter(s -> !s.isEmpty()).toList());
        List<Map<String, Object>> unitMaps = body.units().stream().map(u -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("title", u.title().trim());
            m.put("blurb", u.blurb() == null ? "" : u.blurb().trim());
            m.put("lessonTitles", u.lessonTitles().stream().map(String::trim).filter(s -> !s.isEmpty()).toList());
            return m;
        }).toList();
        newPayload.put("units", unitMaps);
        if (oldPayload.containsKey("learnerProfile")) {
            newPayload.put("learnerProfile", oldPayload.get("learnerProfile"));
        }

        int nextVersion = currentVersion + 1;
        jdbc.sql("""
                INSERT INTO core.course_proposals (id, course_id, version, approved, payload)
                VALUES (:id, :cid, :ver, FALSE, CAST(:payload AS jsonb))
                """)
                .param("id", UUID.randomUUID())
                .param("cid", cid)
                .param("ver", nextVersion)
                .param("payload", json.toJson(newPayload))
                .update();

        jdbc.sql("UPDATE core.courses SET topic = :topic, updated_at = now() WHERE id = :cid")
                .param("topic", body.name().trim())
                .param("cid", cid)
                .update();

        return Map.of("version", nextVersion, "approved", false, "payload", newPayload);
    }

    @PostMapping("/{courseId}/approve")
    @Transactional
    public Map<String, Object> approveCourse(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "course_approve", 20, 60);
        UUID cid = IdCodec.parse(courseId, "crs");

        var courseRow = jdbc.sql("SELECT topic, language, status FROM core.courses WHERE id = :cid AND user_id = :uid FOR UPDATE")
                .param("cid", cid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> Map.of(
                        "topic", rs.getString("topic"),
                        "language", rs.getString("language"),
                        "status", rs.getString("status")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học."));

        Map<String, Object> latestProposal = loadLatestProposal(cid);
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) latestProposal.get("payload");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> units = (List<Map<String, Object>>) payload.getOrDefault("units", List.of());

        jdbc.sql("UPDATE core.course_proposals SET approved = TRUE WHERE course_id = :cid AND version = :ver")
                .param("cid", cid)
                .param("ver", ((Number) latestProposal.get("version")).intValue())
                .update();

        // Create units & queued lessons idempotently if not created yet
        Integer existingUnits = jdbc.sql("SELECT COUNT(*) FROM core.units WHERE course_id = :cid")
                .param("cid", cid).query(Integer.class).single();
        int totalLessons = 0;
        if (existingUnits == null || existingUnits == 0) {
            int globalLessonIdx = 0;
            for (int uIdx = 0; uIdx < units.size(); uIdx++) {
                Map<String, Object> u = units.get(uIdx);
                UUID unitId = UUID.randomUUID();
                jdbc.sql("""
                        INSERT INTO core.units (id, course_id, order_index, title, blurb)
                        VALUES (:id, :cid, :idx, :title, :blurb)
                        """)
                        .param("id", unitId)
                        .param("cid", cid)
                        .param("idx", uIdx)
                        .param("title", String.valueOf(u.getOrDefault("title", "Unit " + (uIdx + 1))))
                        .param("blurb", String.valueOf(u.getOrDefault("blurb", "")))
                        .update();

                @SuppressWarnings("unchecked")
                List<String> lessonTitles = (List<String>) u.getOrDefault("lessonTitles", List.of());
                for (int lIdx = 0; lIdx < lessonTitles.size(); lIdx++) {
                    UUID lessonId = UUID.randomUUID();
                    UUID skillId = UUID.randomUUID();
                    String lTitle = lessonTitles.get(lIdx);
                    jdbc.sql("""
                            INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_version)
                            VALUES (:id, :cid, :uid, :idx, :title, 'queued', 1)
                            """)
                            .param("id", lessonId)
                            .param("cid", cid)
                            .param("uid", unitId)
                            .param("idx", lIdx)
                            .param("title", lTitle)
                            .update();
                    jdbc.sql("""
                            INSERT INTO core.skills (id, course_id, skill_key, title, bloom_level, outcome)
                            VALUES (:sid, :cid, :key, :title, 'apply', :outcome)
                            ON CONFLICT (course_id, skill_key) DO NOTHING
                            """)
                            .param("sid", skillId)
                            .param("cid", cid)
                            .param("key", "skill_" + globalLessonIdx)
                            .param("title", lTitle)
                            .param("outcome", lTitle)
                            .update();
                    jdbc.sql("""
                            INSERT INTO core.lesson_skills (lesson_id, skill_id)
                            SELECT :lid, id FROM core.skills WHERE course_id = :cid AND skill_key = :key
                            ON CONFLICT DO NOTHING
                            """)
                            .param("lid", lessonId)
                            .param("cid", cid)
                            .param("key", "skill_" + globalLessonIdx)
                            .update();
                    globalLessonIdx++;
                    totalLessons++;
                }
            }
        } else {
            totalLessons = jdbc.sql("SELECT COUNT(*) FROM core.lessons WHERE course_id = :cid")
                    .param("cid", cid).query(Integer.class).single();
        }

        UUID jobId = UUID.randomUUID();
        String idempKey = "gen_" + cid + "_" + jobId;
        jdbc.sql("""
                INSERT INTO core.generation_jobs (
                    id, course_id, idempotency_key, status, stage, lessons_done, lessons_total, attempts, dispatched
                ) VALUES (
                    :jid, :cid, :idem, 'queued', 'lessons', 0, :total, 1, TRUE
                )
                """)
                .param("jid", jobId)
                .param("cid", cid)
                .param("idem", idempKey)
                .param("total", totalLessons)
                .update();

        jdbc.sql("UPDATE core.courses SET status = 'generating', updated_at = now() WHERE id = :cid")
                .param("cid", cid)
                .update();

        // Collect ordered lesson IDs for Phase 3 Lesson-1-First progressive callbacks
        List<String> orderedLessonIds = jdbc.sql("""
                SELECT l.id FROM core.lessons l
                JOIN core.units u ON u.id = l.unit_id
                WHERE l.course_id = :cid
                ORDER BY u.order_index ASC, l.order_index ASC
                """)
                .param("cid", cid)
                .query(UUID.class)
                .list()
                .stream()
                .map(id -> IdCodec.format("lsn", id))
                .toList();

        // Dispatch async generation job to Redis Stream `queue:ai:llm` for `ai-worker-llm`
        Map<String, Object> streamMsg = new LinkedHashMap<>();
        streamMsg.put("jobId", IdCodec.format("job", jobId));
        streamMsg.put("idempotencyKey", idempKey);
        streamMsg.put("jobType", "generate_course");
        streamMsg.put("ownerId", IdCodec.format("usr", principal.userId()));
        streamMsg.put("courseId", IdCodec.format("crs", cid));
        streamMsg.put("correlationId", "cor_" + jobId.toString().replace("-", "").substring(0, 16));
        streamMsg.put("attempt", 1);
        streamMsg.put("payload", Map.of(
                "topic", courseRow.get("topic"),
                "language", courseRow.get("language"),
                "learnerProfile", payload.getOrDefault("learnerProfile", Map.of("currentLevel", "beginner")),
                "units", units,
                "lessonIds", orderedLessonIds
        ));
        aiEngine.enqueueLlmJob(streamMsg);

        return Map.of(
                "courseId", IdCodec.format("crs", cid),
                "jobId", IdCodec.format("job", jobId),
                "status", "generating"
        );
    }

    @GetMapping("/{courseId}/generation")
    public Map<String, Object> getGenerationStatus(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        loadOwnedCourse(principal.userId(), cid);
        return jdbc.sql("""
                SELECT id, status, stage, lessons_done, lessons_total, error_json, attempts,
                       dispatched, last_error_code, llm_calls, prompt_tokens, completion_tokens,
                       cost_estimate_usd, cost_known
                FROM core.generation_jobs
                WHERE course_id = :cid
                ORDER BY created_at DESC
                LIMIT 1
                """)
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("jobId", IdCodec.format("job", rs.getObject("id", UUID.class)));
                    m.put("status", rs.getString("status"));
                    m.put("stage", rs.getString("stage"));
                    m.put("lessonsDone", rs.getInt("lessons_done"));
                    m.put("lessonsTotal", rs.getObject("lessons_total"));
                    String errJson = rs.getString("error_json");
                    m.put("error", errJson == null ? null : json.fromJson(errJson, new TypeReference<Map<String, Object>>() {}));
                    m.put("attempts", rs.getInt("attempts"));
                    m.put("dispatched", rs.getBoolean("dispatched"));
                    m.put("lastErrorCode", rs.getString("last_error_code"));
                    m.put("llmCalls", rs.getInt("llm_calls"));
                    m.put("promptTokens", rs.getObject("prompt_tokens"));
                    m.put("completionTokens", rs.getObject("completion_tokens"));
                    m.put("costEstimateUsd", rs.getObject("cost_estimate_usd"));
                    m.put("costKnown", rs.getBoolean("cost_known"));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "JOB_NOT_FOUND", "Chưa có tác vụ sinh khóa học."));
    }

    @PostMapping("/{courseId}/retry")
    @Transactional
    public Map<String, Object> retryCourse(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            HttpServletRequest request
    ) {
        return approveCourse(principal, courseId, request);
    }

    @GetMapping("/{courseId}/glossary")
    public Map<String, Object> getCourseGlossary(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @RequestParam(required = false) String lessonId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        loadOwnedCourse(principal.userId(), cid);
        UUID lessonFilter = (lessonId != null && !lessonId.isBlank()) ? IdCodec.parse(lessonId, "lsn") : null;

        String sql = lessonFilter == null
                ? """
                  SELECT g.id, g.term_key, g.term, g.definition, g.example, g.lesson_id, l.title AS lesson_title
                  FROM core.course_glossary_terms g
                  LEFT JOIN core.lessons l ON l.id = g.lesson_id
                  WHERE g.course_id = :cid
                  ORDER BY g.term ASC
                  """
                : """
                  SELECT g.id, g.term_key, g.term, g.definition, g.example, g.lesson_id, l.title AS lesson_title
                  FROM core.course_glossary_terms g
                  LEFT JOIN core.lessons l ON l.id = g.lesson_id
                  WHERE g.course_id = :cid AND g.lesson_id = :lid
                  ORDER BY g.term ASC
                  """;

        var stmt = jdbc.sql(sql).param("cid", cid);
        if (lessonFilter != null) {
            stmt = stmt.param("lid", lessonFilter);
        }
        List<Map<String, Object>> items = stmt.query((rs, rowNum) -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", IdCodec.format("gls", rs.getObject("id", UUID.class)));
            m.put("termKey", rs.getString("term_key"));
            m.put("term", rs.getString("term"));
            m.put("definition", rs.getString("definition"));
            m.put("example", rs.getString("example"));
            UUID lid = rs.getObject("lesson_id", UUID.class);
            m.put("lessonId", IdCodec.format("lsn", lid));
            m.put("lessonTitle", rs.getString("lesson_title"));
            return m;
        }).list();

        return Map.of("courseId", IdCodec.format("crs", cid), "total", items.size(), "items", items);
    }

    private void createInitialProposalIfAbsent(
            UUID courseId,
            String topic,
            String language,
            List<String> questions,
            List<String> answers
    ) {
        Integer count = jdbc.sql("SELECT COUNT(*) FROM core.course_proposals WHERE course_id = :cid")
                .param("cid", courseId).query(Integer.class).single();
        if (count != null && count > 0) return;

        List<Map<String, String>> qa = new ArrayList<>();
        for (int i = 0; i < questions.size(); i++) {
            qa.add(Map.of("question", questions.get(i), "answer", i < answers.size() ? answers.get(i) : ""));
        }
        Map<String, Object> rawProfile = aiEngine.evaluateInterview(IdCodec.format("crs", courseId), topic, language, qa, null);

        // Normalize depth to frontend display enum (broad|balanced|deep)
        Map<String, Object> profile = new LinkedHashMap<>(rawProfile);
        String rawDepth = String.valueOf(profile.getOrDefault("depth", "practical"));
        String normalizedDepth = switch (rawDepth) {
            case "overview", "broad" -> "broad";
            case "deep" -> "deep";
            default -> "balanced";
        };
        profile.put("depth", normalizedDepth);
        profile.putIfAbsent("warnings", List.of());
        profile.putIfAbsent("goal", answers.size() > 1 ? answers.get(1) : topic);

        boolean en = "en".equals(language);
        List<Map<String, Object>> units = List.of(
                Map.of(
                        "title", en ? "Foundations" : "Nền tảng",
                        "blurb", en ? "Core concepts and mental models for " + topic + "." : "Khái niệm cốt lõi cho " + topic + ".",
                        "lessonTitles", List.of(
                                en ? "What is " + topic + "?" : topic + " là gì?",
                                en ? "Setting up for " + topic : "Thiết lập ban đầu với " + topic
                        )
                ),
                Map.of(
                        "title", en ? "Practice" : "Thực hành",
                        "blurb", en ? "Hands-on exercises and pitfalls in " + topic + "." : "Bài tập áp dụng và lỗi thường gặp với " + topic + ".",
                        "lessonTitles", List.of(
                                en ? "First exercise with " + topic : "Bài tập đầu tiên với " + topic,
                                en ? "Common pitfalls when learning " + topic : "Lỗi thường gặp khi học " + topic
                        )
                )
        );

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("name", topic);
        payload.put("objective", en
                ? "Build a solid practical foundation in " + topic + "."
                : "Xây dựng nền tảng vững chắc và thực hành hiệu quả với " + topic + ".");
        payload.put("outcomes", en
                ? List.of("Explain core concepts of " + topic, "Apply " + topic + " to structured exercises")
                : List.of("Hiểu rõ khái niệm cốt lõi của " + topic, "Áp dụng " + topic + " vào bài tập thực tế"));
        payload.put("units", units);
        payload.put("learnerProfile", profile);

        jdbc.sql("""
                INSERT INTO core.course_proposals (id, course_id, version, approved, payload)
                VALUES (:id, :cid, 1, FALSE, CAST(:payload AS jsonb))
                """)
                .param("id", UUID.randomUUID())
                .param("cid", courseId)
                .param("payload", json.toJson(payload))
                .update();

        jdbc.sql("UPDATE core.courses SET status = 'proposal_ready', updated_at = now() WHERE id = :cid")
                .param("cid", courseId)
                .update();
    }

    private Map<String, Object> loadLatestProposal(UUID courseId) {
        return jdbc.sql("""
                SELECT version, approved, payload
                FROM core.course_proposals
                WHERE course_id = :cid
                ORDER BY version DESC
                LIMIT 1
                """)
                .param("cid", courseId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("version", rs.getInt("version"));
                    m.put("approved", rs.getBoolean("approved"));
                    m.put("payload", json.fromJson(rs.getString("payload"), new TypeReference<Map<String, Object>>() {}));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "PROPOSAL_NOT_FOUND", "Chưa có đề xuất khóa học."));
    }

    private Map<String, Object> loadOwnedCourse(UUID userId, UUID courseId) {
        return jdbc.sql("""
                SELECT id, topic, language, status, created_at, updated_at
                FROM core.courses
                WHERE id = :cid AND user_id = :uid
                """)
                .param("cid", courseId)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("crs", rs.getObject("id", UUID.class)));
                    m.put("topic", rs.getString("topic"));
                    m.put("language", rs.getString("language"));
                    m.put("status", rs.getString("status"));
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học."));
    }

    private void populateCourseProgressSummary(UUID userId, UUID courseId, Map<String, Object> out) {
        List<Map<String, Object>> lessons = jdbc.sql("""
                SELECT l.id, l.title, l.status,
                       EXISTS(
                           SELECT 1 FROM core.lesson_attempts la
                           WHERE la.lesson_id = l.id AND la.user_id = :uid
                             AND la.content_version = l.content_version AND la.completed = TRUE
                       ) AS completed
                FROM core.lessons l
                JOIN core.units u ON u.id = l.unit_id
                WHERE l.course_id = :cid
                ORDER BY u.order_index ASC, l.order_index ASC
                """)
                .param("cid", courseId)
                .param("uid", userId)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", IdCodec.format("lsn", rs.getObject("id", UUID.class)),
                        "title", rs.getString("title"),
                        "status", rs.getString("status"),
                        "completed", rs.getBoolean("completed")
                ))
                .list();

        int total = lessons.size();
        int completed = 0;
        String resumeId = null;
        String resumeTitle = null;
        String lastCompletedTitle = null;
        for (Map<String, Object> l : lessons) {
            if (Boolean.TRUE.equals(l.get("completed"))) {
                completed++;
                lastCompletedTitle = String.valueOf(l.get("title"));
            } else if (resumeId == null && "ready".equals(l.get("status"))) {
                resumeId = String.valueOf(l.get("id"));
                resumeTitle = String.valueOf(l.get("title"));
            }
        }
        int percent = total == 0 ? 0 : (int) Math.round((completed * 100.0) / total);
        out.put("progress", Map.of("completed", completed, "total", total, "percent", percent));
        out.put("resumeLessonId", resumeId);
        out.put("resumeLessonTitle", resumeTitle);
        out.put("lastCompletedLessonTitle", lastCompletedTitle);
    }
}
