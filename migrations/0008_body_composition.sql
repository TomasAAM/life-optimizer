-- Body composition from the smart scale (Vitalia/Fitdays), routed through
-- Android Health Connect.
--
-- The path is Fitdays -> Health Connect -> an on-device exporter reading it via
-- the documented Jetpack background-read API -> a published Google Sheet ->
-- `ingest/body_composition.py`. Health Connect is an on-device store with no
-- REST or server-side access, so nothing in CI can read it directly; the sheet
-- is the relay that makes the feed reachable from GitHub Actions.
--
-- `measured_at_local` is a `timestamp` WITHOUT time zone, and the `_local`
-- suffix is load-bearing -- it follows `garmin_activities.start_time_local`,
-- which `dashboard.activity_metrics` reads for the same reason. What matters
-- about a weigh-in is the clock the athlete read it off: `BENCHMARKS.md`
-- prescribes weighing fasted in the morning, so the hour is data, not
-- metadata. Stored as `timestamptz` it would be normalised to UTC, and from
-- Santiago (UTC-3/-4) an on-protocol 07:12 weigh-in would come back as 10:12
-- and be flagged as off-protocol -- silently mislabelling nearly every
-- correct reading.
--
-- It is also the primary key rather than a surrogate id, because the ingest
-- re-reads the whole sheet every run and upserts. Two weigh-ins cannot share a
-- timestamp, so the natural key makes a full re-read idempotent the way
-- `activity_id` does for `garmin_activities`.
--
-- Health Connect stores each record type in its own table, so weight and body
-- fat arrive as separate records joined on their timestamp. It also has no
-- record type at all for several things the scale reports -- visceral fat,
-- metabolic age, physique rating, BMI -- which are dropped in transit. That is
-- no real loss: every one of those is derived from the same single bioimpedance
-- reading as body fat, through the vendor's own undisclosed regression, so they
-- carry no signal independent of the two columns kept here.
--
-- Fat mass in kg is deliberately NOT stored: it is exactly
-- weight_kg * body_fat_pct / 100, so storing it would let a stale copy
-- contradict its own inputs. It is derived at read time in
-- `dashboard.body_metrics`.
CREATE TABLE IF NOT EXISTS body_composition (
    measured_at_local timestamp PRIMARY KEY,
    weight_kg     numeric NOT NULL,
    body_fat_pct  numeric,
    lean_mass_kg  numeric,
    bone_mass_kg  numeric,
    body_water_kg numeric,
    -- Health Connect's originating app package (e.g. `cn.fitdays.fitdays`), or
    -- `manual` for a hand-corrected row. Several apps write into the same
    -- Health Connect record tables, so without this a manual correction and a
    -- scale reading are indistinguishable.
    source        text,
    fetched_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_body_composition_measured_at
    ON body_composition (measured_at_local);

-- RLS on, with no policies, deliberately. The older tables in this database
-- have RLS disabled, which leaves every row readable and writable by anyone
-- holding the anon key; this table is not going to repeat that. Both the
-- ingest and the dashboard authenticate with the service role key, which
-- bypasses RLS entirely, so an empty policy set costs the pipeline nothing
-- while denying the anon and authenticated roles outright. Bodyweight and
-- body-fat history is the most personal series in here, so deny-by-default is
-- the right posture: add a policy if something ever needs to read it without
-- the service role.
ALTER TABLE body_composition ENABLE ROW LEVEL SECURITY;
