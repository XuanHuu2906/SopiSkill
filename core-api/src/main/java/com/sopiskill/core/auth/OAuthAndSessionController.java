package com.sopiskill.core.auth;

import com.sopiskill.core.common.IdCodec;
import com.sopiskill.core.security.AuthPrincipal;
import com.sopiskill.core.security.CsrfValidator;
import com.sopiskill.core.security.RateLimiterService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * Phase 7 Auth endpoints:
 * - `POST /v1/auth/refresh` (rotating HttpOnly refresh cookie + family reuse detection)
 * - `POST /v1/auth/exchange` (Google/Apple OIDC ID Token exchange + 409 ACCOUNT_LINK_REQUIRED)
 * - `POST /v1/auth/link/confirm` (HMAC linkTicket + proof-of-ownership verification)
 * - `GET/POST /v1/me/identities` (list & attach external OAuth identities)
 */
@RestController
public class OAuthAndSessionController {

    private final SessionService sessionService;
    private final OAuthIdentityService oauthService;
    private final CsrfValidator csrf;
    private final RateLimiterService rateLimiter;

    public OAuthAndSessionController(
            SessionService sessionService,
            OAuthIdentityService oauthService,
            CsrfValidator csrf,
            RateLimiterService rateLimiter
    ) {
        this.sessionService = sessionService;
        this.oauthService = oauthService;
        this.csrf = csrf;
        this.rateLimiter = rateLimiter;
    }

    public record OAuthExchangeRequest(@NotBlank String provider, @NotBlank String idToken) {}

    public record LinkConfirmRequest(@NotBlank String linkTicket, String password) {}

    @PostMapping("/v1/auth/refresh")
    public Map<String, Object> refresh(HttpServletRequest request, HttpServletResponse response) {
        csrf.verify(request);
        rateLimiter.check(request, "auth_refresh", 60, 60);
        return sessionService.rotateRefreshSession(request, response);
    }

    @PostMapping("/v1/auth/exchange")
    public ResponseEntity<Map<String, Object>> exchangeOAuth(
            @Valid @RequestBody OAuthExchangeRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        rateLimiter.check(request, "auth_oauth_exchange", 30, 60);
        Map<String, Object> res = oauthService.exchange(body.provider(), body.idToken());
        UUID uid = (UUID) res.get("userId");
        String email = (String) res.get("email");
        sessionService.issueNewSession(request, response, uid, email);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("usr", uid));
        out.put("email", email);
        out.put("displayName", res.get("displayName"));
        out.put("xp", res.get("xp"));
        boolean created = Boolean.TRUE.equals(res.get("created"));
        return ResponseEntity.status(created ? HttpStatus.CREATED : HttpStatus.OK).body(out);
    }

    @PostMapping("/v1/auth/link/confirm")
    public Map<String, Object> confirmLink(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody LinkConfirmRequest body,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        rateLimiter.check(request, "auth_link_confirm", 15, 60);
        UUID authUid = principal == null ? null : principal.userId();
        Map<String, Object> res = oauthService.confirmLink(body.linkTicket(), body.password(), authUid);
        UUID uid = (UUID) res.get("userId");
        String email = (String) res.get("email");
        sessionService.issueNewSession(request, response, uid, email);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", IdCodec.format("usr", uid));
        out.put("email", email);
        out.put("displayName", res.get("displayName"));
        out.put("xp", res.get("xp"));
        out.put("linkedProvider", res.get("linkedProvider"));
        return out;
    }

    @GetMapping("/v1/me/identities")
    public Map<String, Object> listIdentities(@AuthenticationPrincipal AuthPrincipal principal) {
        List<Map<String, Object>> items = oauthService.listIdentities(principal.userId());
        return Map.of("items", items, "total", items.size());
    }

    @PostMapping("/v1/me/identities")
    public Map<String, Object> attachIdentity(
            @AuthenticationPrincipal AuthPrincipal principal,
            @Valid @RequestBody OAuthExchangeRequest body,
            HttpServletRequest request
    ) {
        csrf.verify(request);
        rateLimiter.check(request, "me_identities_link", 15, 60);
        return oauthService.linkIdentityForAuthenticatedUser(principal.userId(), body.provider(), body.idToken());
    }
}
