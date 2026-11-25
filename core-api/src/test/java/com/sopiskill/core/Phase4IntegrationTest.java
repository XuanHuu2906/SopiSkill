package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.lesson.PublicBlockProjector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 4 integration & security tests against live PostgreSQL 16 (Flyway V3) + Redis 7 + `ai-api`:
 *   1. Flyway V3 `core.short_answer_grades` table + `X-Client-Blocks` capability negotiation.
 *   2. Zero answer key leakage in `GET /v1/lessons/{id}` across Multi-Blank, Scenario MC, Spot/Steps MC,
 *      SpeedRound, and Explain Short blocks.
 *   3. Multi-Blank Word Bank HMAC-shuffled bank + `correctIndices` lock on partial wrong check
 *      (without leaking remaining answers) + 1-blank backward compatibility.
 *   4. Scenario MC reveals ONLY the outcome of the chosen option.
 *   5. SpeedRound server-side grading + Recap block treated as non-gradable.
 *   6. 3-level short-answer grading (`got_it | almost | not_yet`) persisted to `core.short_answer_grades`
 *      and disputable via `POST /v1/lessons/{id}/grades/{gradeId}/dispute`.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:phase4",
        "sopiskill.rate-limit-enabled=false"
})
class Phase4IntegrationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcClient jdbc;

    @Autowired
    private PublicBlockProjector projector;

    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    void projectorEnforcesMutualExclusionAndCapabilityNegotiation() {
        UUID lid = UUID.randomUUID();
        Map<String, Object> teachWithBoth = Map.of(
                "type", "teach",
                "title", "Mutual Exclusion",
                "paragraphs", List.of("Intro"),
                "figure", Map.of("kind", "formula", "latex", "E = mc^2"),
                "image", Map.of("url", "https://example.com/a.png", "alt", "A")
        );
        // Modern client: figure wins, image dropped
        Map<String, Object> full = projector.toPublicBlock(lid, 1, 0, teachWithBoth, null);
        assertThat(full).containsKey("figure").doesNotContainKey("image");

        // Legacy client without `figure` or `teach` capability falls back cleanly
        Map<String, Object> legacy = projector.toPublicBlock(lid, 1, 0, teachWithBoth,
                PublicBlockProjector.parseClientCapabilities("mc,blank"));
        assertThat(legacy).doesNotContainKey("figure").containsKey("image");

        // 1-blank backward compatibility
        Map<String, Object> singleBlank = Map.of("type", "blank", "sentence", "Key is ____.", "answer", "index");
        assertThat(projector.gradeBlank(singleBlank, "INDEX")).isTrue();
        assertThat(projector.gradeBlank(singleBlank, "wrong")).isFalse();
    }

    @Test
    @SuppressWarnings("unchecked")
    void phase4RichLessonWirePrivacyGradingAndShortGradeDispute() throws Exception {
        // 1. Register user
        String email = "phase4-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
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
        String accessCookie = extractCookieValue(setCookies, "access_token");
        String csrfCookie = extractCookieValue(setCookies, "csrf_token");
        String cookieHeader = "access_token=" + accessCookie + "; csrf_token=" + csrfCookie;

        // 2. Seed an owned course + unit + rich Phase 4 lesson directly via SQL
        UUID userId = IdCodec.parse(String.valueOf(parseMap(regResp.body()).get("id")), "usr");
        UUID courseUuid = UUID.randomUUID();
        UUID unitUuid = UUID.randomUUID();
        UUID lessonUuid = UUID.randomUUID();
        String lessonId = IdCodec.format("lsn", lessonUuid);

        List<Map<String, Object>> richBlocks = List.of(
                Map.of(
                        "type", "teach",
                        "kicker", "Unit 1 · Rich",
                        "title", "Vector Search",
                        "paragraphs", List.of("Combine {rrf_term} with $O(\\log n)$ graph search."),
                        "takeaway", "Hybrid search improves recall.",
                        "terms", List.of(Map.of("term", "RRF", "termKey", "rrf_term", "definition", "Reciprocal Rank Fusion")),
                        "figure", Map.of(
                                "kind", "table",
                                "headers", List.of("Engine", "Note"),
                                "rows", List.of(Map.of("tone", "moss", "cells", List.of("pgvector", "HNSW")))
                        )
                ),
                Map.of(
                        "type", "blank",
                        "parts", List.of("Start with ", " and verify with ", "."),
                        "answers", List.of("hypothesis", "test"),
                        "bank", List.of("hypothesis", "test", "guess", "delay")
                ),
                Map.of(
                        "type", "mc",
                        "format", "scenario",
                        "context", "Production query latency spiked.",
                        "question", "What do you inspect first?",
                        "options", List.of("EXPLAIN ANALYZE plan", "Drop all indexes", "Restart laptop"),
                        "outcomes", List.of("Correct outcome A", "Wrong outcome B", "Wrong outcome C"),
                        "answerIndex", 0
                ),
                Map.of(
                        "type", "mc",
                        "format", "spot",
                        "display", "steps",
                        "question", "Spot the buggy step.",
                        "steps", List.of("1. Bind param", "2. Concat raw SQL", "3. Close cursor"),
                        "options", List.of("Step 1", "Step 2", "Step 3"),
                        "answerIndex", 1
                ),
                Map.of(
                        "type", "speed",
                        "prompt", "Quick classify",
                        "timeLimitSeconds", 60,
                        "items", List.of(
                                Map.of("prompt", "Use parameterized query", "choices", List.of("Safe", "Risk"), "answerIndex", 0),
                                Map.of("prompt", "Log plaintext passwords", "choices", List.of("Safe", "Risk"), "answerIndex", 1)
                        )
                ),
                Map.of(
                        "type", "short",
                        "format", "explain",
                        "question", "Why isolate minimal test cases?",
                        "acceptedAnswers", List.of("minimal tests isolate root causes quickly"),
                        "keyPoints", List.of("isolate root cause", "verify early")
                ),
                Map.of(
                        "type", "recap",
                        "title", "Lesson Recap",
                        "points", List.of("Use EXPLAIN ANALYZE", "Isolate minimal repros"),
                        "sources", List.of(Map.of("label", "Unit 1", "count", 5))
                )
        );

        jdbc.sql("INSERT INTO core.courses (id, user_id, topic, language, status) VALUES (:cid, :uid, 'Vector Search', 'en', 'ready')")
                .param("cid", courseUuid).param("uid", userId).update();
        jdbc.sql("INSERT INTO core.units (id, course_id, order_index, title) VALUES (:uid, :cid, 0, 'Foundations')")
                .param("uid", unitUuid).param("cid", courseUuid).update();
        jdbc.sql("""
                INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_version, content_json)
                VALUES (:lid, :cid, :uid, 0, 'Rich Practice', 'ready', 1, CAST(:blocks AS jsonb))
                """)
                .param("lid", lessonUuid)
                .param("cid", courseUuid)
                .param("uid", unitUuid)
                .param("blocks", objectMapper.writeValueAsString(richBlocks))
                .update();

        // 3. GET /v1/lessons/{id} with X-Client-Blocks -> assert ZERO leaked answer keys / outcomes!
        HttpResponse<String> getResp = http.send(
                HttpRequest.newBuilder(URI.create(url("/v1/lessons/" + lessonId)))
                        .header("Cookie", cookieHeader)
                        .header("X-Client-Blocks", "teach,mc,blank,multi_blank,order,match,short,speed,recap,figure")
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(getResp.statusCode()).isEqualTo(200);
        String rawWire = getResp.body();
        for (String forbidden : List.of("\"answerIndex\"", "\"answers\"", "\"outcomes\"", "\"acceptedAnswers\"", "\"keyPoints\"", "Wrong outcome B", "Correct outcome A")) {
            assertThat(rawWire).as("Wire must not contain " + forbidden).doesNotContain(forbidden);
        }

        // 4. Grade Multi-Blank partially right (slot 0 correct, slot 1 wrong) -> correctIndices=[0], solution=null!
        HttpResponse<String> mbPartial = postAuthed("/v1/lessons/" + lessonId + "/blocks/1/grade", cookieHeader, csrfCookie,
                Map.of("contentVersion", 1, "answer", List.of("hypothesis", "guess")));
        assertThat(mbPartial.statusCode()).isEqualTo(200);
        Map<String, Object> mbJson = parseMap(mbPartial.body());
        assertThat(mbJson.get("correct")).isEqualTo(false);
        assertThat((List<Integer>) mbJson.get("correctIndices")).containsExactly(0);
        assertThat(mbJson.get("solution")).isNull();
        assertThat(mbPartial.body()).doesNotContain("test"); // remaining answer NOT leaked!

        // 5. Grade Scenario MC option 1 -> ONLY outcome[1] returned, never outcome[0] or outcome[2]!
        HttpResponse<String> scenResp = postAuthed("/v1/lessons/" + lessonId + "/blocks/2/grade", cookieHeader, csrfCookie,
                Map.of("contentVersion", 1, "answer", 1));
        assertThat(scenResp.statusCode()).isEqualTo(200);
        Map<String, Object> scenJson = parseMap(scenResp.body());
        assertThat(scenJson.get("correct")).isEqualTo(false);
        assertThat(scenJson.get("outcome")).isEqualTo("Wrong outcome B");
        assertThat(scenResp.body()).doesNotContain("Wrong outcome C");

        // 6. Grade SpeedRound server-side -> correct=true
        HttpResponse<String> speedResp = postAuthed("/v1/lessons/" + lessonId + "/blocks/4/grade", cookieHeader, csrfCookie,
                Map.of("contentVersion", 1, "answer", List.of(0, 1)));
        assertThat(speedResp.statusCode()).isEqualTo(200);
        assertThat(parseMap(speedResp.body()).get("correct")).isEqualTo(true);

        // 7. Grade Short Answer partially -> verdict="almost", persisted to core.short_answer_grades -> dispute!
        HttpResponse<String> shortResp = postAuthed("/v1/lessons/" + lessonId + "/blocks/5/grade", cookieHeader, csrfCookie,
                Map.of("contentVersion", 1, "answer", "They isolate root cause nicely"));
        assertThat(shortResp.statusCode()).isEqualTo(200);
        Map<String, Object> shortJson = parseMap(shortResp.body());
        assertThat(shortJson.get("verdict")).isEqualTo("almost");
        String gradeId = String.valueOf(shortJson.get("gradeId"));
        assertThat(gradeId).startsWith("sag_");

        HttpResponse<String> disputeResp = postAuthed(
                "/v1/lessons/" + lessonId + "/grades/" + gradeId + "/dispute",
                cookieHeader, csrfCookie, Map.of("reason", "I explained the core concept")
        );
        assertThat(disputeResp.statusCode()).isEqualTo(200);
        Map<String, Object> disputeJson = parseMap(disputeResp.body());
        assertThat(disputeJson.get("disputed")).isEqualTo(true);

        int disputedRows = jdbc.sql("SELECT COUNT(*) FROM core.short_answer_grades WHERE id = :gid AND disputed = TRUE")
                .param("gid", IdCodec.parse(gradeId, "sag"))
                .query(Integer.class).single();
        assertThat(disputedRows).isEqualTo(1);

        // 8. Submit full attempt: verify `recap` (index 6) is non-gradable so total == 5!
        HttpResponse<String> attemptResp = postAuthed("/v1/lessons/" + lessonId + "/attempts", cookieHeader, csrfCookie, Map.of(
                "clientAttemptId", "att-p4-" + UUID.randomUUID(),
                "contentVersion", 1,
                "answers", List.of(
                        Map.of("index", 1, "answer", List.of("hypothesis", "test")),
                        Map.of("index", 2, "answer", 0),
                        Map.of("index", 3, "answer", 1),
                        Map.of("index", 4, "answer", List.of(0, 1)),
                        Map.of("index", 5, "answer", "minimal tests isolate root causes quickly")
                )
        ));
        assertThat(attemptResp.statusCode()).isEqualTo(200);
        Map<String, Object> score = (Map<String, Object>) parseMap(attemptResp.body()).get("score");
        assertThat(score.get("total")).isEqualTo(5);
        assertThat(score.get("correct")).isEqualTo(5);
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

    private Map<String, Object> parseMap(String body) throws Exception {
        return objectMapper.readValue(body, new TypeReference<>() {});
    }

    private String extractCookieValue(List<String> setCookieHeaders, String name) {
        for (String h : setCookieHeaders) {
            if (h.startsWith(name + "=")) {
                int end = h.indexOf(';');
                return end > 0 ? h.substring(name.length() + 1, end) : h.substring(name.length() + 1);
            }
        }
        return "";
    }
}
