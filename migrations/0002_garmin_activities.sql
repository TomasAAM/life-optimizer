-- Garmin activities: source of truth for training sessions, including
-- unified multisport (HYROX) sessions that Strava fragments. Garmin's native
-- activityTrainingLoad is the preferred load signal over Strava relative_effort.
CREATE TABLE IF NOT EXISTS garmin_activities (
    activity_id        bigint PRIMARY KEY,
    parent_id          bigint,              -- set on multisport child legs
    start_time         timestamptz NOT NULL, -- from startTimeGMT
    start_time_local   timestamp,
    activity_name      text,
    activity_type      text,                -- activityType.typeKey (e.g. multi_sport)
    parent_type        text,                -- activityType.parentTypeId resolved label
    duration_s         numeric,
    elapsed_duration_s numeric,
    moving_duration_s  numeric,
    distance_m         numeric,
    elevation_gain_m   numeric,
    avg_hr             numeric,
    max_hr             numeric,
    calories           numeric,
    training_load      numeric,             -- activityTrainingLoad (Garmin's load)
    aerobic_te         numeric,             -- aerobicTrainingEffect
    anaerobic_te       numeric,             -- anaerobicTrainingEffect
    avg_cadence        numeric,
    is_multisport      boolean DEFAULT false,
    fetched_at         timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_garmin_activities_start_time ON garmin_activities (start_time);
CREATE INDEX IF NOT EXISTS idx_garmin_activities_parent     ON garmin_activities (parent_id);
CREATE INDEX IF NOT EXISTS idx_garmin_activities_type       ON garmin_activities (activity_type);
