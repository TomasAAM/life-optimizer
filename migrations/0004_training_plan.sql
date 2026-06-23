-- Training plan: lactate-anchored zones + LLM-generated weekly prescriptions.
--
-- training_zones is seeded once from the lactate lab test (the garmin-pipeline
-- analysis output) and refreshed only when a new test is done. The plan tables
-- are (re)generated every run by plan.generate: training_plan_weeks holds one
-- audited row per planned week, planned_sessions holds the daily prescriptions.

-- Five training zones derived from the lactate test (anchored on LT2).
CREATE TABLE IF NOT EXISTS training_zones (
    zone_index         int PRIMARY KEY,         -- 1..5, ascending intensity
    zone_name          text NOT NULL,
    hr_low             int,                      -- null = open at the low end (Z1)
    hr_high            int,                      -- null = open at the high end (Z5)
    pace_low_s_per_km  int,                      -- slower bound (larger s/km); null = open
    pace_high_s_per_km int,                      -- faster bound (smaller s/km); null = open
    source_test_date   date NOT NULL,
    lt2_hr             int,                      -- anchor heart rate (LTHR)
    lt2_pace_s_per_km  int,
    lt1_hr             int,                      -- null when the test did not capture LT1
    lt1_pace_s_per_km  int,
    updated_at         timestamptz DEFAULT now()
);

-- One row per generated plan week. input_summary + rationale form the audit
-- trail explaining why the week looks the way it does.
CREATE TABLE IF NOT EXISTS training_plan_weeks (
    week_start       date PRIMARY KEY,           -- Monday of the plan week
    target_race      text NOT NULL,              -- e.g. 'hyrox'
    race_date        date,
    phase            text NOT NULL,              -- base | build | peak | taper | race_week | off
    weeks_to_race    int,
    load_target_low  numeric,                    -- ACWR-bounded weekly load band
    load_target_high numeric,
    model            text,                       -- model id used to generate the week
    input_summary    jsonb,                      -- recent-data snapshot fed to the model
    rationale        text,                       -- model's explanation for the week
    generated_at     timestamptz DEFAULT now()
);

-- One row per prescribed session. prescription holds the structured detail
-- (intervals, distances, station list, reps) as JSON.
CREATE TABLE IF NOT EXISTS planned_sessions (
    week_start    date NOT NULL REFERENCES training_plan_weeks(week_start) ON DELETE CASCADE,
    session_date  date NOT NULL,
    session_type  text NOT NULL,                 -- run | strength | functional | sim | rest | cross
    title         text,
    zone          text,                          -- zone name, 'mixed', or null
    intensity     text,                          -- easy | moderate | hard
    prescription  jsonb,                         -- {detail, duration_min, distance_m}
    purpose       text,
    hyrox_focus   text,
    PRIMARY KEY (session_date, session_type)
);

CREATE INDEX IF NOT EXISTS idx_planned_sessions_week ON planned_sessions (week_start);
