-- Week-level methodology note (the training principles a generated week applies).
-- Per-session "why" is stored inside planned_sessions.prescription JSON, so no
-- column is needed there.
ALTER TABLE training_plan_weeks ADD COLUMN IF NOT EXISTS methodology text;
