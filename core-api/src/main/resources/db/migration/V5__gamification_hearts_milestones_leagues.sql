-- Phase 6: Gamification, Hearts (Timed + FSRS Refill), Milestones & Leagues
-- Owned exclusively by core-api (Spring Boot Flyway).

ALTER TABLE core.users
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS goal_lessons SMALLINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS best_streak_days INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_active_day DATE,
    ADD COLUMN IF NOT EXISTS streak_freezes SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hearts SMALLINT NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS hearts_refill_at TIMESTAMPTZ;

UPDATE core.users
SET last_active_day = last_active_date,
    best_streak_days = GREATEST(best_streak_days, streak_days)
WHERE last_active_day IS NULL AND last_active_date IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_goal_lessons') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_goal_lessons CHECK (goal_lessons IN (1, 2, 3));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_streak_freezes') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_streak_freezes CHECK (streak_freezes BETWEEN 0 AND 2);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_hearts') THEN
        ALTER TABLE core.users ADD CONSTRAINT chk_users_hearts CHECK (hearts BETWEEN 0 AND 5);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS core.user_daily_activity (
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    activity_day DATE NOT NULL,
    lessons_completed INTEGER NOT NULL DEFAULT 0,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    attempts_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, activity_day)
);

CREATE INDEX IF NOT EXISTS ix_user_daily_activity_user_day
    ON core.user_daily_activity (user_id, activity_day DESC);

CREATE TABLE IF NOT EXISTS core.user_milestones (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    code VARCHAR(64) NOT NULL,
    category VARCHAR(32) NOT NULL,
    title VARCHAR(160) NOT NULL,
    description VARCHAR(240) NOT NULL DEFAULT '',
    earned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_milestones_user_code UNIQUE (user_id, code)
);

CREATE INDEX IF NOT EXISTS ix_user_milestones_user_earned
    ON core.user_milestones (user_id, earned_at DESC);

CREATE TABLE IF NOT EXISTS core.league_cohorts (
    id UUID PRIMARY KEY,
    tier VARCHAR(24) NOT NULL,
    week_start DATE NOT NULL,
    settled BOOLEAN NOT NULL DEFAULT FALSE,
    settled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_league_cohorts_tier CHECK (tier IN ('bronze', 'silver', 'gold', 'sapphire', 'ruby'))
);

CREATE INDEX IF NOT EXISTS ix_league_cohorts_tier_week
    ON core.league_cohorts (tier, week_start, settled);

CREATE TABLE IF NOT EXISTS core.league_memberships (
    id UUID PRIMARY KEY,
    cohort_id UUID NOT NULL REFERENCES core.league_cohorts(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    weekly_xp INTEGER NOT NULL DEFAULT 0,
    rank INTEGER,
    outcome VARCHAR(24),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_league_memberships_cohort_user UNIQUE (cohort_id, user_id),
    CONSTRAINT chk_league_memberships_outcome CHECK (outcome IS NULL OR outcome IN ('promoted', 'stayed', 'demoted'))
);

CREATE INDEX IF NOT EXISTS ix_league_memberships_user
    ON core.league_memberships (user_id, joined_at DESC);

CREATE INDEX IF NOT EXISTS ix_league_memberships_cohort_xp
    ON core.league_memberships (cohort_id, weekly_xp DESC, joined_at ASC);
