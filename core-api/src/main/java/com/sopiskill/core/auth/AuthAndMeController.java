package com.sopiskill.core.auth;

import com.fasterxml.jackson.core.type.TypeReference;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.gamification.GamificationService;
import com.sopiskill.core.internal.AiEngineClient;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class AuthAndMeController {

    public static final Set<String> ALLOWED_AVATARS = Set.of("happy", "graduate", "curious", "wink", "excited");
    public static final Set<String> ALLOWED_LANGUAGES = Set.of("vi", "en", "ja", "ko", "zh", "es", "fr", "de", "pt", "id", "th", "hi");

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final PasswordEncoder passwordEncoder;
    private final SessionService sessionService;
    private final CsrfValidator csrfValidator;
    private final RateLimiterService rateLimiter;
    private final AiEngineClient aiEngineClient;
    private final GamificationService gamification;

    public AuthAndMeController(
            JdbcClient jdbc,
            JsonHelper json,
            PasswordEncoder passwordEncoder,
            SessionService sessionService,
            CsrfValidator csrfValidator,
            RateLimiterService rateLimiter,
            AiEngineClient aiEngineClient,
            GamificationService gamification
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.passwordEncoder = passwordEncoder;
        this.sessionService = sessionService;
        this.csrfValidator = csrfValidator;
        this.rateLimiter = rateLimiter;
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

    public record UpdateMeRequest(
            @Size(max = 80) String displayName,
            String avatar,
            String appLanguage,
            String lessonLanguage,
            String locale
    ) {}

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

        sessionService.issueNewSession(request, response, userId, email);
        return ResponseEntity.status(HttpStatus.CREATED).body(loadUserOut(userId));
    }

    @PostMapping("/v1/auth/login")
    @Transactional
    public ResponseEntity<Map<String, Object>> login(
            @Valid @RequestBody LoginRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        rateLimiter.check(request, "auth_login", 20, 60);
        String email = body.email().trim().toLowerCase(Locale.ROOT);
        var rowOpt = jdbc.sql("""
                SELECT id, email, password_hash
                FROM core.users
                WHERE lower(email) = :email
                """)
                .param("email", email)
                .query((rs, rowNum) -> Map.<String, Object>of(
                        "id", rs.getObject("id", UUID.class),
                        "email", rs.getString("email"),
                        "password_hash", rs.getString("password_hash") == null ? "" : rs.getString("password_hash")
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
        sessionService.issueNewSession(request, response, userId, (String) row.get("email"));
        return ResponseEntity.ok(loadUserOut(userId));
    }

    @PostMapping("/v1/auth/logout")
    public ResponseEntity<Void> logout(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(name = "all", defaultValue = "false") boolean revokeAll,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        csrfValidator.verify(request);
        rateLimiter.check(request, "auth_logout", 60, 60);
        sessionService.revokeOnLogout(request, response, principal == null ? null : principal.userId(), revokeAll);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/v1/auth/me")
    public Map<String, Object> me(@AuthenticationPrincipal AuthPrincipal principal) {
        return loadUserOut(principal.userId());
    }

    @GetMapping("/v1/me/stats")
    public Map<String, Object> meStats(@AuthenticationPrincipal AuthPrincipal principal) {
        UUID uid = principal.userId();
        var user = jdbc.sql("""
                SELECT id, email, display_name, xp, streak_days, best_streak_days,
                       streak_freezes, hearts, hearts_refill_at, timezone, goal_lessons,
                       avatar, app_language, lesson_language, onboarded_at,
                       last_active_date, created_at
                FROM core.users WHERE id = :id
                """)
                .param("id", uid)
                .query((rs, rowNum) -> {
                    var ra = rs.getTimestamp("hearts_refill_at");
                    var effectiveHearts = gamification.computeEffectiveHearts(
                            rs.getInt("hearts"),
                            ra == null ? null : ra.toInstant(),
                            Instant.now()
                    );
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("userId", IdCodec.format("usr", rs.getObject("id", UUID.class)));
                    m.put("email", rs.getString("email"));
                    m.put("displayName", rs.getString("display_name"));
                    m.put("avatar", rs.getString("avatar"));
                    m.put("appLanguage", rs.getString("app_language"));
                    m.put("lessonLanguage", rs.getString("lesson_language"));
                    var oa = rs.getTimestamp("onboarded_at");
                    m.put("onboardedAt", oa == null ? null : oa.toInstant().toString());
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

        UUID uid = principal.userId();
        boolean updatedAny = false;

        if (body.displayName() != null) {
            String name = body.displayName().trim();
            if (name.isEmpty()) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_DISPLAY_NAME", "Tên hiển thị không được trống.");
            }
            jdbc.sql("UPDATE core.users SET display_name = :name, updated_at = now() WHERE id = :id")
                    .param("name", name).param("id", uid).update();
            updatedAny = true;
        }
        if (body.avatar() != null && !body.avatar().isBlank()) {
            String av = body.avatar().trim().toLowerCase(Locale.ROOT);
            if (!ALLOWED_AVATARS.contains(av)) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_AVATAR", "Avatar không hợp lệ.");
            }
            jdbc.sql("UPDATE core.users SET avatar = :av, updated_at = now() WHERE id = :id")
                    .param("av", av).param("id", uid).update();
            updatedAny = true;
        }
        if (body.appLanguage() != null && !body.appLanguage().isBlank()) {
            String lang = body.appLanguage().trim().toLowerCase(Locale.ROOT);
            if (!ALLOWED_LANGUAGES.contains(lang)) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_LANGUAGE", "Ngôn ngữ giao diện không hợp lệ.");
            }
            jdbc.sql("UPDATE core.users SET app_language = :lang, updated_at = now() WHERE id = :id")
                    .param("lang", lang).param("id", uid).update();
            updatedAny = true;
        }
        if (body.lessonLanguage() != null && !body.lessonLanguage().isBlank()) {
            String lang = body.lessonLanguage().trim().toLowerCase(Locale.ROOT);
            if (!ALLOWED_LANGUAGES.contains(lang)) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_LANGUAGE", "Ngôn ngữ bài học không hợp lệ.");
            }
            jdbc.sql("UPDATE core.users SET lesson_language = :lang, updated_at = now() WHERE id = :id")
                    .param("lang", lang).param("id", uid).update();
            updatedAny = true;
        }
        if (body.locale() != null && !body.locale().isBlank()) {
            String loc = body.locale().trim();
            if (loc.length() > 16) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_LOCALE", "Locale không hợp lệ.");
            }
            jdbc.sql("UPDATE core.users SET locale = :loc, updated_at = now() WHERE id = :id")
                    .param("loc", loc).param("id", uid).update();
            updatedAny = true;
        }
        if (!updatedAny) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EMPTY_UPDATE", "Không có trường hợp lệ để cập nhật.");
        }
        return loadUserOut(uid);
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
        sessionService.clearSessionCookies(response);
        return ResponseEntity.noContent().build();
    }

    private Map<String, Object> loadUserOut(UUID uid) {
        return jdbc.sql("""
                SELECT id, email, display_name, xp, avatar, locale, app_language, lesson_language,
                       onboarded_at, onboarding_profile::text AS onboarding_profile_json
                FROM core.users
                WHERE id = :id
                """)
                .param("id", uid)
                .query((rs, rowNum) -> {
                    Map<String, Object> out = new LinkedHashMap<>();
                    out.put("id", IdCodec.format("usr", rs.getObject("id", UUID.class)));
                    out.put("email", rs.getString("email"));
                    out.put("displayName", rs.getString("display_name"));
                    out.put("xp", rs.getInt("xp"));
                    out.put("avatar", rs.getString("avatar"));
                    out.put("locale", rs.getString("locale"));
                    out.put("appLanguage", rs.getString("app_language"));
                    out.put("lessonLanguage", rs.getString("lesson_language"));
                    var oa = rs.getTimestamp("onboarded_at");
                    out.put("onboardedAt", oa == null ? null : oa.toInstant().toString());
                    String opJson = rs.getString("onboarding_profile_json");
                    out.put("onboardingProfile", opJson == null ? null : json.fromJson(opJson, new TypeReference<Map<String, Object>>() {}));
                    return out;
                })
                .optional()
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "USER_NOT_FOUND", "Tài khoản không tồn tại."));
    }
}
