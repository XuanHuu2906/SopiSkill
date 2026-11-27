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
 * Phase 10A Integration Gate Tests:
 *  1. Flyway V8 (`core.lesson_reels`, `core.media_calls`, `core.lessons.reel_manifest`).
 *  2. HMAC-signed `/internal/jobs/{jobId}/lesson-ready` persists `reelManifest` + `mediaCalls`,
 *     defensively strips any injected answer-key fields (`answerIndex`, `solution`).
 *  3. `GET /v1/lessons/{lessonId}` returns `reel` with ZERO answer keys.
 *  4. `GET /v1/lessons/{lessonId}/reel/audio/{clipId}` enforces ownership (404 for foreign user),
 *     validates safe filename regex (400 for invalid clip), and verifies clip ownership in `core.media_calls` (404 for unknown clip).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:phase10a",
        "sopiskill.rate-limit-enabled=false",
        "sopiskill.reel-enabled=true"
})
class Phase10AReelEngineTest {

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
    void reelManifestPersistenceZeroAnswerLeakAndAudioOwnershipGuard() throws Exception {
        String suffix = UUID.randomUUID().toString().substring(0, 8);
        UUID userAUuid = null;
        UUID userBUuid = null;

        try {
            var userA = registerAndLogin("reel_a_" + suffix + "@test.local");
            var userB = registerAndLogin("reel_b_" + suffix + "@test.local");
            userAUuid = IdCodec.parse(userA.userId(), "usr");
            userBUuid = IdCodec.parse(userB.userId(), "usr");

            // Create course, unit, lesson, generation_job directly owned by User A
            UUID courseUuid = UUID.randomUUID();
            UUID unitUuid = UUID.randomUUID();
            UUID lessonUuid = UUID.randomUUID();
            UUID jobUuid = UUID.randomUUID();

            jdbc.sql("INSERT INTO core.courses (id, user_id, topic, language, status) VALUES (:cid, :uid, 'Calculus Reel', 'vi', 'generating')")
                    .param("cid", courseUuid).param("uid", userAUuid).update();
            jdbc.sql("INSERT INTO core.units (id, course_id, order_index, title) VALUES (:u, :cid, 0, 'Unit 1')")
                    .param("u", unitUuid).param("cid", courseUuid).update();
            jdbc.sql("INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_version) VALUES (:lid, :cid, :u, 0, 'Lesson 1', 'queued', 1)")
                    .param("lid", lessonUuid).param("cid", courseUuid).param("u", unitUuid).update();
            jdbc.sql("""
                    INSERT INTO core.generation_jobs (id, course_id, idempotency_key, status, stage, lessons_done, lessons_total, attempts, dispatched)
                    VALUES (:jid, :cid, :idem, 'queued', 'lessons', 0, 1, 1, TRUE)
                    """)
                    .param("jid", jobUuid).param("cid", courseUuid).param("idem", "idem_reel_" + suffix).update();

            String courseId = IdCodec.format("crs", courseUuid);
            String lessonId = IdCodec.format("lsn", lessonUuid);
            String jobId = IdCodec.format("job", jobUuid);
            String clipId = "v1_sc_title.wav";
            String objectKey = "reels-audio/" + courseId + "/" + lessonId + "/" + clipId;

            Map<String, Object> reelManifest = new LinkedHashMap<>();
            reelManifest.put("id", "rel_test001");
            reelManifest.put("version", 1);
            reelManifest.put("styleVersion", "v1");
            reelManifest.put("language", "vi");
            reelManifest.put("durationMs", 4200);
            reelManifest.put("scenes", List.of(
                    Map.of(
                            "id", "sc_title",
                            "kind", "title",
                            "title", "Đạo hàm cơ bản",
                            "durationMs", 2200,
                            "answerIndex", 1, // injected answer key MUST be stripped by core-api!
                            "audio", Map.of(
                                    "clipId", clipId,
                                    "url", "/v1/lessons/" + lessonId + "/reel/audio/" + clipId,
                                    "contentType", "audio/wav",
                                    "durationMs", 2200
                            ),
                            "words", List.of(
                                    Map.of("text", "Đạo", "startMs", 60, "endMs", 420),
                                    Map.of("text", "hàm", "startMs", 420, "endMs", 880)
                            ),
                            "beats", List.of(
                                    Map.of("index", 0, "say", "Đạo hàm", "startMs", 0, "endMs", 2200, "cues", List.of(Map.of("verb", "rise", "target", "title")))
                            )
                    ),
                    Map.of(
                            "id", "sc_ready",
                            "kind", "ready",
                            "title", "Bắt đầu luyện tập",
                            "durationMs", 2000,
                            "solution", Map.of("secret", "hidden"), // injected solution MUST be stripped!
                            "words", List.of(),
                            "beats", List.of()
                    )
            ));

            Map<String, Object> cbPayload = new LinkedHashMap<>();
            cbPayload.put("jobId", jobId);
            cbPayload.put("idempotencyKey", "idem_reel_" + suffix + ":lesson:0");
            cbPayload.put("courseId", courseId);
            cbPayload.put("lessonId", lessonId);
            cbPayload.put("lessonOrder", 0);
            cbPayload.put("status", "ready");
            cbPayload.put("estimatedMinutes", 5);
            cbPayload.put("content", Map.of(
                    "title", "Bài 1: Đạo hàm cơ bản",
                    "blocks", List.of(
                            Map.of("type", "teach", "title", "Khái niệm", "paragraphs", List.of("Đạo hàm là độ dốc tiếp tuyến.")),
                            Map.of("type", "mc", "question", "Đạo hàm của x^2?", "options", List.of("x", "2x", "x^2"), "answerIndex", 1)
                    )
            ));
            cbPayload.put("reelManifest", reelManifest);
            cbPayload.put("mediaCalls", List.of(
                    Map.of(
                            "id", "mdc_test001",
                            "kind", "reel_tts",
                            "provider", "mock",
                            "voice", "mock:vi-VN-HoaiMyNeural",
                            "clipId", clipId,
                            "objectKey", objectKey,
                            "contentType", "audio/wav",
                            "byteSize", 35244,
                            "durationMs", 2200,
                            "status", "ready"
                    )
            ));

            Map<String, Object> cbResp = postSignedInternal("/internal/jobs/" + jobId + "/lesson-ready", cbPayload);
            assertThat(cbResp.get("accepted")).isEqualTo(true);

            // Verify Flyway V8 tables populated
            Integer reelRows = jdbc.sql("SELECT COUNT(*) FROM core.lesson_reels WHERE lesson_id = :lid")
                    .param("lid", lessonUuid).query(Integer.class).single();
            Integer mediaRows = jdbc.sql("SELECT COUNT(*) FROM core.media_calls WHERE lesson_id = :lid")
                    .param("lid", lessonUuid).query(Integer.class).single();
            assertThat(reelRows).isEqualTo(1);
            assertThat(mediaRows).isEqualTo(1);

            // User A fetches GET /v1/lessons/{id} -> receives reel with ZERO answer keys!
            HttpResponse<String> lessonResp = http.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create(url("/v1/lessons/" + lessonId)))
                            .header("Cookie", userA.cookieHeader())
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofString()
            );
            assertThat(lessonResp.statusCode()).isEqualTo(200);
            String rawLessonBody = lessonResp.body();
            assertThat(rawLessonBody).doesNotContain("answerIndex");
            assertThat(rawLessonBody).doesNotContain("\"solution\"");

