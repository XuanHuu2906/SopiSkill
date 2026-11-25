-- Phase 5: Multi-Pod Agentic AI Tutor "Sopi" (3 thread kinds, 6 entry points, ChangeCard actions)
-- Owned exclusively by `core-api` (Spring Boot Flyway schema `core`).

ALTER TABLE core.tutor_threads
    ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'course',
    ADD COLUMN IF NOT EXISTS anchor_key VARCHAR(160),
    ADD COLUMN IF NOT EXISTS sealed BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE core.tutor_threads
    ALTER COLUMN lesson_id DROP NOT NULL;

ALTER TABLE core.tutor_messages
    ADD COLUMN IF NOT EXISTS entry_point VARCHAR(32) NOT NULL DEFAULT 'tab',
    ADD COLUMN IF NOT EXISTS context_label VARCHAR(200);

CREATE TABLE IF NOT EXISTS core.tutor_actions (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES core.tutor_threads(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES core.tutor_messages(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    tool_name VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    preview JSONB NOT NULL DEFAULT '{}'::jsonb,
    job_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_core_tutor_actions_course_user
    ON core.tutor_actions(course_id, user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_core_tutor_actions_thread
    ON core.tutor_actions(thread_id);
CREATE INDEX IF NOT EXISTS ix_core_tutor_actions_job
    ON core.tutor_actions(job_id) WHERE job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_core_tutor_threads_user_updated
    ON core.tutor_threads(user_id, updated_at DESC);
