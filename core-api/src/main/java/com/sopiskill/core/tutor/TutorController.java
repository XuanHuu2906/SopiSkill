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
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
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
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * Multi-Pod AI Tutor 'Sopi' SSE Gateway on Spring Boot Virtual Threads (Phase 5):
 *  - Redis Stream `tutor:stream:{messageId}` (TTL 10m) for cross-pod `Last-Event-ID` resume.
 *  - Redis Pub/Sub `tutor:cancel:{messageId}` for instant cross-pod `/stop`.
 *  - 3 thread kinds (`course|anchor|task`), 6 entry points, 6 Sopi tools including server-enforced
 *    `flag_question`, `revise_proposal` (optimistic lock), and `regenerate_unit` (`ChangeCard` confirm/decline).
 */
@RestController
@RequestMapping("/v1/courses/{courseId}/tutor")
public class TutorController {

    private static final String POD_NAME = resolvePodName();

    private static String resolvePodName() {
        String host = System.getenv("HOSTNAME");
        return (host == null || host.isBlank()) ? "local" : host.trim();
    }

    private static final Set<String> VALID_ENTRY_POINTS = Set.of(
            "tab", "wrong_answer", "teach_block", "term", "path_harder", "proposal"
    );
    private static final Set<String> VALID_THREAD_KINDS = Set.of("course", "anchor", "task");
    private static final Set<String> TERMINAL_EVENTS = Set.of("done", "error", "cancelled");

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final SopiProperties props;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;
    private final PublicBlockProjector projector;
    private final AiEngineClient aiEngine;
    private final TutorRedisStreamService redisStream;
    private final ConcurrentHashMap<UUID, AtomicBoolean> activeCancelFlags = new ConcurrentHashMap<>();

    public TutorController(
            JdbcClient jdbc,
            JsonHelper json,
            SopiProperties props,
            CsrfValidator csrf,
            RateLimiterService rateLimiter,
            PublicBlockProjector projector,
            AiEngineClient aiEngine,
            TutorRedisStreamService redisStream
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.props = props;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
        this.projector = projector;
        this.aiEngine = aiEngine;
        this.redisStream = redisStream;
    }

    public record ContextRef(@NotBlank String lessonId, @NotNull Integer blockIndex) {}

    public record TutorMessageRequest(
            @NotBlank String clientMessageId,
            String threadId,
            @NotBlank @Size(min = 1, max = 2000) String text,
            @Valid ContextRef contextRef,
            String entryPoint,
            String contextLabel,
            String threadKind,
            String anchorKey,
            Integer delayMs
    ) {}

    public record CreateSessionRequest(
            String kind,
            String lessonId,
            String anchorKey,
            String title
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

    @GetMapping
    public Map<String, Object> queryCourseTutor(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @RequestParam(required = false) String entryPoint,
            @RequestParam(required = false) String anchor,
            @RequestParam(required = false) String before,
            @RequestParam(defaultValue = "20") int limit
    ) {
        requireTutorEnabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);
        int safeLimit = Math.max(1, Math.min(limit, 50));

        Timestamp beforeTs = null;
        if (before != null && !before.isBlank()) {
            try {
                beforeTs = Timestamp.from(Instant.parse(before.trim()));
            } catch (Exception ex) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_CURSOR", "Cursor thời gian không hợp lệ.");
            }
        }

