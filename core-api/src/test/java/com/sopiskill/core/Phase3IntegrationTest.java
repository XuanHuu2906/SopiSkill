package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.internal.InternalHmacSigner;
import com.sopiskill.core.sources.CitationLinkResolver;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
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
 * Phase 3 integration tests against live PostgreSQL 16 + Redis 7 + MinIO (`deploy/docker-compose.yml`):
 *   1. Flyway V2 columns & `core.content_flags`.
 *   2. TopicGuard (`422 TOPIC_REJECTED` on YouTube URL / unsafe / too_vague / too_narrow) + CitationLinkResolver.
 *   3. Presigned PDF upload (`POST /v1/sources/upload` -> direct PUT to MinIO -> `/ingest` -> callback with `brief`).
 *   4. Structured interview chips (`structuredQuestions` with `kind` + `choices`).
 *   5. Lesson-1-First progressive unlock (`/internal/jobs/{id}/lesson-ready` unlocks course immediately,
 *      keeps Lesson 2 in `preparing`, records `content_flags`).
 *   6. `GET /v1/lessons/{id}?prefetch=1` (`Cache-Control: private, max-age=30`), `POST /v1/lessons/{id}/retry`.
 *   7. Idempotent `DELETE /v1/courses/{courseId}`.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:phase3",
        "sopiskill.stream-ingest-key=test:queue:ai:ingest:phase3",
        "sopiskill.rate-limit-enabled=false"
})
class Phase3IntegrationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private InternalHmacSigner hmacSigner;

    @Autowired
    private JdbcClient jdbc;

    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    void citationLinkResolverHandlesArxivWebAndPdf() {
        assertThat(CitationLinkResolver.resolveDeepLink("https://arxiv.org/abs/1706.03762", "sec-attention"))
                .isEqualTo("https://arxiv.org/html/1706.03762#sec-attention");
        assertThat(CitationLinkResolver.resolveDeepLink("https://docs.python.org/3/tutorial/", "lists"))
                .isEqualTo("https://docs.python.org/3/tutorial/#lists");
        assertThat(CitationLinkResolver.resolveDeepLink(null, "p1"))
                .isNull();
    }

    @Test
    @SuppressWarnings("unchecked")
    void phase3EndToEndSourcePresignTopicGuardLesson1FirstAndCourseLifecycle() throws Exception {
        // 1. Register user
        String email = "phase3-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
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
        String cookieHeader = "access_token=" + extractCookieValue(setCookies, "access_token")
                + "; csrf_token=" + extractCookieValue(setCookies, "csrf_token");
        String csrfCookie = extractCookieValue(setCookies, "csrf_token");

        // 2. TopicGuard rejections -> 422 TOPIC_REJECTED across all 4 canonical reasons
        for (String badTopic : List.of(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "https://youtu.be/abc123",
                "how to make a bomb",
                "a",
                "yes",
                "what year was python released"
        )) {
            HttpResponse<String> badResp = postAuthed("/v1/courses", cookieHeader, csrfCookie,
                    Map.of("topic", badTopic, "language", "en"));
            assertThat(badResp.statusCode()).as("Topic should be rejected: " + badTopic).isEqualTo(422);
            assertThat(badResp.body()).contains("TOPIC_REJECTED");
        }

        // 3. Presigned PDF upload -> direct PUT to MinIO -> trigger ingest -> callback with structured brief
        byte[] dummyPdf = "%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n".getBytes(StandardCharsets.UTF_8);
        HttpResponse<String> presignResp = postAuthed("/v1/sources/upload", cookieHeader, csrfCookie, Map.of(
                "filename", "attention_paper.pdf",
                "contentType", "application/pdf",
                "byteSize", dummyPdf.length,
                "title", "Attention Paper"
        ));
        assertThat(presignResp.statusCode()).isEqualTo(201);
        Map<String, Object> presign = parseMap(presignResp.body());
        String sourceId = String.valueOf(presign.get("sourceId"));
        String documentId = String.valueOf(presign.get("documentId"));
        String uploadUrl = String.valueOf(presign.get("uploadUrl"));
        assertThat(uploadUrl).contains("X-Amz-Signature=");

        HttpResponse<Void> minioPut = http.send(
                HttpRequest.newBuilder(URI.create(uploadUrl))
                        .PUT(HttpRequest.BodyPublishers.ofByteArray(dummyPdf))
                        .build(),
                HttpResponse.BodyHandlers.discarding()
        );
        assertThat(minioPut.statusCode()).isEqualTo(200);

        HttpResponse<String> ingestResp = postAuthed("/v1/sources/" + sourceId + "/ingest", cookieHeader, csrfCookie,
                Map.of("documentId", documentId));
        assertThat(ingestResp.statusCode()).isEqualTo(202);

        // Simulate HMAC-signed ai-worker-ingest callback with structured brief
        Map<String, Object> briefPayload = Map.of(
                "what", "Explains the Transformer architecture based on self-attention.",
                "claims", List.of("Self-attention replaces recurrence for parallel sequence modeling."),
                "notation", List.of("Q, K, V", "d_k"),
                "assumes", List.of("Matrix multiplication"),
                "sections", List.of(Map.of("anchor", "sec-1", "heading", "Introduction", "gist", "Overview of attention"))
        );
        Map<String, Object> srcCbBody = Map.of(
                "documentId", documentId,
                "status", "ready",
                "chunkCount", 3,
                "pipelineVersion", "pypdf-v1",
                "brief", briefPayload,
                "wordCount", 420,
                "durationMinutes", 3,
                "suggestedTopic", "Transformer Attention"
        );
        HttpResponse<String> srcCbResp = postSignedInternal("/internal/sources/" + sourceId + "/complete", srcCbBody);
        assertThat(srcCbResp.statusCode()).isEqualTo(200);

        HttpResponse<String> srcGetResp = getAuthed("/v1/sources/" + sourceId, cookieHeader);
        assertThat(srcGetResp.statusCode()).isEqualTo(200);
        Map<String, Object> srcGet = parseMap(srcGetResp.body());
        assertThat(srcGet.get("suggestedTopic")).isEqualTo("Transformer Attention");
        assertThat(srcGet.get("wordCount")).isEqualTo(420);
        assertThat(srcGet.get("durationMinutes")).isEqualTo(3);
        assertThat((Map<String, Object>) srcGet.get("brief")).containsKey("claims");

        // 4. Create course linked to source -> check structuredQuestions with chips
        HttpResponse<String> createCourse = postAuthed("/v1/courses", cookieHeader, csrfCookie,
                Map.of("topic", "Transformer Attention", "language", "en", "sourceId", sourceId));
        assertThat(createCourse.statusCode()).isEqualTo(201);
        String courseId = String.valueOf(parseMap(createCourse.body()).get("id"));

        HttpResponse<String> interviewResp = getAuthed("/v1/courses/" + courseId + "/interview", cookieHeader);
        assertThat(interviewResp.statusCode()).isEqualTo(200);
        Map<String, Object> interviewJson = parseMap(interviewResp.body());
        List<Map<String, Object>> structuredQs = (List<Map<String, Object>>) interviewJson.get("structuredQuestions");
        assertThat(structuredQs).hasSize(5);
        assertThat((List<?>) structuredQs.get(0).get("choices")).isNotEmpty();

        for (int pos = 0; pos < 5; pos++) {
            HttpResponse<String> ansResp = postAuthed("/v1/courses/" + courseId + "/interview/answer",
                    cookieHeader, csrfCookie, Map.of("position", pos, "answer", "Intermediate learner."));
            assertThat(ansResp.statusCode()).isEqualTo(200);
            Map<String, Object> ansJson = parseMap(ansResp.body());
            assertThat((List<String>) ansJson.get("answers")).hasSize(pos + 1);
            assertThat(((List<String>) ansJson.get("answers")).get(pos)).isEqualTo("Intermediate learner.");
        }

        // 5. Approve course -> get ordered lesson IDs -> simulate Lesson-1-First callback ONLY for Lesson 1
        HttpResponse<String> approveResp = postAuthed("/v1/courses/" + courseId + "/approve",
                cookieHeader, csrfCookie, Map.of());
        assertThat(approveResp.statusCode()).isEqualTo(200);
        String jobId = String.valueOf(parseMap(approveResp.body()).get("jobId"));

        UUID courseUuid = IdCodec.parse(courseId, "crs");
        List<UUID> orderedLessons = jdbc.sql("""
                SELECT l.id FROM core.lessons l
                JOIN core.units u ON u.id = l.unit_id
                WHERE l.course_id = :cid
                ORDER BY u.order_index ASC, l.order_index ASC
                """).param("cid", courseUuid).query(UUID.class).list();
        assertThat(orderedLessons.size()).isGreaterThanOrEqualTo(2);

        String lesson1Id = IdCodec.format("lsn", orderedLessons.get(0));
        String lesson2Id = IdCodec.format("lsn", orderedLessons.get(1));

        List<Map<String, Object>> l1Blocks = List.of(
                Map.of("type", "teach", "heading", "Self-Attention", "body", "Attention weights relate all token positions directly."),
                Map.of("type", "mc", "prompt", "What stabilizes dot products?", "options", List.of("Scaling by sqrt(d_k)", "Dropout only"), "answerIndex", 0, "explain", "Scaling prevents large softmax inputs.")
        );
        HttpResponse<String> l1Cb = postSignedInternal("/internal/jobs/" + jobId + "/lesson-ready", Map.of(
                "courseId", courseId,
                "lessonId", lesson1Id,
                "lessonOrder", 0,
                "status", "ready",
                "estimatedMinutes", 6,
                "content", Map.of("title", "Lesson 1: Self-Attention", "blocks", l1Blocks),
                "contentFlags", List.of(Map.of(
                        "blockIndex", 0,
                        "source", "validator",
                        "code", "TEACH_TOO_SHORT",
                        "severity", "warning",
                        "details", "Teach block brief"
                ))
        ));
        assertThat(l1Cb.statusCode()).isEqualTo(200);

        // Verify course is ALREADY ready while Lesson 2 is still `preparing`
        HttpResponse<String> pathResp = getAuthed("/v1/courses/" + courseId + "/path", cookieHeader);
        assertThat(pathResp.statusCode()).isEqualTo(200);
        Map<String, Object> pathJson = parseMap(pathResp.body());
        assertThat(pathJson.get("status")).isEqualTo("ready");
        assertThat(pathJson.get("hasPreparingLessons")).isEqualTo(true);
        List<Map<String, Object>> units = (List<Map<String, Object>>) pathJson.get("units");
        List<Map<String, Object>> unit0Lessons = (List<Map<String, Object>>) units.get(0).get("lessons");
        assertThat(unit0Lessons.get(0).get("state")).isEqualTo("next");
        assertThat(unit0Lessons.get(0).get("estimatedMinutes")).isEqualTo(6);
        assertThat(unit0Lessons.get(1).get("state")).isEqualTo("preparing");

        // Verify content_flags persisted in PostgreSQL
        int flagCount = jdbc.sql("SELECT COUNT(*) FROM core.content_flags WHERE course_id = :cid AND code = 'TEACH_TOO_SHORT'")
                .param("cid", courseUuid).query(Integer.class).single();
        assertThat(flagCount).isEqualTo(1);

        // 6. Prefetch lesson + verify Cache-Control + 0 leaked answer keys
        HttpResponse<String> prefetchResp = getAuthed("/v1/lessons/" + lesson1Id + "?prefetch=1", cookieHeader);
        assertThat(prefetchResp.statusCode()).isEqualTo(200);
        assertThat(prefetchResp.headers().firstValue("cache-control").orElse("")).contains("max-age=30");
        assertThat(prefetchResp.body()).doesNotContain("answerIndex");

        // Mark Lesson 2 failed and test POST /v1/lessons/{id}/retry -> 202
        jdbc.sql("UPDATE core.lessons SET status = 'failed' WHERE id = :lid")
                .param("lid", orderedLessons.get(1)).update();
        HttpResponse<String> retryLessonResp = postAuthed("/v1/lessons/" + lesson2Id + "/retry",
                cookieHeader, csrfCookie, Map.of());
        assertThat(retryLessonResp.statusCode()).isEqualTo(200);
        assertThat(parseMap(retryLessonResp.body()).get("status")).isEqualTo("queued");

        // 7. DELETE /v1/courses/{courseId} -> 204 and idempotent second call -> 204
        HttpResponse<String> del1 = deleteAuthed("/v1/courses/" + courseId, cookieHeader, csrfCookie);
        assertThat(del1.statusCode()).isEqualTo(204);
        HttpResponse<String> del2 = deleteAuthed("/v1/courses/" + courseId, cookieHeader, csrfCookie);
        assertThat(del2.statusCode()).isEqualTo(204);
        HttpResponse<String> afterDel = getAuthed("/v1/courses/" + courseId, cookieHeader);
        assertThat(afterDel.statusCode()).isEqualTo(404);
    }

    private HttpResponse<String> getAuthed(String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Cookie", cookie)
                        .GET()
                        .build(),
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

    private HttpResponse<String> deleteAuthed(String path, String cookie, String csrf) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .DELETE()
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> postSignedInternal(String path, Object bodyObj) throws Exception {
        byte[] raw = objectMapper.writeValueAsBytes(bodyObj);
        Map<String, String> headers = hmacSigner.signHeaders("POST", path, raw, "cor_p3_test");
        HttpRequest.Builder req = HttpRequest.newBuilder(URI.create(url(path)))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(raw));
        headers.forEach(req::header);
        return http.send(req.build(), HttpResponse.BodyHandlers.ofString());
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
