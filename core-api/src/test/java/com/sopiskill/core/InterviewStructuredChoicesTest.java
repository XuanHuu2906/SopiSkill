package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.internal.AiEngineClient;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class InterviewStructuredChoicesTest {

    private final SopiProperties props = new SopiProperties(
            "test", "http://localhost:3000", "jwt-secret-at-least-32-bytes-for-hmac-test",
            "iss", "aud", 60, false, "super-secret-shuffle-key-32-bytes!!",
            "http://127.0.0.1:8010", "tok", "hmac", 300,
            "queue:ai:llm", "queue:ai:ingest", true, 30, 100000, 2, false, true, false, false,
            "http://127.0.0.1:9010", "http://127.0.0.1:9010", "minio", "minio-pass", "sopiskill-sources", "us-east-1",
            80, 20, 5, 30, false, false,
            30, "sopiskill-google-client", "com.sopiskill.web", "", false, true
    );

    private final AiEngineClient client = new AiEngineClient(props, null, null, null);

    @Test
    @SuppressWarnings("unchecked")
    void defaultStructuredInterviewQuestionsAlwaysProvideChoices() {
        for (String lang : List.of("vi", "en")) {
            List<Map<String, Object>> qs = client.defaultStructuredInterviewQuestions("Binary Tree", lang);
            assertThat(qs).hasSize(5);
            assertThat(String.valueOf(qs.get(0).get("prompt"))).contains("Binary Tree");
            for (int i = 0; i < qs.size(); i++) {
                Map<String, Object> q = qs.get(i);
                assertThat(q.get("index")).isEqualTo(i);
                assertThat(String.valueOf(q.get("kind"))).isIn("single", "multi");
                assertThat((List<String>) q.get("choices")).hasSizeGreaterThanOrEqualTo(3);
            }
        }
    }

    @Test
    @SuppressWarnings("unchecked")
    void ensureStructuredChoicesBackfillsLegacyFreeformRowsAndPreservesAiChoices() {
        List<Map<String, Object>> mixed = List.of(
                // Legacy freeform row (like existing DB rows without choices)
                Map.of(
                        "index", 0,
                        "prompt", "Bạn đã từng tiếp xúc hay làm việc với Binary Tree chưa?",
                        "kind", "freeform",
                        "choices", List.of()
                ),
                // AI-generated topic-specific row with valid choices
                Map.of(
                        "index", 1,
                        "prompt", "Mục tiêu chính khi học Binary Tree là gì?",
                        "kind", "single",
                        "choices", List.of("Hiểu DFS/BFS", "Luyện phỏng vấn thuật toán")
                )
        );

        List<Map<String, Object>> normalized = client.ensureStructuredChoices(mixed, "Binary Tree", "vi");
        assertThat(normalized).hasSize(5);

        // Slot 0 keeps legacy prompt and gains selectable choices
        assertThat(normalized.get(0).get("prompt")).isEqualTo("Bạn đã từng tiếp xúc hay làm việc với Binary Tree chưa?");
        assertThat(normalized.get(0).get("kind")).isEqualTo("single");
        assertThat((List<String>) normalized.get(0).get("choices")).hasSize(4);

        // Slot 1 preserves AI-generated prompt & choices untouched
        assertThat(normalized.get(1).get("prompt")).isEqualTo("Mục tiêu chính khi học Binary Tree là gì?");
        assertThat((List<String>) normalized.get(1).get("choices")).containsExactly("Hiểu DFS/BFS", "Luyện phỏng vấn thuật toán");

        // Slots 2..4 are filled from defaults
        assertThat(normalized.get(3).get("kind")).isEqualTo("multi");
        assertThat((List<String>) normalized.get(4).get("choices")).hasSize(3);
    }
}
