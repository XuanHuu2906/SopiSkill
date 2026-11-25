-- Phase 4: Short-answer 3-level grading (`got_it | almost | not_yet`) & dispute ledger
-- Owned exclusively by `core-api` (Spring Boot Flyway schema `core`).

CREATE TABLE IF NOT EXISTS core.short_answer_grades (
    id UUID PRIMARY KEY,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    block_index INT NOT NULL,
    content_version INT NOT NULL,
    learner_answer TEXT NOT NULL,
    verdict VARCHAR(16) NOT NULL CHECK (verdict IN ('got_it', 'almost', 'not_yet')),
    correct BOOLEAN NOT NULL DEFAULT FALSE,
    grader VARCHAR(32) NOT NULL DEFAULT 'deterministic',
    key_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    feedback TEXT NOT NULL DEFAULT '',
    disputed BOOLEAN NOT NULL DEFAULT FALSE,
    dispute_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_core_short_grades_lesson_user
    ON core.short_answer_grades(lesson_id, user_id, block_index);
