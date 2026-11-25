package com.sopiskill.core.internal;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.config.SopiProperties;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

/**
 * Signs outgoing `core-api -> ai-engine` requests and verifies incoming `ai-worker -> core-api`
 * callbacks using the exact canonical HMAC-SHA256 replay-protection contract from
 * `contracts/internal-ai.yaml`.
 */
@Component
public class InternalHmacSigner {

    public static final String HEADER_TOKEN = "X-Internal-Service-Token";
    public static final String HEADER_TIMESTAMP = "X-Internal-Timestamp";
    public static final String HEADER_SIGNATURE = "X-Internal-Signature";
    public static final String HEADER_CORRELATION = "X-Correlation-Id";

    private final SopiProperties props;

    public InternalHmacSigner(SopiProperties props) {
        this.props = props;
    }

    public String sha256Hex(byte[] rawBody) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(rawBody == null ? new byte[0] : rawBody));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public String computeSignature(String timestamp, String method, String pathWithQuery, byte[] rawBody) {
        String canonical = timestamp + "." + method.toUpperCase() + "." + pathWithQuery + "." + sha256Hex(rawBody);
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(props.internalHmacSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] digest = mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8));
            return "sha256=" + HexFormat.of().formatHex(digest);
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public Map<String, String> signHeaders(String method, String pathWithQuery, byte[] rawBody, String correlationId) {
        String ts = String.valueOf(Instant.now().getEpochSecond());
        String cid = (correlationId == null || correlationId.isBlank())
                ? "cor_" + UUID.randomUUID().toString().replace("-", "").substring(0, 16)
                : correlationId;
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put(HEADER_TOKEN, props.internalServiceToken());
        headers.put(HEADER_TIMESTAMP, ts);
        headers.put(HEADER_SIGNATURE, computeSignature(ts, method, pathWithQuery, rawBody));
        headers.put(HEADER_CORRELATION, cid);
        return headers;
    }

    public void verifyIncomingCallback(HttpServletRequest request, byte[] rawBody) {
        String token = request.getHeader(HEADER_TOKEN);
        String tsRaw = request.getHeader(HEADER_TIMESTAMP);
        String sig = request.getHeader(HEADER_SIGNATURE);

        if (token == null || !MessageDigest.isEqual(
                token.trim().getBytes(StandardCharsets.UTF_8),
                props.internalServiceToken().getBytes(StandardCharsets.UTF_8)
        )) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INTERNAL_AUTH_INVALID", "Invalid internal service token.");
        }

        if (tsRaw == null || tsRaw.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INTERNAL_TIMESTAMP_MISSING", "Missing X-Internal-Timestamp.");
        }
        long ts;
        try {
            ts = Long.parseLong(tsRaw.trim());
        } catch (NumberFormatException ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INTERNAL_TIMESTAMP_INVALID", "Invalid X-Internal-Timestamp.");
        }

        long now = Instant.now().getEpochSecond();
        if (Math.abs(now - ts) > Math.max(1L, props.internalMaxClockSkewSeconds())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INTERNAL_TIMESTAMP_EXPIRED", "Timestamp outside replay window.");
        }

        String pathWithQuery = request.getRequestURI()
                + (request.getQueryString() != null ? "?" + request.getQueryString() : "");
        String expectedSig = computeSignature(String.valueOf(ts), request.getMethod(), pathWithQuery, rawBody);
        if (sig == null || !MessageDigest.isEqual(
                sig.trim().toLowerCase().getBytes(StandardCharsets.UTF_8),
                expectedSig.toLowerCase().getBytes(StandardCharsets.UTF_8)
        )) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INTERNAL_SIGNATURE_INVALID", "HMAC verification failed.");
        }
    }
}
