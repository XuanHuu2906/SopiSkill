package com.sopiskill.core.internal;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.course.GlossaryService;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * HMAC-authenticated internal callbacks invoked by `ai-worker-llm` and `ai-worker-ingest`.
 * Only `core-api` ever writes to `core.*` tables.
 */
@RestController
@RequestMapping("/internal")
public class InternalCallbackController {

    private final InternalHmacSigner signer;
    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final GlossaryService glossaryService;

    public InternalCallbackController(
            InternalHmacSigner signer,
            JdbcClient jdbc,
            JsonHelper json,
            GlossaryService glossaryService
    ) {
        this.signer = signer;
        this.jdbc = jdbc;
        this.json = json;
        this.glossaryService = glossaryService;
    }

    @PostMapping("/jobs/{jobId}/complete")
    @Transactional
    @SuppressWarnings("unchecked")
    public Map<String, Object> jobComplete(
            @PathVariable String jobId,
            @RequestBody byte[] rawBody,
            HttpServletRequest request
    ) {
        signer.verifyIncomingCallback(request, rawBody);

        UUID jid = IdCodec.parse(jobId, "job");
        Map<String, Object> body = json.fromJson(new String(rawBody, StandardCharsets.UTF_8), new TypeReference<>() {});

        var jobRow = jdbc.sql("""
                SELECT id, course_id, status
                FROM core.generation_jobs
                WHERE id = :jid
                FOR UPDATE
                """)
                .param("jid", jid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "courseId", rs.getObject("course_id", UUID.class),
                        "status", rs.getString("status")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "JOB_NOT_FOUND", "Job not found."));

        String existingStatus = String.valueOf(jobRow.get("status"));
        if ("ready".equals(existingStatus) || "failed".equals(existingStatus)) {
            return Map.of("accepted", true, "duplicate", true);
        }

        UUID courseId = (UUID) jobRow.get("courseId");
        String status = String.valueOf(body.getOrDefault("status", "failed"));

        if ("completed".equals(status)) {
            Map<String, Object> result = (Map<String, Object>) body.get("result");
            List<Map<String, Object>> generatedLessons = result == null
                    ? List.of()
                    : (List<Map<String, Object>>) result.getOrDefault("lessons", List.of());

            List<UUID> orderedLessonIds = jdbc.sql("""
                    SELECT l.id
                    FROM core.lessons l
                    JOIN core.units u ON u.id = l.unit_id
                    WHERE l.course_id = :cid
                    ORDER BY u.order_index ASC, l.order_index ASC
                    """)
                    .param("cid", courseId)
                    .query(UUID.class)
                    .list();

            int count = Math.min(orderedLessonIds.size(), generatedLessons.size());
            for (int i = 0; i < count; i++) {
                UUID lid = orderedLessonIds.get(i);
                Map<String, Object> gen = generatedLessons.get(i);
                List<Map<String, Object>> blocks = (List<Map<String, Object>>) gen.getOrDefault("blocks", List.of());
                String title = gen.get("title") == null ? null : String.valueOf(gen.get("title"));

                jdbc.sql("""
                        UPDATE core.lessons
                        SET status = 'ready',
                            title = COALESCE(:title, title),
                            content_json = CAST(:blocks AS jsonb),
                            updated_at = now()
                        WHERE id = :lid
                        """)
                        .param("title", title)
                        .param("blocks", json.toJson(blocks))
                        .param("lid", lid)
                        .update();

                // Extract glossary terms strictly from teach blocks (never quiz blocks)
                glossaryService.extractAndUpsertFromTeachBlocks(courseId, lid, blocks);
            }

            jdbc.sql("""
                    UPDATE core.generation_jobs
                    SET status = 'ready', stage = 'lessons', lessons_done = :done,
                        lessons_total = :total, llm_calls = llm_calls + :done, updated_at = now()
                    WHERE id = :jid
                    """)
                    .param("done", count)
                    .param("total", orderedLessonIds.size())
                    .param("jid", jid)
                    .update();

            jdbc.sql("UPDATE core.courses SET status = 'ready', updated_at = now() WHERE id = :cid")
                    .param("cid", courseId)
                    .update();
        } else {
            String errCode = String.valueOf(body.getOrDefault("errorCode", "GENERATION_FAILED"));
            String errMsg = String.valueOf(body.getOrDefault("errorMessage", "Sinh khóa học thất bại."));
            jdbc.sql("""
                    UPDATE core.generation_jobs
                    SET status = 'failed', last_error_code = :code,
                        error_json = CAST(:err AS jsonb), updated_at = now()
                    WHERE id = :jid
                    """)
                    .param("code", errCode)
                    .param("err", json.toJson(Map.of("code", errCode, "message", errMsg, "retryable", true)))
                    .param("jid", jid)
                    .update();

            jdbc.sql("UPDATE core.courses SET status = 'failed', updated_at = now() WHERE id = :cid")
                    .param("cid", courseId)
                    .update();
        }

