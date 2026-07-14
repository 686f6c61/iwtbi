-- Canonical schema for IWTBI on internal PostgreSQL.
--
-- A fresh installation creates only empty tables and application contracts.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS analyses (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_url       text        NOT NULL UNIQUE,
    repo_full_name text        NOT NULL,
    document       text        NOT NULL,
    git_sha        text        NOT NULL,
    tags           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS analyses_set_updated_at ON analyses;
CREATE TRIGGER analyses_set_updated_at
    BEFORE UPDATE ON analyses
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_analyses_tags
    ON analyses USING gin (tags);

CREATE TABLE IF NOT EXISTS repo_notifications (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     text        NOT NULL,
    repo_url   text        NOT NULL,
    email      text        NOT NULL,
    sent_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repo_notifications_job_id
    ON repo_notifications (job_id);

CREATE INDEX IF NOT EXISTS idx_repo_notifications_repo_pending
    ON repo_notifications (repo_url, created_at)
    WHERE sent_at IS NULL;

CREATE TABLE IF NOT EXISTS email_preferences (
    email                  text        PRIMARY KEY,
    future_updates_enabled boolean     NOT NULL DEFAULT TRUE,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    unsubscribed_at         timestamptz
);

DROP TRIGGER IF EXISTS email_preferences_set_updated_at ON email_preferences;
CREATE TRIGGER email_preferences_set_updated_at
    BEFORE UPDATE ON email_preferences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS repo_subscriptions (
    repo_url              text        NOT NULL,
    email                 text        NOT NULL,
    active                boolean     NOT NULL DEFAULT TRUE,
    last_notified_git_sha text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    unsubscribed_at        timestamptz,
    PRIMARY KEY (repo_url, email)
);

DROP TRIGGER IF EXISTS repo_subscriptions_set_updated_at ON repo_subscriptions;
CREATE TRIGGER repo_subscriptions_set_updated_at
    BEFORE UPDATE ON repo_subscriptions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_repo_subscriptions_repo_active
    ON repo_subscriptions (repo_url, updated_at)
    WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_repo_subscriptions_email
    ON repo_subscriptions (email);

COMMIT;
