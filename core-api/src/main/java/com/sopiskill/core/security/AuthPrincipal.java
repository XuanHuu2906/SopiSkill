package com.sopiskill.core.security;

import java.util.UUID;

public record AuthPrincipal(UUID userId, String email) {}
