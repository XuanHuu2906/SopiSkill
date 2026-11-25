package com.sopiskill.core.security;

import com.sopiskill.core.common.ApiException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

@Component
public class CsrfValidator {

    public static final String CSRF_COOKIE = "csrf_token";
    public static final String CSRF_HEADER = "X-CSRF-Token";
    private static final Set<String> SAFE_METHODS = Set.of("GET", "HEAD", "OPTIONS");
    private final SecureRandom random = new SecureRandom();

    public String newToken() {
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public String extractCookie(HttpServletRequest request, String name) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) return null;
        for (Cookie cookie : cookies) {
            if (name.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }

    public void verify(HttpServletRequest request) {
        if (SAFE_METHODS.contains(request.getMethod().toUpperCase())) {
            return;
        }
        String cookieVal = extractCookie(request, CSRF_COOKIE);
        String headerVal = request.getHeader(CSRF_HEADER);
        if (cookieVal == null || cookieVal.isBlank() || headerVal == null || headerVal.isBlank()) {
            throw new ApiException(HttpStatus.FORBIDDEN, "CSRF_INVALID", "Thiếu hoặc sai CSRF token.");
        }
        boolean equal = MessageDigest.isEqual(
                cookieVal.getBytes(StandardCharsets.UTF_8),
                headerVal.getBytes(StandardCharsets.UTF_8)
        );
        if (!equal) {
            throw new ApiException(HttpStatus.FORBIDDEN, "CSRF_INVALID", "Thiếu hoặc sai CSRF token.");
        }
    }
}
