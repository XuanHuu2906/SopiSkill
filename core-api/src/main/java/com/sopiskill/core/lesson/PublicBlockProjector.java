package com.sopiskill.core.lesson;

import com.sopiskill.core.config.SopiProperties;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
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
 * with server-secret HMAC-SHA256 deterministic shuffling, and performs
 * 100% server-authoritative grading.
 */
@Component
public class PublicBlockProjector {

    public static final int COMPLETION_THRESHOLD_PERCENT = 80;

    private final byte[] shuffleKey;

    public PublicBlockProjector(SopiProperties props) {
        String raw = props.lessonShuffleSecret();
        if (raw == null || raw.isBlank()) {
            raw = props.jwtSecret();
        }
        this.shuffleKey = raw.getBytes(StandardCharsets.UTF_8);
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

    @SuppressWarnings("unchecked")
    public Map<String, Object> toPublicBlock(UUID lessonId, int contentVersion, int blockIndex, Map<String, Object> block) {
        String type = String.valueOf(block.getOrDefault("type", ""));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("type", type);

        switch (type) {
            case "teach" -> {
                out.put("title", String.valueOf(block.getOrDefault("title", "")));
                Object paras = block.get("paragraphs");
                out.put("paragraphs", paras instanceof List<?> l ? new ArrayList<>(l) : List.of());
            }
            case "mc" -> {
                out.put("question", String.valueOf(block.getOrDefault("question", "")));
                Object opts = block.get("options");
                out.put("options", opts instanceof List<?> l ? new ArrayList<>(l) : List.of());
            }
            case "blank" -> out.put("sentence", String.valueOf(block.getOrDefault("sentence", "")));
            case "short" -> out.put("question", String.valueOf(block.getOrDefault("question", "")));
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
            default -> {
                // Unknown block type: expose type only, never private fields.
            }
        }
        return out;
    }

    public List<Map<String, Object>> toPublicBlocks(UUID lessonId, int contentVersion, List<Map<String, Object>> blocks) {
        if (blocks == null) return List.of();
        List<Map<String, Object>> result = new ArrayList<>(blocks.size());
        for (int i = 0; i < blocks.size(); i++) {
            result.add(toPublicBlock(lessonId, contentVersion, i, blocks.get(i)));
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

    public boolean gradeBlank(Map<String, Object> block, Object answer) {
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
            case "blank" -> sol.put("answer", String.valueOf(block.getOrDefault("answer", "")));
            case "short" -> sol.put("acceptedAnswers", toStringList(block.get("acceptedAnswers")));
            case "order" -> sol.put("order", toStringList(block.get("items")));
            case "match" -> sol.put("pairs", toPairs(block.get("pairs")));
            default -> {}
        }
        return sol;
    }

    public static boolean isCompleted(int correct, int total) {
        return total > 0 && correct * 100 >= total * COMPLETION_THRESHOLD_PERCENT;
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
