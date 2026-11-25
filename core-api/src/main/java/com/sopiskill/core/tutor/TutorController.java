package com.sopiskill.core.tutor;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.lesson.PublicBlockProjector;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * AI Tutor 'Sopi' SSE Gateway on Spring Boot Virtual Threads.
 * Enforces ownership, CSRF, quota, and strict 0-answer-key projection before calling `ai-api`.
 */
@RestController
@RequestMapping("/v1/courses/{courseId}/tutor")
public class TutorController {

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final SopiProperties props;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final PublicBlockProjector projector;
    private final AiEngineClient aiEngine;
    private final ConcurrentHashMap<UUID, AtomicBoolean> activeCancelFlags = new ConcurrentHashMap<>();

    public TutorController(
            JdbcClient jdbc,
            JsonHelper json,
            SopiProperties props,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            PublicBlockProjector projector,
            AiEngineClient aiEngine
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.props = props;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.projector = projector;
        this.aiEngine = aiEngine;
    }

    public record ContextRef(@NotBlank String lessonId, @NotNull Integer blockIndex) {}

    public record TutorMessageRequest(
            @NotBlank String clientMessageId,
            String threadId,
            @NotBlank @Size(min = 1, max = 2000) String text,
            @NotNull @Valid ContextRef contextRef
    ) {}

    @GetMapping("/usage")
    public Map<String, Object> usage(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        requireTutorEnabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        var row = jdbc.sql("""
                SELECT COUNT(*) AS msgs, COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS toks
                FROM core.tutor_usage_events
                WHERE user_id = :uid AND created_at >= now() - INTERVAL '24 hours'
                """)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> Map.of("msgs", rs.getInt("msgs"), "toks", rs.getInt("toks")))
                .single();

        int usedMsgs = row.get("msgs");
        int usedToks = row.get("toks");
        int maxMsgs = props.tutorMessagesPerDay();
        int maxToks = props.tutorTokensPerDay();

