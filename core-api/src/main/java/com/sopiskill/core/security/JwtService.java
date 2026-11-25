package com.sopiskill.core.security;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.config.SopiProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;
import javax.crypto.SecretKey;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class JwtService {

    public static final String ACCESS_COOKIE = "access_token";

    private final SopiProperties props;
    private final SecretKey signingKey;

    public JwtService(SopiProperties props) {
        this.props = props;
        byte[] raw = props.jwtSecret().getBytes(StandardCharsets.UTF_8);
        if (raw.length < 32) {
            try {
                raw = MessageDigest.getInstance("SHA-256").digest(raw);
            } catch (NoSuchAlgorithmException ex) {
                throw new IllegalStateException(ex);
            }
        }
        this.signingKey = Keys.hmacShaKeyFor(raw);
    }

    public String createAccessToken(UUID userId, String email) {
        Instant now = Instant.now();
        Instant exp = now.plusSeconds(Math.max(60, props.accessTokenTtlMinutes() * 60));
        return Jwts.builder()
                .subject(userId.toString())
                .issuer(props.jwtIssuer())
                .audience().add(props.jwtAudience()).and()
                .claim("email", email)
                .issuedAt(Date.from(now))
                .expiration(Date.from(exp))
                .signWith(signingKey)
                .compact();
    }

    public AuthPrincipal verifyAccessToken(String token) {
        try {
            Claims claims = Jwts.parser()
                    .verifyWith(signingKey)
                    .requireIssuer(props.jwtIssuer())
                    .requireAudience(props.jwtAudience())
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            UUID userId = UUID.fromString(claims.getSubject());
            String email = claims.get("email", String.class);
            return new AuthPrincipal(userId, email);
        } catch (JwtException | IllegalArgumentException ex) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "NOT_AUTHENTICATED", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.");
        }
    }
}
