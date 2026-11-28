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
        return postJson(path, payload, correlationId, Duration.ofSeconds(30));
    }

    public Map<String, Object> postJson(String path, Map<String, Object> payload, String correlationId, Duration timeout) {
        return circuitBreaker.executeSupplier(() -> {
            byte[] rawBody = json.toJson(payload).getBytes(StandardCharsets.UTF_8);
            Map<String, String> signed = signer.signHeaders("POST", path, rawBody, correlationId);
            String url = props.aiEngineUrl().replaceAll("/+$", "") + path;

            HttpRequest.Builder req = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(timeout)
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

    public HttpResponse<byte[]> getBinary(String path, String correlationId) {
        byte[] empty = new byte[0];
        Map<String, String> signed = signer.signHeaders("GET", path, empty, correlationId);
        String url = props.aiEngineUrl().replaceAll("/+$", "") + path;

        HttpRequest.Builder req = HttpRequest.newBuilder()
                .uri(URI.create(url))
                .timeout(Duration.ofSeconds(15))
                .GET();
        signed.forEach(req::header);

        try {
            return httpClient.send(req.build(), HttpResponse.BodyHandlers.ofByteArray());
        } catch (Exception ex) {
            throw new RuntimeException("Failed fetching binary from ai-engine " + path + ": " + ex.getMessage(), ex);
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
    public List<Map<String, Object>> fetchStructuredInterviewQuestions(
            String courseId,
            String topic,
            String language,
            Map<String, Object> sourceBrief,
            String correlationId
    ) {
        try {
            Map<String, Object> reqBody = new java.util.LinkedHashMap<>();
            reqBody.put("courseId", courseId);
            reqBody.put("topic", topic);
            reqBody.put("language", language);
            if (sourceBrief != null) {
                reqBody.put("sourceBrief", sourceBrief);
            }
            Map<String, Object> resp = postJson("/internal/interview/questions", reqBody, correlationId);
            List<Map<String, Object>> qs = (List<Map<String, Object>>) resp.get("questions");
            if (qs != null && !qs.isEmpty()) {
                return ensureStructuredChoices(qs, topic, language);
            }
        } catch (Exception ex) {
            log.warn("ai_engine_interview_questions_fallback errorType={}", ex.getClass().getSimpleName());
        }
        return defaultStructuredInterviewQuestions(topic, language);
    }

    /**
     * Guarantee every interview slot has selectable {@code kind} ({@code single}/{@code multi}) and non-empty {@code choices}.
     * Preserves any valid prompt/choices returned by AI or stored in DB, backfilling only missing choices.
     */
    public List<Map<String, Object>> ensureStructuredChoices(
            List<?> rawQuestions,
            String topic,
            String language
    ) {
        List<Map<String, Object>> defaults = defaultStructuredInterviewQuestions(topic, language);
        List<Map<String, Object>> out = new java.util.ArrayList<>(defaults.size());
        int count = Math.max(defaults.size(), rawQuestions == null ? 0 : rawQuestions.size());
        for (int i = 0; i < count; i++) {
            Map<String, Object> def = i < defaults.size() ? defaults.get(i) : defaults.get(defaults.size() - 1);
            Object rawItem = (rawQuestions != null && i < rawQuestions.size()) ? rawQuestions.get(i) : null;
            if (rawItem instanceof Map<?, ?> m) {
                Object rawPrompt = m.get("prompt");
                String prompt = (rawPrompt != null && !String.valueOf(rawPrompt).isBlank())
                        ? String.valueOf(rawPrompt).trim()
                        : String.valueOf(def.get("prompt"));
                String rawKind = m.get("kind") == null ? "freeform" : String.valueOf(m.get("kind"));
                List<String> validChoices = new java.util.ArrayList<>();
                if (m.get("choices") instanceof List<?> rawChoices) {
                    for (Object c : rawChoices) {
                        if (c != null && !String.valueOf(c).isBlank()) {
                            validChoices.add(String.valueOf(c).trim());
                        }
                    }
                }
                boolean hasChoices = validChoices.size() >= 2 && ("single".equals(rawKind) || "multi".equals(rawKind));
                Map<String, Object> item = new java.util.LinkedHashMap<>();
                item.put("index", i);
                item.put("prompt", prompt);
                item.put("kind", hasChoices ? rawKind : String.valueOf(def.get("kind")));
                item.put("choices", hasChoices ? validChoices : def.get("choices"));
                out.add(item);
            } else if (rawItem != null && !String.valueOf(rawItem).isBlank()) {
                Map<String, Object> item = new java.util.LinkedHashMap<>();
                item.put("index", i);
                item.put("prompt", String.valueOf(rawItem).trim());
                item.put("kind", String.valueOf(def.get("kind")));
                item.put("choices", def.get("choices"));
                out.add(item);
            } else if (i < defaults.size()) {
                out.add(def);
            }
        }
        return out;
    }

    public List<Map<String, Object>> defaultStructuredInterviewQuestions(String topic, String language) {
        if ("en".equals(language)) {
            return List.of(
                    Map.of(
                            "index", 0,
                            "prompt", "Have you worked with " + topic + " before?",
                            "kind", "single",
                            "choices", List.of(
                                    "Complete beginner — never used it",
                                    "Some experience — know the basics",
                                    "Intermediate — use it occasionally",
                                    "Advanced — want to deepen mastery"
                            )
                    ),
                    Map.of(
                            "index", 1,
                            "prompt", "What concrete goal do you want to achieve with " + topic + "?",
                            "kind", "single",
                            "choices", List.of(
                                    "Understand core concepts quickly",
                                    "Build a clean working project",
                                    "Prepare for work or interviews",
                                    "Apply it to my own documents"
                            )
                    ),
                    Map.of(
                            "index", 2,
                            "prompt", "How many hours per week can you dedicate to learning?",
                            "kind", "single",
                            "choices", List.of("1-2 hours per week", "3 hours per week", "5+ hours per week")
                    ),
                    Map.of(
                            "index", 3,
                            "prompt", "Which learning style helps you most (examples, diagrams, projects)?",
                            "kind", "multi",
                            "choices", List.of("Hands-on examples", "Visual diagrams", "Mini projects", "Clear theory")
                    ),
                    Map.of(
                            "index", 4,
                            "prompt", "Do you prefer a quick practical overview or a deep dive?",
                            "kind", "single",
                            "choices", List.of("Quick practical overview", "Balanced theory & practice", "Deep dive into core ideas")
                    )
            );
        }
        return List.of(
                Map.of(
                        "index", 0,
                        "prompt", "Bạn đã từng tiếp xúc hay làm việc với " + topic + " chưa?",
                        "kind", "single",
                        "choices", List.of(
                                "Mới bắt đầu từ con số 0",
                                "Đã biết cơ bản một chút",
                                "Đã dùng thực tế ở mức trung bình",
                                "Khá vững, muốn đào sâu chuyên môn"
                        )
                ),
                Map.of(
                        "index", 1,
                        "prompt", "Mục tiêu cụ thể bạn muốn đạt được với " + topic + " là gì?",
                        "kind", "single",
                        "choices", List.of(
                                "Nắm nhanh khái niệm cốt lõi",
                                "Tự làm được bài tập / dự án nhỏ",
                                "Ứng dụng ngay vào công việc",
                                "Hiểu sâu tài liệu chuyên ngành"
                        )
                ),
                Map.of(
                        "index", 2,
                        "prompt", "Mỗi tuần bạn có thể dành khoảng bao nhiêu giờ để học?",
                        "kind", "single",
                        "choices", List.of("1-2 giờ mỗi tuần", "Khoảng 3 giờ mỗi tuần", "5 giờ trở lên mỗi tuần")
                ),
                Map.of(
                        "index", 3,
                        "prompt", "Bạn thích học theo phong cách nào (ví dụ thực tế, sơ đồ, dự án)?",
                        "kind", "multi",
                        "choices", List.of("Ví dụ thực tế", "Sơ đồ trực quan", "Dự án nhỏ", "Giải thích lý thuyết rõ ràng")
                ),
                Map.of(
                        "index", 4,
                        "prompt", "Bạn muốn nắm tổng quan nhanh hay đi sâu vào nền tảng?",
                        "kind", "single",
                        "choices", List.of("Tổng quan nhanh, dễ áp dụng", "Cân bằng lý thuyết và thực hành", "Đi sâu vào bản chất nền tảng")
                )
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

    @SuppressWarnings("unchecked")
    public Map<String, Object> generateProposal(
            String courseId,
            String topic,
            String language,
            Map<String, Object> learnerProfile,
            Map<String, Object> sourceBrief,
            String correlationId
    ) {
        try {
            Map<String, Object> reqBody = new java.util.LinkedHashMap<>();
            reqBody.put("courseId", courseId);
            reqBody.put("topic", topic);
            reqBody.put("language", language);
            reqBody.put("learnerProfile", learnerProfile == null ? Map.of() : learnerProfile);
            if (sourceBrief != null) {
                reqBody.put("sourceBrief", sourceBrief);
            }
            Map<String, Object> resp = postJson("/internal/proposal/generate", reqBody, correlationId, Duration.ofSeconds(60));
            Object prop = resp.get("proposal");
            if (prop instanceof Map<?, ?> map) {
                return (Map<String, Object>) map;
            }
        } catch (Exception ex) {
            log.warn("ai_engine_proposal_generate_fallback errorType={}", ex.getClass().getSimpleName());
        }
        return null;
    }
}
