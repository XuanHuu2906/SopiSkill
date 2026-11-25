package com.sopiskill.core.auth;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.JwtService;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.http.ResponseCookie;

/**
 * Rotating HttpOnly Refresh Session manager (`core.user_sessions`).
 * - Stores only SHA-256 hashes of opaque refresh tokens.
 * - Rotates on every `/v1/auth/refresh` within the same `family_id`.
 * - Detects reuse of any already-rotated or revoked refresh token and immediately revokes the
 *   entire session family (`REFRESH_TOKEN_REUSE_DETECTED`).
 */
@Service
public class SessionService {

    public static final String REFRESH_COOKIE = "refresh_token";
    private static final SecureRandom RNG = new SecureRandom();

    private final JdbcClient jdbc;
    private final JwtService jwtService;
    private final CsrfValidator csrfValidator;
    private final SopiProperties props;

    public SessionService(
            JdbcClient jdbc,
            JwtService jwtService,
            CsrfValidator csrfValidator,
            SopiProperties props
    ) {
        this.jdbc = jdbc;
        this.jwtService = jwtService;
        this.csrfValidator = csrfValidator;
        this.props = props;
    }

    @Transactional
    public String issueNewSession(
            HttpServletRequest request,
            HttpServletResponse response,
            UUID userId,
            String email
    ) {
        UUID familyId = UUID.randomUUID();
        return createSessionInFamily(request, response, userId, email, familyId);
    }

    private String createSessionInFamily(
            HttpServletRequest request,
            HttpServletResponse response,
            UUID userId,
            String email,
            UUID familyId
    ) {
        String rawRefresh = generateOpaqueToken();
        String hash = sha256Hex(rawRefresh);
        UUID sessionId = UUID.randomUUID();
        long refreshDays = Math.max(1L, props.refreshTokenTtlDays());
        Instant expiresAt = Instant.now().plus(Duration.ofDays(refreshDays));
        String ua = request.getHeader("User-Agent");
        if (ua != null && ua.length() > 250) ua = ua.substring(0, 250);
        String ip = request.getRemoteAddr();
        if (ip != null && ip.length() > 60) ip = ip.substring(0, 60);

        jdbc.sql("""
                INSERT INTO core.user_sessions (
                    id, user_id, family_id, refresh_token_hash, user_agent, ip_address, expires_at
                ) VALUES (
                    :id, :uid, :fid, :hash, :ua, :ip, :exp
                )
                """)
                .param("id", sessionId)
                .param("uid", userId)
                .param("fid", familyId)
                .param("hash", hash)
                .param("ua", ua)
                .param("ip", ip)
                .param("exp", Timestamp.from(expiresAt))
                .update();

        writeSessionCookies(request, response, userId, email, rawRefresh, refreshDays);
        return IdCodec.format("ses", sessionId);
    }