        List<Map<String, Object>> messages = jdbc.sql("""
                SELECT m.id, m.thread_id, m.role, m.status, m.content, m.entry_point, m.context_label,
                       m.context_ref, m.citations_json, m.created_at, t.kind, t.anchor_key
                FROM core.tutor_messages m
                JOIN core.tutor_threads t ON t.id = m.thread_id
                WHERE t.user_id = :uid AND t.course_id = :cid
                  AND (CAST(:ep AS text) IS NULL OR m.entry_point = :ep)
                  AND (CAST(:anchor AS text) IS NULL OR t.anchor_key = :anchor)
                  AND (CAST(:beforeTs AS timestamptz) IS NULL OR m.created_at < :beforeTs)
                ORDER BY m.created_at DESC
                LIMIT :limit
                """)
                .param("uid", principal.userId())
                .param("cid", cid)
                .param("ep", (entryPoint == null || entryPoint.isBlank()) ? null : entryPoint.trim())
                .param("anchor", (anchor == null || anchor.isBlank()) ? null : anchor.trim())
                .param("beforeTs", beforeTs)
                .param("limit", safeLimit)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("tmsg", rs.getObject("id", UUID.class)));
                    m.put("threadId", IdCodec.format("thr", rs.getObject("thread_id", UUID.class)));
                    m.put("threadKind", rs.getString("kind"));
                    m.put("anchorKey", rs.getString("anchor_key"));
                    m.put("role", rs.getString("role"));
                    m.put("status", rs.getString("status"));
                    m.put("content", rs.getString("content"));
                    m.put("entryPoint", rs.getString("entry_point"));
                    m.put("contextLabel", rs.getString("context_label"));
                    String ctx = rs.getString("context_ref");
                    m.put("contextRef", ctx == null ? null : json.fromJson(ctx, new TypeReference<Map<String, Object>>() {}));
                    m.put("citations", json.fromJson(rs.getString("citations_json"), new TypeReference<List<Map<String, Object>>>() {}));
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .list();

        String nextCursor = messages.isEmpty() ? null : String.valueOf(messages.getLast().get("createdAt"));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("courseId", IdCodec.format("crs", cid));
        out.put("items", messages);
        out.put("total", messages.size());
        out.put("nextBefore", nextCursor);
        return out;
    }

    @PostMapping("/sessions")
    @Transactional
    public ResponseEntity<Map<String, Object>> createSession(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @RequestBody(required = false) CreateSessionRequest body,
            HttpServletRequest request
    ) {
        requireTutorEnabled();
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        verifyOwnedCourse(principal.userId(), cid);

        String kind = (body != null && body.kind() != null && VALID_THREAD_KINDS.contains(body.kind()))
                ? body.kind()
                : "course";
        UUID lid = (body != null && body.lessonId() != null && !body.lessonId().isBlank())
                ? IdCodec.parse(body.lessonId(), "lsn")
                : null;
        String anchorKey = body == null ? null : body.anchorKey();
        String title = (body != null && body.title() != null && !body.title().isBlank())
                ? body.title().trim()
                : "Phiên hỏi Sopi";

        UUID tid = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.tutor_threads (id, user_id, course_id, lesson_id, kind, anchor_key, title)
                VALUES (:tid, :uid, :cid, :lid, :kind, :anchor, :title)
                """)
                .param("tid", tid)
                .param("uid", principal.userId())
                .param("cid", cid)
                .param("lid", lid)
                .param("kind", kind)
                .param("anchor", anchorKey)
                .param("title", title)
                .update();

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("thr", tid));
        out.put("courseId", IdCodec.format("crs", cid));
        out.put("lessonId", lid == null ? null : IdCodec.format("lsn", lid));
        out.put("kind", kind);
        out.put("anchorKey", anchorKey);
        out.put("title", title);
        out.put("sealed", false);
        return ResponseEntity.status(HttpStatus.CREATED).body(out);
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
                SELECT t.id, t.course_id, t.lesson_id, t.kind, t.anchor_key, t.title, t.sealed, t.created_at, t.updated_at,
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
                    UUID lid = rs.getObject("lesson_id", UUID.class);
                    m.put("lessonId", lid == null ? null : IdCodec.format("lsn", lid));
                    m.put("kind", rs.getString("kind"));
                    m.put("anchorKey", rs.getString("anchor_key"));
                    m.put("title", rs.getString("title"));
                    m.put("sealed", rs.getBoolean("sealed"));
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
                SELECT id, course_id, lesson_id, kind, anchor_key, title, sealed, created_at, updated_at
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
                    UUID lid = rs.getObject("lesson_id", UUID.class);
                    m.put("lessonId", lid == null ? null : IdCodec.format("lsn", lid));
                    m.put("kind", rs.getString("kind"));
                    m.put("anchorKey", rs.getString("anchor_key"));
                    m.put("title", rs.getString("title"));
                    m.put("sealed", rs.getBoolean("sealed"));
                    var ca = rs.getTimestamp("created_at");
                    var ua = rs.getTimestamp("updated_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    m.put("updatedAt", ua == null ? null : ua.toInstant().toString());
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "THREAD_NOT_FOUND", "Không tìm thấy hội thoại."));

        List<Map<String, Object>> messages = jdbc.sql("""
                SELECT id, role, status, content, entry_point, context_label, context_ref,
                       error_code, finish_reason, citations_json, created_at
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
                    m.put("entryPoint", rs.getString("entry_point"));
                    m.put("contextLabel", rs.getString("context_label"));
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

        List<Map<String, Object>> actions = jdbc.sql("""
                SELECT id, message_id, tool_name, status, payload, preview, job_id, created_at, updated_at
                FROM core.tutor_actions
                WHERE thread_id = :tid AND user_id = :uid
                ORDER BY created_at ASC
                """)
                .param("tid", tid)
                .param("uid", principal.userId())
                .query(this::mapActionRow)
                .list();

        thread.put("messageCount", messages.size());
        thread.put("messages", messages);
        thread.put("actions", actions);
        thread.put("replaySupported", true);
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

        String entryPoint = (body.entryPoint() != null && VALID_ENTRY_POINTS.contains(body.entryPoint().trim()))
                ? body.entryPoint().trim()
                : "tab";
        String threadKind = (body.threadKind() != null && VALID_THREAD_KINDS.contains(body.threadKind().trim()))
                ? body.threadKind().trim()
                : ("proposal".equals(entryPoint) ? "task" : (body.anchorKey() != null ? "anchor" : "course"));

        UUID lid = null;
        int blockIdx = 0;
        Map<String, Object> lessonContext = null;
        Map<String, Object> unitContext = null;
        Map<String, Object> proposalContext = null;

        if ("proposal".equals(entryPoint)) {
            proposalContext = jdbc.sql("""
                    SELECT version, approved, payload
                    FROM core.course_proposals
                    WHERE course_id = :cid
                    ORDER BY version DESC LIMIT 1
                    """)
                    .param("cid", cid)
                    .query((rs, rowNum) -> {
                        Map<String, Object> m = new LinkedHashMap<>();
                        m.put("version", rs.getInt("version"));
                        m.put("approved", rs.getBoolean("approved"));
                        m.put("payload", json.fromJson(rs.getString("payload"), new TypeReference<Map<String, Object>>() {}));
                        return m;
                    })
                    .optional()
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "PROPOSAL_NOT_FOUND", "Không tìm thấy đề cương khóa học."));
        } else {
            if (body.contextRef() == null) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TUTOR_CONTEXT_INVALID", "Thiếu ngữ cảnh bài học.");
            }
            lid = IdCodec.parse(body.contextRef().lessonId(), "lsn");
            blockIdx = body.contextRef().blockIndex();
            var lessonRow = jdbc.sql("""
                    SELECT l.title, l.unit_id, l.content_version, l.content_json, u.title AS unit_title
                    FROM core.lessons l
                    JOIN core.units u ON u.id = l.unit_id
                    WHERE l.id = :lid AND l.course_id = :cid
                    """)
                    .param("lid", lid)
                    .param("cid", cid)
                    .query((rs, rowNum) -> Map.<String, Object>of(
                            "title", rs.getString("title"),
                            "unitId", IdCodec.format("unit", rs.getObject("unit_id", UUID.class)),
                            "unitTitle", rs.getString("unit_title"),
                            "contentVersion", rs.getInt("content_version"),
                            "blocks", json.fromJson(rs.getString("content_json"), new TypeReference<List<Map<String, Object>>>() {})
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TUTOR_CONTEXT_INVALID", "Ngữ cảnh bài học không hợp lệ."));

            @SuppressWarnings("unchecked")
            List<Map<String, Object>> privateBlocks = (List<Map<String, Object>>) lessonRow.get("blocks");
            if (blockIdx < 0 || (!privateBlocks.isEmpty() && blockIdx >= privateBlocks.size())) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TUTOR_CONTEXT_INVALID", "Chỉ số block nằm ngoài bài học.");
            }

            // Strictly sanitize blocks through PublicBlockProjector -> ZERO answer keys sent to ai-api!
            List<Map<String, Object>> publicBlocks = projector.toPublicBlocks(
                    lid,
                    ((Number) lessonRow.get("contentVersion")).intValue(),
                    privateBlocks
            );
            lessonContext = Map.of(
                    "lessonId", IdCodec.format("lsn", lid),
                    "lessonTitle", String.valueOf(lessonRow.get("title")),
                    "activeBlockIndex", blockIdx,
                    "publicBlocks", publicBlocks
            );
            unitContext = Map.of(
                    "unitId", String.valueOf(lessonRow.get("unitId")),
                    "unitTitle", String.valueOf(lessonRow.get("unitTitle"))
            );
        }

        // Load linked source IDs (max 3) & primary brief for `read_source` Hybrid RAG + section-anchor lookup
        List<Map<String, Object>> linkedSources = jdbc.sql("""
                SELECT s.id, s.brief::text AS brief_text
                FROM core.course_sources cs
                JOIN core.sources s ON s.id = cs.source_id
                WHERE cs.course_id = :cid
                ORDER BY CASE WHEN cs.role = 'primary' THEN 0 ELSE 1 END ASC, cs.linked_at ASC
                LIMIT 3
                """)
                .param("cid", cid)
                .query((rs, rowNum) -> {
                    Map<String, Object> r = new LinkedHashMap<>();
                    r.put("id", IdCodec.format("src", rs.getObject("id", UUID.class)));
                    r.put("briefText", rs.getString("brief_text"));
                    return r;
                })
                .list();
        List<String> linkedSourceIds = linkedSources.stream()
                .map(r -> String.valueOf(r.get("id")))
                .toList();
        Map<String, Object> sourceBrief = linkedSources.stream()
                .filter(r -> r.get("briefText") != null)
                .findFirst()
                .map(r -> json.fromJson(String.valueOf(r.get("briefText")), new TypeReference<Map<String, Object>>() {}))
                .orElse(null);

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
                    INSERT INTO core.tutor_threads (id, user_id, course_id, lesson_id, kind, anchor_key, title)
                    VALUES (:tid, :uid, :cid, :lid, :kind, :anchor, :title)
                    """)
                    .param("tid", threadUuid)
                    .param("uid", uid)
                    .param("cid", cid)
                    .param("lid", lid)
                    .param("kind", threadKind)
                    .param("anchor", body.anchorKey())
                    .param("title", title)
                    .update();
        }

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
        String ctxJson = lid == null
                ? json.toJson(Map.of("entryPoint", entryPoint))
                : json.toJson(Map.of("lessonId", IdCodec.format("lsn", lid), "blockIndex", blockIdx));

        jdbc.sql("""
                INSERT INTO core.tutor_messages (
                    id, thread_id, user_id, client_message_id, role, status, content,
                    entry_point, context_label, context_ref
                ) VALUES (
                    :id, :tid, :uid, :cmid, 'user', 'completed', :content,
                    :ep, :clabel, CAST(:ctx AS jsonb)
                )
                """)
                .param("id", userMsgId)
                .param("tid", threadUuid)
                .param("uid", uid)
                .param("cmid", body.clientMessageId())
                .param("content", body.text().trim())
                .param("ep", entryPoint)
                .param("clabel", body.contextLabel())
                .param("ctx", ctxJson)
                .update();

        jdbc.sql("""
                INSERT INTO core.tutor_messages (
                    id, thread_id, user_id, role, status, content, entry_point, context_label, context_ref
                ) VALUES (
                    :id, :tid, :uid, 'assistant', 'streaming', '', :ep, :clabel, CAST(:ctx AS jsonb)
                )
                """)
                .param("id", assistantMsgId)
                .param("tid", threadUuid)
                .param("uid", uid)
                .param("ep", entryPoint)
                .param("clabel", body.contextLabel())
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
        response.setHeader("X-Pod-Name", POD_NAME);
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");

        List<String> allowedTools = "proposal".equals(entryPoint)
                ? List.of("revise_proposal", "read_source")
                : List.of("read_lesson", "explain_deeper", "read_source", "flag_question", "regenerate_unit");

        Map<String, Object> aiPayload = new LinkedHashMap<>();
        aiPayload.put("ownerId", IdCodec.format("usr", uid));
        aiPayload.put("courseId", IdCodec.format("crs", cid));
        aiPayload.put("threadId", formattedThreadId);
        aiPayload.put("messageId", formattedMsgId);
        aiPayload.put("language", language);
        aiPayload.put("entryPoint", entryPoint);
        aiPayload.put("userMessage", body.text().trim());
        if (lessonContext != null) aiPayload.put("lessonContext", lessonContext);
        if (unitContext != null) aiPayload.put("unitContext", unitContext);
        if (proposalContext != null) aiPayload.put("proposalContext", proposalContext);
        if (sourceBrief != null) aiPayload.put("sourceBrief", sourceBrief);
        if (!linkedSourceIds.isEmpty()) aiPayload.put("sourceIds", linkedSourceIds);
        if (body.delayMs() != null && body.delayMs() > 0) aiPayload.put("delayMs", Math.min(body.delayMs(), 2000));
        aiPayload.put("history", history);
        aiPayload.put("ragEnabled", props.ragEnabled());
        aiPayload.put("allowedTools", allowedTools);

        SseEmitter emitter = new SseEmitter(120_000L);
        AtomicBoolean cancelled = new AtomicBoolean(false);
        activeCancelFlags.put(assistantMsgId, cancelled);
        emitter.onCompletion(() -> activeCancelFlags.remove(assistantMsgId));
        emitter.onTimeout(() -> {
            cancelled.set(true);
            activeCancelFlags.remove(assistantMsgId);
        });

        final UUID finalLid = lid;
        Thread.startVirtualThread(() -> relayAiStream(
                emitter, uid, cid, finalLid, assistantMsgId, threadUuid, aiPayload, cancelled
        ));
        return emitter;
    }

    @GetMapping(value = "/messages/{messageId}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter resumeStream(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String messageId,
            @RequestHeader(value = "Last-Event-ID", required = false) String lastEventIdHeader,
            @RequestParam(value = "lastEventId", required = false) String lastEventIdParam,
            HttpServletResponse response
    ) {
        requireTutorEnabled();
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID mid = IdCodec.parse(messageId, "tmsg");
        verifyOwnedCourse(principal.userId(), cid);

        var msgRow = jdbc.sql("""
                SELECT m.id, m.thread_id, m.status, m.content
                FROM core.tutor_messages m
                JOIN core.tutor_threads t ON t.id = m.thread_id
                WHERE m.id = :mid AND t.course_id = :cid AND m.user_id = :uid
                """)
                .param("mid", mid)
                .param("cid", cid)
                .param("uid", principal.userId())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "threadId", IdCodec.format("thr", rs.getObject("thread_id", UUID.class)),
                        "status", rs.getString("status"),
                        "content", rs.getString("content")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "MESSAGE_NOT_FOUND", "Không tìm thấy luồng tin nhắn."));

        String formattedMsgId = IdCodec.format("tmsg", mid);
        String cursor = (lastEventIdHeader != null && !lastEventIdHeader.isBlank())
                ? lastEventIdHeader.trim()
                : (lastEventIdParam != null ? lastEventIdParam.trim() : "0-0");

        response.setHeader("X-Tutor-Thread-Id", String.valueOf(msgRow.get("threadId")));
        response.setHeader("X-Tutor-Message-Id", formattedMsgId);
        response.setHeader("X-Pod-Name", POD_NAME);
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");

        SseEmitter emitter = new SseEmitter(60_000L);
        Thread.startVirtualThread(() -> {
            try {
                if (!redisStream.streamExists(formattedMsgId)) {
                    String restartedJson = json.toJson(Map.of(
                            "messageId", formattedMsgId,
                            "threadId", msgRow.get("threadId"),
                            "status", msgRow.get("status"),
                            "content", msgRow.get("content"),
                            "reason", "stream_expired"
                    ));
                    emitter.send(SseEmitter.event().name("restarted").data(restartedJson, MediaType.APPLICATION_JSON));
                    emitter.complete();
                    return;
                }

                String currentCursor = cursor;
                long deadline = System.currentTimeMillis() + 30_000L;
                while (System.currentTimeMillis() < deadline) {
                    var frames = redisStream.readFramesAfter(formattedMsgId, currentCursor);
                    boolean sawTerminal = false;
                    for (var f : frames) {
                        emitter.send(SseEmitter.event()
                                .id(f.id())
                                .name(f.event())
                                .data(f.data(), MediaType.APPLICATION_JSON));
                        currentCursor = f.id();
                        if (TERMINAL_EVENTS.contains(f.event())) {
                            sawTerminal = true;
                        }
                    }
                    if (sawTerminal) break;

                    String liveStatus = jdbc.sql("SELECT status FROM core.tutor_messages WHERE id = :mid")
                            .param("mid", mid).query(String.class).optional().orElse("completed");
                    if (!"streaming".equals(liveStatus)) {
                        // Drain once more after DB finished
                        for (var f : redisStream.readFramesAfter(formattedMsgId, currentCursor)) {
                            emitter.send(SseEmitter.event()
                                    .id(f.id())
                                    .name(f.event())
                                    .data(f.data(), MediaType.APPLICATION_JSON));
                            currentCursor = f.id();
                        }
                        break;
                    }
                    Thread.sleep(60);
                }
                emitter.complete();
            } catch (Exception ex) {
                emitter.completeWithError(ex);
            }
        });
        return emitter;
    }

    @PostMapping("/messages/{messageId}/stop")
    public Map<String, Object> stopMessage(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String messageId,
            HttpServletRequest request,
            HttpServletResponse response
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

        String formattedMsgId = IdCodec.format("tmsg", mid);
        AtomicBoolean flag = activeCancelFlags.get(mid);
        if (flag != null) {
            flag.set(true);
        }
        // Multi-Pod Instant Stop via Redis Pub/Sub (`tutor:cancel:{msgId}`)!
        redisStream.publishCancel(formattedMsgId);
        response.setHeader("X-Pod-Name", POD_NAME);

        return Map.of(
                "messageId", formattedMsgId,
                "podName", POD_NAME,
                "status", "cancel_requested",
                "providerStopGuaranteed", false,
                "notice", "Đã yêu cầu dừng câu trả lời."
        );
    }

    @GetMapping("/actions/{actionId}")
    public Map<String, Object> getAction(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String actionId
    ) {
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID aid = IdCodec.parse(actionId, "act");
        verifyOwnedCourse(principal.userId(), cid);
        return jdbc.sql("""
                SELECT id, message_id, tool_name, status, payload, preview, job_id, created_at, updated_at
                FROM core.tutor_actions
                WHERE id = :aid AND course_id = :cid AND user_id = :uid
                """)
                .param("aid", aid)
                .param("cid", cid)
                .param("uid", principal.userId())
                .query(this::mapActionRow)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ACTION_NOT_FOUND", "Không tìm thấy đề xuất chỉnh sửa."));
    }

    @PostMapping("/actions/{actionId}/confirm")
    @Transactional
    public Map<String, Object> confirmAction(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String actionId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID uid = principal.userId();
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID aid = IdCodec.parse(actionId, "act");
        String language = verifyOwnedCourse(uid, cid);

        var action = jdbc.sql("""
                SELECT id, tool_name, status, payload, preview
                FROM core.tutor_actions
                WHERE id = :aid AND course_id = :cid AND user_id = :uid
                FOR UPDATE
                """)
                .param("aid", aid)
                .param("cid", cid)
                .param("uid", uid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "toolName", rs.getString("tool_name"),
                        "status", rs.getString("status"),
                        "payload", json.fromJson(rs.getString("payload"), new TypeReference<Map<String, Object>>() {})
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ACTION_NOT_FOUND", "Không tìm thấy đề xuất chỉnh sửa."));

        String status = String.valueOf(action.get("status"));
        if (!"pending".equals(status)) {
            throw new ApiException(HttpStatus.CONFLICT, "ACTION_ALREADY_HANDLED", "Đề xuất này đã được xử lý (" + status + ").");
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> payload = (Map<String, Object>) action.get("payload");
        UUID targetUnitId = null;
        if (payload.get("unitId") instanceof String uidStr && !uidStr.isBlank()) {
            targetUnitId = IdCodec.parse(uidStr, "unit");
        } else {
            targetUnitId = jdbc.sql("SELECT id FROM core.units WHERE course_id = :cid ORDER BY order_index ASC LIMIT 1")
                    .param("cid", cid).query(UUID.class).optional().orElse(null);
        }
        if (targetUnitId == null) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "UNIT_NOT_FOUND", "Không tìm thấy chương mục cần viết lại.");
        }

        String unitTitle = jdbc.sql("SELECT title FROM core.units WHERE id = :uid AND course_id = :cid")
                .param("uid", targetUnitId).param("cid", cid).query(String.class).single();
        String topic = jdbc.sql("SELECT topic FROM core.courses WHERE id = :cid")
                .param("cid", cid).query(String.class).single();

        // Increment content_version + 1 on all lessons in the target unit, clear old reel state & mark generating
        jdbc.sql("""
                UPDATE core.lessons
                SET content_version = content_version + 1,
                    status = 'generating',
                    reel_manifest = NULL,
                    reel_status = 'none',
                    updated_at = now()
                WHERE unit_id = :unitId AND course_id = :cid
                """)
                .param("unitId", targetUnitId)
                .param("cid", cid)
                .update();

        List<Map<String, Object>> unitLessons = jdbc.sql("""
                SELECT id, title, content_version FROM core.lessons
                WHERE unit_id = :unitId AND course_id = :cid
                ORDER BY order_index ASC
                """)
                .param("unitId", targetUnitId)
                .param("cid", cid)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "uuid", rs.getObject("id", UUID.class),
                        "id", IdCodec.format("lsn", rs.getObject("id", UUID.class)),
                        "title", rs.getString("title"),
                        "contentVersion", rs.getInt("content_version")
                ))
                .list();

        String formattedCourseId = IdCodec.format("crs", cid);
        for (Map<String, Object> ul : unitLessons) {
            UUID lidUuid = (UUID) ul.get("uuid");
            String lidFormatted = String.valueOf(ul.get("id"));
            jdbc.sql("DELETE FROM core.media_calls WHERE lesson_id = :lid").param("lid", lidUuid).update();
            jdbc.sql("DELETE FROM core.lesson_reels WHERE lesson_id = :lid").param("lid", lidUuid).update();
            aiEngine.deleteRagResourceBestEffort("/internal/reels/audio/" + formattedCourseId + "/" + lidFormatted, null);
        }

        List<String> lessonIds = unitLessons.stream().map(m -> String.valueOf(m.get("id"))).toList();
        List<String> lessonTitles = unitLessons.stream().map(m -> String.valueOf(m.get("title"))).toList();
        int nextVersion = unitLessons.isEmpty() ? 2 : ((Number) unitLessons.get(0).get("contentVersion")).intValue();

        UUID jobId = UUID.randomUUID();
        String idempKey = "regen_unit_" + targetUnitId + "_" + jobId;
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
                .param("total", lessonIds.size())
                .update();

        jdbc.sql("""
                UPDATE core.tutor_actions
                SET status = 'preparing', job_id = :jid, updated_at = now()
                WHERE id = :aid
                """)
                .param("jid", jobId)
                .param("aid", aid)
                .update();

        aiEngine.enqueueLlmJob(Map.of(
                "jobId", IdCodec.format("job", jobId),
                "idempotencyKey", idempKey,
                "jobType", "regenerate_unit",
                "ownerId", IdCodec.format("usr", uid),
                "courseId", IdCodec.format("crs", cid),
                "correlationId", "cor_" + jobId.toString().replace("-", "").substring(0, 16),
                "attempt", 1,
                "payload", Map.of(
                        "topic", topic,
                        "language", language,
                        "lessonIds", lessonIds,
                        "contentVersion", nextVersion,
                        "reelEnabled", props.reelEnabled(),
                        "units", List.of(Map.of("title", unitTitle, "lessonTitles", lessonTitles))
                )
        ));

        return getAction(principal, courseId, actionId);
    }

    @PostMapping("/actions/{actionId}/decline")
    @Transactional
    public Map<String, Object> declineAction(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String courseId,
            @PathVariable String actionId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        UUID cid = IdCodec.parse(courseId, "crs");
        UUID aid = IdCodec.parse(actionId, "act");
        verifyOwnedCourse(principal.userId(), cid);

        int updated = jdbc.sql("""
                UPDATE core.tutor_actions
                SET status = 'declined', updated_at = now()
                WHERE id = :aid AND course_id = :cid AND user_id = :uid AND status = 'pending'
                """)
                .param("aid", aid)
                .param("cid", cid)
                .param("uid", principal.userId())
                .update();
        if (updated == 0) {
            throw new ApiException(HttpStatus.CONFLICT, "ACTION_ALREADY_HANDLED", "Đề xuất không còn ở trạng thái chờ xác nhận.");
        }
        return getAction(principal, courseId, actionId);
    }

    private void relayAiStream(
            SseEmitter emitter,
            UUID userId,
            UUID courseId,
            UUID lessonId,
            UUID assistantMsgId,
            UUID threadUuid,
            Map<String, Object> aiPayload,
            AtomicBoolean cancelled
    ) {
        String formattedMsgId = IdCodec.format("tmsg", assistantMsgId);
        StringBuilder fullText = new StringBuilder();
        String finalStatus = "completed";
        String errorCode = null;
        String citationsJson = "[]";
        AtomicReference<InputStream> upstreamBodyRef = new AtomicReference<>();

        Runnable unsubscribeCancel = redisStream.subscribeCancel(formattedMsgId, () -> {
            cancelled.set(true);
            InputStream bodyStream = upstreamBodyRef.get();
            if (bodyStream != null) {
                try {
                    bodyStream.close();
                } catch (Exception ignored) {}
            }
        });

        try {
            HttpResponse<InputStream> upstream = aiEngine.openTutorSseStream(aiPayload, null);
            if (upstream.statusCode() != 200) {
                throw new IllegalStateException("ai-api returned HTTP " + upstream.statusCode());
            }
            upstreamBodyRef.set(upstream.body());
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(upstream.body(), StandardCharsets.UTF_8))) {
                String currentEvent = "message";
                StringBuilder dataBuf = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    if (cancelled.get()) {
                        finalStatus = "cancelled";
                        emitBuffered(emitter, formattedMsgId, "cancelled", json.toJson(
                                Map.of("messageId", formattedMsgId, "partial", true)
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

                        if ("tool_effect".equals(currentEvent)) {
                            handleToolEffect(emitter, userId, courseId, lessonId, threadUuid, assistantMsgId, formattedMsgId, parsed);
                            currentEvent = "message";
                            continue;
                        }

                        if ("delta".equals(currentEvent) && parsed.get("text") != null) {
                            fullText.append(parsed.get("text"));
                        } else if ("citations".equals(currentEvent) && parsed.get("citations") != null) {
                            citationsJson = json.toJson(parsed.get("citations"));
                        } else if ("error".equals(currentEvent)) {
                            finalStatus = "failed";
                            errorCode = String.valueOf(parsed.getOrDefault("code", "TUTOR_PROVIDER_ERROR"));
                        }
                        emitBuffered(emitter, formattedMsgId, currentEvent, rawData);
                        currentEvent = "message";
                    }
                }
            }
            emitter.complete();
        } catch (Exception ex) {
            if (cancelled.get()) {
                finalStatus = "cancelled";
                errorCode = null;
                try {
                    emitBuffered(emitter, formattedMsgId, "cancelled", json.toJson(
                            Map.of("messageId", formattedMsgId, "partial", true)
                    ));
                } catch (Exception ignored) {}
            } else {
                finalStatus = "failed";
                errorCode = "TUTOR_PROVIDER_ERROR";
                try {
                    emitBuffered(emitter, formattedMsgId, "error", json.toJson(Map.of(
                            "messageId", formattedMsgId,
                            "code", "TUTOR_PROVIDER_ERROR",
                            "message", "Trợ giảng AI tạm thời gián đoạn."
                    )));
                } catch (Exception ignored) {}
            }
            try {
                emitter.complete();
            } catch (Exception ignored) {}
        } finally {
            unsubscribeCancel.run();
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

    @SuppressWarnings("unchecked")
    private void handleToolEffect(
            SseEmitter emitter,
            UUID userId,
            UUID courseId,
            UUID lessonId,
            UUID threadUuid,
            UUID assistantMsgId,
            String formattedMsgId,
            Map<String, Object> effect
    ) {
        String kind = String.valueOf(effect.getOrDefault("kind", ""));
        if ("flag_question".equals(kind) && lessonId != null) {
            Integer blkIdx = effect.get("blockIndex") instanceof Number n ? n.intValue() : null;
            String code = String.valueOf(effect.getOrDefault("code", "LEARNER_FLAGGED_QUESTION"));
            String severity = String.valueOf(effect.getOrDefault("severity", "warning"));
            String details = String.valueOf(effect.getOrDefault("details", "Flagged via Sopi Tutor."));
            jdbc.sql("""
                    INSERT INTO core.content_flags (id, course_id, lesson_id, block_index, source, code, severity, details)
                    VALUES (:id, :cid, :lid, :bidx, 'tutor', :code, :sev, :details)
                    """)
                    .param("id", UUID.randomUUID())
                    .param("cid", courseId)
                    .param("lid", lessonId)
                    .param("bidx", blkIdx)
                    .param("code", code)
                    .param("sev", severity)
                    .param("details", details)
                    .update();
        } else if ("revise_proposal".equals(kind)) {
            Map<String, Object> newPayload = effect.get("proposal") instanceof Map<?, ?> m
                    ? (Map<String, Object>) m
                    : null;
            if (newPayload != null) {
                var currentProp = jdbc.sql("""
                        SELECT id, version FROM core.course_proposals
                        WHERE course_id = :cid
                        ORDER BY version DESC LIMIT 1
                        """)
                        .param("cid", courseId)
                        .query((rs, rowNum) -> Map.<String, Object>of(
                                "id", rs.getObject("id", UUID.class),
                                "version", rs.getInt("version")
                        ))
                        .optional();
                if (currentProp.isPresent()) {
                    int nextVer = ((Number) currentProp.get().get("version")).intValue() + 1;
                    jdbc.sql("""
                            INSERT INTO core.course_proposals (id, course_id, version, approved, payload)
                            VALUES (:id, :cid, :ver, FALSE, CAST(:payload AS jsonb))
                            """)
                            .param("id", UUID.randomUUID())
                            .param("cid", courseId)
                            .param("ver", nextVer)
                            .param("payload", json.toJson(newPayload))
                            .update();
                    String eventJson = json.toJson(Map.of(
                            "messageId", formattedMsgId,
                            "version", nextVer,
                            "approved", false,
                            "payload", newPayload
                    ));
                    emitBuffered(emitter, formattedMsgId, "proposal_revised", eventJson);
                }
            }
        } else if ("regenerate_unit".equals(kind)) {
            UUID actionId = UUID.randomUUID();
            Map<String, Object> preview = effect.get("preview") instanceof Map<?, ?> m
                    ? (Map<String, Object>) m
                    : Map.of("summary", "Viết lại chương theo độ khó phù hợp hơn.");
            Map<String, Object> actionPayload = new LinkedHashMap<>();
            if (effect.get("unitId") != null) actionPayload.put("unitId", effect.get("unitId"));
            if (effect.get("unitTitle") != null) actionPayload.put("unitTitle", effect.get("unitTitle"));

            jdbc.sql("""
                    INSERT INTO core.tutor_actions (
                        id, thread_id, message_id, course_id, user_id, tool_name, status, payload, preview
                    ) VALUES (
                        :id, :tid, :mid, :cid, :uid, 'regenerate_unit', 'pending',
                        CAST(:payload AS jsonb), CAST(:preview AS jsonb)
                    )
                    """)
                    .param("id", actionId)
                    .param("tid", threadUuid)
                    .param("mid", assistantMsgId)
                    .param("cid", courseId)
                    .param("uid", userId)
                    .param("payload", json.toJson(actionPayload))
                    .param("preview", json.toJson(preview))
                    .update();

            String confirmJson = json.toJson(Map.of(
                    "messageId", formattedMsgId,
                    "actionId", IdCodec.format("act", actionId),
                    "toolName", "regenerate_unit",
                    "status", "pending",
                    "payload", actionPayload,
                    "preview", preview
            ));
            emitBuffered(emitter, formattedMsgId, "confirm", confirmJson);
        }
    }

    private void emitBuffered(SseEmitter emitter, String formattedMsgId, String eventName, String jsonData) {
        String entryId = redisStream.appendFrame(formattedMsgId, eventName, jsonData);
        try {
            emitter.send(SseEmitter.event()
                    .id(entryId)
                    .name(eventName)
                    .data(jsonData, MediaType.APPLICATION_JSON));
        } catch (Exception ignored) {
            // Client may have disconnected mid-stream; frame is safely persisted in Redis Stream for Last-Event-ID resume!
        }
    }

    private Map<String, Object> mapActionRow(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", IdCodec.format("act", rs.getObject("id", UUID.class)));
        m.put("actionId", IdCodec.format("act", rs.getObject("id", UUID.class)));
        m.put("messageId", IdCodec.format("tmsg", rs.getObject("message_id", UUID.class)));
        m.put("toolName", rs.getString("tool_name"));
        m.put("status", rs.getString("status"));
        m.put("payload", json.fromJson(rs.getString("payload"), new TypeReference<Map<String, Object>>() {}));
        m.put("preview", json.fromJson(rs.getString("preview"), new TypeReference<Map<String, Object>>() {}));
        UUID jid = rs.getObject("job_id", UUID.class);
        m.put("jobId", jid == null ? null : IdCodec.format("job", jid));
        var ca = rs.getTimestamp("created_at");
        var ua = rs.getTimestamp("updated_at");
        m.put("createdAt", ca == null ? null : ca.toInstant().toString());
        m.put("updatedAt", ua == null ? null : ua.toInstant().toString());
        return m;
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
