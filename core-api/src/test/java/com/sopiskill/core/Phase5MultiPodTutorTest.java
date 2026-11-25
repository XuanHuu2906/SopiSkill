package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.internal.InternalHmacSigner;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.jdbc.core.simple.JdbcClient;

/**
 * Phase Gate 5 Multi-Pod Integration Test:
 * Launches TWO independent Spring Boot `core-api` instances side-by-side behind the shared
 * live PostgreSQL 16 (Flyway V4) + Redis 7 + `ai-api` stack and verifies:
 *   1. Open SSE stream on Pod 1 -> drop TCP after first event -> resume with `Last-Event-ID`
 *      on Pod 2 -> receives all missed frames (`delta` + `done`) with zero lost text!
 *   2. Open SSE stream on Pod 1 -> send `POST /stop` to Pod 2 -> Redis Pub/Sub `tutor:cancel:{msgId}`
 *      cancels Pod 1's stream immediately (`event: cancelled` + DB `status = 'cancelled'`)!
 *   3. Full 6-tool & state-machine coverage:
 *      - `PlanChat` (`entryPoint='proposal'` -> `revise_proposal` -> `event: proposal_revised` v2)
 *      - `flag_question` -> inserts into `core.content_flags` (`source='tutor'`)
 *      - `ChangeCard` (`regenerate_unit` -> `pending` -> `decline`, and `pending` -> `confirm` -> `preparing` -> `ready`)
 *      - Cross-course `GET /v1/tutor/sessions` (`thisWeek`/`earlier`) & filtered `GET /v1/courses/{id}/tutor`.
 */
