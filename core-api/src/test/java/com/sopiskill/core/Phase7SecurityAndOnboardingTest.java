package com.sopiskill.core;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sopiskill.core.auth.OAuthIdentityService;
import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.notifications.NotificationService;
import io.jsonwebtoken.Jwts;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.TestPropertySource;

/**
 * Phase 7 Security & Feature Gate tests:
 *  1. Anti-account-takeover on Google/Apple OAuth2 OIDC exchange + link confirmation.
 *  2. Rotating HttpOnly Refresh Token + Reuse Detection revoking entire session family + logout?all=true.
 *  3. Quiet hours 22:00-08:00 enforcement, 15-min reminder step validation, Web Push registration & 7-kind scanner.
 *  4. 4-step Onboarding profile + independent `appLanguage` vs `lessonLanguage` + Avatar.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = {
        "sopiskill.stream-llm-key=test:queue:ai:llm:phase7",
        "sopiskill.rate-limit-enabled=false"
})
class Phase7SecurityAndOnboardingTest {

    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private JdbcClient jdbc;

    @Autowired
    private OAuthIdentityService oauthService;

    @Autowired
    private NotificationService notificationService;

    private final HttpClient http = HttpClient.newHttpClient();

    private String url(String path) {
        return "http://127.0.0.1:" + port + path;
    }

    @Test
    void oauthAntiAccountTakeoverAndCryptographicVerification() throws Exception {
        KeyPairGenerator kpg = KeyPairGenerator.getInstance("RSA");
        kpg.initialize(2048);
        KeyPair googleKeys = kpg.generateKeyPair();
        KeyPair appleKeys = kpg.generateKeyPair();
        KeyPair attackerKeys = kpg.generateKeyPair();

        oauthService.registerTrustedPublicKey("google", "kid-google-test", googleKeys.getPublic());
        oauthService.registerTrustedPublicKey("apple", "kid-apple-test", appleKeys.getPublic());

        String existingEmail = "p7-victim-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
        String brandNewAppleEmail = "p7-apple-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
        UUID victimUid = null;
        UUID appleUid = null;

        try {
            // 1. Register victim with email + password
            var victimReg = register(existingEmail, "VictimSecret99!");
            victimUid = IdCodec.parse(victimReg.get("userId"), "usr");

            // 2. Forged token signed with attacker's key -> MUST fail 401 INVALID_ID_TOKEN
            String forgedToken = Jwts.builder()
                    .header().keyId("kid-google-test").and()
                    .issuer("https://accounts.google.com")
                    .audience().add("sopiskill-google-client").and()
                    .subject("google-sub-forged")
                    .claim("email", existingEmail)
                    .claim("email_verified", true)
                    .expiration(Date.from(Instant.now().plusSeconds(300)))
                    .signWith(attackerKeys.getPrivate(), Jwts.SIG.RS256)
                    .compact();

            HttpResponse<String> forgedResp = postAnon("/v1/auth/exchange", Map.of("provider", "google", "idToken", forgedToken));
            assertThat(forgedResp.statusCode()).isEqualTo(401);
            assertThat(forgedResp.body()).contains("INVALID_ID_TOKEN");

            // 3. Valid Google token for SAME email as existing account -> MUST NOT auto-link; returns 409 ACCOUNT_LINK_REQUIRED + signed linkTicket!
            String validGoogleToken = Jwts.builder()
                    .header().keyId("kid-google-test").and()
                    .issuer("https://accounts.google.com")
                    .audience().add("sopiskill-google-client").and()
                    .subject("google-sub-" + UUID.randomUUID())
                    .claim("email", existingEmail)
                    .claim("email_verified", true)
                    .claim("name", "Victim Google")
                    .expiration(Date.from(Instant.now().plusSeconds(300)))
                    .signWith(googleKeys.getPrivate(), Jwts.SIG.RS256)
                    .compact();

            HttpResponse<String> conflictResp = postAnon("/v1/auth/exchange", Map.of("provider", "google", "idToken", validGoogleToken));
            assertThat(conflictResp.statusCode()).isEqualTo(409);
            Map<String, Object> conflictBody = parseMap(conflictResp.body());
            @SuppressWarnings("unchecked")
            Map<String, Object> detail = (Map<String, Object>) conflictBody.get("detail");
            assertThat(detail.get("code")).isEqualTo("ACCOUNT_LINK_REQUIRED");
            String linkTicket = String.valueOf(detail.get("linkTicket"));
            assertThat(linkTicket).contains(".");

            // 4. Tampered linkTicket -> 401 INVALID_LINK_TICKET
            HttpResponse<String> tamperedResp = postAnon("/v1/auth/link/confirm", Map.of(
                    "linkTicket", linkTicket + "x",
                    "password", "VictimSecret99!"
            ));
            assertThat(tamperedResp.statusCode()).isEqualTo(401);

            // 5. Valid linkTicket + WRONG password -> 401 INVALID_CREDENTIALS (account takeover blocked!)
            HttpResponse<String> wrongPwResp = postAnon("/v1/auth/link/confirm", Map.of(
                    "linkTicket", linkTicket,
                    "password", "WrongPassword!"
            ));
            assertThat(wrongPwResp.statusCode()).isEqualTo(401);
            assertThat(wrongPwResp.body()).contains("INVALID_CREDENTIALS");

            // 6. Valid linkTicket + CORRECT password -> 200 links Google identity & issues rotating session!
            HttpResponse<String> linkedResp = postAnon("/v1/auth/link/confirm", Map.of(
                    "linkTicket", linkTicket,
                    "password", "VictimSecret99!"
            ));
            assertThat(linkedResp.statusCode()).isEqualTo(200);
            assertThat(linkedResp.body()).contains("\"linkedProvider\":\"google\"");

            // 7. Subsequent exchange with same Google ID Token now succeeds directly (200)
            HttpResponse<String> directLogin = postAnon("/v1/auth/exchange", Map.of("provider", "google", "idToken", validGoogleToken));
            assertThat(directLogin.statusCode()).isEqualTo(200);
            String newCookie = buildCookieHeader(directLogin.headers().allValues("set-cookie"));

            HttpResponse<String> identitiesResp = getAuthed("/v1/me/identities", newCookie);
            assertThat(identitiesResp.statusCode()).isEqualTo(200);
            assertThat(identitiesResp.body()).contains("\"provider\":\"google\"");

            // 8. Brand-new Apple OIDC token -> creates new user (201)
            String appleToken = Jwts.builder()
                    .header().keyId("kid-apple-test").and()
                    .issuer("https://appleid.apple.com")
                    .audience().add("com.sopiskill.web").and()
                    .subject("apple-sub-" + UUID.randomUUID())
                    .claim("email", brandNewAppleEmail)
                    .claim("email_verified", true)
                    .expiration(Date.from(Instant.now().plusSeconds(300)))
                    .signWith(appleKeys.getPrivate(), Jwts.SIG.RS256)
                    .compact();

            HttpResponse<String> appleResp = postAnon("/v1/auth/exchange", Map.of("provider", "apple", "idToken", appleToken));
            assertThat(appleResp.statusCode()).isEqualTo(201);
            appleUid = IdCodec.parse(String.valueOf(parseMap(appleResp.body()).get("id")), "usr");
        } finally {
            if (victimUid != null) jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", victimUid).update();
            if (appleUid != null) jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", appleUid).update();
        }
    }

    @Test
    void rotatingRefreshTokenDetectsReuseAndLogoutAllRevokesAllDevices() throws Exception {
        String email = "p7-rot-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
        var reg = register(email, "StrongPassword123!");
        UUID uid = IdCodec.parse(reg.get("userId"), "usr");

        try {
            String r1 = reg.get("refresh");
            String csrf1 = reg.get("csrf");
            assertThat(r1).isNotBlank();

            // 1. Rotate R1 -> R2 succeeds
            HttpResponse<String> rot1 = postAuthed(
                    "/v1/auth/refresh",
                    "refresh_token=" + r1 + "; csrf_token=" + csrf1,
                    csrf1,
                    Map.of()
            );
            assertThat(rot1.statusCode()).isEqualTo(200);
            String r2 = extractCookieValue(rot1.headers().allValues("set-cookie"), "refresh_token");
            assertThat(r2).isNotBlank().isNotEqualTo(r1);

            // 2. Attacker replays already-rotated R1 -> 401 REFRESH_TOKEN_REUSE_DETECTED & revokes ENTIRE family!
            HttpResponse<String> replayR1 = postAuthed(
                    "/v1/auth/refresh",
                    "refresh_token=" + r1 + "; csrf_token=" + csrf1,
                    csrf1,
                    Map.of()
            );
            assertThat(replayR1.statusCode()).isEqualTo(401);
            assertThat(replayR1.body()).contains("REFRESH_TOKEN_REUSE_DETECTED");

            // 3. Legitimate user's R2 in the same compromised family is now ALSO revoked!
            HttpResponse<String> useR2AfterReuse = postAuthed(
                    "/v1/auth/refresh",
                    "refresh_token=" + r2 + "; csrf_token=" + csrf1,
                    csrf1,
                    Map.of()
            );
            assertThat(useR2AfterReuse.statusCode()).isEqualTo(401);
            assertThat(useR2AfterReuse.body()).contains("REFRESH_TOKEN_REUSE_DETECTED");

            // 4. Login on 2 devices -> POST /v1/auth/logout?all=true revokes BOTH devices!
            var dev1 = login(email, "StrongPassword123!");
            var dev2 = login(email, "StrongPassword123!");

            HttpResponse<String> logoutAll = postAuthed(
                    "/v1/auth/logout?all=true",
                    dev1.get("cookie"),
                    dev1.get("csrf"),
                    Map.of()
            );
            assertThat(logoutAll.statusCode()).isEqualTo(204);

            HttpResponse<String> dev2Refresh = postAuthed(
                    "/v1/auth/refresh",
                    "refresh_token=" + dev2.get("refresh") + "; csrf_token=" + dev2.get("csrf"),
                    dev2.get("csrf"),
                    Map.of()
            );
            assertThat(dev2Refresh.statusCode()).isEqualTo(401);
        } finally {
            jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", uid).update();
        }
    }

    @Test
    void onboardingLanguageSeparationQuietHoursAndNotificationScanner() throws Exception {
        // Pure unit assertion on overnight quiet hours 22:00-08:00
        assertThat(NotificationService.isInQuietHours(LocalTime.of(22, 0), 1320, 480)).isTrue();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(23, 30), 1320, 480)).isTrue();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(3, 15), 1320, 480)).isTrue();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(7, 59), 1320, 480)).isTrue();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(8, 0), 1320, 480)).isFalse();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(19, 0), 1320, 480)).isFalse();
        assertThat(NotificationService.isInQuietHours(LocalTime.of(21, 59), 1320, 480)).isFalse();

        String email = "p7-notif-" + UUID.randomUUID().toString().substring(0, 8) + "@sopi.test";
        var reg = register(email, "StrongPassword123!");
        String cookie = reg.get("cookie");
        String csrf = reg.get("csrf");
        UUID uid = IdCodec.parse(reg.get("userId"), "usr");

        try {
            // 1. Onboarding incomplete -> 422; complete 4 groups -> 200
            HttpResponse<String> badOnb = putAuthed("/v1/me/onboarding", cookie, csrf, Map.of(
                    "roles", List.of("Engineer"), "topics", List.of(), "learningStyles", List.of("Visual"), "goals", List.of("Practice")
            ));
            assertThat(badOnb.statusCode()).isEqualTo(422);

            HttpResponse<String> goodOnb = putAuthed("/v1/me/onboarding", cookie, csrf, Map.of(
                    "roles", List.of("Engineer"),
                    "topics", List.of("Distributed Systems"),
                    "learningStyles", List.of("Diagrams"),
                    "goals", List.of("Daily 10m"),
                    "avatar", "graduate",
                    "lessonLanguage", "en"
            ));
            assertThat(goodOnb.statusCode()).isEqualTo(200);

            // 2. Switch appLanguage to "en" independently of lessonLanguage ("vi")
            HttpResponse<String> langPatch = patchAuthed("/v1/me", cookie, csrf, Map.of(
                    "appLanguage", "en",
                    "lessonLanguage", "vi"
            ));
            assertThat(langPatch.statusCode()).isEqualTo(200);
            Map<String, Object> meOut = parseMap(langPatch.body());
            assertThat(meOut.get("appLanguage")).isEqualTo("en");
            assertThat(meOut.get("lessonLanguage")).isEqualTo("vi");
            assertThat(meOut.get("avatar")).isEqualTo("graduate");
            assertThat(meOut.get("onboardedAt")).isNotNull();

            // 3. Reminder time must be multiple of 15 min
            HttpResponse<String> badStep = patchAuthed("/v1/me/notifications", cookie, csrf, Map.of("dailyReminderMinutes", 1147));
            assertThat(badStep.statusCode()).isEqualTo(422);
            assertThat(badStep.body()).contains("INVALID_REMINDER_STEP");

            HttpResponse<String> goodPrefs = patchAuthed("/v1/me/notifications", cookie, csrf, Map.of(
                    "dailyReminderMinutes", 1140,
                    "quietStartMinutes", 1320,
                    "quietEndMinutes", 480
            ));
            assertThat(goodPrefs.statusCode()).isEqualTo(200);

            // 4. Web Push registration validates HTTPS
            HttpResponse<String> badPush = postAuthed("/v1/push/register", cookie, csrf, Map.of(
                    "endpoint", "http://evil.example/push", "p256dh", "k1", "auth", "a1"
            ));
            assertThat(badPush.statusCode()).isEqualTo(422);

            HttpResponse<String> okPush = postAuthed("/v1/push/register", cookie, csrf, Map.of(
                    "endpoint", "https://fcm.googleapis.com/fcm/send/test-" + UUID.randomUUID(),
                    "p256dh", "BNcRdreALRFXTkOOUHK1",
                    "auth", "tBHItJI5svbp"
            ));
            assertThat(okPush.statusCode()).isEqualTo(200);

            // 5. Quiet hours suppression vs active dispatch across retention kinds
            // Set user timezone = Asia/Ho_Chi_Minh (+07:00), streak=5, last_active_day = 2 days before Sunday 2026-06-14
            jdbc.sql("""
                    UPDATE core.users
                    SET timezone = 'Asia/Ho_Chi_Minh', streak_days = 5, last_active_day = :lad, last_active_date = :lad
                    WHERE id = :uid
                    """)
                    .param("lad", LocalDate.of(2026, 6, 12))
                    .param("uid", uid)
                    .update();

            // 23:30 VN time (16:30 UTC) -> inside 22:00-08:00 quiet hours -> 0 notifications dispatched!
            List<String> suppressed = notificationService.scanUserNotifications(uid, Instant.parse("2026-06-14T16:30:00Z"));
            assertThat(suppressed).isEmpty();

            // 19:05 VN time (12:05 UTC) on Sunday 2026-06-14 -> outside quiet hours -> dispatches daily.reminder, streak.guard, weekly.recap, comeback.nudge (day 2)!
            List<String> sent = notificationService.scanUserNotifications(uid, Instant.parse("2026-06-14T12:05:00Z"));
            assertThat(sent).contains("daily.reminder", "streak.guard", "weekly.recap", "comeback.nudge");

            HttpResponse<String> inbox = getAuthed("/v1/me/notifications/inbox", cookie);
            assertThat(inbox.statusCode()).isEqualTo(200);
            Map<String, Object> inboxBody = parseMap(inbox.body());
            assertThat(((Number) inboxBody.get("unreadCount")).intValue()).isGreaterThanOrEqualTo(4);

            HttpResponse<String> readAll = postAuthed("/v1/me/notifications/inbox/read-all", cookie, csrf, Map.of());
            assertThat(readAll.statusCode()).isEqualTo(200);

            HttpResponse<String> inboxAfter = getAuthed("/v1/me/notifications/inbox", cookie);
            assertThat(((Number) parseMap(inboxAfter.body()).get("unreadCount")).intValue()).isEqualTo(0);
        } finally {
            jdbc.sql("DELETE FROM core.users WHERE id = :uid").param("uid", uid).update();
        }
    }

    private Map<String, String> register(String email, String password) throws Exception {
        HttpResponse<String> resp = postAnon("/v1/auth/register", Map.of("email", email, "password", password));
        assertThat(resp.statusCode()).isEqualTo(201);
        return extractSessionMap(resp);
    }

    private Map<String, String> login(String email, String password) throws Exception {
        HttpResponse<String> resp = postAnon("/v1/auth/login", Map.of("email", email, "password", password));
        assertThat(resp.statusCode()).isEqualTo(200);
        return extractSessionMap(resp);
    }

    private Map<String, String> extractSessionMap(HttpResponse<String> resp) throws Exception {
        List<String> cookies = resp.headers().allValues("set-cookie");
        String access = extractCookieValue(cookies, "access_token");
        String refresh = extractCookieValue(cookies, "refresh_token");
        String csrf = extractCookieValue(cookies, "csrf_token");
        Map<String, Object> body = parseMap(resp.body());
        return Map.of(
                "userId", String.valueOf(body.get("id")),
                "access", access,
                "refresh", refresh,
                "csrf", csrf,
                "cookie", "access_token=" + access + "; refresh_token=" + refresh + "; csrf_token=" + csrf
        );
    }

    private String buildCookieHeader(List<String> setCookies) {
        return "access_token=" + extractCookieValue(setCookies, "access_token")
                + "; refresh_token=" + extractCookieValue(setCookies, "refresh_token")
                + "; csrf_token=" + extractCookieValue(setCookies, "csrf_token");
    }

    private HttpResponse<String> postAnon(String path, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> getAuthed(String path, String cookie) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path))).header("Cookie", cookie).GET().build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> postAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> putAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .PUT(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private HttpResponse<String> patchAuthed(String path, String cookie, String csrf, Object body) throws Exception {
        return http.send(
                HttpRequest.newBuilder(URI.create(url(path)))
                        .header("Content-Type", "application/json")
                        .header("Cookie", cookie)
                        .header("X-CSRF-Token", csrf)
                        .method("PATCH", HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(body)))
                        .build(),
                HttpResponse.BodyHandlers.ofString()
        );
    }

    private Map<String, Object> parseMap(String raw) throws Exception {
        return objectMapper.readValue(raw.getBytes(StandardCharsets.UTF_8), new TypeReference<>() {});
    }

    private String extractCookieValue(List<String> setCookies, String name) {
        for (String header : setCookies) {
            String firstPart = header.split(";")[0].trim();
            if (firstPart.startsWith(name + "=")) {
                return firstPart.substring((name + "=").length());
            }
        }
        return "";
    }
}