        return Map.of(
                "courseId", IdCodec.format("crs", cid),
                "windowSeconds", 86400,
                "used", Map.of("messages", usedMsgs, "tokens", usedToks),
                "limits", Map.of(
                        "messagesPerDay", maxMsgs,
                        "tokensPerDay", maxToks,
                        "maxConcurrentStreams", props.tutorMaxConcurrentStreams()
                ),
                "remaining", Map.of(
                        "messages", Math.max(0, maxMsgs - usedMsgs),
                        "tokens", Math.max(0, maxToks - usedToks)
                ),
                "runningStreams", activeCancelFlags.size(),
                "tokensKnown", true
        );
    }

    @GetMapping("/threads")
    public Map<String, Object> listThreads(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId
    ) {
        requireTutorEnabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        List<Map<String, Object>> items = jdbc.sql("""
                SELECT t.id, t.course_id, t.lesson_id, t.title, t.created_at, t.updated_at,
                       (SELECT COUNT(*) FROM core.tutor_messages m WHERE m.thread_id = t.id) AS msg_count
                FROM core.tutor_threads t
                WHERE t.user_id = :uid AND t.course_id = :cid
                ORDER BY t.updated_at DESC
                """)
                .param("uid", principal.userId())
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("thr", rs.getObject("id", UUID.class)));
                    m.put("courseId", IdCodec.format("crs", rs.getObject("course_id", UUID.class)));
                    m.put("lessonId", IdCodec.format("lsn", rs.getObject("lesson_id", UUID.class)));
                    m.put("title", rs.getString("title"));
                    m.put("messageCount", rs.getInt("msg_count"));
                    var ca = rs.getTimestamp("created_at");
                    var ua = rs.getTimestamp("updated_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    m.put("updatedAt", ua == null ? null : ua.toInstant().toString());
                    return m;
                })
                .list();

        return Map.of("items", items, "total", items.size());
    }

    @GetMapping("/threads/{threadId}")
    public Map<String, Object> getThread(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String threadId
    ) {
        requireTutorEnabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID tid = IdCodec.parse(threadId, "thr");
        verifyOwnedCourse(principal.userId(), cid);

        var thread = jdbc.sql("""
                SELECT id, course_id, lesson_id, title, created_at, updated_at
                FROM core.tutor_threads
                WHERE id = :tid AND course_id = :cid AND user_id = :uid
                """)
                .param("tid", tid)
                .param("cid", cid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("thr", rs.getObject("id", UUID.class)));
                    m.put("courseId", IdCodec.format("crs", rs.getObject("course_id", UUID.class)));
                    m.put("lessonId", IdCodec.format("lsn", rs.getObject("lesson_id", UUID.class)));
                    m.put("title", rs.getString("title"));
                    var ca = rs.getTimestamp("created_at");
                    var ua = rs.getTimestamp("updated_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    m.put("updatedAt", ua == null ? null : ua.toInstant().toString());
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "THREAD_NOT_FOUND", "Không tìm thấy hội thoại."));

        List<Map<String, Object>> messages = jdbc.sql("""
                SELECT id, role, status, content, context_ref, error_code, finish_reason, citations_json, created_at
                FROM core.tutor_messages
                WHERE thread_id = :tid
                ORDER BY created_at ASC
                """)
                .param("tid", tid)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("tmsg", rs.getObject("id", UUID.class)));
                    m.put("role", rs.getString("role"));
                    m.put("status", rs.getString("status"));
                    m.put("content", rs.getString("content"));
                    String ctx = rs.getString("context_ref");
                    m.put("contextRef", ctx == null ? null : json.fromJson(ctx, new TypeReference<Map<String, Object>>() {}));
                    m.put("errorCode", rs.getString("error_code"));
                    m.put("finishReason", rs.getString("finish_reason"));
                    m.put("citations", json.fromJson(rs.getString("citations_json"), new TypeReference<List<Map<String, Object>>>() {}));
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .list();

        thread.put("messageCount", messages.size());
        thread.put("messages", messages);
        thread.put("replaySupported", false);
        thread.put("notice", null);
        return thread;
    }

    @PostMapping(value = "/messages", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamMessage(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @Valid @RequestBody TutorMessageRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        requireTutorEnabled();
        csrf.verify(request);
        rateLimiter.check(request, "tutor_message", 30, 60);

        UUID uid = principal.userId();
        UUID cid = IdCodec.parse(courseId, "crs");
        String language = verifyOwnedCourse(uid, cid);
        UUID lid = IdCodec.parse(body.contextRef().lessonId(), "lsn");

        var lessonRow = jdbc.sql("""
                SELECT title, content_version, content_json
                FROM core.lessons
                WHERE id = :lid AND course_id = :cid
                """)
                .param("lid", lid)
                .param("cid", cid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "title", rs.getString("title"),
                        "contentVersion", rs.getInt("content_version"),
                        "blocks", json.fromJson(rs.getString("content_json"), new TypeReference<List<Map<String, Object>>>() {})
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TUTOR_CONTEXT_INVALID", "Ngữ cảnh bài học không hợp lệ."));

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lessonRow.get("blocks");
        int blockIdx = body.contextRef().blockIndex();
        if (blockIdx < 0 || (!privateBlocks.isEmpty() && blockIdx >= privateBlocks.size())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TUTOR_CONTEXT_INVALID", "Chỉ số block nằm ngoài bài học.");
        }

        // Enforce 24h message quota
        int usedMsgs = jdbc.sql("""
                SELECT COUNT(*) FROM core.tutor_usage_events
                WHERE user_id = :uid AND created_at >= now() - INTERVAL '24 hours'
                """).param("uid", uid).query(Integer.class).single();
        if (usedMsgs >= props.tutorMessagesPerDay()) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS, "TUTOR_LIMIT_REACHED", "Bạn đã hết lượt hỏi trợ giảng trong 24 giờ qua.");
        }

        UUID threadUuid;
        if (body.threadId() != null && !body.threadId().isBlank()) {
            threadUuid = IdCodec.parse(body.threadId(), "thr");
            Integer ownsThread = jdbc.sql("SELECT COUNT(*) FROM core.tutor_threads WHERE id = :tid AND course_id = :cid AND user_id = :uid")
                    .param("tid", threadUuid).param("cid", cid).param("uid", uid).query(Integer.class).single();
            if (ownsThread == null || ownsThread == 0) {
                throw new ApiException(HttpStatus.NOT_FOUND, "THREAD_NOT_FOUND", "Không tìm thấy hội thoại.");
            }
        } else {
            threadUuid = UUID.randomUUID();
            String title = body.text().trim();
            if (title.length() > 80) title = title.substring(0, 80);
            jdbc.sql("""
                    INSERT INTO core.tutor_threads (id, user_id, course_id, lesson_id, title)
                    VALUES (:tid, :uid, :cid, :lid, :title)
                    """)
                    .param("tid", threadUuid)
                    .param("uid", uid)
                    .param("cid", cid)
                    .param("lid", lid)
                    .param("title", title)
                    .update();
        }

        // Load bounded history BEFORE inserting current turn
        List<Map<String, Object>> history = jdbc.sql("""
                SELECT role, content FROM core.tutor_messages
                WHERE thread_id = :tid AND status = 'completed'
                ORDER BY created_at DESC LIMIT 12
                """)
                .param("tid", threadUuid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "role", rs.getString("role"),
                        "content", rs.getString("content")
                ))
                .list()
                .reversed();

        UUID userMsgId = UUID.randomUUID();
        UUID assistantMsgId = UUID.randomUUID();
        String ctxJson = json.toJson(Map.of("lessonId", IdCodec.format("lsn", lid), "blockIndex", blockIdx));

        jdbc.sql("""
                INSERT INTO core.tutor_messages (id, thread_id, user_id, client_message_id, role, status, content, context_ref)
                VALUES (:id, :tid, :uid, :cmid, 'user', 'completed', :content, CAST(:ctx AS jsonb))
                """)
                .param("id", userMsgId)
                .param("tid", threadUuid)
                .param("uid", uid)
                .param("cmid", body.clientMessageId())
                .param("content", body.text().trim())
                .param("ctx", ctxJson)
                .update();

        jdbc.sql("""
                INSERT INTO core.tutor_messages (id, thread_id, user_id, role, status, content, context_ref)
                VALUES (:id, :tid, :uid, 'assistant', 'streaming', '', CAST(:ctx AS jsonb))
                """)
                .param("id", assistantMsgId)
                .param("tid", threadUuid)
                .param("uid", uid)
                .param("ctx", ctxJson)
                .update();

        jdbc.sql("INSERT INTO core.tutor_usage_events (id, user_id, course_id, message_id) VALUES (:id, :uid, :cid, :mid)")
                .param("id", UUID.randomUUID())
                .param("uid", uid)
                .param("cid", cid)
                .param("mid", assistantMsgId)
                .update();

        String formattedThreadId = IdCodec.format("thr", threadUuid);
        String formattedMsgId = IdCodec.format("tmsg", assistantMsgId);
        response.setHeader("X-Tutor-Thread-Id", formattedThreadId);
        response.setHeader("X-Tutor-Message-Id", formattedMsgId);
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");

        // Strictly sanitize blocks through PublicBlockProjector -> ZERO answer keys sent to ai-api!
        List<Map<String, Object>> publicBlocks = projector.toPublicBlocks(
                lid,
                ((Number) lessonRow.get("contentVersion")).intValue(),
                privateBlocks
        );

        Map<String, Object> aiPayload = new LinkedHashMap<>();
        aiPayload.put("ownerId", IdCodec.format("usr", uid));
        aiPayload.put("courseId", IdCodec.format("crs", cid));
        aiPayload.put("threadId", formattedThreadId);
        aiPayload.put("messageId", formattedMsgId);
        aiPayload.put("language", language);
        aiPayload.put("entryPoint", "tab");
        aiPayload.put("userMessage", body.text().trim());
        aiPayload.put("lessonContext", Map.of(
                "lessonId", IdCodec.format("lsn", lid),
                "lessonTitle", String.valueOf(lessonRow.get("title")),
                "activeBlockIndex", blockIdx,
                "publicBlocks", publicBlocks
        ));
        aiPayload.put("history", history);
        aiPayload.put("ragEnabled", props.ragEnabled());
        aiPayload.put("allowedTools", List.of("read_lesson", "explain_deeper", "read_source"));

        SseEmitter emitter = new SseEmitter(120_000L);
        AtomicBoolean cancelled = new AtomicBoolean(false);
        activeCancelFlags.put(assistantMsgId, cancelled);
        emitter.onCompletion(() -> activeCancelFlags.remove(assistantMsgId));
        emitter.onTimeout(() -> {
            cancelled.set(true);
            activeCancelFlags.remove(assistantMsgId);
        });

        Thread.startVirtualThread(() -> relayAiStream(emitter, assistantMsgId, threadUuid, aiPayload, cancelled));
        return emitter;
    }

    @PostMapping("/messages/{messageId}/stop")
    public Map<String, Object> stopMessage(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String messageId,
            HttpServletRequest request
    ) {
        requireTutorEnabled();
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID mid = IdCodec.parse(messageId, "tmsg");
        verifyOwnedCourse(principal.userId(), cid);

        int updated = jdbc.sql("""
                UPDATE core.tutor_messages
                SET cancel_requested_at = now()
                WHERE id = :mid AND user_id = :uid
                """)
                .param("mid", mid)
                .param("uid", principal.userId())
                .update();
        if (updated == 0) {
            throw new ApiException(HttpStatus.NOT_FOUND, "TUTOR_STOP_NOT_FOUND", "Không tìm thấy câu trả lời để dừng.");
        }

        AtomicBoolean flag = activeCancelFlags.get(mid);
        if (flag != null) {
            flag.set(true);
        }

        return Map.of(
                "messageId", IdCodec.format("tmsg", mid),
                "status", "cancel_requested",
                "providerStopGuaranteed", false,
                "notice", "Đã yêu cầu dừng câu trả lời."
        );
    }

    private void relayAiStream(
            SseEmitter emitter,
            UUID assistantMsgId,
            UUID threadUuid,
            Map<String, Object> aiPayload,
            AtomicBoolean cancelled
    ) {
        StringBuilder fullText = new StringBuilder();
        String finalStatus = "completed";
        String errorCode = null;
        String citationsJson = "[]";

        try {
            HttpResponse<InputStream> upstream = aiEngine.openTutorSseStream(aiPayload, null);
            if (upstream.statusCode() != 200) {
                throw new IllegalStateException("ai-api returned HTTP " + upstream.statusCode());
            }
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(upstream.body(), StandardCharsets.UTF_8))) {
                String currentEvent = "message";
                StringBuilder dataBuf = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    if (cancelled.get()) {
                        finalStatus = "cancelled";
                        emitter.send(SseEmitter.event().name("cancelled").data(
                                Map.of("messageId", IdCodec.format("tmsg", assistantMsgId), "partial", true)
                        ));
                        break;
                    }
                    if (line.startsWith("event:")) {
                        currentEvent = line.substring(6).trim();
                    } else if (line.startsWith("data:")) {
                        if (!dataBuf.isEmpty()) dataBuf.append('\n');
                        dataBuf.append(line.substring(5).trim());
                    } else if (line.isBlank() && !dataBuf.isEmpty()) {
                        String rawData = dataBuf.toString();
                        dataBuf.setLength(0);
                        Map<String, Object> parsed = json.fromJson(rawData, new TypeReference<>() {});
                        if ("delta".equals(currentEvent) && parsed.get("text") != null) {
                            fullText.append(parsed.get("text"));
                        } else if ("citations".equals(currentEvent) && parsed.get("citations") != null) {
                            citationsJson = json.toJson(parsed.get("citations"));
                        } else if ("error".equals(currentEvent)) {
                            finalStatus = "failed";
                            errorCode = String.valueOf(parsed.getOrDefault("code", "TUTOR_PROVIDER_ERROR"));
                        }
                        emitter.send(SseEmitter.event().name(currentEvent).data(rawData, MediaType.APPLICATION_JSON));
                        currentEvent = "message";
                    }
                }
            }
            emitter.complete();
        } catch (Exception ex) {
            finalStatus = cancelled.get() ? "cancelled" : "failed";
            errorCode = cancelled.get() ? null : "TUTOR_PROVIDER_ERROR";
            try {
                emitter.send(SseEmitter.event().name("error").data(
                        Map.of(
                                "messageId", IdCodec.format("tmsg", assistantMsgId),
                                "code", "TUTOR_PROVIDER_ERROR",
                                "message", "Trợ giảng AI tạm thời gián đoạn."
                        )
                ));
            } catch (Exception ignored) {}
            emitter.complete();
        } finally {
            activeCancelFlags.remove(assistantMsgId);
            jdbc.sql("""
                    UPDATE core.tutor_messages
                    SET status = :status, content = :content, error_code = :err,
                        citations_json = CAST(:cites AS jsonb)
                    WHERE id = :mid
                    """)
                    .param("status", finalStatus)
                    .param("content", fullText.toString())
                    .param("err", errorCode)
                    .param("cites", citationsJson)
                    .param("mid", assistantMsgId)
                    .update();
            jdbc.sql("UPDATE core.tutor_threads SET updated_at = now() WHERE id = :tid")
                    .param("tid", threadUuid)
                    .update();
        }
    }

    private void requireTutorEnabled() {
        if (!props.tutorEnabled()) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "TUTOR_DISABLED", "Trợ giảng AI chưa được bật trên hệ thống này.");
        }
    }

    private String verifyOwnedCourse(UUID userId, UUID courseId) {
        return jdbc.sql("SELECT language FROM core.courses WHERE id = :cid AND user_id = :uid")
                .param("cid", courseId)
                .param("uid", userId)
                .query(String.class)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "COURSE_NOT_FOUND", "Không tìm thấy khóa học."));
    }
}