            Map<String, Object> lessonMap = objectMapper.readValue(rawLessonBody, new TypeReference<>() {});
            Map<String, Object> returnedReel = (Map<String, Object>) lessonMap.get("reel");
            assertThat(returnedReel).isNotNull();
            assertThat(returnedReel.get("version")).isEqualTo(1);
            List<Map<String, Object>> scenes = (List<Map<String, Object>>) returnedReel.get("scenes");
            assertThat(scenes).hasSize(2);

            // Security 1: Foreign User B cannot access User A's Reel audio clip (404 LESSON_NOT_FOUND)
            HttpResponse<byte[]> foreignAudio = http.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create(url("/v1/lessons/" + lessonId + "/reel/audio/" + clipId)))
                            .header("Cookie", userB.cookieHeader())
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofByteArray()
            );
            assertThat(foreignAudio.statusCode()).isEqualTo(404);

            // Security 2: Invalid filename rejected with 400
            HttpResponse<byte[]> invalidClip = http.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create(url("/v1/lessons/" + lessonId + "/reel/audio/evil.exe")))
                            .header("Cookie", userA.cookieHeader())
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofByteArray()
            );
            assertThat(invalidClip.statusCode()).isEqualTo(400);

            // Security 3: Unknown clipId not present in core.media_calls rejected with 404
            HttpResponse<byte[]> unknownClip = http.send(
                    HttpRequest.newBuilder()
                            .uri(URI.create(url("/v1/lessons/" + lessonId + "/reel/audio/v1_other_lesson.wav")))
                            .header("Cookie", userA.cookieHeader())
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofByteArray()
            );
            assertThat(unknownClip.statusCode()).isEqualTo(404);
        } finally {
            if (userAUuid != null) {
                jdbc.sql("DELETE FROM core.users WHERE id = :id").param("id", userAUuid).update();
            }
            if (userBUuid != null) {
                jdbc.sql("DELETE FROM core.users WHERE id = :id").param("id", userBUuid).update();
            }
        }
    }

    private record AuthSession(String userId, String cookieHeader) {}

    private AuthSession registerAndLogin(String email) throws Exception {
        String body = objectMapper.writeValueAsString(Map.of(
                "email", email,
                "password", "StrongPass123!",
                "displayName", "Reel Tester"
        ));
        HttpResponse<String> resp = http.send(
                HttpRequest.newBuilder()
                        .uri(URI.create(url("/v1/auth/register")))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
        assertThat(resp.statusCode()).isIn(200, 201);
        Map<String, Object> parsed = objectMapper.readValue(resp.body(), new TypeReference<>() {});
        String userId = String.valueOf(parsed.get("id"));
        List<String> cookies = resp.headers().allValues("Set-Cookie");
        String cookieHeader = String.join("; ", cookies.stream().map(c -> c.split(";", 2)[0]).toList());
        return new AuthSession(userId, cookieHeader);
    }

    private Map<String, Object> postSignedInternal(String path, Map<String, Object> payload) throws Exception {
        byte[] raw = objectMapper.writeValueAsBytes(payload);
        Map<String, String> signed = signer.signHeaders("POST", path, raw, "cor_phase10a");
        HttpRequest.Builder req = HttpRequest.newBuilder()
                .uri(URI.create(url(path)))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(raw));
        signed.forEach(req::header);
        HttpResponse<String> resp = http.send(req.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        assertThat(resp.statusCode()).isEqualTo(200);
        return objectMapper.readValue(resp.body(), new TypeReference<>() {});
    }
}
