package com.sopiskill.core.course;

import com.sopiskill.core.common.ApiException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;

/**
 * Structured topic admission guard returning `422 TOPIC_REJECTED` with canonical `reason`
 * (`unsafe | too_vague | not_teachable | too_narrow`) and optional `suggestedRephrase`.
 */
public final class TopicGuard {

    private static final Pattern YOUTUBE_URL = Pattern.compile("(?i)(?:https?://)?(?:www\\.|m\\.)?(?:youtube\\.com|youtu\\.be)/");
    private static final List<String> UNSAFE_TERMS = List.of(
            "build a bomb", "make a bomb", "make explosives", "ransomware source", "steal passwords",
            "self-harm", "how to hack bank", "tạo mã độc", "tấn công ddos"
    );
    private static final List<String> VAGUE_EXACT = List.of(
            "test", "abc", "xyz", "hello", "hi", "yes", "no", "anything", "something", "learn", "study",
            "học", "gì cũng được", "không biết", "???"
    );

    private TopicGuard() {}

    public static void validateOrThrow(String rawTopic) {
        String topic = rawTopic == null ? "" : rawTopic.trim();
        String lower = topic.toLowerCase(Locale.ROOT);

        if (YOUTUBE_URL.matcher(topic).find()) {
            reject(
                    "not_teachable",
                    "SopiSkill chưa hỗ trợ nhập trực tiếp link YouTube. Hãy nêu tên chủ đề hoặc tải tài liệu PDF lên.",
                    "Nhập tên chủ đề chính của video (ví dụ: \"Cơ chế Attention trong Transformer\")"
            );
        }

        for (String bad : UNSAFE_TERMS) {
            if (lower.contains(bad)) {
                reject(
                        "unsafe",
                        "Chủ đề này không phù hợp với chính sách an toàn học tập.",
                        "An toàn thông tin phòng thủ và bảo mật hệ thống cơ bản"
                );
            }
        }

        if (topic.length() < 3 || VAGUE_EXACT.contains(lower)) {
            reject(
                    "too_vague",
                    "Chủ đề quá chung chung để lập lộ trình học cụ thể.",
                    "Python cho người mới bắt đầu"
            );
        }

        if (lower.startsWith("what year was ") || lower.startsWith("who won ") || lower.startsWith("mấy giờ rồi")) {
            reject(
                    "too_narrow",
                    "Chủ đề này chỉ là một câu hỏi tra cứu đơn lẻ thay vì một kỹ năng có thể luyện tập.",
                    "Lịch sử phát triển và khái niệm cốt lõi liên quan đến chủ đề này"
            );
        }
    }

    private static void reject(String reason, String message, String suggestedRephrase) {
        Map<String, Object> extra = new LinkedHashMap<>();
        extra.put("reason", reason);
        if (suggestedRephrase != null) {
            extra.put("suggestedRephrase", suggestedRephrase);
        }
        throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TOPIC_REJECTED", message, extra);
    }
}
