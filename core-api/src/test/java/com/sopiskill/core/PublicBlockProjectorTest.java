package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.lesson.PublicBlockProjector;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PublicBlockProjectorTest {

    private final SopiProperties props = new SopiProperties(
            "test", "http://localhost:3000", "jwt-secret-at-least-32-bytes-for-hmac-test",
            "iss", "aud", 60, false, "super-secret-shuffle-key-32-bytes!!",
            "http://127.0.0.1:8010", "tok", "hmac", 300,
            "queue:ai:llm", "queue:ai:ingest", true, 30, 100000, 2, false, true, false, false,
            "http://127.0.0.1:9010", "http://127.0.0.1:9010", "minio", "minio-pass", "sopiskill-sources", "us-east-1",
            80, 20, 5, 30, false, false,
            30, "sopiskill-google-client", "com.sopiskill.web", "", false, true
    );
    private final PublicBlockProjector projector = new PublicBlockProjector(props);

    @Test
    void publicProjectionStripsAllAnswerKeysAndDeterministicallyShufflesOrderAndMatch() {
        UUID lid = UUID.randomUUID();
        List<Map<String, Object>> privateBlocks = List.of(
                Map.of("type", "teach", "title", "Intro", "paragraphs", List.of("Hello"), "terms", List.of()),
                Map.of("type", "mc", "question", "2+2?", "options", List.of("3", "4"), "answerIndex", 1),
                Map.of("type", "blank", "sentence", "SQL stands for ____.", "answer", "Structured Query Language"),
                Map.of("type", "order", "prompt", "Order steps", "items", List.of("A", "B", "C")),
                Map.of("type", "match", "prompt", "Match", "pairs", List.of(List.of("K1", "V1"), List.of("K2", "V2"))),
                Map.of("type", "short", "question", "Explain index", "acceptedAnswers", List.of("B-Tree index"))
        );

        List<Map<String, Object>> pub = projector.toPublicBlocks(lid, 1, privateBlocks);
        assertThat(pub).hasSize(6);

        // Zero answer key fields leaked
        for (Map<String, Object> blk : pub) {
            assertThat(blk).doesNotContainKeys("answerIndex", "answer", "acceptedAnswers", "pairs", "solution", "answer_key");
        }

        // Deterministic shuffle is never identity for len >= 2 and stable across calls
        List<Map<String, Object>> pub2 = projector.toPublicBlocks(lid, 1, privateBlocks);
        assertThat(pub2).isEqualTo(pub);

        @SuppressWarnings("unchecked")
        List<Map<String, Object>> orderItems = (List<Map<String, Object>>) pub.get(3).get("items");
        List<String> displayedTexts = orderItems.stream().map(m -> String.valueOf(m.get("text"))).toList();
        assertThat(displayedTexts).isNotEqualTo(List.of("A", "B", "C"));

        // Reconstruct correct order by mapping original texts -> displayed IDs
        List<Integer> correctOrderIds = List.of("A", "B", "C").stream()
                .map(target -> orderItems.stream()
                        .filter(m -> target.equals(m.get("text")))
                        .map(m -> ((Number) m.get("id")).intValue())
                        .findFirst().orElseThrow())
                .toList();
        assertThat(projector.gradeOrder(lid, 1, 3, privateBlocks.get(3), correctOrderIds)).isTrue();
        assertThat(projector.gradeOrder(lid, 1, 3, privateBlocks.get(3), List.of(0, 1, 2))).isFalse();

        // Short semantic diacritic-folded grading
        Map<String, Object> viShort = Map.of(
                "type", "short",
                "question", "Chỉ mục là gì?",
                "acceptedAnswers", List.of("Chỉ mục B-Tree tăng tốc truy vấn")
        );
        assertThat(projector.gradeShortSemantic(viShort, "chi muc b tree tang toc truy van")).isTrue();
        assertThat(projector.gradeMc(privateBlocks.get(1), Boolean.TRUE)).isFalse();
        assertThat(projector.gradeMc(privateBlocks.get(1), 1)).isTrue();
    }
}
