package com.sopiskill.core.course;

import java.text.Normalizer;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * Extracts course glossary terms strictly from `teach` blocks only (never quiz blocks,
 * preserving 0 answer-key exposure).
 */
@Service
public class GlossaryService {

    private final JdbcClient jdbc;

    public GlossaryService(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public static String normalizeTermKey(String term) {
        if (term == null) return "";
        String folded = Normalizer.normalize(term.trim().toLowerCase(Locale.ROOT).replace('đ', 'd'), Normalizer.Form.NFD)
                .replaceAll("\\p{M}+", "")
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("^-+|-+$", "");
        return folded.length() > 160 ? folded.substring(0, 160) : folded;
    }

    @SuppressWarnings("unchecked")
    public void extractAndUpsertFromTeachBlocks(UUID courseId, UUID lessonId, List<Map<String, Object>> blocks) {
        if (blocks == null) return;
        for (Map<String, Object> block : blocks) {
            if (!"teach".equals(block.get("type"))) {
                continue;
            }
            Object rawTerms = block.get("terms");
            if (rawTerms instanceof List<?> list && !list.isEmpty()) {
                for (Object item : list) {
                    if (item instanceof Map<?, ?> m) {
                        String term = m.get("term") == null ? "" : String.valueOf(m.get("term")).trim();
                        String def = m.get("definition") == null ? "" : String.valueOf(m.get("definition")).trim();
                        String example = m.get("example") == null ? null : String.valueOf(m.get("example")).trim();
                        upsert(courseId, lessonId, term, def, example);
                    }
                }
            } else {
                // Fallback: derive a term entry from teach block title + first paragraph
                String title = block.get("title") == null ? "" : String.valueOf(block.get("title")).trim();
                Object parasObj = block.get("paragraphs");
                String firstPara = "";
                if (parasObj instanceof List<?> paras && !paras.isEmpty()) {
                    firstPara = String.valueOf(paras.getFirst()).trim();
                }
                if (!title.isBlank() && !firstPara.isBlank()) {
                    upsert(courseId, lessonId, title, firstPara, null);
                }
            }
        }
    }

    private void upsert(UUID courseId, UUID lessonId, String term, String definition, String example) {
        if (term.isBlank() || definition.isBlank()) return;
        String key = normalizeTermKey(term);
        if (key.isBlank()) return;
        jdbc.sql("""
                INSERT INTO core.course_glossary_terms (id, course_id, lesson_id, term_key, term, definition, example)
                VALUES (:id, :courseId, :lessonId, :key, :term, :def, :example)
                ON CONFLICT (course_id, term_key) DO UPDATE SET
                    term = EXCLUDED.term,
                    definition = EXCLUDED.definition,
                    example = COALESCE(EXCLUDED.example, core.course_glossary_terms.example)
                """)
                .param("id", UUID.randomUUID())
                .param("courseId", courseId)
                .param("lessonId", lessonId)
                .param("key", key)
                .param("term", term.substring(0, Math.min(term.length(), 200)))
                .param("def", definition)
                .param("example", example)
                .update();
    }
}