    /**
     * Rotates the refresh token cookie. If an already-rotated or revoked refresh token is presented,
     * revokes the ENTIRE `family_id` immediately and throws `401 REFRESH_TOKEN_REUSE_DETECTED`.
     */
    @Transactional(noRollbackFor = ApiException.class)
    public Map<String, Object> rotateRefreshSession(
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        String rawRefresh = extractCookie(request, REFRESH_COOKIE);
        if (rawRefresh == null || rawRefresh.isBlank()) {
            clearSessionCookies(response);
            throw new ApiException(HttpStatus.UNAUTHORIZED, "REFRESH_TOKEN_MISSING", "Thiếu phiên làm mới.");
        }

        String hash = sha256Hex(rawRefresh);
        var rowOpt = jdbc.sql("""
                SELECT s.id, s.user_id, s.family_id, s.expires_at, s.rotated_at, s.revoked_at,
                       u.email, u.display_name, u.xp
                FROM core.user_sessions s
                JOIN core.users u ON u.id = s.user_id
                WHERE s.refresh_token_hash = :hash
                FOR UPDATE OF s
                """)
                .param("hash", hash)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("sessionId", rs.getObject("id", UUID.class));
                    m.put("userId", rs.getObject("user_id", UUID.class));
                    m.put("familyId", rs.getObject("family_id", UUID.class));
                    m.put("expiresAt", rs.getTimestamp("expires_at").toInstant());
                    m.put("rotatedAt", rs.getTimestamp("rotated_at"));
                    m.put("revokedAt", rs.getTimestamp("revoked_at"));
                    m.put("email", rs.getString("email"));
                    m.put("displayName", rs.getString("display_name"));
                    m.put("xp", rs.getInt("xp"));
                    return m;
                })
                .optional();

        if (rowOpt.isEmpty()) {
            clearSessionCookies(response);
            throw new ApiException(HttpStatus.UNAUTHORIZED, "REFRESH_TOKEN_INVALID", "Phiên làm mới không hợp lệ.");
        }

        Map<String, Object> row = rowOpt.get();
        UUID sessionId = (UUID) row.get("sessionId");
        UUID userId = (UUID) row.get("userId");
        UUID familyId = (UUID) row.get("familyId");
        Instant expiresAt = (Instant) row.get("expiresAt");
        boolean alreadyRotated = row.get("rotatedAt") != null;
        boolean alreadyRevoked = row.get("revokedAt") != null;

        if (alreadyRotated || alreadyRevoked) {
            // Security incident: stolen or replayed refresh token -> kill the ENTIRE session family!
            jdbc.sql("""
                    UPDATE core.user_sessions
                    SET revoked_at = COALESCE(revoked_at, now()),
                        reuse_detected = TRUE
                    WHERE family_id = :fid
                    """)
                    .param("fid", familyId)
                    .update();
            clearSessionCookies(response);
            throw new ApiException(
                    HttpStatus.UNAUTHORIZED,
                    "REFRESH_TOKEN_REUSE_DETECTED",
                    "Phát hiện tái sử dụng mã phiên bất thường. Toàn bộ phiên liên quan đã bị thu hồi để bảo vệ tài khoản."
            );
        }

        if (Instant.now().isAfter(expiresAt)) {
            jdbc.sql("UPDATE core.user_sessions SET revoked_at = now() WHERE id = :sid")
                    .param("sid", sessionId).update();
            clearSessionCookies(response);
            throw new ApiException(HttpStatus.UNAUTHORIZED, "REFRESH_TOKEN_EXPIRED", "Phiên đăng nhập đã hết hạn.");
        }

        // Mark current session rotated and issue successor in the same family
        jdbc.sql("UPDATE core.user_sessions SET rotated_at = now() WHERE id = :sid")
                .param("sid", sessionId)
                .update();

        String email = (String) row.get("email");
        String newSessionId = createSessionInFamily(request, response, userId, email, familyId);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("sessionId", newSessionId);
        out.put("userId", IdCodec.format("usr", userId));
        out.put("email", email);
        out.put("displayName", row.get("displayName"));
        out.put("xp", row.get("xp"));
        return out;
    }

    @Transactional
    public void revokeOnLogout(
            HttpServletRequest request,
            HttpServletResponse response,
            UUID authenticatedUserId,
            boolean revokeAllDevices
    ) {
        String rawRefresh = extractCookie(request, REFRESH_COOKIE);
        UUID targetUserId = authenticatedUserId;

        if (rawRefresh != null && !rawRefresh.isBlank()) {
            String hash = sha256Hex(rawRefresh);
            if (targetUserId == null) {
                targetUserId = jdbc.sql("SELECT user_id FROM core.user_sessions WHERE refresh_token_hash = :hash")
                        .param("hash", hash).query(UUID.class).optional().orElse(null);
            }
            if (!revokeAllDevices) {
                jdbc.sql("UPDATE core.user_sessions SET revoked_at = COALESCE(revoked_at, now()) WHERE refresh_token_hash = :hash")
                        .param("hash", hash).update();
            }
        }

        if (revokeAllDevices && targetUserId != null) {
            jdbc.sql("UPDATE core.user_sessions SET revoked_at = COALESCE(revoked_at, now()) WHERE user_id = :uid AND revoked_at IS NULL")
                    .param("uid", targetUserId).update();
        }
        clearSessionCookies(response);
    }

    public void clearSessionCookies(HttpServletResponse response) {
        ResponseCookie clearAccess = ResponseCookie.from(JwtService.ACCESS_COOKIE, "")
                .httpOnly(true).secure(props.cookieSecure()).sameSite("Lax").path("/").maxAge(0).build();
        ResponseCookie clearRefresh = ResponseCookie.from(REFRESH_COOKIE, "")
                .httpOnly(true).secure(props.cookieSecure()).sameSite("Lax").path("/v1/auth").maxAge(0).build();
        ResponseCookie clearCsrf = ResponseCookie.from(CsrfValidator.CSRF_COOKIE, "")
                .httpOnly(false).secure(props.cookieSecure()).sameSite("Lax").path("/").maxAge(0).build();
        response.addHeader(HttpHeaders.SET_COOKIE, clearAccess.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, clearRefresh.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, clearCsrf.toString());
    }

    private void writeSessionCookies(
            HttpServletRequest request,
            HttpServletResponse response,
            UUID userId,
            String email,
            String rawRefresh,
            long refreshDays
    ) {
        long accessSec = Math.max(60L, props.accessTokenTtlMinutes() * 60L);
        long refreshSec = Duration.ofDays(refreshDays).toSeconds();
        String token = jwtService.createAccessToken(userId, email);

        ResponseCookie accessCookie = ResponseCookie.from(JwtService.ACCESS_COOKIE, token)
                .httpOnly(true).secure(props.cookieSecure()).sameSite("Lax").path("/")
                .maxAge(Duration.ofSeconds(accessSec)).build();

        ResponseCookie refreshCookie = ResponseCookie.from(REFRESH_COOKIE, rawRefresh)
                .httpOnly(true).secure(props.cookieSecure()).sameSite("Lax").path("/v1/auth")
                .maxAge(Duration.ofSeconds(refreshSec)).build();

        String existingCsrf = csrfValidator.extractCookie(request, CsrfValidator.CSRF_COOKIE);
        String csrfVal = (existingCsrf != null && !existingCsrf.isBlank()) ? existingCsrf : csrfValidator.newToken();
        ResponseCookie csrfCookie = ResponseCookie.from(CsrfValidator.CSRF_COOKIE, csrfVal)
                .httpOnly(false).secure(props.cookieSecure()).sameSite("Lax").path("/")
                .maxAge(Duration.ofSeconds(refreshSec)).build();

        response.addHeader(HttpHeaders.SET_COOKIE, accessCookie.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, refreshCookie.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, csrfCookie.toString());
    }

    public static String extractCookie(HttpServletRequest request, String name) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie c : cookies) {
            if (name.equals(c.getName())) return c.getValue();
        }
        return null;
    }

    public static String sha256Hex(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(input.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private static String generateOpaqueToken() {
        byte[] bytes = new byte[32];
        RNG.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }
}
