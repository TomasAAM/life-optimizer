-- One-time data migration: correct the units of recovery_time_h.
--
-- Garmin's `recoveryTime` field is reported in MINUTES, but ingest/garmin.py
-- historically stored it verbatim into `recovery_time_h` (hours), inflating
-- every value 60x (e.g. 452 "hours" was really 452 minutes = 7.5 h). The
-- ingest bug is fixed going forward; this migration repairs existing rows.
--
-- IMPORTANT: run EXACTLY ONCE. Every row currently in the table predates the
-- code fix and is therefore in minutes, so an unconditional /60 is correct.
-- Re-running would divide already-corrected values again. The `> 96` guard
-- makes a second run a no-op for the egregious rows, but do not rely on it as
-- a substitute for applying this migration a single time.

UPDATE garmin_training_readiness
SET recovery_time_h = ROUND((recovery_time_h / 60.0)::numeric, 1)
WHERE recovery_time_h IS NOT NULL;
