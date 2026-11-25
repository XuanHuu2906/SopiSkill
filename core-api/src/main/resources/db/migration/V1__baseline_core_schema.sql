-- Phase 2 Baseline Core Schema (owned exclusively by Spring Boot `core-api` via Flyway).
-- Never touches `rag.*` schema (owned by Python `ai-engine` via Alembic).

CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(255),
    display_name VARCHAR(120) NOT NULL DEFAULT 'Người học',
    xp INTEGER NOT NULL DEFAULT 0,
    streak_days INTEGER NOT NULL DEFAULT 0,
    last_active_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.courses (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    topic VARCHAR(300) NOT NULL,
    language VARCHAR(16) NOT NULL DEFAULT 'vi',
    status VARCHAR(32) NOT NULL DEFAULT 'interviewing',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_courses_user ON core.courses (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.course_interviews (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL UNIQUE REFERENCES core.courses(id) ON DELETE CASCADE,
    questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    answers JSONB NOT NULL DEFAULT '[]'::jsonb,
    completed_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.course_proposals (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_course_proposals_version UNIQUE (course_id, version)
);
CREATE INDEX IF NOT EXISTS ix_core_proposals_course ON core.course_proposals (course_id, version DESC);

CREATE TABLE IF NOT EXISTS core.generation_jobs (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    stage VARCHAR(64),
    lessons_done INTEGER NOT NULL DEFAULT 0,
    lessons_total INTEGER,
    attempts INTEGER NOT NULL DEFAULT 1,
    dispatched BOOLEAN NOT NULL DEFAULT FALSE,
    last_error_code VARCHAR(64),
    error_json JSONB,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_estimate_usd DOUBLE PRECISION,
    cost_known BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_gen_jobs_course ON core.generation_jobs (course_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.units (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL,
    title VARCHAR(300) NOT NULL,
    blurb TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_units_course ON core.units (course_id, order_index);

CREATE TABLE IF NOT EXISTS core.lessons (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    unit_id UUID NOT NULL REFERENCES core.units(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL,
    title VARCHAR(300) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    content_version INTEGER NOT NULL DEFAULT 1,
    content_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    grounding VARCHAR(32) NOT NULL DEFAULT 'general_ai_knowledge',
    evidence_notice TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_lessons_course ON core.lessons (course_id, order_index);
CREATE INDEX IF NOT EXISTS ix_core_lessons_unit ON core.lessons (unit_id, order_index);

CREATE TABLE IF NOT EXISTS core.lesson_attempts (
    id UUID PRIMARY KEY,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    client_attempt_id VARCHAR(128) NOT NULL,
    content_version INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    total INTEGER NOT NULL,
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    xp_earned INTEGER NOT NULL DEFAULT 0,
    answers_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    results_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_lesson_attempt_idemp UNIQUE (lesson_id, user_id, client_attempt_id)
);
CREATE INDEX IF NOT EXISTS ix_core_attempts_user_lesson ON core.lesson_attempts (user_id, lesson_id, content_version);

CREATE TABLE IF NOT EXISTS core.xp_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    lesson_id UUID REFERENCES core.lessons(id) ON DELETE SET NULL,
    attempt_id UUID REFERENCES core.lesson_attempts(id) ON DELETE SET NULL,
    amount INTEGER NOT NULL,
    reason VARCHAR(64) NOT NULL DEFAULT 'lesson_attempt',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_xp_events_user ON core.xp_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.course_glossary_terms (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    lesson_id UUID REFERENCES core.lessons(id) ON DELETE SET NULL,
    term_key VARCHAR(200) NOT NULL,
    term VARCHAR(200) NOT NULL,
    definition TEXT NOT NULL,
    example TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_glossary_course_term UNIQUE (course_id, term_key)
);

CREATE TABLE IF NOT EXISTS core.sources (
    id UUID PRIMARY KEY,
    owner_id UUID REFERENCES core.users(id) ON DELETE CASCADE,
    source_type VARCHAR(32) NOT NULL DEFAULT 'user_document',
    title VARCHAR(300) NOT NULL,
    canonical_url TEXT,
    author VARCHAR(200),
    publisher VARCHAR(200),
    publication_date VARCHAR(64),
    source_updated_at VARCHAR(64),
    retrieved_at TIMESTAMPTZ,
    language VARCHAR(32),
    version VARCHAR(64),
    visibility VARCHAR(32) NOT NULL DEFAULT 'private',
    license_info TEXT,
    content_hash VARCHAR(128),
    verification_status VARCHAR(32) NOT NULL DEFAULT 'unverified',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_sources_owner ON core.sources (owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.source_documents (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES core.sources(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    origin VARCHAR(32) NOT NULL DEFAULT 'upload',
    origin_url TEXT,
    mime VARCHAR(128) NOT NULL DEFAULT 'application/pdf',
    byte_size BIGINT NOT NULL DEFAULT 0,
    page_count INTEGER,
    pipeline_version VARCHAR(64) NOT NULL DEFAULT 'pypdf-v1',
    original_filename VARCHAR(300),
    storage_key VARCHAR(500),
    chunk_count INTEGER NOT NULL DEFAULT 0,
    preview TEXT,
    error_json JSONB,
    attempts INTEGER NOT NULL DEFAULT 1,
    rights_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    text_source VARCHAR(32),
    ocr_pages INTEGER NOT NULL DEFAULT 0,
    ocr_engine VARCHAR(64),
    ocr_version VARCHAR(64),
    ingested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_source_docs_source ON core.source_documents (source_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.course_sources (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES core.sources(id) ON DELETE CASCADE,
    evaluation_json JSONB,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_course_source UNIQUE (course_id, source_id)
);

CREATE TABLE IF NOT EXISTS core.lesson_citations (
    id UUID PRIMARY KEY,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES core.sources(id) ON DELETE CASCADE,
    source_version VARCHAR(64),
    chunk_id VARCHAR(128),
    page_number INTEGER,
    section_anchor VARCHAR(200),
    evidence_text TEXT,
    validation_status VARCHAR(32) NOT NULL DEFAULT 'unverified',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.source_research_runs (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    query_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidates_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    accepted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.skills (
    id UUID PRIMARY KEY,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    skill_key VARCHAR(128) NOT NULL,
    title VARCHAR(300) NOT NULL,
    bloom_level VARCHAR(32) NOT NULL DEFAULT 'understand',
    outcome TEXT NOT NULL DEFAULT '',
    prerequisites_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT uq_core_skills_course_key UNIQUE (course_id, skill_key)
);

CREATE TABLE IF NOT EXISTS core.lesson_skills (
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES core.skills(id) ON DELETE CASCADE,
    PRIMARY KEY (lesson_id, skill_id)
);

CREATE TABLE IF NOT EXISTS core.skill_mastery (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES core.skills(id) ON DELETE CASCADE,
    mastery_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    method VARCHAR(32) NOT NULL DEFAULT 'bkt_ewma',
    attempts INTEGER NOT NULL DEFAULT 0,
    correct INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    pass_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    last_attempt_at TIMESTAMPTZ,
    CONSTRAINT uq_core_skill_mastery UNIQUE (user_id, skill_id)
);

CREATE TABLE IF NOT EXISTS core.review_cards (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    state INTEGER NOT NULL DEFAULT 1,
    stability DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    difficulty DOUBLE PRECISION NOT NULL DEFAULT 5.0,
    due_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_review_at TIMESTAMPTZ,
    scheduler_version VARCHAR(32) NOT NULL DEFAULT 'fsrs-v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_review_card_user_lesson UNIQUE (user_id, lesson_id)
);
CREATE INDEX IF NOT EXISTS ix_core_review_cards_due ON core.review_cards (user_id, due_at);

CREATE TABLE IF NOT EXISTS core.review_events (
    id UUID PRIMARY KEY,
    card_id UUID NOT NULL REFERENCES core.review_cards(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    client_review_id VARCHAR(128) NOT NULL,
    rating INTEGER NOT NULL,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_review_event_idemp UNIQUE (card_id, user_id, client_review_id)
);

CREATE TABLE IF NOT EXISTS core.recommendation_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    token_hash VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_core_rec_event_token UNIQUE (user_id, course_id, token_hash)
);

CREATE TABLE IF NOT EXISTS core.tutor_threads (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    lesson_id UUID NOT NULL REFERENCES core.lessons(id) ON DELETE CASCADE,
    title VARCHAR(300) NOT NULL DEFAULT 'Hội thoại',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_tutor_threads_user_course ON core.tutor_threads (user_id, course_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS core.tutor_messages (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES core.tutor_threads(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    client_message_id VARCHAR(128),
    role VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'completed',
    content TEXT NOT NULL DEFAULT '',
    context_ref JSONB,
    error_code VARCHAR(64),
    finish_reason VARCHAR(32),
    citations_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    cancel_requested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_tutor_messages_thread ON core.tutor_messages (thread_id, created_at ASC);

CREATE TABLE IF NOT EXISTS core.tutor_tool_calls (
    id UUID PRIMARY KEY,
    message_id UUID NOT NULL REFERENCES core.tutor_messages(id) ON DELETE CASCADE,
    tool_name VARCHAR(64) NOT NULL,
    status VARCHAR(24) NOT NULL,
    summary TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS core.tutor_usage_events (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    course_id UUID NOT NULL REFERENCES core.courses(id) ON DELETE CASCADE,
    message_id UUID REFERENCES core.tutor_messages(id) ON DELETE SET NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_core_tutor_usage_user_time ON core.tutor_usage_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS core.llm_usage_events (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES core.users(id) ON DELETE SET NULL,
    course_id UUID REFERENCES core.courses(id) ON DELETE SET NULL,
    operation VARCHAR(64) NOT NULL,
    provider VARCHAR(64) NOT NULL DEFAULT 'mock',
    model VARCHAR(128) NOT NULL DEFAULT 'mock-v1',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
