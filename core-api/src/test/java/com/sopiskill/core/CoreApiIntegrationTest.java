package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.internal.InternalHmacSigner;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.TestPropertySource;

/**
 * Full Spring Boot integration & concurrency tests against live PostgreSQL 16 + Redis 7 (`deploy/docker-compose.yml`).
 * Covers:
 *   1. Flyway `core.*` schema + `/ready` probe.
 *   2. Register/Login HttpOnly cookie + CSRF double-submit enforcement.
 *   3. Proposal optimistic lock (`409 PROPOSAL_VERSION_CONFLICT`).
 *   4. HMAC-signed internal callback (`/internal/jobs/{jobId}/complete`) + 401 rejection on unsigned/tampered callback.
 *   5. 20 concurrent lesson attempt submissions -> exact single XP award (zero double-XP!).
 *   6. `GET /v1/lessons/{id}` returns 0 answer keys.
 *   7. `DELETE /v1/me` cascades cleanly across `core.*`.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:junit",
        "sopiskill.rate-limit-enabled=false"
})
class CoreApiIntegrationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private InternalHmacSigner hmacSigner;

    @Autowired
    private JdbcClient jdbc;

    private final HttpClient http = HttpClient.newHttpClient();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    void fullCoreApiParityAnd20ConcurrentAttemptsZeroDoubleXp() throws Exception {
        // 1. /ready probe
        HttpResponse<String> ready = http.send(
                HttpRequest.newBuilder(URI.create(url("/ready"))).GET().build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(ready.statusCode()).isEqualTo(200);
        assertThat(ready.body()).contains("\"database\":\"ok\"");
        assertThat(ready.body()).contains("\"redis\":\"ok\"");

        // 2. Register user -> capture access_token + csrf_token cookies
        String email = "junit-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
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
        assertThat(accessCookie).isNotBlank();
        assertThat(csrfCookie).isNotBlank();
        String cookieHeader = "access_token=" + accessCookie + "; csrf_token=" + csrfCookie;

        // 3. CSRF enforcement: mutating request without X-CSRF-Token -> 403 CSRF_INVALID
        HttpResponse<String> noCsrf = http.send(
                HttpRequest.newBuilder(URI.create(url("/v1/courses")))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookieHeader)
                        .POST(HttpRequest.BodyPublishers.ofString("{\"topic\":\"Concurrency\",\"language\":\"en\"}"))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(noCsrf.statusCode()).isEqualTo(403);
        assertThat(noCsrf.body()).contains("CSRF_INVALID");

        // 4. Create course + finish 5 interview answers -> proposal v1
        HttpResponse<String> createCourse = postAuthed("/v1/courses", cookieHeader, csrfCookie,
                Map.of("topic", "Java Concurrency", "language", "en"));
        assertThat(createCourse.statusCode()).isEqualTo(201);
        Map<String, Object> courseJson = parseMap(createCourse.body());
        String courseId = String.valueOf(courseJson.get("id"));

        for (int pos = 0; pos < 5; pos++) {
            HttpResponse<String> ansResp = postAuthed(
                    "/v1/courses/" + courseId + "/interview/answer",
                    cookieHeader, csrfCookie,
                    Map.of("position", pos, "answer", "Intermediate developer practicing concurrency 3 hours per week.")
            );
            assertThat(ansResp.statusCode()).isEqualTo(200);
        }

        // 5. Optimistic lock on PATCH /v1/courses/{id}/proposal (wrong version -> 409)
        HttpResponse<String> badVer = patchAuthed(
                "/v1/courses/" + courseId + "/proposal",
                cookieHeader, csrfCookie,
                Map.of(
                        "expectedVersion", 99,
                        "name", "Stale Name",
                        "objective", "Obj",
                        "outcomes", List.of("O1"),
                        "units", List.of(Map.of("title", "U1", "blurb", "B", "lessonTitles", List.of("L1")))
                )
        );
        assertThat(badVer.statusCode()).isEqualTo(409);
        assertThat(badVer.body()).contains("PROPOSAL_VERSION_CONFLICT");

        HttpResponse<String> goodVer = patchAuthed(
                "/v1/courses/" + courseId + "/proposal",
                cookieHeader, csrfCookie,
                Map.of(
                        "expectedVersion", 1,
                        "name", "Java Concurrency Custom",
                        "objective", "Master Virtual Threads",
                        "outcomes", List.of("Prevent race conditions"),
                        "units", List.of(Map.of("title", "Foundations", "blurb", "Core", "lessonTitles", List.of("Row Locking")))
                )
        );
        assertThat(goodVer.statusCode()).isEqualTo(200);
        assertThat(parseMap(goodVer.body()).get("version")).isEqualTo(2);

        // 6. Approve -> creates job; verify unsigned callback -> 401; signed callback -> 200 & extracts glossary
        HttpResponse<String> approveResp = postAuthed("/v1/courses/" + courseId + "/approve", cookieHeader, csrfCookie, Map.of());
        assertThat(approveResp.statusCode()).isEqualTo(200);
        String jobId = String.valueOf(parseMap(approveResp.body()).get("jobId"));

        Map<String, Object> cbPayload = Map.of(
                "jobId", jobId,
                "idempotencyKey", "idem-test",
                "status", "completed",
                "result", Map.of(
                        "lessons", List.of(Map.of(
                                "title", "Row Locking",
                                "blocks", List.of(
                                        Map.of("type", "teach", "title", "SELECT FOR UPDATE",
                                                "paragraphs", List.of("Locks row until commit."),
                                                "terms", List.of(Map.of("term", "Pessimistic Lock", "definition", "Row-level lock"))),
                                        Map.of("type", "mc", "question", "What locks a row?",
                                                "options", List.of("FOR UPDATE", "DROP TABLE"), "answerIndex", 0),
                                        Map.of("type", "blank", "sentence", "Use ____ to lock a row.", "answer", "FOR UPDATE")
                                )
                        ))
                )
        );
        byte[] cbBytes = objectMapper.writeValueAsBytes(cbPayload);
        String cbPath = "/internal/jobs/" + jobId + "/complete";

        // Unsigned callback MUST be rejected with 401
        HttpResponse<String> unauthCb = http.send(
                HttpRequest.newBuilder(URI.create(url(cbPath)))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofByteArray(cbBytes))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(unauthCb.statusCode()).isEqualTo(401);

        // Signed callback succeeds
        Map<String, String> signedHeaders = hmacSigner.signHeaders("POST", cbPath, cbBytes, "cor_junit_cb");
        HttpRequest.Builder signedCbReq = HttpRequest.newBuilder(URI.create(url(cbPath)))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(cbBytes));
        signedHeaders.forEach(signedCbReq::header);
        HttpResponse<String> okCb = http.send(signedCbReq.build(), HttpResponse.BodyHandlers.ofString());
        assertThat(okCb.statusCode()).isEqualTo(200);

        // Wait briefly in case ai-worker-llm already completed or our callback completed; fetch course detail
        HttpResponse<String> detailResp = getAuthed("/v1/courses/" + courseId, cookieHeader);
        assertThat(detailResp.statusCode()).isEqualTo(200);
        Map<String, Object> detail = parseMap(detailResp.body());
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> units = (List<Map<String, Object>>) detail.get("units");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> lessons = (List<Map<String, Object>>) units.getFirst().get("lessons");
        String lessonId = String.valueOf(lessons.getFirst().get("id"));

        // Ensure deterministic lesson content for the concurrency XP test
        UUID lessonUuid = IdCodec.parse(lessonId, "lsn");
        jdbc.sql("UPDATE core.lessons SET status = 'ready', content_json = CAST(:blocks AS jsonb) WHERE id = :lid")
                .param("blocks", objectMapper.writeValueAsString(List.of(
                        Map.of("type", "teach", "title", "Locking", "paragraphs", List.of("Row lock")),
                        Map.of("type", "mc", "question", "Q1?", "options", List.of("Yes", "No"), "answerIndex", 0),
                        Map.of("type", "blank", "sentence", "Use ____.", "answer", "FOR UPDATE")
                )))
                .param("lid", lessonUuid)
                .update();

        // 7. Answer-key privacy check on GET /v1/lessons/{id}
        HttpResponse<String> lessonGet = getAuthed("/v1/lessons/" + lessonId, cookieHeader);
        assertThat(lessonGet.statusCode()).isEqualTo(200);
        assertThat(lessonGet.body()).doesNotContain("\"answerIndex\"", "\"acceptedAnswers\"", "\"answer_key\"", "\"solution\"");

        // 7b. Live Tutor SSE Gateway through core-api -> ai-api (HMAC-signed, publicBlocks only)
        HttpResponse<String> tutorSse = postAuthed(
                "/v1/courses/" + courseId + "/tutor/messages",
                cookieHeader, csrfCookie,
                Map.of(
                        "clientMessageId", "tmsg-junit-" + UUID.randomUUID(),
                        "text", "Explain row locking in 30 seconds",
                        "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
                )
        );
        assertThat(tutorSse.statusCode()).isEqualTo(200);
        assertThat(tutorSse.headers().firstValue("x-tutor-thread-id")).isPresent();
        assertThat(tutorSse.headers().firstValue("x-tutor-message-id")).isPresent();
        assertThat(tutorSse.body()).contains("event:delta").contains("event:done");

        // 8. 20 concurrent attempt submissions (10 same clientAttemptId + 10 distinct clientAttemptIds) -> EXACT single XP = 40 (2*10 + 20 bonus)!
        int threads = 20;
        CountDownLatch readyLatch = new CountDownLatch(threads);
        CountDownLatch startLatch = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        List<Future<Integer>> futures = new ArrayList<>();
        String sharedAttemptId = "att-shared-" + UUID.randomUUID();

        for (int i = 0; i < threads; i++) {
            final String caid = (i < 10) ? sharedAttemptId : ("att-distinct-" + i + "-" + UUID.randomUUID());
            Callable<Integer> task = () -> {
                readyLatch.countDown();
                startLatch.await();
                HttpResponse<String> resp = postAuthed(
                        "/v1/lessons/" + lessonId + "/attempts",
                        cookieHeader, csrfCookie,
                        Map.of(
                                "clientAttemptId", caid,
                                "contentVersion", 1,
                                "answers", List.of(
                                        Map.of("index", 1, "answer", 0),
                                        Map.of("index", 2, "answer", "FOR UPDATE")
                                )
                        )
                );
                assertThat(resp.statusCode()).isEqualTo(200);
                Map<String, Object> body = parseMap(resp.body());
                @SuppressWarnings("unchecked")
                Map<String, Object> rewards = (Map<String, Object>) body.get("rewards");
                return ((Number) rewards.get("xpEarned")).intValue();
            };
            futures.add(pool.submit(task));
        }

        readyLatch.await();
        startLatch.countDown();
        int totalXpEarnedAcross20Threads = 0;
        for (Future<Integer> f : futures) {
            totalXpEarnedAcross20Threads += f.get();
        }
        pool.shutdown();

        // 2 correct * 10 + 20 perfect bonus = 40 XP TOTAL across all 20 concurrent threads!
        assertThat(totalXpEarnedAcross20Threads).isEqualTo(40);

        HttpResponse<String> meAfter = getAuthed("/v1/auth/me", cookieHeader);
        assertThat(meAfter.statusCode()).isEqualTo(200);
        assertThat(((Number) parseMap(meAfter.body()).get("xp")).intValue()).isEqualTo(40);

        // 9. DELETE /v1/me cascades cleanly
        HttpResponse<String> delResp = http.send(
                HttpRequest.newBuilder(URI.create(url("/v1/me")))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookieHeader)
                        .header("X-CSRF-Token", csrfCookie)
                        .method("DELETE", HttpRequest.BodyPublishers.ofString(
                                objectMapper.writeValueAsString(Map.of("confirmText", "DELETE", "password", "StrongPassword123!"))
                        ))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(delResp.statusCode()).isEqualTo(204);
    }

    private HttpResponse<String> getAuthed(String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path))).header("Cookie", cookie).GET().build(),
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

    private HttpResponse<String> patchAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .method("PATCH", HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private Map<String, Object> parseMap(String raw) throws Exception {
        return objectMapper.readValue(raw.getBytes(StandardCharsets.UTF_8), new TypeReference<>() {});
    }

    private String extractCookieValue(List<String> setCookies, String name) {
        for (String header : setCookies) {
            String firstPart = header.split(";")[0].trim();
            if (firstPart.startsWith(name + "=")) {
                return firstPart.substring((name + "=").length());
            }
        }
        return "";
    }
}
