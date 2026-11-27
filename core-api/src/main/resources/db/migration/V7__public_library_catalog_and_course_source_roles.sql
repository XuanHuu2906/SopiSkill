-- Phase L2: Shared Curated Public Library Catalog & Course Source Roles (strictly additive)

ALTER TABLE core.sources
    ADD COLUMN IF NOT EXISTS external_key VARCHAR(160),
    ADD COLUMN IF NOT EXISTS domain_slug VARCHAR(64),
    ADD COLUMN IF NOT EXISTS pedagogy_tier VARCHAR(24) NOT NULL DEFAULT 'user_upload',
    ADD COLUMN IF NOT EXISTS commercial_safe BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS isbn VARCHAR(64),
    ADD COLUMN IF NOT EXISTS doi VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS ux_core_sources_external_key
    ON core.sources (external_key)
    WHERE external_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_core_sources_public_domain
    ON core.sources (domain_slug, pedagogy_tier)
    WHERE visibility = 'public';

ALTER TABLE core.course_sources
    ADD COLUMN IF NOT EXISTS role VARCHAR(24) NOT NULL DEFAULT 'reference';

CREATE UNIQUE INDEX IF NOT EXISTS ux_core_course_sources_primary
    ON core.course_sources (course_id)
    WHERE role = 'primary';

ALTER TABLE core.lessons
    ADD COLUMN IF NOT EXISTS grounding VARCHAR(32) NOT NULL DEFAULT 'general_ai_knowledge';
