-- Canonical idempotent schema for a fresh IWTBI installation.
--
-- Use this file when bootstrapping a brand-new database for the public release.

BEGIN;

-- ---------------------------------------------------------------------------
-- analyses
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.analyses (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_url       text        NOT NULL UNIQUE,
    repo_full_name text        NOT NULL,
    document       text        NOT NULL,
    git_sha        text        NOT NULL,
    tags           jsonb       NOT NULL DEFAULT '[]',
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.analyses
    ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]';

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
   SET search_path = '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'analyses_set_updated_at'
          AND tgrelid = 'public.analyses'::regclass
    ) THEN
        CREATE TRIGGER analyses_set_updated_at
            BEFORE UPDATE ON public.analyses
            FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_analyses_tags
    ON public.analyses USING gin (tags);

ALTER TABLE public.analyses ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'analyses'
          AND policyname = 'lectura_publica'
    ) THEN
        CREATE POLICY "lectura_publica" ON public.analyses
            FOR SELECT USING (true);
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- repo_notifications
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.repo_notifications (
    id         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id     text        NOT NULL,
    repo_url   text        NOT NULL,
    email      text        NOT NULL,
    sent_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_repo_notifications_job_id
    ON public.repo_notifications (job_id);

ALTER TABLE public.repo_notifications ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'repo_notifications'
          AND policyname = 'bloqueo_acceso_publico'
    ) THEN
        CREATE POLICY "bloqueo_acceso_publico" ON public.repo_notifications
            AS RESTRICTIVE
            USING (false);
    END IF;
END;
$$;

COMMIT;
