-- Running dynamics: the form metrics Garmin already returns alongside every
-- run, in the same `get_activities_by_date` payload the activity ingest
-- already fetches. Only `avg_cadence` was being stored.
--
-- Units follow Garmin's payload verbatim and are named into the column so a
-- reader never has to guess: stride length and vertical oscillation are
-- centimetres, vertical ratio a percentage, ground contact time milliseconds.
--
-- Two of these are derived rather than measured, which matters when reading
-- them: stride length is speed / cadence, and vertical ratio is vertical
-- oscillation / stride length. They are stored as returned rather than
-- recomputed, so the numbers match Garmin Connect exactly.
ALTER TABLE garmin_activities
    ADD COLUMN IF NOT EXISTS avg_stride_length_cm       numeric,
    ADD COLUMN IF NOT EXISTS avg_vertical_oscillation_cm numeric,
    ADD COLUMN IF NOT EXISTS avg_vertical_ratio_pct     numeric,
    ADD COLUMN IF NOT EXISTS avg_ground_contact_time_ms numeric;
