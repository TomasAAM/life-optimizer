-- Keep one current row per ingestion stage. A failed attempt updates the attempt
-- and status fields while retaining the previous last_success_at timestamp. CI
-- and the dashboard use that timestamp to distinguish failures from fresh data.
CREATE TABLE IF NOT EXISTS public.ingestion_source_status (
    source          text PRIMARY KEY,
    status          text NOT NULL CHECK (
        status IN ('success', 'degraded', 'failed', 'skipped')
    ),
    last_attempt_at timestamptz NOT NULL,
    last_success_at timestamptz,
    attempted       integer NOT NULL DEFAULT 0 CHECK (attempted >= 0),
    succeeded       integer NOT NULL DEFAULT 0 CHECK (succeeded >= 0),
    failed          integer NOT NULL DEFAULT 0 CHECK (failed >= 0),
    rows_written    integer NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    detail_code     text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.ingestion_source_status ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES
ON TABLE public.ingestion_source_status
FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE public.ingestion_source_status
TO service_role;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'ingestion_source_status'
          AND (
              NOT c.relrowsecurity
              OR pg_catalog.has_table_privilege(
                  'anon', c.oid, 'SELECT, INSERT, UPDATE, DELETE'
              )
              OR pg_catalog.has_table_privilege(
                  'authenticated', c.oid, 'SELECT, INSERT, UPDATE, DELETE'
              )
          )
    ) THEN
        RAISE EXCEPTION
            'RLS verification failed for public.ingestion_source_status';
    END IF;
END
$$;
