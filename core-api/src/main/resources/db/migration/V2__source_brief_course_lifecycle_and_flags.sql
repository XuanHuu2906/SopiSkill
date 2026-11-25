-- Phase 3: Source Brief, Course/Lesson/Unit Lifecycle Metadata & Content QA Flags
-- Owned exclusively by Spring Boot `core-api` in schema `core`.

ALTER TABLE core.sources
    ADD COLUMN IF NOT EXISTS brief JSONB,
    ADD COLUMN IF NOT EXISTS word_count INTEGER,
    ADD COLUMN IF NOT EXISTS duration_minutes INTEGER,
    ADD COLUMN IF NOT EXISTS suggested_topic VARCHAR(200),
    ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(64);

ALTER TABLE core.lessons
    ADD COLUMN IF NOT EXISTS estimated_minutes SMALLINT NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS kind VARCHAR(24) NOT NULL DEFAULT 'lesson',
    ADD COLUMN IF NOT EXISTS format VARCHAR(24);

ALTER TABLE core.units
    ADD COLUMN IF NOT EXISTS kicker VARCHAR(120),
    ADD COLUMN IF NOT EXISTS blurb TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS tone VARCHAR(16) NOT NULL DEFAULT 'ember';

CREATE TABLE IF NOT EXISTS core.content_flags (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    lesson_id UUID REFERENCES core.lessons(id) ON DELETE CASCADE,
    block_index INTEGER,
    source VARCHAR(16) NOT NULL,
    code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'warning',
    details TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_core_content_flags_course ON core.content_flags (course_id, lesson_id);
CREATE INDEX IF NOT EXISTS ix_core_content_flags_unresolved ON core.content_flags (course_id) WHERE resolved_at IS NULL;
