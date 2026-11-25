package com.sopiskill.core.common;

import java.util.UUID;
import org.springframework.http.HttpStatus;

public final class IdCodec {

    private IdCodec() {}

    public static String format(String prefix, UUID id) {
        if (id == null) return null;
        return prefix + "_" + id;
    }

    public static UUID parse(String raw, String expectedPrefix) {
        if (raw == null || raw.isBlank()) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Không tìm thấy tài nguyên.");
        }
        String candidate = raw.trim();
        String withUnderscore = expectedPrefix + "_";
        if (candidate.startsWith(withUnderscore)) {
            candidate = candidate.substring(withUnderscore.length());
        } else if (candidate.contains("_")) {
            // Wrong prefix
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Định danh không hợp lệ.");
        }
        try {
            return UUID.fromString(candidate);
        } catch (IllegalArgumentException ex) {
            throw new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", "Không tìm thấy tài nguyên.");
        }
    }
}
