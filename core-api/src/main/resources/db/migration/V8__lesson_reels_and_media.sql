-- Phase 10A: 2-Phase Narrated Reel Engine & Media Call Ledger (`rel_`, `mdc_`)
-- Purely additive migration in `core` schema owned exclusively by `core-api`.

ALTER TABLE core.lessons
    ADD COLUMN IF NOT EXISTS reel_manifest JSONB,
    ADD COLUMN IF NOT EXISTS reel_status VARCHAR(24) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS reel_version INT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS core.lesson_reels (
    id UUID PRIMARY KEY,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    content_version INT NOT NULL DEFAULT 1,
    style_version VARCHAR(32) NOT NULL DEFAULT 'v1',
    language VARCHAR(16) NOT NULL DEFAULT 'vi',
    status VARCHAR(24) NOT NULL DEFAULT 'ready',
    duration_ms INT NOT NULL DEFAULT 0,
    manifest_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_lesson_reels_lesson_version UNIQUE (lesson_id, content_version)
);

CREATE INDEX IF NOT EXISTS idx_lesson_reels_course_id
    ON core.lesson_reels (course_id);

CREATE TABLE IF NOT EXISTS core.media_calls (
    id UUID PRIMARY KEY,
    lesson_id UUID REFERENCES core.lessons(id) ON DELETE CASCADE,
    course_id UUID REFERENCES core.courses(id) ON DELETE CASCADE,
    reel_id UUID REFERENCES core.lesson_reels(id) ON DELETE CASCADE,
    kind VARCHAR(32) NOT NULL DEFAULT 'reel_tts',
    provider VARCHAR(64) NOT NULL,
    voice VARCHAR(80),
    clip_id VARCHAR(96) NOT NULL,
    object_key TEXT NOT NULL,
    content_type VARCHAR(64) NOT NULL DEFAULT 'audio/wav',
    byte_size INT NOT NULL DEFAULT 0,
    duration_ms INT NOT NULL DEFAULT 0,
    status VARCHAR(24) NOT NULL DEFAULT 'ready',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_calls_lesson_clip
    ON core.media_calls (lesson_id, clip_id);

CREATE INDEX IF NOT EXISTS idx_media_calls_course_id
    ON core.media_calls (course_id);
