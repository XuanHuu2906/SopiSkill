package com.sopiskill.core.notifications;

import com.sopiskill.core.auth.AuthAndMeController;
import com.sopiskill.core.common.ApiException;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.common.JsonHelper;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Phase 7 Onboarding (4 steps), Notification Preferences, In-App Inbox, and Web Push Registration.
 */
@RestController
public class OnboardingAndNotificationsController {

    private final JdbcClient jdbc;
    private final JsonHelper json;
    private final NotificationService notifications;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;

    public OnboardingAndNotificationsController(
            JdbcClient jdbc,
            JsonHelper json,
            NotificationService notifications,
            CsrfValidator csrf,
            RateLimiterService rateLimiter
    ) {
        this.jdbc = jdbc;
        this.json = json;
        this.notifications = notifications;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
    }

    public record OnboardingRequest(
            List<String> roles,
            List<String> topics,
            List<String> learningStyles,
            List<String> goals,
            String avatar,
            String appLanguage,
            String lessonLanguage
    ) {}

    public record PushRegisterRequest(
            @NotBlank String endpoint,
            @NotBlank String p256dh,
            @NotBlank String auth
    ) {}

    public record PushUnregisterRequest(String endpoint) {}

    @PutMapping("/v1/me/onboarding")
    @Transactional
    public Map<String, Object> saveOnboarding(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestBody OnboardingRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "me_onboarding", 20, 60);

        List<String> roles = cleanList(body.roles(), 6);
        List<String> topics = cleanList(body.topics(), 10);
        List<String> styles = cleanList(body.learningStyles(), 6);
        List<String> goals = cleanList(body.goals(), 6);

        if (roles.isEmpty() || topics.isEmpty() || styles.isEmpty() || goals.isEmpty()) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_ENTITY,
                    "ONBOARDING_INCOMPLETE",
                    "Vui lòng chọn ít nhất 1 mục cho cả 4 bước (vai trò, chủ đề, phong cách học, mục tiêu)."
            );
        }

        Map<String, Object> profile = new LinkedHashMap<>();
        profile.put("roles", roles);
        profile.put("topics", topics);
        profile.put("learningStyles", styles);
        profile.put("goals", goals);

        String avatar = null;
        if (body.avatar() != null && !body.avatar().isBlank()) {
            String candidate = body.avatar().trim().toLowerCase(Locale.ROOT);
            if (!AuthAndMeController.ALLOWED_AVATARS.contains(candidate)) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_AVATAR", "Avatar không hợp lệ.");
            }
            avatar = candidate;
        }
        String appLang = validateOptionalLang(body.appLanguage());
        String lessonLang = validateOptionalLang(body.lessonLanguage());

        jdbc.sql("""
                UPDATE core.users
                SET onboarding_profile = CAST(:profile AS jsonb),
                    onboarded_at = COALESCE(onboarded_at, now()),
                    avatar = COALESCE(:avatar, avatar),
                    app_language = COALESCE(:appLang, app_language),
                    lesson_language = COALESCE(:lessonLang, lesson_language),
                    updated_at = now()
                WHERE id = :uid
                """)
                .param("profile", json.toJson(profile))
                .param("avatar", avatar)
                .param("appLang", appLang)
                .param("lessonLang", lessonLang)
                .param("uid", principal.userId())
                .update();

        return Map.of(
                "onboarded", true,
                "onboardingProfile", profile
        );
    }

    @GetMapping("/v1/me/notifications")
    public Map<String, Object> getNotificationPreferences(@AuthenticationPrincipal AuthPrincipal principal) {
        return notifications.getPreferences(principal.userId());
    }

    @PatchMapping("/v1/me/notifications")
    public Map<String, Object> updateNotificationPreferences(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestBody Map<String, Object> patch,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "notif_prefs", 30, 60);
        return notifications.updatePreferences(principal.userId(), patch);
    }

    @GetMapping("/v1/me/notifications/inbox")
    public Map<String, Object> listInbox(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestParam(defaultValue = "20") int limit
    ) {
        return notifications.listInbox(principal.userId(), limit);
    }

    @PostMapping("/v1/me/notifications/inbox/{notificationId}/read")
    public Map<String, Object> markNotificationRead(
            @AuthenticationPrincipal AuthPrincipal principal,
            @PathVariable String notificationId,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        notifications.markRead(principal.userId(), IdCodec.parse(notificationId, "ntf"));
        return Map.of("read", true);
    }

    @PostMapping("/v1/me/notifications/inbox/read-all")
    public Map<String, Object> markAllNotificationsRead(
            @AuthenticationPrincipal AuthPrincipal principal,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        notifications.markAllRead(principal.userId());
        return Map.of("readAll", true);
    }

    @PostMapping("/v1/push/register")
    public Map<String, Object> registerPush(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody PushRegisterRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "push_register", 20, 60);
        return notifications.registerPushSubscription(
                principal.userId(),
                body.endpoint(),
                body.p256dh(),
                body.auth(),
                request.getHeader("User-Agent")
        );
    }

    @DeleteMapping("/v1/push/register")
    public Map<String, Object> unregisterPush(
            @AuthenticationPrincipal AuthPrincipal principal,
            @RequestBody(required = false) PushUnregisterRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "push_unregister", 20, 60);
        return notifications.unregisterPushSubscription(
                principal.userId(),
                body == null ? null : body.endpoint()
        );
    }

    private static List<String> cleanList(List<String> input, int maxItems) {
        if (input == null) return List.of();
        return input.stream()
                .filter(s -> s != null && !s.isBlank())
                .map(s -> s.trim().substring(0, Math.min(s.trim().length(), 80)))
                .distinct()
                .limit(maxItems)
                .toList();
    }

    private static String validateOptionalLang(String raw) {
        if (raw == null || raw.isBlank()) return null;
        String lang = raw.trim().toLowerCase(Locale.ROOT);
        if (!AuthAndMeController.ALLOWED_LANGUAGES.contains(lang)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_LANGUAGE", "Ngôn ngữ không được hỗ trợ.");
        }
        return lang;
    }
}
