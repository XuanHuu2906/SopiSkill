package com.sopiskill.core.internal;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.config.SopiProperties;
import io.github.resilience4j.circuitbreaker.CircuitBreaker;
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

/**
 * Signed HTTP/SSE client and Redis Streams job dispatcher from `core-api` to `ai-engine`.
 */
@Service
public class AiEngineClient {

    private static final Logger log = LoggerFactory.getLogger(AiEngineClient.class);

    private final SopiProperties props;
    private final InternalHmacSigner signer;
    private final JsonHelper json;
    private final StringRedisTemplate redis;
    private final HttpClient httpClient;
    private final CircuitBreaker circuitBreaker;

    public AiEngineClient(
            SopiProperties props,
            InternalHmacSigner signer,
            JsonHelper json,
            StringRedisTemplate redis
    ) {
        this.props = props;
        this.signer = signer;
        this.json = json;
        this.redis = redis;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();
        this.circuitBreaker = CircuitBreaker.of(
                "ai-engine",
                CircuitBreakerConfig.custom()
                        .failureRateThreshold(50)
                        .waitDurationInOpenState(Duration.ofSeconds(15))
                        .slidingWindowSize(10)
                        .build()
        );
    }

    public Map<String, Object> postJson(String path, Map<String, Object> payload, String correlationId) {
        return circuitBreaker.executeSupplier(() -> {
            byte[] rawBody = json.toJson(payload).getBytes(StandardCharsets.UTF_8);
            Map<String, String> signed = signer.signHeaders("POST", path, rawBody, correlationId);
            String url = props.aiEngineUrl().replaceAll("/+$", "") + path;

            HttpRequest.Builder req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(30))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(rawBody));
            signed.forEach(req::header);

            try {
                HttpResponse<String> resp = httpClient.send(req.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (resp.statusCode() < 200 || resp.statusCode() >= 300) {
                    throw new IllegalStateException("ai-engine returned HTTP " + resp.statusCode() + " for " + path);
                }
                return json.fromJson(resp.body(), new TypeReference<>() {});
            } catch (Exception ex) {
                throw new RuntimeException("Failed calling ai-engine " + path + ": " + ex.getMessage(), ex);
            }
        });
    }

    public HttpResponse<InputStream> openTutorSseStream(Map<String, Object> payload, String correlationId) {
        String path = "/internal/tutor/stream";
        byte[] rawBody = json.toJson(payload).getBytes(StandardCharsets.UTF_8);
        Map<String, String> signed = signer.signHeaders("POST", path, rawBody, correlationId);
        String url = props.aiEngineUrl().replaceAll("/+$", "") + path;

        HttpRequest.Builder req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(120))
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofByteArray(rawBody));
        signed.forEach(req::header);

        try {
            return httpClient.send(req.build(), HttpResponse.BodyHandlers.ofInputStream());
        } catch (Exception ex) {
            throw new RuntimeException("Failed opening tutor SSE stream: " + ex.getMessage(), ex);
        }
    }

    public void deleteRagResourceBestEffort(String path, String correlationId) {
        try {
            byte[] empty = new byte[0];
            Map<String, String> signed = signer.signHeaders("DELETE", path, empty, correlationId);
            String url = props.aiEngineUrl().replaceAll("/+$", "") + path;
            HttpRequest.Builder req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(10))
                    .DELETE();
            signed.forEach(req::header);
            httpClient.send(req.build(), HttpResponse.BodyHandlers.discarding());
        } catch (Exception ex) {
            log.warn("ai_engine_rag_delete_failed path={} errorType={}", path, ex.getClass().getSimpleName());
        }
    }

    public String enqueueLlmJob(Map<String, Object> message) {
        String serialized = json.toJson(message);
        var record = StreamRecords.string(Map.of("data", serialized)).withStreamKey(props.streamLlmKey());
        var id = redis.opsForStream().add(record);
        return id == null ? "" : id.getValue();
    }

    public String enqueueIngestJob(Map<String, Object> message) {
        String serialized = json.toJson(message);
        var record = StreamRecords.string(Map.of("data", serialized)).withStreamKey(props.streamIngestKey());
        var id = redis.opsForStream().add(record);
        return id == null ? "" : id.getValue();
    }

    @SuppressWarnings("unchecked")
    public List<String> fetchInterviewQuestions(String courseId, String topic, String language, String correlationId) {
        try {
            Map<String, Object> resp = postJson(
                    "/internal/interview/questions",
                    Map.of("courseId", courseId, "topic", topic, "language", language),
                    correlationId
            );
            List<Map<String, Object>> qs = (List<Map<String, Object>>) resp.get("questions");
            if (qs != null && !qs.isEmpty()) {
                return qs.stream().map(q -> String.valueOf(q.get("prompt"))).toList();
            }
        } catch (Exception ex) {
            log.warn("ai_engine_interview_questions_fallback errorType={}", ex.getClass().getSimpleName());
        }
        if ("en".equals(language)) {
            return List.of(
                    "Have you worked with " + topic + " before?",
                    "What concrete goal do you want to achieve with " + topic + "?",
                    "How many hours per week can you dedicate to learning?",
                    "Which learning style helps you most (examples, diagrams, projects)?",
                    "Do you prefer a quick practical overview or a deep dive?"
            );
        }
        return List.of(
                "Bạn đã từng tiếp xúc hay làm việc với " + topic + " chưa?",
                "Mục tiêu cụ thể bạn muốn đạt được với " + topic + " là gì?",
                "Mỗi tuần bạn có thể dành khoảng bao nhiêu giờ để học?",
                "Bạn thích học theo phong cách nào (ví dụ thực tế, sơ đồ, dự án)?",
                "Bạn muốn nắm tổng quan nhanh hay đi sâu vào nền tảng?"
        );
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> evaluateInterview(
            String courseId,
            String topic,
            String language,
            List<Map<String, String>> answers,
            String correlationId
    ) {
        try {
            Map<String, Object> resp = postJson(
                    "/internal/interview/evaluate",
                    Map.of(
                            "courseId", courseId,
                            "topic", topic,
                            "language", language,
                            "answers", answers
                    ),
                    correlationId
            );
            Object lp = resp.get("learnerProfile");
            if (lp instanceof Map<?, ?> map) {
                return (Map<String, Object>) map;
            }
        } catch (Exception ex) {
            log.warn("ai_engine_interview_eval_fallback errorType={}", ex.getClass().getSimpleName());
        }
        return Map.of(
                "currentLevel", "beginner",
                "depth", "balanced",
                "preferredStyles", List.of("hands_on"),
                "weeklyMinutes", 180,
                "goal", topic,
                "warnings", List.of()
        );
    }
}
