package com.sopiskill.core.tutor;

import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.security.AuthPrincipal;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Cross-course Sopi Tutor sessions listing (`GET /v1/tutor/sessions`) grouped by
 * `thisWeek` ("Tuần này") and `earlier` ("Trước đó").
 */
@RestController
@RequestMapping("/v1/tutor")
public class GlobalTutorSessionsController {

    private final JdbcClient jdbc;

    public GlobalTutorSessionsController(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/sessions")
    public Map<String, Object> listGlobalSessions(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(defaultValue = "30") int limit
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        List<Map<String, Object>> all = jdbc.sql("""
                SELECT t.id, t.course_id, t.lesson_id, t.kind, t.anchor_key, t.title, t.sealed,
                       t.created_at, t.updated_at, c.topic AS course_topic,
                       (SELECT COUNT(*) FROM core.tutor_messages m WHERE m.thread_id = t.id) AS msg_count
                FROM core.tutor_threads t
                JOIN core.courses c ON c.id = t.course_id
                WHERE t.user_id = :uid
                ORDER BY t.updated_at DESC
                LIMIT :limit
                """)
                .param("uid", principal.userId())
                .param("limit", safeLimit)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("thr", rs.getObject("id", UUID.class)));
                    m.put("courseId", IdCodec.format("crs", rs.getObject("course_id", UUID.class)));
                    UUID lid = rs.getObject("lesson_id", UUID.class);
                    m.put("lessonId", lid == null ? null : IdCodec.format("lsn", lid));
                    m.put("courseTopic", rs.getString("course_topic"));
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

        Instant weekCutoff = Instant.now().minus(7, ChronoUnit.DAYS);
        List<Map<String, Object>> thisWeek = new ArrayList<>();
        List<Map<String, Object>> earlier = new ArrayList<>();
        for (Map<String, Object> item : all) {
            String ua = (String) item.get("updatedAt");
            Instant ts = ua == null ? Instant.EPOCH : Instant.parse(ua);
            if (!ts.isBefore(weekCutoff)) {
                thisWeek.add(item);
            } else {
                earlier.add(item);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", all);
        out.put("thisWeek", thisWeek);
        out.put("earlier", earlier);
        out.put("total", all.size());
        return out;
    }
}
