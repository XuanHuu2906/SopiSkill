-- Phase 7: OAuth2 (Google/Apple), Rotating Refresh Sessions, Onboarding 4 Steps, i18n & Web Push
-- Owned exclusively by core-api (Spring Boot Flyway).

ALTER TABLE core.users
    ADD COLUMN IF NOT EXISTS avatar VARCHAR(24) NOT NULL DEFAULT 'happy',
    ADD COLUMN IF NOT EXISTS locale VARCHAR(16) NOT NULL DEFAULT 'vi-VN',
    ADD COLUMN IF NOT EXISTS app_language VARCHAR(8) NOT NULL DEFAULT 'vi',
    ADD COLUMN IF NOT EXISTS lesson_language VARCHAR(8) NOT NULL DEFAULT 'vi',
    ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS onboarding_profile JSONB;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_avatar') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_avatar
            CHECK (avatar IN ('happy', 'graduate', 'curious', 'wink', 'excited'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_app_language') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_app_language
            CHECK (app_language IN ('vi', 'en', 'ja', 'ko', 'zh', 'es', 'fr', 'de', 'pt', 'id', 'th', 'hi'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_lesson_language') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_lesson_language
            CHECK (lesson_language IN ('vi', 'en', 'ja', 'ko', 'zh', 'es', 'fr', 'de', 'pt', 'id', 'th', 'hi'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS core.user_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    family_id UUID NOT NULL,
    refresh_token_hash VARCHAR(64) NOT NULL UNIQUE,
    user_agent VARCHAR(255),
    ip_address VARCHAR(64),
    expires_at TIMESTAMPTZ NOT NULL,
    rotated_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    reuse_detected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user ON core.user_sessions (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_user_sessions_family ON core.user_sessions (family_id);

CREATE TABLE IF NOT EXISTS core.auth_identities (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    provider VARCHAR(24) NOT NULL,
    provider_subject VARCHAR(191) NOT NULL,
    email VARCHAR(254),
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_auth_identities_provider_sub UNIQUE (provider, provider_subject),
    CONSTRAINT chk_auth_identities_provider CHECK (provider IN ('google', 'apple'))
);

CREATE INDEX IF NOT EXISTS ix_auth_identities_user ON core.auth_identities (user_id);

CREATE TABLE IF NOT EXISTS core.notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES core.users(id) ON DELETE CASCADE,
    daily_reminder_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    daily_reminder_minutes SMALLINT NOT NULL DEFAULT 1140,
    streak_guard_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    weekly_recap_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    comeback_nudge_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    course_ready_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    league_settled_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    quiet_start_minutes SMALLINT NOT NULL DEFAULT 1320,
    quiet_end_minutes SMALLINT NOT NULL DEFAULT 480,
    web_push_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_notif_daily_step CHECK (daily_reminder_minutes BETWEEN 0 AND 1425 AND (daily_reminder_minutes % 15) = 0),
    CONSTRAINT chk_notif_quiet_start CHECK (quiet_start_minutes BETWEEN 0 AND 1439),
    CONSTRAINT chk_notif_quiet_end CHECK (quiet_end_minutes BETWEEN 0 AND 1439)
);

CREATE TABLE IF NOT EXISTS core.push_subscriptions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh VARCHAR(255) NOT NULL,
    auth VARCHAR(255) NOT NULL,
    user_agent VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_push_subscriptions_user ON core.push_subscriptions (user_id);

CREATE TABLE IF NOT EXISTS core.in_app_notifications (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,
    title VARCHAR(180) NOT NULL,
    body TEXT NOT NULL,
    action_url VARCHAR(255),
    read_at TIMESTAMPTZ,
    dedupe_key VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_in_app_notifications_kind CHECK (
        kind IN ('course.ready', 'course.failed', 'league.settled', 'daily.reminder', 'streak.guard', 'weekly.recap', 'comeback.nudge')
    ),
    CONSTRAINT uq_in_app_notifications_dedupe UNIQUE (user_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS ix_in_app_notifications_user_created
    ON core.in_app_notifications (user_id, created_at DESC);
