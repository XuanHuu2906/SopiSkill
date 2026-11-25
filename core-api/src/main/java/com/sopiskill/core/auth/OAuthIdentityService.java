package com.sopiskill.core.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import java.math.BigInteger;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.spec.RSAPublicKeySpec;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Cryptographic OIDC ID Token verification for Google & Apple + anti-account-takeover linking:
 * - Verifies RS256/ES256 ID token signatures against official provider JWKS (or explicitly
 *   registered public keys in tests), validating `iss`, `aud`, `exp`, `sub`, `email`, `email_verified`.
 * - NEVER auto-links an OAuth identity to an existing email/password account: returns
 *   `409 ACCOUNT_LINK_REQUIRED` with a short-lived HMAC-signed `linkTicket` (TTL 5 minutes).
 * - Confirming link (`POST /v1/auth/link/confirm`) requires proof of ownership of the existing
 *   account (either authenticated session for `targetUserId` OR Argon2id password verification).
 */
@Service
public class OAuthIdentityService {

    private static final String GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs";
    private static final String APPLE_JWKS = "https://appleid.apple.com/auth/keys";
    private static final Set<String> GOOGLE_ISSUERS = Set.of("https://accounts.google.com", "accounts.google.com");
    private static final Set<String> APPLE_ISSUERS = Set.of("https://appleid.apple.com");
    private static final long LINK_TICKET_TTL_SECONDS = 300L;

    public record VerifiedOidcClaims(
            String provider,
            String subject,
            String email,
            boolean emailVerified,
            String displayName
    ) {}

    public record LinkTicketPayload(
            String provider,
            String subject,
            String email,
            boolean emailVerified,
            UUID targetUserId,
            long expEpochSec
    ) {}

    private final JdbcClient jdbc;
    private final SopiProperties props;
    private final PasswordEncoder passwordEncoder;
    private final ObjectMapper objectMapper;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final Map<String, PublicKey> keyCache = new ConcurrentHashMap<>();

    public OAuthIdentityService(
            JdbcClient jdbc,
            SopiProperties props,
            PasswordEncoder passwordEncoder,
            ObjectMapper objectMapper
    ) {
        this.jdbc = jdbc;
        this.props = props;
        this.passwordEncoder = passwordEncoder;
        this.objectMapper = objectMapper;
    }

    /** Registers a trusted public key (used by integration tests with real RS256 signed OIDC JWTs). */
    public void registerTrustedPublicKey(String provider, String kid, PublicKey publicKey) {
        keyCache.put(provider.toLowerCase(Locale.ROOT) + ":" + kid, publicKey);
    }

    public VerifiedOidcClaims verifyIdToken(String rawProvider, String idToken) {
        if (rawProvider == null || idToken == null || idToken.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Thiếu provider hoặc idToken.");
        }
        String provider = rawProvider.trim().toLowerCase(Locale.ROOT);
        if (!"google".equals(provider) && !"apple".equals(provider)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "UNSUPPORTED_PROVIDER", "Chỉ hỗ trợ google hoặc apple.");
        }

