-- Initial schema for the training intelligence dashboard.
-- Stores raw Strava activities/streams and raw Garmin wellness time series.

-- Strava activity summaries (one row per activity)
CREATE TABLE IF NOT EXISTS strava_activities (
    activity_id      bigint PRIMARY KEY,
    start_date       timestamptz NOT NULL,
    sport_type       text,
    name             text,
    distance_m       numeric,
    moving_time_s    int,
    elapsed_time_s   int,
    elevation_gain_m numeric,
    avg_hr           numeric,
    max_hr           numeric,
    avg_watts        numeric,
    avg_speed_ms     numeric,
    avg_cadence      numeric,
    relative_effort  numeric,
    calories         numeric,
    fetched_at       timestamptz DEFAULT now()
);

-- Strava per-second streams (one row per second per activity)
CREATE TABLE IF NOT EXISTS strava_activity_streams (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    activity_id bigint REFERENCES strava_activities(activity_id) ON DELETE CASCADE,
    t_seconds   int,
    hr_bpm      int,
    cadence     int,
    distance_m  numeric,
    altitude_m  numeric,
    velocity_ms numeric,
    watts       int,
    grade_pct   numeric,
    lat         numeric,
    lng         numeric,
    temp_c      numeric,
    UNIQUE (activity_id, t_seconds)
);

-- Garmin daily wellness summary (one row per calendar day)
CREATE TABLE IF NOT EXISTS garmin_daily_wellness (
    date               date PRIMARY KEY,
    resting_hr         int,
    min_hr             int,
    max_hr             int,
    avg_stress         int,
    max_stress         int,
    avg_spo2           numeric,
    lowest_spo2        numeric,
    body_battery_wake  int,
    body_battery_high  int,
    body_battery_low   int,
    body_battery_now   int,
    total_steps        int,
    active_calories    int,
    total_calories     int,
    avg_respiration    numeric,
    fetched_at         timestamptz DEFAULT now()
);

-- Garmin HRV readings (multiple readings per night)
CREATE TABLE IF NOT EXISTS garmin_hrv_readings (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date             date NOT NULL,
    ts               timestamptz,
    hrv_ms           int,
    hrv_avg_night    int,
    hrv_weekly_avg   int,
    hrv_baseline_low int,
    hrv_baseline_high int,
    hrv_status       text,
    UNIQUE (date, ts)
);

-- Garmin per-minute heart rate readings
CREATE TABLE IF NOT EXISTS garmin_heart_rate_readings (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date    date NOT NULL,
    ts      timestamptz NOT NULL,
    hr_bpm  int,
    UNIQUE (date, ts)
);

-- Garmin per-minute stress readings
CREATE TABLE IF NOT EXISTS garmin_stress_readings (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date         date NOT NULL,
    ts           timestamptz NOT NULL,
    stress_level int,
    UNIQUE (date, ts)
);

-- Garmin daily training readiness score
CREATE TABLE IF NOT EXISTS garmin_training_readiness (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date            date NOT NULL,
    ts              timestamptz,
    context         text,
    score           int,
    level           text,
    recovery_time_h int,
    acute_load      numeric,
    hrv_weekly_avg  int,
    sleep_score     int,
    UNIQUE (date, ts)
);

-- Indexes on date columns for efficient range queries
CREATE INDEX IF NOT EXISTS idx_strava_activities_start_date     ON strava_activities (start_date);
CREATE INDEX IF NOT EXISTS idx_strava_activity_streams_activity ON strava_activity_streams (activity_id);
CREATE INDEX IF NOT EXISTS idx_garmin_hrv_date                  ON garmin_hrv_readings (date);
CREATE INDEX IF NOT EXISTS idx_garmin_hr_date                   ON garmin_heart_rate_readings (date);
CREATE INDEX IF NOT EXISTS idx_garmin_stress_date               ON garmin_stress_readings (date);
CREATE INDEX IF NOT EXISTS idx_garmin_readiness_date            ON garmin_training_readiness (date);