        return Map.of("accepted", true, "duplicate", false);
    }

    @PostMapping("/jobs/{jobId}/lesson-ready")
    @Transactional
    @SuppressWarnings("unchecked")
    public Map<String, Object> lessonReady(
            @PathVariable String jobId,
            @RequestBody byte[] rawBody,
            HttpServletRequest request
    ) {
        signer.verifyIncomingCallback(request, rawBody);

        UUID jid = IdCodec.parse(jobId, "job");
        Map<String, Object> body = json.fromJson(new String(rawBody, StandardCharsets.UTF_8), new TypeReference<>() {});
        UUID cid = IdCodec.parse(String.valueOf(body.get("courseId")), "crs");
        UUID lid = IdCodec.parse(String.valueOf(body.get("lessonId")), "lsn");
        int lessonOrder = body.get("lessonOrder") instanceof Number n ? n.intValue() : 0;
        String status = String.valueOf(body.getOrDefault("status", "ready"));

        if ("ready".equals(status)) {
            Map<String, Object> content = (Map<String, Object>) body.get("content");
            List<Map<String, Object>> blocks = content == null
                    ? List.of()
                    : (List<Map<String, Object>>) content.getOrDefault("blocks", List.of());
            String title = content != null && content.get("title") != null ? String.valueOf(content.get("title")) : null;
            int estMinutes = body.get("estimatedMinutes") instanceof Number n ? Math.max(1, n.intValue()) : 5;

            jdbc.sql("""
                    UPDATE core.lessons
                    SET status = 'ready',
                        title = COALESCE(:title, title),
                        estimated_minutes = :est,
                        content_json = CAST(:blocks AS jsonb),
                        updated_at = now()
                    WHERE id = :lid AND course_id = :cid
                    """)
                    .param("title", title)
                    .param("est", estMinutes)
                    .param("blocks", json.toJson(blocks))
                    .param("lid", lid)
                    .param("cid", cid)
                    .update();

            glossaryService.extractAndUpsertFromTeachBlocks(cid, lid, blocks);

            List<Map<String, Object>> flags = (List<Map<String, Object>>) body.getOrDefault("contentFlags", List.of());
            persistContentFlags(cid, lid, flags);

            int readyLessonsCount = jdbc.sql("SELECT COUNT(*) FROM core.lessons WHERE course_id = :cid AND status = 'ready'")
                    .param("cid", cid).query(Integer.class).single();
            int totalLessonsCount = jdbc.sql("SELECT COUNT(*) FROM core.lessons WHERE course_id = :cid")
                    .param("cid", cid).query(Integer.class).single();

            // Lesson-1-First: unlock the course immediately when Lesson 1 (lessonOrder == 0) is ready!
            if (lessonOrder == 0) {
                jdbc.sql("UPDATE core.courses SET status = 'ready', updated_at = now() WHERE id = :cid")
                        .param("cid", cid)
                        .update();
            }

            jdbc.sql("""
                    UPDATE core.generation_jobs
                    SET status = CASE WHEN :done >= :total THEN 'ready' ELSE 'running' END,
                        stage = 'lessons',
                        lessons_done = :done,
                        lessons_total = :total,
                        llm_calls = llm_calls + 1,
                        updated_at = now()
                    WHERE id = :jid
                    """)
                    .param("done", readyLessonsCount)
                    .param("total", totalLessonsCount)
                    .param("jid", jid)
                    .update();
        } else {
            jdbc.sql("UPDATE core.lessons SET status = 'failed', updated_at = now() WHERE id = :lid AND course_id = :cid")
                    .param("lid", lid)
                    .param("cid", cid)
                    .update();
        }

        return Map.of("accepted", true, "duplicate", false);
    }

    private void persistContentFlags(UUID courseId, UUID lessonId, List<Map<String, Object>> flags) {
        if (flags == null || flags.isEmpty()) return;
        for (Map<String, Object> f : flags) {
            Integer blkIdx = f.get("blockIndex") instanceof Number n ? n.intValue() : null;
            String source = String.valueOf(f.getOrDefault("source", "validator"));
            String code = String.valueOf(f.getOrDefault("code", "QA_WARNING"));
            String severity = String.valueOf(f.getOrDefault("severity", "warning"));
            String details = f.get("details") == null ? null : String.valueOf(f.get("details"));
            jdbc.sql("""
                    INSERT INTO core.content_flags (id, course_id, lesson_id, block_index, source, code, severity, details)
                    VALUES (:id, :cid, :lid, :bidx, :src, :code, :sev, :details)
                    """)
                    .param("id", UUID.randomUUID())
                    .param("cid", courseId)
                    .param("lid", lessonId)
                    .param("bidx", blkIdx)
                    .param("src", source)
                    .param("code", code)
                    .param("sev", severity)
                    .param("details", details)
                    .update();
        }
    }

    @PostMapping("/sources/{sourceId}/complete")
    @Transactional
    public Map<String, Object> sourceIngestComplete(
            @PathVariable String sourceId,
            @RequestBody byte[] rawBody,
            HttpServletRequest request
    ) {
        signer.verifyIncomingCallback(request, rawBody);

        UUID sid = IdCodec.parse(sourceId, "src");
        Map<String, Object> body = json.fromJson(new String(rawBody, StandardCharsets.UTF_8), new TypeReference<>() {});
        UUID did = IdCodec.parse(String.valueOf(body.get("documentId")), "doc");
        String status = String.valueOf(body.getOrDefault("status", "failed"));
        int chunkCount = body.get("chunkCount") instanceof Number n ? n.intValue() : 0;
        String pipelineVersion = body.get("pipelineVersion") == null ? "pypdf-v1" : String.valueOf(body.get("pipelineVersion"));

        if ("ready".equals(status)) {
            jdbc.sql("""
                    UPDATE core.source_documents
                    SET status = 'ready', chunk_count = :chunks, pipeline_version = :pv,
                        ingested_at = :now, error_json = NULL
                    WHERE id = :did AND source_id = :sid
                    """)
                    .param("chunks", chunkCount)
                    .param("pv", pipelineVersion)
                    .param("now", Timestamp.from(Instant.now()))
                    .param("did", did)
                    .param("sid", sid)
                    .update();

            Object briefObj = body.get("brief");
            Integer wordCount = body.get("wordCount") instanceof Number n ? n.intValue() : null;
            Integer durationMin = body.get("durationMinutes") instanceof Number n ? n.intValue() : null;
            String suggestedTopic = body.get("suggestedTopic") == null ? null : String.valueOf(body.get("suggestedTopic"));

            jdbc.sql("""
                    UPDATE core.sources
                    SET brief = CASE WHEN :brief IS NOT NULL THEN CAST(:brief AS jsonb) ELSE brief END,
                        word_count = COALESCE(:wc, word_count),
                        duration_minutes = COALESCE(:dur, duration_minutes),
                        suggested_topic = COALESCE(:st, suggested_topic),
                        verification_status = 'locator_verified'
                    WHERE id = :sid
                    """)
                    .param("brief", briefObj == null ? null : json.toJson(briefObj))
                    .param("wc", wordCount)
                    .param("dur", durationMin)
                    .param("st", suggestedTopic)
                    .param("sid", sid)
                    .update();
        } else {
            String errCode = String.valueOf(body.getOrDefault("errorCode", "INGEST_FAILED"));
            String errMsg = String.valueOf(body.getOrDefault("errorMessage", "Trích xuất tài liệu thất bại."));
            jdbc.sql("""
                    UPDATE core.source_documents
                    SET status = 'failed', error_json = CAST(:err AS jsonb)
                    WHERE id = :did AND source_id = :sid
                    """)
                    .param("err", json.toJson(Map.of("code", errCode, "message", errMsg)))
                    .param("did", did)
                    .param("sid", sid)
                    .update();

            jdbc.sql("UPDATE core.sources SET reject_reason = :code WHERE id = :sid")
                    .param("code", errCode)
                    .param("sid", sid)
                    .update();
        }

        return Map.of("accepted", true, "duplicate", false);
    }
}