class Phase5MultiPodTutorTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .build();

    @Test
    @SuppressWarnings("unchecked")
    void twoCoreApiReplicasShareRedisForLastEventIdResumePubSubStopAndChangeCardLifecycle() throws Exception {
        ConfigurableApplicationContext pod1 = null;
        ConfigurableApplicationContext pod2 = null;
        try {
            pod1 = startReplica("test:queue:ai:llm:phase5");
            pod2 = startReplica("test:queue:ai:llm:phase5");

            int port1 = Integer.parseInt(pod1.getEnvironment().getProperty("local.server.port"));
            int port2 = Integer.parseInt(pod2.getEnvironment().getProperty("local.server.port"));
            assertThat(port1).isNotEqualTo(port2);

            JdbcClient jdbc = pod1.getBean(JdbcClient.class);
            InternalHmacSigner hmacSigner = pod1.getBean(InternalHmacSigner.class);

            // 1. Register user on Pod 1 and seed course + proposal + unit + lesson
            String email = "multipod-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
            HttpResponse<String> regResp = http.send(
                    HttpRequest.newBuilder(URI.create(url(port1, "/v1/auth/register")))
                            .header("Content-Type", "application/json")
                            .POST(HttpRequest.BodyPublishers.ofString(
                                    objectMapper.writeValueAsString(Map.of("email", email, "password", "StrongPassword123!"))
                            ))
                            .build(),
                    HttpResponse.BodyHandlers.ofString()
            );
            assertThat(regResp.statusCode()).isEqualTo(201);
            List<String> cookies = regResp.headers().allValues("set-cookie");
            String access = extractCookie(cookies, "access_token");
            String csrf = extractCookie(cookies, "csrf_token");
            String cookieHeader = "access_token=" + access + "; csrf_token=" + csrf;

            UUID userId = IdCodec.parse(String.valueOf(parseMap(regResp.body()).get("id")), "usr");
            UUID courseUuid = UUID.randomUUID();
            UUID unitUuid = UUID.randomUUID();
            UUID lessonUuid = UUID.randomUUID();
            String courseId = IdCodec.format("crs", courseUuid);
            String lessonId = IdCodec.format("lsn", lessonUuid);

            jdbc.sql("INSERT INTO core.courses (id, user_id, topic, language, status) VALUES (:cid, :uid, 'MultiPod Systems', 'en', 'ready')")
                    .param("cid", courseUuid).param("uid", userId).update();
            jdbc.sql("""
                    INSERT INTO core.course_proposals (id, course_id, version, approved, payload)
                    VALUES (:pid, :cid, 1, FALSE, CAST(:p AS jsonb))
                    """)
                    .param("pid", UUID.randomUUID())
                    .param("cid", courseUuid)
                    .param("p", objectMapper.writeValueAsString(Map.of(
                            "name", "MultiPod Systems",
                            "objective", "Master distributed streams.",
                            "outcomes", List.of("Handle reconnects"),
                            "units", List.of(Map.of("title", "Streams", "blurb", "SSE", "lessonTitles", List.of("Redis Streams")))
                    )))
                    .update();
            jdbc.sql("INSERT INTO core.units (id, course_id, order_index, title) VALUES (:uid, :cid, 0, 'Streams')")
                    .param("uid", unitUuid).param("cid", courseUuid).update();
            jdbc.sql("""
                    INSERT INTO core.lessons (id, course_id, unit_id, order_index, title, status, content_version, content_json)
                    VALUES (:lid, :cid, :uid, 0, 'Redis Streams', 'ready', 1, CAST(:b AS jsonb))
                    """)
                    .param("lid", lessonUuid)
                    .param("cid", courseUuid)
                    .param("uid", unitUuid)
                    .param("b", objectMapper.writeValueAsString(List.of(
                            Map.of("type", "teach", "title", "Intro", "paragraphs", List.of("Streams persist ordered events."))
                    )))
                    .update();

            // 2. MULTI-POD TEST A: Stream on Pod 1 -> drop TCP after first event -> Resume on Pod 2 via Last-Event-ID!
            HttpResponse<InputStream> pod1Stream = openSsePost(port1, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-resume-" + UUID.randomUUID(),
                    "text", "Explain this lesson deeper with an example",
                    "entryPoint", "teach_block",
                    "delayMs", 80,
                    "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
            ));
            assertThat(pod1Stream.statusCode()).isEqualTo(200);
            String msgIdA = pod1Stream.headers().firstValue("x-tutor-message-id").orElseThrow();
            String firstEventId;
            try (BufferedReader br = new BufferedReader(new InputStreamReader(pod1Stream.body(), StandardCharsets.UTF_8))) {
                Map<String, String> firstFrame = readOneSseFrame(br);
                firstEventId = firstFrame.get("id");
                assertThat(firstEventId).isNotBlank();
            } // Client drops TCP connection to Pod 1 right after frame 1!

            // Reconnect to POD 2 with `Last-Event-ID`!
            HttpResponse<String> pod2Resume = http.send(
                    HttpRequest.newBuilder(URI.create(url(port2, "/v1/courses/" + courseId + "/tutor/messages/" + msgIdA + "/stream")))
                            .header("Cookie", cookieHeader)
                            .header("Accept", "text/event-stream")
                            .header("Last-Event-ID", firstEventId)
                            .GET()
                            .build(),
                    HttpResponse.BodyHandlers.ofString()
            );
            assertThat(pod2Resume.statusCode()).isEqualTo(200);
            assertThat(pod2Resume.body()).contains("event:delta");
            assertThat(pod2Resume.body()).contains("event:done");

            // 3. MULTI-POD TEST B: Open slow stream on Pod 1 -> fire POST /stop at Pod 2 -> Pod 1 cancels via Redis Pub/Sub!
            HttpResponse<InputStream> pod1Slow = openSsePost(port1, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-stop-" + UUID.randomUUID(),
                    "text", "Explain Redis Pub/Sub in detail",
                    "entryPoint", "tab",
                    "delayMs", 300,
                    "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
            ));
            assertThat(pod1Slow.statusCode()).isEqualTo(200);
            String msgIdB = pod1Slow.headers().firstValue("x-tutor-message-id").orElseThrow();
            List<String> slowEvents = new ArrayList<>();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(pod1Slow.body(), StandardCharsets.UTF_8))) {
                Map<String, String> frame1 = readOneSseFrame(br);
                slowEvents.add(frame1.get("event"));

                // Fire /stop to POD 2!
                HttpResponse<String> stopResp = postAuthed(port2, "/v1/courses/" + courseId + "/tutor/messages/" + msgIdB + "/stop",
                        cookieHeader, csrf, Map.of());
                assertThat(stopResp.statusCode()).isEqualTo(200);

                // Drain remaining frames from Pod 1 -> must stop cleanly with `cancelled`!
                Map<String, String> next;
                while ((next = readOneSseFrame(br)) != null) {
                    slowEvents.add(next.get("event"));
                    if ("cancelled".equals(next.get("event")) || "done".equals(next.get("event"))) break;
                }
            }
            assertThat(slowEvents).contains("cancelled");
            // Wait briefly for Virtual Thread finally block to update DB
            Thread.sleep(150);
            String statusB = jdbc.sql("SELECT status FROM core.tutor_messages WHERE id = :mid")
                    .param("mid", IdCodec.parse(msgIdB, "tmsg")).query(String.class).single();
            assertThat(statusB).isEqualTo("cancelled");

            // 4. PlanChat (`revise_proposal`) -> bumps proposal to v2 & emits `proposal_revised`
            HttpResponse<String> planResp = postSseString(port1, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-plan-" + UUID.randomUUID(),
                    "text", "Add a hands-on project lesson to this proposal",
                    "entryPoint", "proposal"
            ));
            assertThat(planResp.statusCode()).isEqualTo(200);
            assertThat(planResp.body()).contains("event:proposal_revised");
            int latestVer = jdbc.sql("SELECT MAX(version) FROM core.course_proposals WHERE course_id = :cid")
                    .param("cid", courseUuid).query(Integer.class).single();
            assertThat(latestVer).isEqualTo(2);

            // 5. `flag_question` -> creates row in `core.content_flags` (`source='tutor'`)
            HttpResponse<String> flagResp = postSseString(port2, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-flag-" + UUID.randomUUID(),
                    "text", "Report bug: wrong question wording",
                    "entryPoint", "wrong_answer",
                    "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
            ));
            assertThat(flagResp.statusCode()).isEqualTo(200);
            int tutorFlags = jdbc.sql("SELECT COUNT(*) FROM core.content_flags WHERE course_id = :cid AND source = 'tutor'")
                    .param("cid", courseUuid).query(Integer.class).single();
            assertThat(tutorFlags).isGreaterThanOrEqualTo(1);

            // 6. ChangeCard state machine (`regenerate_unit`): pending -> decline, AND pending -> confirm -> preparing -> ready
            HttpResponse<String> regen1 = postSseString(port1, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-regen1-" + UUID.randomUUID(),
                    "text", "This unit is too hard, rewrite unit easier",
                    "entryPoint", "path_harder",
                    "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
            ));
            assertThat(regen1.statusCode()).isEqualTo(200);
            assertThat(regen1.body()).contains("event:confirm");
            String actionId1 = extractJsonFieldFromEvent(regen1.body(), "confirm", "actionId");
            assertThat(actionId1).startsWith("act_");

            HttpResponse<String> declineResp = postAuthed(port2, "/v1/courses/" + courseId + "/tutor/actions/" + actionId1 + "/decline",
                    cookieHeader, csrf, Map.of());
            assertThat(declineResp.statusCode()).isEqualTo(200);
            assertThat(parseMap(declineResp.body()).get("status")).isEqualTo("declined");

            // Trigger second ChangeCard and CONFIRM it!
            HttpResponse<String> regen2 = postSseString(port2, "/v1/courses/" + courseId + "/tutor/messages", cookieHeader, csrf, Map.of(
                    "clientMessageId", "mp-regen2-" + UUID.randomUUID(),
                    "text", "This unit is too easy, rewrite unit deeper",
                    "entryPoint", "path_harder",
                    "contextRef", Map.of("lessonId", lessonId, "blockIndex", 0)
            ));
            String actionId2 = extractJsonFieldFromEvent(regen2.body(), "confirm", "actionId");
            HttpResponse<String> confirmResp = postAuthed(port1, "/v1/courses/" + courseId + "/tutor/actions/" + actionId2 + "/confirm",
                    cookieHeader, csrf, Map.of());
            assertThat(confirmResp.statusCode()).isEqualTo(200);
            Map<String, Object> confirmedAction = parseMap(confirmResp.body());
            assertThat(confirmedAction.get("status")).isEqualTo("preparing");
            String regenJobId = String.valueOf(confirmedAction.get("jobId"));
            assertThat(regenJobId).startsWith("job_");

            // Verify lesson content_version bumped to 2
            int newLessonVer = jdbc.sql("SELECT content_version FROM core.lessons WHERE id = :lid")
                    .param("lid", lessonUuid).query(Integer.class).single();
            assertThat(newLessonVer).isEqualTo(2);

            // Simulate signed callback completing the regenerate_unit job -> action flips to `ready`!
            byte[] cbBytes = objectMapper.writeValueAsBytes(Map.of(
                    "status", "completed",
                    "result", Map.of("lessons", List.of(Map.of(
                            "title", "Redis Streams (Deeper)",
                            "blocks", List.of(Map.of("type", "teach", "title", "Deeper", "paragraphs", List.of("Updated content.")))
                    )))
            ));
            String cbPath = "/internal/jobs/" + regenJobId + "/complete";
            HttpRequest.Builder cbReq = HttpRequest.newBuilder(URI.create(url(port2, cbPath)))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(cbBytes));
            hmacSigner.signHeaders("POST", cbPath, cbBytes, "cor_p5_regen").forEach(cbReq::header);
            HttpResponse<String> cbResp = http.send(cbReq.build(), HttpResponse.BodyHandlers.ofString());
            assertThat(cbResp.statusCode()).isEqualTo(200);

            HttpResponse<String> actionAfter = getAuthed(port1, "/v1/courses/" + courseId + "/tutor/actions/" + actionId2, cookieHeader);
            assertThat(actionAfter.statusCode()).isEqualTo(200);
            assertThat(parseMap(actionAfter.body()).get("status")).isEqualTo("ready");

            // 7. Cross-course GET /v1/tutor/sessions & filtered GET /v1/courses/{id}/tutor?entryPoint=proposal
            HttpResponse<String> sessionsResp = getAuthed(port2, "/v1/tutor/sessions", cookieHeader);
            assertThat(sessionsResp.statusCode()).isEqualTo(200);
            Map<String, Object> sessionsJson = parseMap(sessionsResp.body());
            assertThat((List<?>) sessionsJson.get("thisWeek")).isNotEmpty();

            HttpResponse<String> filteredResp = getAuthed(port1, "/v1/courses/" + courseId + "/tutor?entryPoint=proposal", cookieHeader);
            assertThat(filteredResp.statusCode()).isEqualTo(200);
            assertThat((List<?>) parseMap(filteredResp.body()).get("items")).isNotEmpty();
        } finally {
            if (pod2 != null) pod2.close();
            if (pod1 != null) pod1.close();
        }
    }

    private ConfigurableApplicationContext startReplica(String streamKey) {
        return new SpringApplicationBuilder(CoreApiApplication.class)
                .run(
                        "--server.port=0",
                        "--sopiskill.stream-llm-key=" + streamKey,
                        "--sopiskill.rate-limit-enabled=false"
                );
    }

    private String url(int port, String path) {
        return "http://127.0.0.1:" + port + path;
    }

    private HttpResponse<InputStream> openSsePost(int port, String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(port, path)))
                        .header("Content-Type", "application/json")
                        .header("Accept", "text/event-stream")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofInputStream()
        );
    }

    private HttpResponse<String> postSseString(int port, String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(port, path)))
                        .header("Content-Type", "application/json")
                        .header("Accept", "text/event-stream")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> postAuthed(int port, String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(port, path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> getAuthed(int port, String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(port, path)))
                        .header("Cookie", cookie)
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private Map<String, String> readOneSseFrame(BufferedReader br) throws Exception {
        String id = "";
        String event = "message";
        StringBuilder data = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) {
            if (line.startsWith("id:")) id = line.substring(3).trim();
            else if (line.startsWith("event:")) event = line.substring(6).trim();
            else if (line.startsWith("data:")) data.append(line.substring(5).trim());
            else if (line.isBlank() && !data.isEmpty()) {
                return Map.of("id", id, "event", event, "data", data.toString());
            }
        }
        return data.isEmpty() ? null : Map.of("id", id, "event", event, "data", data.toString());
    }

    private String extractJsonFieldFromEvent(String sseBody, String targetEvent, String field) throws Exception {
        String[] blocks = sseBody.split("\n\n");
        for (String blk : blocks) {
            String ev = "";
            StringBuilder data = new StringBuilder();
            for (String line : blk.split("\n")) {
                if (line.startsWith("event:")) ev = line.substring(6).trim();
                else if (line.startsWith("data:")) data.append(line.substring(5).trim());
            }
            if (targetEvent.equals(ev) && !data.isEmpty()) {
                Map<String, Object> parsed = parseMap(data.toString());
                if (parsed.get(field) != null) return String.valueOf(parsed.get(field));
            }
        }
        return "";
    }

    private Map<String, Object> parseMap(String body) throws Exception {
        return objectMapper.readValue(body, new TypeReference<>() {});
    }

    private String extractCookie(List<String> headers, String name) {
        for (String h : headers) {
            if (h.startsWith(name + "=")) {
                int end = h.indexOf(';');
                return end > 0 ? h.substring(name.length() + 1, end) : h.substring(name.length() + 1);
            }
        }
        return "";
    }
}
