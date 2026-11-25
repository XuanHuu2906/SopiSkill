package com.sopiskill.core.config;

import java.util.Arrays;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "sopiskill")
public record SopiProperties(
        String env,
        String corsOrigins,
        String jwtSecret,
        String jwtIssuer,
        String jwtAudience,
        long accessTokenTtlMinutes,
        boolean cookieSecure,
        String lessonShuffleSecret,
        String aiEngineUrl,
        String internalServiceToken,
        String internalHmacSecret,
        long internalMaxClockSkewSeconds,
        String streamLlmKey,
        String streamIngestKey,
        boolean tutorEnabled,
        int tutorMessagesPerDay,
        int tutorTokensPerDay,
        int tutorMaxConcurrentStreams,
        boolean ragEnabled,
        boolean p50Enabled,
        boolean rateLimitEnabled,
        boolean rateLimitFailClosed,
        String s3Endpoint,
        String s3PublicEndpoint,
        String s3AccessKey,
        String s3SecretKey,
        String s3Bucket,
        String s3Region
) {
    public List<String> corsOriginList() {
        if (corsOrigins == null || corsOrigins.isBlank()) {
            return List.of("http://localhost:3000", "http://127.0.0.1:3000");
        }
        return Arrays.stream(corsOrigins.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .toList();
    }
}
