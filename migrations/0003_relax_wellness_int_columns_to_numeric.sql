-- The Garmin API (garminconnect 0.3.5) returns float values for several fields
-- that were originally modeled as integers (e.g. restingHeartRate = 53.0).
-- Relax these to numeric so raw values are stored without coercion or errors.
ALTER TABLE garmin_daily_wellness
    ALTER COLUMN resting_hr        TYPE numeric,
    ALTER COLUMN min_hr            TYPE numeric,
    ALTER COLUMN max_hr            TYPE numeric,
    ALTER COLUMN avg_stress        TYPE numeric,
    ALTER COLUMN max_stress        TYPE numeric,
    ALTER COLUMN body_battery_wake TYPE numeric,
    ALTER COLUMN body_battery_high TYPE numeric,
    ALTER COLUMN body_battery_low  TYPE numeric,
    ALTER COLUMN body_battery_now  TYPE numeric,
    ALTER COLUMN total_steps       TYPE numeric,
    ALTER COLUMN active_calories   TYPE numeric,
    ALTER COLUMN total_calories    TYPE numeric;

ALTER TABLE garmin_hrv_readings
    ALTER COLUMN hrv_ms            TYPE numeric,
    ALTER COLUMN hrv_avg_night     TYPE numeric,
    ALTER COLUMN hrv_weekly_avg    TYPE numeric,
    ALTER COLUMN hrv_baseline_low  TYPE numeric,
    ALTER COLUMN hrv_baseline_high TYPE numeric;

ALTER TABLE garmin_heart_rate_readings
    ALTER COLUMN hr_bpm            TYPE numeric;

ALTER TABLE garmin_stress_readings
    ALTER COLUMN stress_level      TYPE numeric;

ALTER TABLE garmin_training_readiness
    ALTER COLUMN score             TYPE numeric,
    ALTER COLUMN recovery_time_h   TYPE numeric,
    ALTER COLUMN hrv_weekly_avg    TYPE numeric,
    ALTER COLUMN sleep_score       TYPE numeric;
