-- Lock down every table that predates the deny-by-default RLS policy introduced
-- for body composition and exercise sets. The application reads and writes these
-- tables only from trusted backend jobs using the Supabase service-role key; the
-- generated GitHub Pages site contains no database credentials and makes no
-- browser-side Supabase requests.
--
-- RLS with no policies denies Data API access to anon and authenticated users.
-- Explicit privilege revocation provides a second guard and makes the intended
-- access model visible in PostgreSQL's catalog.

ALTER TABLE public.strava_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.strava_activity_streams ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_daily_wellness ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_hrv_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_heart_rate_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_stress_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_training_readiness ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.garmin_activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.training_zones ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.training_plan_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.planned_sessions ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.strava_activities FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.strava_activity_streams FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_daily_wellness FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_hrv_readings FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_heart_rate_readings FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_stress_readings FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_training_readiness FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_activities FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.training_zones FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.training_plan_weeks FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.planned_sessions FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.body_composition FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_activity_exercises FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.garmin_exercise_sets FROM anon, authenticated;

-- Abort the migration if any table is missing RLS or still grants client-role
-- access. The service_role is deliberately omitted because it is the trusted
-- backend identity used by ingestion and dashboard generation.
DO $$
DECLARE
    insecure_table text;
BEGIN
    SELECT c.relname
    INTO insecure_table
    FROM pg_catalog.pg_class AS c
    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname IN (
          'strava_activities',
          'strava_activity_streams',
          'garmin_daily_wellness',
          'garmin_hrv_readings',
          'garmin_heart_rate_readings',
          'garmin_stress_readings',
          'garmin_training_readiness',
          'garmin_activities',
          'training_zones',
          'training_plan_weeks',
          'planned_sessions',
          'body_composition',
          'garmin_activity_exercises',
          'garmin_exercise_sets'
      )
      AND (
          NOT c.relrowsecurity
          OR pg_catalog.has_table_privilege('anon', c.oid, 'SELECT, INSERT, UPDATE, DELETE')
          OR pg_catalog.has_table_privilege(
              'authenticated', c.oid, 'SELECT, INSERT, UPDATE, DELETE'
          )
      )
    LIMIT 1;

    IF insecure_table IS NOT NULL THEN
        RAISE EXCEPTION 'RLS verification failed for public.%', insecure_table;
    END IF;
END
$$;
