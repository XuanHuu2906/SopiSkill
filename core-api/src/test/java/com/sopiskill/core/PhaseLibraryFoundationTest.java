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
import java.util.LinkedHashMap;
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
 * Library Foundation Integration Gate Tests (Phases L1, L2, L3, L4, L5):
 *  1. HMAC-signed idempotent `/internal/library/sources/upsert` (Run 1 inserts, Run 2 skips).
 *  2. Pedagogical Ranking on `/v1/sources/discover` & `/v1/courses/{id}/research-runs`:
 *     Vietnamese beginner query selects Tier-1 OpenStax textbook and excludes narrow Tier-3 arXiv paper.
 *  3. Cross-tenant & Public Library protection: user cannot delete public books (404) or link another user's private source (404).
 *  4. Server-authoritative `lesson-ready` citations: accepts linked sourceId, silently rejects foreign sourceId,
 *     and returns Open-License `attributions[]` with 0 answer keys on `GET /v1/lessons/{id}`.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:library",
        "sopiskill.rate-limit-enabled=false"
})
class PhaseLibraryFoundationTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcClient jdbc;

    @Autowired
    private InternalHmacSigner signer;

    private final HttpClient http = HttpClient.newHttpClient();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    @SuppressWarnings("unchecked")
    void publicLibraryUpsertRankingTenantIsolationCitationsAndAttribution() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        String t1Key = "openstax:test-py-" + suffix;
        String t3Key = "arxiv:test-py-narrow-" + suffix;

        UUID userAUuid = null;
        UUID userBUuid = null;
        UUID pubT1Uuid = null;
        UUID pubT3Uuid = null;

        try {
            // 1. Upsert Tier-1 OpenStax Python textbook + Tier-3 arXiv narrow paper via HMAC endpoint
            Map<String, Object> t1Body = new LinkedHashMap<>();
            t1Body.put("externalKey", t1Key);
            t1Body.put("sourceType", "open_textbook");
            t1Body.put("title", "Introduction to Python Programming " + suffix);
            t1Body.put("canonicalUrl", "https://openstax.org/details/books/introduction-python-programming");
            t1Body.put("author", "Udayan Das, Aubrey Lawson");
            t1Body.put("publisher", "OpenStax");
            t1Body.put("language", "en");
            t1Body.put("licenseInfo", "CC BY 4.0");
            t1Body.put("contentHash", "hash-t1-" + suffix);
            t1Body.put("domainSlug", "computer-science");
            t1Body.put("pedagogyTier", "tier1_textbook");
            t1Body.put("commercialSafe", true);
            t1Body.put("pipelineVersion", "md-heading-v1");
            t1Body.put("chunkCount", 42);
            t1Body.put("brief", Map.of(
                    "what", "Introductory Python programming textbook covering variables, loops, and functions.",
                    "claims", List.of("Python uses dynamic typing."),
                    "sections", List.of(Map.of("anchor", "ch1-intro", "heading", "Chapter 1: Python Basics", "gist", "Variables and expressions."))
            ));

            Map<String, Object> upsert1 = postSignedInternal("/internal/library/sources/upsert", t1Body);
            assertThat(upsert1.get("skipped")).isEqualTo(false);
            String pubT1Id = String.valueOf(upsert1.get("sourceId"));
            pubT1Uuid = IdCodec.parse(pubT1Id, "src");

            // Idempotent re-upsert with identical hash + pipelineVersion -> MUST skip!
            Map<String, Object> upsert1Again = postSignedInternal("/internal/library/sources/upsert", t1Body);
            assertThat(upsert1Again.get("skipped")).isEqualTo(true);

            Map<String, Object> t3Body = new LinkedHashMap<>();
            t3Body.put("externalKey", t3Key);
            t3Body.put("sourceType", "academic_paper");
            t3Body.put("title", "Formal Coq Verification of Python Tensor Compilers " + suffix);
            t3Body.put("canonicalUrl", "https://arxiv.org/abs/2401.99999");
            t3Body.put("language", "en");
            t3Body.put("licenseInfo", "arXiv.org Open Access License");
            t3Body.put("contentHash", "hash-t3-" + suffix);
            t3Body.put("domainSlug", "computer-science");
            t3Body.put("pedagogyTier", "tier3_paper");
            t3Body.put("commercialSafe", false);
            t3Body.put("pipelineVersion", "md-heading-v1");
            t3Body.put("chunkCount", 8);
            Map<String, Object> upsert3 = postSignedInternal("/internal/library/sources/upsert", t3Body);
            String pubT3Id = String.valueOf(upsert3.get("sourceId"));
            pubT3Uuid = IdCodec.parse(pubT3Id, "src");

            // 2. Register User A & User B
            var regA = register("lib-a-" + suffix + "@sopi.test", "StrongPass99!");
            var regB = register("lib-b-" + suffix + "@sopi.test", "StrongPass99!");
            userAUuid = IdCodec.parse(regA.get("userId"), "usr");
            userBUuid = IdCodec.parse(regB.get("userId"), "usr");
            String cookieA = regA.get("cookie");
            String csrfA = regA.get("csrf");
            String cookieB = regB.get("cookie");
            String csrfB = regB.get("csrf");

            // 3. Gate L4: Vietnamese beginner query discovers Tier-1 OpenStax and EXCLUDES Tier-3 arXiv paper!
            HttpResponse<String> discResp = getAuthed("/v1/sources/discover?q=H%E1%BB%8Dc+l%E1%BA%ADp+tr%C3%ACnh+Python+" + suffix + "&level=beginner", cookieA);
            assertThat(discResp.statusCode()).isEqualTo(200);
            Map<String, Object> discMap = parseJson(discResp.body());
            List<Map<String, Object>> discItems = (List<Map<String, Object>>) discMap.get("items");
            assertThat(discItems).anyMatch(it -> pubT1Id.equals(it.get("id")));
            assertThat(discItems).noneMatch(it -> pubT3Id.equals(it.get("id")));

            // 4. Gate L2: User A cannot delete system public textbook -> 404
            HttpResponse<String> delPub = deleteAuthed("/v1/sources/" + pubT1Id, cookieA, csrfA);
            assertThat(delPub.statusCode()).isEqualTo(404);

            // User A creates a private source; User B attempting to link User A's private source -> 404
            HttpResponse<String> privResp = postAuthed("/v1/sources", Map.of("title", "Private Notes A"), cookieA, csrfA);
            assertThat(privResp.statusCode()).isEqualTo(201);
            String privAId = String.valueOf(parseJson(privResp.body()).get("id"));

            HttpResponse<String> crsBResp = postAuthed("/v1/courses", Map.of("topic", "Python Basics " + suffix, "language", "vi"), cookieB, csrfB);
            assertThat(crsBResp.statusCode()).isEqualTo(201);
            String courseBId = String.valueOf(parseJson(crsBResp.body()).get("id"));

            HttpResponse<String> spoofLink = postAuthed("/v1/courses/" + courseBId + "/sources", Map.of("sourceId", privAId), cookieB, csrfB);
            assertThat(spoofLink.statusCode()).isEqualTo(404);

            // 5. Gate L4 + L1: User B runs research-runs -> accepts -> links Tier-1 OpenStax as `primary`
            HttpResponse<String> runResp = postAuthed(
                    "/v1/courses/" + courseBId + "/research-runs",
                    Map.of("maxSources", 2, "learnerLevel", "beginner"),
                    cookieB,
                    csrfB
            );
            assertThat(runResp.statusCode()).isEqualTo(201);
            Map<String, Object> runMap = parseJson(runResp.body());
            String runId = String.valueOf(runMap.get("id"));
            List<Map<String, Object>> runCands = (List<Map<String, Object>>) runMap.get("candidates");
            assertThat(runCands).anyMatch(c -> pubT1Id.equals(c.get("id")));
            assertThat(runCands).noneMatch(c -> pubT3Id.equals(c.get("id")));

            HttpResponse<String> acceptResp = postAuthed("/v1/courses/" + courseBId + "/research-runs/" + runId + "/accept", Map.of(), cookieB, csrfB);
            assertThat(acceptResp.statusCode()).isEqualTo(200);

            // 6. Gate L1 + L5: Seed a lesson + job and send signed `lesson-ready` callback with 1 valid + 1 spoofed citation
            UUID cidUuid = IdCodec.parse(courseBId, "crs");
            UUID unitUuid = UUID.randomUUID();
            UUID lessonUuid = UUID.randomUUID();
            UUID jobUuid = UUID.randomUUID();
            jdbc.sql("INSERT INTO core.units (id, course_id, order_index, title) VALUES (:id, :cid, 0, 'Unit 1')")
                    .param("id", unitUuid).param("cid", cidUuid).update();
            jdbc.sql("INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_json) VALUES (:id, :cid, :uid, 0, 'Python Intro', 'queued', '[]'::jsonb)")
                    .param("id", lessonUuid).param("cid", cidUuid).param("uid", unitUuid).update();
            jdbc.sql("INSERT INTO core.generation_jobs (id, course_id, idempotency_key, status, stage, lessons_done, lessons_total, attempts, dispatched) VALUES (:jid, :cid, :idem, 'queued', 'lessons', 0, 1, 1, TRUE)")
                    .param("jid", jobUuid).param("cid", cidUuid).param("idem", "idem-lib-" + suffix).update();

            Map<String, Object> cbBody = new LinkedHashMap<>();
            cbBody.put("jobId", IdCodec.format("job", jobUuid));
            cbBody.put("courseId", courseBId);
            cbBody.put("lessonId", IdCodec.format("lsn", lessonUuid));
            cbBody.put("lessonOrder", 0);
            cbBody.put("status", "ready");
            cbBody.put("grounding", "source_grounded");
            cbBody.put("content", Map.of(
                    "title", "Python Variables",
                    "blocks", List.of(
                            Map.of("type", "teach", "title", "Variables", "paragraphs", List.of("Python binds variable names dynamically.")),
                            Map.of("type", "mc", "question", "Is Python dynamically typed?", "options", List.of("Yes", "No"), "answerIndex", 0)
                    )
            ));
            cbBody.put("citations", List.of(
                    Map.of("chunkId", "chk_valid_1", "sourceId", pubT1Id, "pageNumber", 15, "sectionAnchor", "ch1-intro", "evidenceText", "Python uses dynamic typing.", "validationStatus", "locator_verified"),
                    // Foreign unlinked sourceId -> MUST be rejected silently by server!
                    Map.of("chunkId", "chk_spoof_2", "sourceId", privAId, "pageNumber", 1, "sectionAnchor", "secret", "evidenceText", "Stolen!", "validationStatus", "locator_verified")
            ));

            Map<String, Object> cbResp = postSignedInternal("/internal/jobs/" + IdCodec.format("job", jobUuid) + "/lesson-ready", cbBody);
            assertThat(cbResp.get("accepted")).isEqualTo(true);

            // Verify GET /v1/lessons/{id}: 0 answer keys, ONLY valid citation saved, AND OpenStax CC BY attribution present!
            HttpResponse<String> lessonResp = getAuthed("/v1/lessons/" + IdCodec.format("lsn", lessonUuid), cookieB);
            assertThat(lessonResp.statusCode()).isEqualTo(200);
            String rawLesson = lessonResp.body();
            assertThat(rawLesson).doesNotContain("answerIndex");
            assertThat(rawLesson).doesNotContain("acceptedAnswers");
            assertThat(rawLesson).doesNotContain("chk_spoof_2");

            Map<String, Object> lessonMap = parseJson(rawLesson);
            assertThat(lessonMap.get("grounding")).isEqualTo("source_grounded");
            List<Map<String, Object>> savedCits = (List<Map<String, Object>>) lessonMap.get("citations");
            assertThat(savedCits).hasSize(1);
            assertThat(savedCits.get(0).get("sourceId")).isEqualTo(pubT1Id);
            assertThat(savedCits.get(0).get("validationStatus")).isEqualTo("locator_verified");

            List<Map<String, Object>> attrs = (List<Map<String, Object>>) lessonMap.get("attributions");
            assertThat(attrs).isNotEmpty();
            assertThat(attrs).anyMatch(a ->
                    pubT1Id.equals(a.get("sourceId"))
                            && String.valueOf(a.get("attributionText")).contains("OpenStax")
                            && String.valueOf(a.get("attributionText")).contains("CC BY 4.0")
                            && String.valueOf(a.get("attributionText")).contains("openstax.org")
            );
        } finally {
            if (userAUuid != null) jdbc.sql("DELETE FROM core.users WHERE id = :id").param("id", userAUuid).update();
            if (userBUuid != null) jdbc.sql("DELETE FROM core.users WHERE id = :id").param("id", userBUuid).update();
            if (pubT1Uuid != null) jdbc.sql("DELETE FROM core.sources WHERE id = :id").param("id", pubT1Uuid).update();
            if (pubT3Uuid != null) jdbc.sql("DELETE FROM core.sources WHERE id = :id").param("id", pubT3Uuid).update();
        }
    }

    private Map<String, Object> postSignedInternal(String path, Map<String, Object> payload) throws Exception {
        byte[] raw = objectMapper.writeValueAsBytes(payload);
        Map<String, String> signed = signer.signHeaders("POST", path, raw, "cor_test_" + UUID.randomUUID().toString().substring(0, 8));
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url(path)))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(raw));
        signed.forEach(b::header);
        HttpResponse<String> resp = http.send(b.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        assertThat(resp.statusCode()).withFailMessage("Expected 2xx for %s, got %d: %s", path, resp.statusCode(), resp.body()).isBetween(200, 299);
        return parseJson(resp.body());
    }

    private Map<String, String> register(String email, String password) throws Exception {
        byte[] body = objectMapper.writeValueAsBytes(Map.of("email", email, "password", password, "displayName", "Lib Tester"));
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder(URI.create(url("/v1/auth/register")))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8)
        );
        assertThat(resp.statusCode()).isEqualTo(201);
        List<String> setCookies = resp.headers().allValues("set-cookie");
        String cookieHeader = setCookies.stream().map(c -> c.split(";", 2)[0]).reduce((a, b) -> a + "; " + b).orElse("");
        String csrf = setCookies.stream()
                .map(c -> c.split(";", 2)[0])
                .filter(c -> c.startsWith("csrf_token="))
                .map(c -> c.substring("csrf_token=".length()))
                .findFirst().orElse("");
        Map<String, Object> json = parseJson(resp.body());
        @SuppressWarnings("unchecked")
        Map<String, Object> user = (Map<String, Object>) json.get("user");
        String userId = String.valueOf(user != null ? user.get("id") : json.get("id"));
        return Map.of("userId", userId, "cookie", cookieHeader, "csrf", csrf);
    }

    private HttpResponse<String> getAuthed(String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path))).header("Cookie", cookie).GET().build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8)
        );
    }

    private HttpResponse<String> postAuthed(String path, Map<String, Object> payload, String cookie, String csrf) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofByteArray(objectMapper.writeValueAsBytes(payload)))
                        .build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8)
        );
    }

    private HttpResponse<String> deleteAuthed(String path, String cookie, String csrf) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .DELETE()
                        .build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8)
        );
    }

    private Map<String, Object> parseJson(String raw) throws Exception {
        return objectMapper.readValue(raw, new TypeReference<>() {});
    }
}
