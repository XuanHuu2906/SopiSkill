package com.sopiskill.core.lesson;

import com.sopiskill.core.config.SopiProperties;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.stereotype.Component;

/**
 * Projects private DB lesson blocks to public-safe wire blocks (0 answer keys)
 * with server-secret HMAC-SHA256 deterministic shuffling, capability negotiation (`X-Client-Blocks`),
 * and performs 100% server-authoritative grading (including Phase 4 multi-blank, scenario outcomes,
 * spot/steps, speed round, and 3-level short-answer verdicts).
 */
@Component
public class PublicBlockProjector {

    public static final int COMPLETION_THRESHOLD_PERCENT = 80;

    private static final Set<String> SAFE_FIGURE_KEYS = Set.of(
            "kind", "type", "layout", "title", "caption", "latex", "headers", "rows",
            "nodes", "edges", "left", "right", "tone", "items", "steps", "center", "spokes"
    );

    private static final Set<String> SAFE_IMAGE_KEYS = Set.of(
            "url", "alt", "caption", "width", "height", "sourceId", "pageNumber"
    );

    public record ShortGradeVerdict(
            String verdict,
            boolean correct,
            String grader,
            String feedback,
            List<String> matchedKeyPoints
    ) {}

    private final byte[] shuffleKey;

    public PublicBlockProjector(SopiProperties props) {
        String raw = props.lessonShuffleSecret();
        if (raw == null || raw.isBlank()) {
            raw = props.jwtSecret();
        }
        this.shuffleKey = raw.getBytes(StandardCharsets.UTF_8);
    }

    public static Set<String> parseClientCapabilities(String headerValue) {
        if (headerValue == null || headerValue.isBlank()) {
            return null; // Default: modern client supporting all Phase 4 blocks
        }
        Set<String> caps = new HashSet<>();
        Arrays.stream(headerValue.split(","))
                .map(s -> s.trim().toLowerCase(Locale.ROOT))
                .filter(s -> !s.isBlank())
                .forEach(caps::add);
        return caps.isEmpty() ? null : caps;
    }

