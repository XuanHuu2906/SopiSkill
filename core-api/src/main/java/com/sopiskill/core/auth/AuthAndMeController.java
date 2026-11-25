package com.sopiskill.core.auth;

import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.config.SopiProperties;
import com.sopiskill.core.gamification.GamificationService;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.JwtService;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuthAndMeController {

    private final JdbcClient jdbc;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;
    private final CsrfValidator csrfValidator;
    private final RateLimiterService rateLimiter;
    private final SopiProperties props;
    private final AiEngineClient aiEngineClient;
    private final GamificationService gamification;

    public AuthAndMeController(
            JdbcClient jdbc,
            PasswordEncoder passwordEncoder,
            JwtService jwtService,
            CsrfValidator csrfValidator,
            RateLimiterService rateLimiter,
            SopiProperties props,
            AiEngineClient aiEngineClient,
            GamificationService gamification
    ) {
        this.jdbc = jdbc;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
        this.csrfValidator = csrfValidator;
        this.rateLimiter = rateLimiter;
        this.props = props;
        this.aiEngineClient = aiEngineClient;
        this.gamification = gamification;
    }

    public record RegisterRequest(
            @NotBlank @Size(min = 3, max = 254) String email,
            @NotBlank @Size(min = 8, max = 128) String password
    ) {}

    public record LoginRequest(
            @NotBlank @Size(min = 3, max = 254) String email,
            @NotBlank @Size(min = 1, max = 128) String password
    ) {}

    public record UpdateMeRequest(@NotBlank @Size(min = 1, max = 80) String displayName) {}

    public record DeleteMeRequest(@NotBlank String confirmText, String password) {}

    @PostMapping("/v1/auth/register")
    @Transactional
    public ResponseEntity<Map<String, Object>> register(
            @Valid @RequestBody RegisterRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        rateLimiter.check(request, "auth_register", 30, 60);
        String email = body.email().trim().toLowerCase(Locale.ROOT);
        if (!email.contains("@") || email.startsWith("@") || email.endsWith("@")) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_EMAIL", "Email không hợp lệ.");
        }
        Integer exists = jdbc.sql("SELECT COUNT(*) FROM core.users WHERE lower(email) = :email")
                .param("email", email)
                .query(Integer.class)
                .single();
        if (exists != null && exists > 0) {
            throw new ApiException(HttpStatus.CONFLICT, "EMAIL_EXISTS", "Email này đã được đăng ký.");
        }

        UUID userId = UUID.randomUUID();
        String defaultName = email.substring(0, email.indexOf('@'));
        if (defaultName.isBlank()) defaultName = "Người học";
        String hash = passwordEncoder.encode(body.password());

        jdbc.sql("""
                INSERT INTO core.users (id, email, password_hash, display_name, xp, streak_days)
                VALUES (:id, :email, :hash, :name, 0, 0)
                """)
                .param("id", userId)
                .param("email", email)
                .param("hash", hash)
                .param("name", defaultName.substring(0, Math.min(defaultName.length(), 80)))
                .update();

        setSessionCookies(request, response, userId, email);
        return ResponseEntity.status(HttpStatus.CREATED).body(userOut(userId, email, defaultName, 0));
    }

    @PostMapping("/v1/auth/login")
    public ResponseEntity<Map<String, Object>> login(
            @Valid @RequestBody LoginRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        rateLimiter.check(request, "auth_login", 20, 60);
        String email = body.email().trim().toLowerCase(Locale.ROOT);
        var rowOpt = jdbc.sql("""
                SELECT id, email, password_hash, display_name, xp
                FROM core.users
                WHERE lower(email) = :email
                """)
                .param("email", email)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "email", rs.getString("email"),
                        "password_hash", rs.getString("password_hash") == null ? "" : rs.getString("password_hash"),
                        "display_name", rs.getString("display_name"),
                        "xp", rs.getInt("xp")
                ))
                .optional();

        if (rowOpt.isEmpty()) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu.");
        }
        Map<String, Object> row = rowOpt.get();
        String storedHash = (String) row.get("password_hash");
        if (storedHash.isBlank() || !passwordEncoder.matches(body.password(), storedHash)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu.");
        }

        UUID userId = (UUID) row.get("id");
        setSessionCookies(request, response, userId, (String) row.get("email"));
        return ResponseEntity.ok(userOut(userId, (String) row.get("email"), (String) row.get("display_name"), (Integer) row.get("xp")));
    }

    @PostMapping("/v1/auth/logout")
    public ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        csrfValidator.verify(request);
        rateLimiter.check(request, "auth_logout", 60, 60);
        clearSessionCookies(response);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/v1/auth/me")
    public Map<String, Object> me(@AuthenticationPrincipal AuthPrincipal principal) {
        return jdbc.sql("SELECT id, email, display_name, xp FROM core.users WHERE id = :id")
                .param("id", principal.userId())
                .query((rs, rowNum) -> userOut(
                        rs.getObject("id", UUID.class),
                        rs.getString("email"),
                        rs.getString("display_name"),
                        rs.getInt("xp")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."));
    }

    @GetMapping("/v1/me/stats")
    public Map<String, Object> meStats(@AuthenticationPrincipal AuthPrincipal principal) {
        UUID uid = principal.userId();
        var user = jdbc.sql("""
                SELECT id, email, display_name, xp, streak_days, best_streak_days,
                       streak_freezes, hearts, hearts_refill_at, timezone, goal_lessons,
                       last_active_date, created_at
                FROM core.users WHERE id = :id
                """)
                .param("id", uid)
                .query((rs, rowNum) -> {
                    var ra = rs.getTimestamp("hearts_refill_at");
                    var effectiveHearts = gamification.computeEffectiveHearts(
                            rs.getInt("hearts"),
                            ra == null ? null : ra.toInstant(),
                            java.time.Instant.now()
                    );
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("userId", IdCodec.format("usr", rs.getObject("id", UUID.class)));
                    m.put("email", rs.getString("email"));
                    m.put("displayName", rs.getString("display_name"));
                    m.put("xp", rs.getInt("xp"));
                    m.put("streakDays", rs.getInt("streak_days"));
                    m.put("bestStreakDays", rs.getInt("best_streak_days"));
                    m.put("streakFreezes", rs.getInt("streak_freezes"));
                    m.put("hearts", effectiveHearts.hearts());
                    m.put("heartsMax", effectiveHearts.heartsMax());
                    m.put("heartsRefillAt", effectiveHearts.heartsRefillAt() == null ? null : effectiveHearts.heartsRefillAt().toString());
                    m.put("timezone", rs.getString("timezone"));
                    m.put("goalLessons", rs.getInt("goal_lessons"));
                    var lad = rs.getDate("last_active_date");
                    m.put("lastActiveDate", lad == null ? null : lad.toLocalDate().toString());
                    var ca = rs.getTimestamp("created_at");
                    m.put("createdAt", ca == null ? null : ca.toInstant().toString());
                    return m;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."));

        int coursesTotal = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid")
                .param("uid", uid).query(Integer.class).single();
        int coursesReady = jdbc.sql("SELECT COUNT(*) FROM core.courses WHERE user_id = :uid AND status = 'ready'")
                .param("uid", uid).query(Integer.class).single();
        int lessonsTotal = jdbc.sql("""
                SELECT COUNT(*) FROM core.lessons l
                JOIN core.courses c ON c.id = l.course_id
                WHERE c.user_id = :uid
                """).param("uid", uid).query(Integer.class).single();
        int lessonsCompleted = jdbc.sql("""
                SELECT COUNT(DISTINCT la.lesson_id) FROM core.lesson_attempts la
                WHERE la.user_id = :uid AND la.completed = TRUE
                """).param("uid", uid).query(Integer.class).single();
        int attemptsTotal = jdbc.sql("SELECT COUNT(*) FROM core.lesson_attempts WHERE user_id = :uid")
                .param("uid", uid).query(Integer.class).single();
        int reviewsDue = jdbc.sql("SELECT COUNT(*) FROM core.review_cards WHERE user_id = :uid AND due_at <= now()")
                .param("uid", uid).query(Integer.class).single();

        user.put("coursesTotal", coursesTotal);
        user.put("coursesReady", coursesReady);
        user.put("lessonsCompleted", lessonsCompleted);
        user.put("lessonsTotal", lessonsTotal);
        user.put("attemptsTotal", attemptsTotal);
        user.put("reviewsDue", reviewsDue);
        return user;
    }

    @PatchMapping("/v1/me")
    @Transactional
    public Map<String, Object> updateMe(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody UpdateMeRequest body,
            HttpServletRequest request
    ) {
        csrfValidator.verify(request);
        rateLimiter.check(request, "me_update", 30, 60);
        String name = body.displayName().trim();
        if (name.isEmpty()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_DISPLAY_NAME", "Tên hiển thị không được trống.");
        }
        jdbc.sql("UPDATE core.users SET display_name = :name, updated_at = now() WHERE id = :id")
                .param("name", name)
                .param("id", principal.userId())
                .update();
        return me(principal);
    }

    @DeleteMapping("/v1/me")
    @Transactional
    public ResponseEntity<Void> deleteMe(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody DeleteMeRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        csrfValidator.verify(request);
        rateLimiter.check(request, "me_delete", 5, 60);

        if (!"DELETE".equals(body.confirmText().trim())) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "CONFIRM_REQUIRED", "Vui lòng nhập chính xác DELETE để xác nhận.");
        }

        UUID uid = principal.userId();
        String storedHash = jdbc.sql("SELECT password_hash FROM core.users WHERE id = :id FOR UPDATE")
                .param("id", uid)
                .query(String.class)
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."));

        if (storedHash != null && !storedHash.isBlank()) {
            if (body.password() == null || !passwordEncoder.matches(body.password(), storedHash)) {
                throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_PASSWORD", "Mật khẩu hiện tại không đúng.");
            }
        }

        // Single-transaction cascade delete across `core.*` via ON DELETE CASCADE
        jdbc.sql("DELETE FROM core.users WHERE id = :id").param("id", uid).update();

        // Cascade delete `rag.document_chunks` on ai-engine (best effort, signed HMAC)
        aiEngineClient.deleteRagResourceBestEffort("/internal/rag/users/" + IdCodec.format("usr", uid), null);
        clearSessionCookies(response);
        return ResponseEntity.noContent().build();
    }

    private void setSessionCookies(HttpServletRequest request, HttpServletResponse response, UUID userId, String email) {
        long maxAgeSec = Math.max(60L, props.accessTokenTtlMinutes() * 60L);
        String token = jwtService.createAccessToken(userId, email);
        ResponseCookie accessCookie = ResponseCookie.from(JwtService.ACCESS_COOKIE, token)
                .httpOnly(true)
                .secure(props.cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofSeconds(maxAgeSec))
                .build();

        String existingCsrf = csrfValidator.extractCookie(request, CsrfValidator.CSRF_COOKIE);
        String csrfVal = (existingCsrf != null && !existingCsrf.isBlank()) ? existingCsrf : csrfValidator.newToken();
        ResponseCookie csrfCookie = ResponseCookie.from(CsrfValidator.CSRF_COOKIE, csrfVal)
                .httpOnly(false)
                .secure(props.cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofSeconds(maxAgeSec))
                .build();

        response.addHeader(HttpHeaders.SET_COOKIE, accessCookie.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, csrfCookie.toString());
    }

    private void clearSessionCookies(HttpServletResponse response) {
        ResponseCookie clearAccess = ResponseCookie.from(JwtService.ACCESS_COOKIE, "")
                .httpOnly(true)
                .secure(props.cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(0)
                .build();
        ResponseCookie clearCsrf = ResponseCookie.from(CsrfValidator.CSRF_COOKIE, "")
                .httpOnly(false)
                .secure(props.cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(0)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, clearAccess.toString());
        response.addHeader(HttpHeaders.SET_COOKIE, clearCsrf.toString());
    }

    private Map<String, Object> userOut(UUID id, String email, String displayName, int xp) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("usr", id));
        out.put("email", email);
        out.put("displayName", displayName);
        out.put("xp", xp);
        return out;
    }
}