        String[] parts = idToken.split("\\.");
        if (parts.length != 3) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Định dạng ID Token không hợp lệ.");
        }

        String kid;
        String alg;
        try {
            byte[] headerBytes = Base64.getUrlDecoder().decode(parts[0]);
            Map<String, Object> header = objectMapper.readValue(headerBytes, new TypeReference<>() {});
            kid = String.valueOf(header.getOrDefault("kid", ""));
            alg = String.valueOf(header.getOrDefault("alg", ""));
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Header ID Token không hợp lệ.");
        }

        // Explicitly reject alg=none or symmetric HS* downgrade attacks!
        if ("none".equalsIgnoreCase(alg) || alg.toUpperCase(Locale.ROOT).startsWith("HS") || kid.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Thuật toán ký ID Token không được phép.");
        }

        PublicKey key = resolvePublicKey(provider, kid);
        if (key == null) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Không xác minh được khóa ký của nhà cung cấp.");
        }

        Claims claims;
        try {
            claims = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(idToken)
                    .getPayload();
        } catch (JwtException | IllegalArgumentException ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Chữ ký ID Token không hợp lệ hoặc đã hết hạn.");
        }

        String iss = claims.getIssuer();
        Set<String> allowedIssuers = "google".equals(provider) ? GOOGLE_ISSUERS : APPLE_ISSUERS;
        if (iss == null || !allowedIssuers.contains(iss)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Issuer ID Token không khớp.");
        }

        String expectedAud = "google".equals(provider) ? props.googleClientId() : props.appleClientId();
        Set<String> auds = claims.getAudience();
        if (expectedAud != null && !expectedAud.isBlank() && (auds == null || !auds.contains(expectedAud))) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "Audience ID Token không khớp.");
        }

        String sub = claims.getSubject();
        String email = claims.get("email", String.class);
        Object evRaw = claims.get("email_verified");
        boolean emailVerified = Boolean.TRUE.equals(evRaw) || "true".equalsIgnoreCase(String.valueOf(evRaw));
        String name = claims.get("name", String.class);

        if (sub == null || sub.isBlank() || email == null || email.isBlank()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_ID_TOKEN", "ID Token thiếu thông tin định danh (sub/email).");
        }
        String normalizedEmail = email.trim().toLowerCase(Locale.ROOT);
        if (name == null || name.isBlank()) {
            int at = normalizedEmail.indexOf('@');
            name = at > 0 ? normalizedEmail.substring(0, at) : "Người học";
        }
        return new VerifiedOidcClaims(provider, sub.trim(), normalizedEmail, emailVerified, name.trim());
    }

    @Transactional
    public Map<String, Object> exchange(String provider, String idToken) {
        VerifiedOidcClaims claims = verifyIdToken(provider, idToken);

        // 1. Existing linked identity -> direct login
        var linkedUserOpt = jdbc.sql("""
                SELECT u.id, u.email, u.display_name, u.xp
                FROM core.auth_identities ai
                JOIN core.users u ON u.id = ai.user_id
                WHERE ai.provider = :provider AND ai.provider_subject = :sub
                """)
                .param("provider", claims.provider())
                .param("sub", claims.subject())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "userId", rs.getObject("id", UUID.class),
                        "email", rs.getString("email"),
                        "displayName", rs.getString("display_name"),
                        "xp", rs.getInt("xp"),
                        "created", false
                ))
                .optional();

        if (linkedUserOpt.isPresent()) {
            return linkedUserOpt.get();
        }

        // 2. Email already belongs to an existing user -> NEVER auto-link! Require explicit link confirmation!
        var existingEmailOpt = jdbc.sql("""
                SELECT id, email
                FROM core.users
                WHERE lower(email) = :email
                """)
                .param("email", claims.email())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "email", rs.getString("email")
                ))
                .optional();

        if (existingEmailOpt.isPresent()) {
            UUID targetUserId = (UUID) existingEmailOpt.get().get("id");
            String ticket = signLinkTicket(new LinkTicketPayload(
                    claims.provider(),
                    claims.subject(),
                    claims.email(),
                    claims.emailVerified(),
                    targetUserId,
                    Instant.now().plusSeconds(LINK_TICKET_TTL_SECONDS).getEpochSecond()
            ));
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "ACCOUNT_LINK_REQUIRED",
                    "Email này đã tồn tại trên SopiSkill. Vui lòng xác nhận mật khẩu tài khoản hiện có để liên kết " + claims.provider() + ".",
                    Map.of(
                            "linkTicket", ticket,
                            "provider", claims.provider(),
                            "email", claims.email(),
                            "expiresInSeconds", LINK_TICKET_TTL_SECONDS
                    )
            );
        }

        // 3. Brand new user -> create account + auth_identity
        UUID newUserId = UUID.randomUUID();
        String displayName = claims.displayName().substring(0, Math.min(claims.displayName().length(), 80));
        jdbc.sql("""
                INSERT INTO core.users (id, email, password_hash, display_name, xp, streak_days)
                VALUES (:id, :email, '', :name, 0, 0)
                """)
                .param("id", newUserId)
                .param("email", claims.email())
                .param("name", displayName)
                .update();

        jdbc.sql("""
                INSERT INTO core.auth_identities (id, user_id, provider, provider_subject, email, email_verified)
                VALUES (:id, :uid, :provider, :sub, :email, :verified)
                """)
                .param("id", UUID.randomUUID())
                .param("uid", newUserId)
                .param("provider", claims.provider())
                .param("sub", claims.subject())
                .param("email", claims.email())
                .param("verified", claims.emailVerified())
                .update();

        return Map.of(
                "userId", newUserId,
                "email", claims.email(),
                "displayName", displayName,
                "xp", 0,
                "created", true
        );
    }

    @Transactional
    public Map<String, Object> confirmLink(String linkTicket, String password, UUID authenticatedUserId) {
        LinkTicketPayload payload = verifyLinkTicket(linkTicket);

        var userRow = jdbc.sql("""
                SELECT id, email, password_hash, display_name, xp
                FROM core.users
                WHERE id = :uid
                FOR UPDATE
                """)
                .param("uid", payload.targetUserId())
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "email", rs.getString("email"),
                        "passwordHash", rs.getString("password_hash") == null ? "" : rs.getString("password_hash"),
                        "displayName", rs.getString("display_name"),
                        "xp", rs.getInt("xp")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản đích không tồn tại."));

        // Anti-account-takeover proof: MUST either already be authenticated as targetUserId OR provide valid password!
        boolean provenBySession = authenticatedUserId != null && authenticatedUserId.equals(payload.targetUserId());
        String storedHash = (String) userRow.get("passwordHash");
        boolean provenByPassword = password != null && !password.isBlank()
                && !storedHash.isBlank()
                && passwordEncoder.matches(password, storedHash);

        if (!provenBySession && !provenByPassword) {
            throw new ApiException(
                    HttpStatus.UNAUTHORIZED,
                    "INVALID_CREDENTIALS",
                    "Không thể liên kết tài khoản: mật khẩu xác nhận không đúng hoặc chưa đăng nhập tài khoản đích."
            );
        }

        jdbc.sql("""
                INSERT INTO core.auth_identities (id, user_id, provider, provider_subject, email, email_verified)
                VALUES (:id, :uid, :provider, :sub, :email, :verified)
                ON CONFLICT (provider, provider_subject) DO NOTHING
                """)
                .param("id", UUID.randomUUID())
                .param("uid", payload.targetUserId())
                .param("provider", payload.provider())
                .param("sub", payload.subject())
                .param("email", payload.email())
                .param("verified", payload.emailVerified())
                .update();

        return Map.of(
                "userId", payload.targetUserId(),
                "email", userRow.get("email"),
                "displayName", userRow.get("displayName"),
                "xp", userRow.get("xp"),
                "linkedProvider", payload.provider()
        );
    }

    @Transactional
    public Map<String, Object> linkIdentityForAuthenticatedUser(UUID userId, String provider, String idToken) {
        VerifiedOidcClaims claims = verifyIdToken(provider, idToken);

        var ownerOpt = jdbc.sql("""
                SELECT user_id FROM core.auth_identities
                WHERE provider = :provider AND provider_subject = :sub
                """)
                .param("provider", claims.provider())
                .param("sub", claims.subject())
                .query(UUID.class)
                .optional();

        if (ownerOpt.isPresent() && !ownerOpt.get().equals(userId)) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "IDENTITY_ALREADY_LINKED",
                    "Tài khoản " + claims.provider() + " này đã được liên kết với người dùng khác."
            );
        }

        UUID aid = UUID.randomUUID();
        jdbc.sql("""
                INSERT INTO core.auth_identities (id, user_id, provider, provider_subject, email, email_verified)
                VALUES (:id, :uid, :provider, :sub, :email, :verified)
                ON CONFLICT (provider, provider_subject) DO NOTHING
                """)
                .param("id", aid)
                .param("uid", userId)
                .param("provider", claims.provider())
                .param("sub", claims.subject())
                .param("email", claims.email())
                .param("verified", claims.emailVerified())
                .update();

        return Map.of(
                "linked", true,
                "provider", claims.provider(),
                "email", claims.email()
        );
    }

    public List<Map<String, Object>> listIdentities(UUID userId) {
        return jdbc.sql("""
                SELECT id, provider, email, email_verified, created_at
                FROM core.auth_identities
                WHERE user_id = :uid
                ORDER BY created_at ASC
                """)
                .param("uid", userId)
                .query((rs, rowNum) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", IdCodec.format("aid", rs.getObject("id", UUID.class)));
                    m.put("provider", rs.getString("provider"));
                    m.put("email", rs.getString("email"));
                    m.put("emailVerified", rs.getBoolean("email_verified"));
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .list();
    }

    public String signLinkTicket(LinkTicketPayload payload) {
        try {
            byte[] jsonBytes = objectMapper.writeValueAsBytes(payload);
            String bodyB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(jsonBytes);
            String sigB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(hmacSha256(bodyB64));
            return bodyB64 + "." + sigB64;
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    public LinkTicketPayload verifyLinkTicket(String ticket) {
        if (ticket == null || ticket.isBlank() || !ticket.contains(".")) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_LINK_TICKET", "Link ticket không hợp lệ.");
        }
        String[] parts = ticket.split("\\.", 2);
        byte[] expectedSig = hmacSha256(parts[0]);
        byte[] providedSig;
        try {
            providedSig = Base64.getUrlDecoder().decode(parts[1]);
        } catch (IllegalArgumentException ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_LINK_TICKET", "Chữ ký link ticket không hợp lệ.");
        }
        if (!MessageDigest.isEqual(expectedSig, providedSig)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_LINK_TICKET", "Link ticket đã bị sửa đổi.");
        }
        try {
            LinkTicketPayload payload = objectMapper.readValue(
                    Base64.getUrlDecoder().decode(parts[0]),
                    LinkTicketPayload.class
            );
            if (Instant.now().getEpochSecond() > payload.expEpochSec()) {
                throw new ApiException(HttpStatus.UNAUTHORIZED, "LINK_TICKET_EXPIRED", "Link ticket đã hết hạn, vui lòng thử lại.");
            }
            return payload;
        } catch (ApiException ex) {
            throw ex;
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_LINK_TICKET", "Dữ liệu link ticket không hợp lệ.");
        }
    }

    private byte[] hmacSha256(String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            Key key = new SecretKeySpec(
                    ("link-ticket:" + props.jwtSecret()).getBytes(StandardCharsets.UTF_8),
                    "HmacSHA256"
            );
            mac.init(key);
            return mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
        } catch (Exception ex) {
            throw new IllegalStateException(ex);
        }
    }

    private PublicKey resolvePublicKey(String provider, String kid) {
        String cacheKey = provider + ":" + kid;
        PublicKey cached = keyCache.get(cacheKey);
        if (cached != null) return cached;

        String jwksUrl = "google".equals(provider) ? GOOGLE_JWKS : APPLE_JWKS;
        try {
            HttpResponse<String> resp = http.send(
                    HttpRequest.newBuilder(URI.create(jwksUrl)).timeout(Duration.ofSeconds(5)).GET().build(),
                    HttpResponse.BodyHandlers.ofString()
            );
            if (resp.statusCode() != 200) return null;
            Map<String, Object> doc = objectMapper.readValue(resp.body(), new TypeReference<>() {});
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> keys = (List<Map<String, Object>>) doc.getOrDefault("keys", List.of());
            for (Map<String, Object> jwk : keys) {
                if ("RSA".equals(jwk.get("kty")) && jwk.get("kid") != null && jwk.get("n") != null && jwk.get("e") != null) {
                    BigInteger n = new BigInteger(1, Base64.getUrlDecoder().decode(String.valueOf(jwk.get("n"))));
                    BigInteger e = new BigInteger(1, Base64.getUrlDecoder().decode(String.valueOf(jwk.get("e"))));
                    PublicKey pk = KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(n, e));
                    keyCache.put(provider + ":" + jwk.get("kid"), pk);
                }
            }
            return keyCache.get(cacheKey);
        } catch (Exception ex) {
            return null;
        }
    }
}