    public boolean isGradable(Map<String, Object> block) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        return !"teach".equals(type) && !"recap".equals(type);
    }

    public boolean isMultiBlank(Map<String, Object> block) {
        return "blank".equals(String.valueOf(block.getOrDefault("type", "")))
                && block.get("parts") instanceof List<?>
                && block.get("answers") instanceof List<?> ans
                && !ans.isEmpty();
    }

    private long seed(UUID lessonId, int contentVersion, int blockIndex) {
        String msg = lessonId + ":" + contentVersion + ":" + blockIndex;
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(shuffleKey, "HmacSHA256"));
            byte[] digest = mac.doFinal(msg.getBytes(StandardCharsets.UTF_8));
            return ByteBuffer.wrap(digest, 0, 8).getLong();
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public <T> List<T> shuffled(List<T> items, UUID lessonId, int contentVersion, int blockIndex) {
        if (items == null || items.size() < 2) {
            return items == null ? List.of() : new ArrayList<>(items);
        }
        Random rng = new Random(seed(lessonId, contentVersion, blockIndex));
        List<T> work = new ArrayList<>(items);
        for (int attempt = 0; attempt < 8; attempt++) {
            Collections.shuffle(work, rng);
            if (!work.equals(items)) {
                return work;
            }
        }
        List<T> rotated = new ArrayList<>(items.size());
        rotated.addAll(items.subList(1, items.size()));
        rotated.add(items.getFirst());
        return rotated;
    }

    public Map<String, Object> toPublicBlock(UUID lessonId, int contentVersion, int blockIndex, Map<String, Object> block) {
        return toPublicBlock(lessonId, contentVersion, blockIndex, block, null);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> toPublicBlock(
            UUID lessonId,
            int contentVersion,
            int blockIndex,
            Map<String, Object> block,
            Set<String> clientCaps
    ) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("type", type);

        switch (type) {
            case "teach" -> {
                out.put("title", String.valueOf(block.getOrDefault("title", "")));
                Object paras = block.get("paragraphs");
                out.put("paragraphs", paras instanceof List<?> l ? new ArrayList<>(l) : List.of());
                if (block.get("kicker") != null) out.put("kicker", String.valueOf(block.get("kicker")));
                if (block.get("takeaway") != null) out.put("takeaway", String.valueOf(block.get("takeaway")));
                if (block.get("terms") instanceof List<?> t) out.put("terms", sanitizeTerms(t));
                if (block.get("cite") instanceof Map<?, ?> c) out.put("cite", sanitizeCite(c));

                boolean allowFigure = clientCaps == null || clientCaps.contains("figure") || clientCaps.contains("teach");
                // Mutual exclusion: figure OR image, never both on the same teach block
                if (allowFigure && block.get("figure") instanceof Map<?, ?> fig) {
                    out.put("figure", sanitizeAllowedMap(fig, SAFE_FIGURE_KEYS));
                } else if (block.get("image") instanceof Map<?, ?> img) {
                    out.put("image", sanitizeAllowedMap(img, SAFE_IMAGE_KEYS));
                }
            }
            case "mc" -> {
                out.put("question", String.valueOf(block.getOrDefault("question", "")));
                Object opts = block.get("options");
                out.put("options", opts instanceof List<?> l ? new ArrayList<>(l) : List.of());
                if (block.get("format") != null) out.put("format", String.valueOf(block.get("format")));
                if (block.get("display") != null) out.put("display", String.valueOf(block.get("display")));
                if (block.get("steps") instanceof List<?> s) out.put("steps", toStringList(s));
                if (block.get("context") != null) out.put("context", String.valueOf(block.get("context")));
                // answerIndex & outcomes are STRICTLY stripped from GET /v1/lessons/{id}!
            }
            case "blank" -> {
                boolean allowMulti = clientCaps == null || clientCaps.contains("multi_blank") || clientCaps.contains("blank");
                if (allowMulti && isMultiBlank(block)) {
                    List<String> parts = toStringList(block.get("parts"));
                    List<String> answers = toStringList(block.get("answers"));
                    List<String> bankRaw = toStringList(block.get("bank"));
                    LinkedHashSet<String> mergedBank = new LinkedHashSet<>(bankRaw);
                    mergedBank.addAll(answers);
                    List<String> shuffledBank = shuffled(new ArrayList<>(mergedBank), lessonId, contentVersion, blockIndex);
                    out.put("mode", "multi_bank");
                    out.put("parts", parts);
                    out.put("blankCount", answers.size());
                    out.put("bank", shuffledBank);
                    out.put("sentence", String.join(" ____ ", parts));
                    // `answers` and `answer` are STRICTLY stripped!
                } else {
                    out.put("sentence", String.valueOf(block.getOrDefault("sentence", "")));
                }
            }
            case "short" -> {
                out.put("question", String.valueOf(block.getOrDefault("question", "")));
                if (block.get("format") != null) out.put("format", String.valueOf(block.get("format")));
                if (block.get("hint") != null) out.put("hint", String.valueOf(block.get("hint")));
                // `acceptedAnswers`, `keyPoints`, `rubric` are STRICTLY stripped!
            }
            case "order" -> {
                List<String> orig = toStringList(block.get("items"));
                List<String> shuf = shuffled(orig, lessonId, contentVersion, blockIndex);
                List<Map<String, Object>> idItems = new ArrayList<>();
                for (int i = 0; i < shuf.size(); i++) {
                    idItems.add(Map.of("id", i, "text", shuf.get(i)));
                }
                out.put("prompt", String.valueOf(block.getOrDefault("prompt", "")));
                out.put("items", idItems);
            }
            case "match" -> {
                List<List<String>> pairs = toPairs(block.get("pairs"));
                List<String> lefts = pairs.stream().map(p -> p.get(0)).toList();
                List<String> rights = pairs.stream().map(p -> p.get(1)).toList();
                List<String> shufRights = shuffled(rights, lessonId, contentVersion, blockIndex);
                List<Map<String, Object>> leftObjs = new ArrayList<>();
                List<Map<String, Object>> rightObjs = new ArrayList<>();
                for (int i = 0; i < lefts.size(); i++) {
                    leftObjs.add(Map.of("id", i, "text", lefts.get(i)));
                }
                for (int i = 0; i < shufRights.size(); i++) {
                    rightObjs.add(Map.of("id", i, "text", shufRights.get(i)));
                }
                out.put("prompt", String.valueOf(block.getOrDefault("prompt", "")));
                out.put("lefts", leftObjs);
                out.put("rights", rightObjs);
            }
            case "speed" -> {
                out.put("prompt", String.valueOf(block.getOrDefault("prompt", "")));
                int limit = block.get("timeLimitSeconds") instanceof Number n ? Math.max(15, Math.min(180, n.intValue())) : 60;
                out.put("timeLimitSeconds", limit);
                List<Map<String, Object>> publicItems = new ArrayList<>();
                if (block.get("items") instanceof List<?> rawItems) {
                    int idx = 0;
                    for (Object rawItem : rawItems) {
                        if (rawItem instanceof Map<?, ?> itemMap) {
                            Map<String, Object> pub = new LinkedHashMap<>();
                            pub.put("id", idx++);
                            pub.put("prompt", String.valueOf(itemMap.get("prompt") != null ? itemMap.get("prompt") : ""));
                            pub.put("choices", toStringList(itemMap.get("choices")));
                            // `answerIndex` is STRICTLY stripped!
                            publicItems.add(pub);
                        }
                    }
                }
                out.put("items", publicItems);
            }
            case "recap" -> {
                out.put("title", String.valueOf(block.getOrDefault("title", "")));
                out.put("points", toStringList(block.get("points")));
                if (block.get("sources") instanceof List<?> srcs) {
                    out.put("sources", new ArrayList<>(srcs));
                } else {
                    out.put("sources", List.of());
                }
            }
            default -> {
                // Unknown block type: expose type only, never private fields.
            }
        }
        return out;
    }

    public List<Map<String, Object>> toPublicBlocks(UUID lessonId, int contentVersion, List<Map<String, Object>> blocks) {
        return toPublicBlocks(lessonId, contentVersion, blocks, null);
    }

    public List<Map<String, Object>> toPublicBlocks(
            UUID lessonId,
            int contentVersion,
            List<Map<String, Object>> blocks,
            Set<String> clientCaps
    ) {
        if (blocks == null) return List.of();
        List<Map<String, Object>> result = new ArrayList<>(blocks.size());
        for (int i = 0; i < blocks.size(); i++) {
            result.add(toPublicBlock(lessonId, contentVersion, i, blocks.get(i), clientCaps));
        }
        return result;
    }

    public boolean gradeBlock(UUID lessonId, int contentVersion, int blockIndex, Map<String, Object> block, Object answer) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        return switch (type) {
            case "mc" -> gradeMc(block, answer);
            case "blank" -> gradeBlank(block, answer);
            case "order" -> gradeOrder(lessonId, contentVersion, blockIndex, block, answer);
            case "match" -> gradeMatch(lessonId, contentVersion, blockIndex, block, answer);
            case "short" -> gradeShortExact(block, answer) || gradeShortSemantic(block, answer);
            case "speed" -> gradeSpeed(block, answer);
            default -> false;
        };
    }

    public boolean gradeMc(Map<String, Object> block, Object answer) {
        if (answer instanceof Boolean || !(answer instanceof Number num)) {
            return false;
        }
        Object ansIdxObj = block.get("answerIndex");
        if (!(ansIdxObj instanceof Number expected)) return false;
        return num.intValue() == expected.intValue();
    }

    public String selectedOutcomeFor(Map<String, Object> block, Object answer) {
        if (!"mc".equals(String.valueOf(block.getOrDefault("type", "")))) return null;
        if (answer instanceof Boolean || !(answer instanceof Number num)) return null;
        List<String> outcomes = toStringList(block.get("outcomes"));
        int idx = num.intValue();
        if (idx < 0 || idx >= outcomes.size()) return null;
        String text = outcomes.get(idx);
        return text.isBlank() ? null : text;
    }

    public boolean gradeBlank(Map<String, Object> block, Object answer) {
        if (isMultiBlank(block)) {
            List<String> expected = toStringList(block.get("answers"));
            if (!(answer instanceof List<?> given) || given.size() != expected.size()) {
                return false;
            }
            for (int i = 0; i < expected.size(); i++) {
                String val = given.get(i) == null ? "" : String.valueOf(given.get(i));
                if (!normalizeSimple(val).equals(normalizeSimple(expected.get(i)))) {
                    return false;
                }
            }
            return true;
        }
        if (!(answer instanceof String s)) return false;
        String expected = String.valueOf(block.getOrDefault("answer", ""));
        return !expected.isBlank() && normalizeSimple(s).equals(normalizeSimple(expected));
    }

    public boolean gradeOrder(UUID lessonId, int contentVersion, int blockIndex, Map<String, Object> block, Object answer) {
        if (!(answer instanceof List<?> list)) return false;
        List<String> orig = toStringList(block.get("items"));
        if (list.size() != orig.size()) return false;
        List<String> shuf = shuffled(orig, lessonId, contentVersion, blockIndex);
        List<String> chosen = new ArrayList<>(orig.size());
        Set<Integer> seen = new HashSet<>();
        for (Object item : list) {
            if (item instanceof Boolean || !(item instanceof Number num)) return false;
            int id = num.intValue();
            if (id < 0 || id >= shuf.size() || !seen.add(id)) return false;
            chosen.add(shuf.get(id));
        }
        return chosen.equals(orig);
    }

    public boolean gradeMatch(UUID lessonId, int contentVersion, int blockIndex, Map<String, Object> block, Object answer) {
        if (!(answer instanceof Map<?, ?> map)) return false;
        List<List<String>> pairs = toPairs(block.get("pairs"));
        if (map.size() != pairs.size()) return false;
        List<String> rights = pairs.stream().map(p -> p.get(1)).toList();
        List<String> shufRights = shuffled(rights, lessonId, contentVersion, blockIndex);

        Set<Integer> usedRightIds = new HashSet<>();
        for (int leftIdx = 0; leftIdx < pairs.size(); leftIdx++) {
            Object rawVal = map.containsKey(String.valueOf(leftIdx))
                    ? map.get(String.valueOf(leftIdx))
                    : map.get(leftIdx);
            if (rawVal instanceof Boolean || !(rawVal instanceof Number num)) return false;
            int rightIdx = num.intValue();
            if (rightIdx < 0 || rightIdx >= shufRights.size() || !usedRightIds.add(rightIdx)) return false;
            if (!shufRights.get(rightIdx).equals(pairs.get(leftIdx).get(1))) {
                return false;
            }
        }
        return true;
    }

    public boolean gradeSpeed(Map<String, Object> block, Object answer) {
        if (!(answer instanceof List<?> given)) return false;
        List<Integer> expected = speedAnswerIndices(block);
        if (expected.isEmpty() || given.size() != expected.size()) return false;
        int correct = 0;
        for (int i = 0; i < expected.size(); i++) {
            Object g = given.get(i);
            if (g instanceof Number n && !(g instanceof Boolean) && n.intValue() == expected.get(i)) {
                correct++;
            }
        }
        return correct * 100 >= expected.size() * 70;
    }

    /**
     * Returns indices of sub-items the learner answered correctly so the UI can lock
     * already-correct slots on retry without leaking the remaining answers.
     */
    public List<Integer> computeCorrectIndices(
            UUID lessonId,
            int contentVersion,
            int blockIndex,
            Map<String, Object> block,
            Object answer
    ) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        List<Integer> out = new ArrayList<>();
        switch (type) {
            case "blank" -> {
                if (isMultiBlank(block) && answer instanceof List<?> given) {
                    List<String> expected = toStringList(block.get("answers"));
                    int n = Math.min(expected.size(), given.size());
                    for (int i = 0; i < n; i++) {
                        String val = given.get(i) == null ? "" : String.valueOf(given.get(i));
                        if (normalizeSimple(val).equals(normalizeSimple(expected.get(i)))) {
                            out.add(i);
                        }
                    }
                }
            }
            case "order" -> {
                if (answer instanceof List<?> list) {
                    List<String> orig = toStringList(block.get("items"));
                    List<String> shuf = shuffled(orig, lessonId, contentVersion, blockIndex);
                    int n = Math.min(orig.size(), list.size());
                    for (int i = 0; i < n; i++) {
                        Object item = list.get(i);
                        if (item instanceof Number num && !(item instanceof Boolean)) {
                            int id = num.intValue();
                            if (id >= 0 && id < shuf.size() && shuf.get(id).equals(orig.get(i))) {
                                out.add(i);
                            }
                        }
                    }
                }
            }
            case "match" -> {
                if (answer instanceof Map<?, ?> map) {
                    List<List<String>> pairs = toPairs(block.get("pairs"));
                    List<String> rights = pairs.stream().map(p -> p.get(1)).toList();
                    List<String> shufRights = shuffled(rights, lessonId, contentVersion, blockIndex);
                    for (int leftIdx = 0; leftIdx < pairs.size(); leftIdx++) {
                        Object rawVal = map.containsKey(String.valueOf(leftIdx))
                                ? map.get(String.valueOf(leftIdx))
                                : map.get(leftIdx);
                        if (rawVal instanceof Number num && !(rawVal instanceof Boolean)) {
                            int rightIdx = num.intValue();
                            if (rightIdx >= 0 && rightIdx < shufRights.size()
                                    && shufRights.get(rightIdx).equals(pairs.get(leftIdx).get(1))) {
                                out.add(leftIdx);
                            }
                        }
                    }
                }
            }
            case "speed" -> {
                if (answer instanceof List<?> given) {
                    List<Integer> expected = speedAnswerIndices(block);
                    int n = Math.min(expected.size(), given.size());
                    for (int i = 0; i < n; i++) {
                        Object g = given.get(i);
                        if (g instanceof Number num && !(g instanceof Boolean) && num.intValue() == expected.get(i)) {
                            out.add(i);
                        }
                    }
                }
            }
            default -> {}
        }
        return out;
    }

    public ShortGradeVerdict evaluateShortThreeLevel(Map<String, Object> block, Object answer) {
        String rawAnswer = answer instanceof String s ? s.trim() : "";
        List<String> keyPoints = toStringList(block.get("keyPoints"));
        List<String> matchedPoints = findMatchedKeyPoints(rawAnswer, keyPoints);

        if (gradeShortExact(block, rawAnswer)) {
            return new ShortGradeVerdict(
                    "got_it",
                    true,
                    "deterministic",
                    "Chính xác!",
                    keyPoints.isEmpty() ? matchedPoints : keyPoints
            );
        }
        if (gradeShortSemantic(block, rawAnswer)) {
            return new ShortGradeVerdict(
                    "got_it",
                    true,
                    "semantic_rubric",
                    "Chính xác — câu trả lời khớp với ý chính theo tiêu chí chấm.",
                    keyPoints.isEmpty() ? matchedPoints : keyPoints
            );
        }

        // Check partial overlap -> `almost`
        if (!keyPoints.isEmpty() && !matchedPoints.isEmpty()) {
            return new ShortGradeVerdict(
                    "almost",
                    false,
                    "semantic_rubric",
                    "Gần đúng rồi! Bạn đã chạm được một phần ý chính — hãy bổ sung thêm để trọn vẹn hoặc bấm 'Yêu cầu chấm lại'.",
                    matchedPoints
            );
        }
        if (hasPartialSemanticOverlap(block, rawAnswer)) {
            return new ShortGradeVerdict(
                    "almost",
                    false,
                    "semantic_rubric",
                    "Gần đúng — câu trả lời có ý liên quan nhưng chưa đủ rõ ràng.",
                    matchedPoints
            );
        }

        return new ShortGradeVerdict(
                "not_yet",
                false,
                "deterministic",
                "Chưa khớp đáp án mẫu. Bạn có thể bấm 'Yêu cầu chấm lại' nếu câu trả lời đúng ý.",
                List.of()
        );
    }

    public boolean gradeShortExact(Map<String, Object> block, Object answer) {
        if (!(answer instanceof String s) || s.isBlank()) return false;
        String normAns = normalizeSimple(s);
        for (String acc : toStringList(block.get("acceptedAnswers"))) {
            if (!acc.isBlank() && normalizeSimple(acc).equals(normAns)) {
                return true;
            }
        }
        return false;
    }

    public boolean gradeShortSemantic(Map<String, Object> block, Object answer) {
        if (!(answer instanceof String s) || s.isBlank()) return false;
        List<String> ansTokens = foldTokens(s);
        if (ansTokens.isEmpty()) return false;
        String ansJoined = String.join(" ", ansTokens);
        Set<String> ansSet = new HashSet<>(ansTokens);

        for (String acc : toStringList(block.get("acceptedAnswers"))) {
            List<String> accTokens = foldTokens(acc);
            if (accTokens.isEmpty()) continue;
            if (String.join(" ", accTokens).equals(ansJoined)) return true;
            if (accTokens.size() >= 2) {
                Set<String> accSet = new HashSet<>(accTokens);
                long overlap = accSet.stream().filter(ansSet::contains).count();
                double recall = (double) overlap / accSet.size();
                double precision = (double) overlap / ansSet.size();
                if (recall >= 0.8 && precision >= 0.5) return true;
            }
        }
        return false;
    }

    private boolean hasPartialSemanticOverlap(Map<String, Object> block, String answer) {
        List<String> ansTokens = foldTokens(answer);
        if (ansTokens.isEmpty()) return false;
        Set<String> ansSet = new HashSet<>(ansTokens);
        for (String acc : toStringList(block.get("acceptedAnswers"))) {
            List<String> accTokens = foldTokens(acc);
            if (accTokens.size() < 2) continue;
            Set<String> accSet = new HashSet<>(accTokens);
            long overlap = accSet.stream().filter(ansSet::contains).count();
            double recall = (double) overlap / accSet.size();
            if (recall >= 0.4) return true;
        }
        return false;
    }

    private List<String> findMatchedKeyPoints(String answer, List<String> keyPoints) {
        if (answer == null || answer.isBlank() || keyPoints.isEmpty()) return List.of();
        Set<String> ansSet = new HashSet<>(foldTokens(answer));
        if (ansSet.isEmpty()) return List.of();
        List<String> matched = new ArrayList<>();
        for (String kp : keyPoints) {
            List<String> kpTokens = foldTokens(kp);
            if (kpTokens.isEmpty()) continue;
            long hits = kpTokens.stream().filter(ansSet::contains).count();
            if ((double) hits / kpTokens.size() >= 0.5) {
                matched.add(kp);
            }
        }
        return matched;
    }

    public Map<String, Object> solutionFor(Map<String, Object> block) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        Map<String, Object> sol = new LinkedHashMap<>();
        switch (type) {
            case "mc" -> {
                List<String> options = toStringList(block.get("options"));
                int idx = block.get("answerIndex") instanceof Number n ? n.intValue() : -1;
                sol.put("answerIndex", idx);
                sol.put("answerText", (idx >= 0 && idx < options.size()) ? options.get(idx) : null);
            }
            case "blank" -> {
                if (isMultiBlank(block)) {
                    sol.put("answers", toStringList(block.get("answers")));
                } else {
                    sol.put("answer", String.valueOf(block.getOrDefault("answer", "")));
                }
            }
            case "short" -> {
                sol.put("acceptedAnswers", toStringList(block.get("acceptedAnswers")));
                List<String> kps = toStringList(block.get("keyPoints"));
                if (!kps.isEmpty()) sol.put("keyPoints", kps);
            }
            case "order" -> sol.put("order", toStringList(block.get("items")));
            case "match" -> sol.put("pairs", toPairs(block.get("pairs")));
            case "speed" -> sol.put("answerIndices", speedAnswerIndices(block));
            default -> {}
        }
        return sol;
    }

    public static boolean isCompleted(int correct, int total) {
        return total > 0 && correct * 100 >= total * COMPLETION_THRESHOLD_PERCENT;
    }

    private static List<Integer> speedAnswerIndices(Map<String, Object> block) {
        List<Integer> out = new ArrayList<>();
        if (block.get("items") instanceof List<?> rawItems) {
            for (Object raw : rawItems) {
                if (raw instanceof Map<?, ?> m && m.get("answerIndex") instanceof Number n) {
                    out.add(n.intValue());
                } else {
                    out.add(-1);
                }
            }
        }
        return out;
    }

    private static List<Map<String, Object>> sanitizeTerms(List<?> rawTerms) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object item : rawTerms) {
            if (item instanceof Map<?, ?> m) {
                Map<String, Object> clean = new LinkedHashMap<>();
                if (m.get("term") != null) clean.put("term", String.valueOf(m.get("term")));
                if (m.get("termKey") != null) clean.put("termKey", String.valueOf(m.get("termKey")));
                if (m.get("definition") != null) clean.put("definition", String.valueOf(m.get("definition")));
                if (m.get("example") != null) clean.put("example", String.valueOf(m.get("example")));
                if (!clean.isEmpty()) out.add(clean);
            }
        }
        return out;
    }

    private static Map<String, Object> sanitizeCite(Map<?, ?> raw) {
        Map<String, Object> clean = new LinkedHashMap<>();
        for (String key : List.of("sourceId", "label", "url", "anchor", "pageNumber", "sourceTitle")) {
            if (raw.get(key) != null) clean.put(key, raw.get(key));
        }
        return clean;
    }

    private static Map<String, Object> sanitizeAllowedMap(Map<?, ?> raw, Set<String> allowedKeys) {
        Map<String, Object> clean = new LinkedHashMap<>();
        for (Map.Entry<?, ?> e : raw.entrySet()) {
            String k = String.valueOf(e.getKey());
            if (allowedKeys.contains(k) && e.getValue() != null) {
                clean.put(k, e.getValue());
            }
        }
        return clean;
    }

    private static String normalizeSimple(String text) {
        return text == null ? "" : text.trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", " ");
    }

    private static List<String> foldTokens(String text) {
        if (text == null) return List.of();
        String raw = text.trim().toLowerCase(Locale.ROOT).replace('đ', 'd');
        String nfkd = Normalizer.normalize(raw, Normalizer.Form.NFKD).replaceAll("\\p{M}+", "");
        String cleaned = nfkd.replaceAll("[^\\p{L}\\p{N}\\s]+", " ").trim();
        if (cleaned.isEmpty()) return List.of();
        return List.of(cleaned.split("\\s+"));
    }

    private static List<String> toStringList(Object raw) {
        if (!(raw instanceof List<?> list)) return List.of();
        return list.stream().map(String::valueOf).toList();
    }

    private static List<List<String>> toPairs(Object raw) {
        if (!(raw instanceof List<?> list)) return List.of();
        List<List<String>> pairs = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof List<?> pair && pair.size() >= 2) {
                pairs.add(List.of(String.valueOf(pair.get(0)), String.valueOf(pair.get(1))));
            }
        }
        return pairs;
    }
}
