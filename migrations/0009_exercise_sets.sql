-- Strength work: what was lifted, how much of it, and how sure Garmin is.
--
-- Two tables at two fidelity levels, because the two halves of this feed cost
-- very different things to fetch.
--
-- `garmin_activity_exercises` comes from `summarizedExerciseSets`, which is
-- already inside the `get_activities_by_date` payload `ingest/garmin_activities.py`
-- fetches and was being discarded -- the same situation migration 0007 found
-- for running dynamics. It costs no extra API call and backfills to the first
-- logged session.
--
-- `garmin_exercise_sets` comes from `get_activity_exercise_sets`, one call per
-- session. It is what carries the individual set -- and, crucially, Garmin's
-- confidence in having named the exercise at all.
--
-- Both are keyed so that a full re-read of a session is idempotent, and both
-- are rewritten per activity rather than upserted row by row: relabelling an
-- exercise in Garmin Connect changes the key, so an upsert alone would leave
-- the old row behind as a ghost set that was never performed.

-- Weights are stored in KILOGRAMS, converted at ingest. Garmin serialises them
-- as grams (a 130 kg deadlift arrives as 130000.0), which is a wire format
-- rather than a unit anyone reads; `body_composition` already converts mass the
-- same way. This is a deliberate departure from 0007's store-as-returned rule,
-- which applied because those values had to reconcile against Garmin Connect's
-- own display.
--
-- Garmin uses two different "no load" sentinels in the same field -- `0.0` for a
-- bodyweight movement and `-1.0` for one where the weight was never entered --
-- and both are normalised to NULL at ingest. Left as numbers they would drag a
-- tonnage total and a mean load toward zero while looking like measurements.

CREATE TABLE IF NOT EXISTS garmin_activity_exercises (
    activity_id       bigint NOT NULL
                      REFERENCES garmin_activities(activity_id) ON DELETE CASCADE,
    -- Garmin's movement taxonomy, e.g. SQUAT, DEADLIFT, PULL_UP. `UNKNOWN` is a
    -- real value: the watch recorded reps it could not attribute to a movement.
    category          text NOT NULL,
    -- The specific lift within the category, e.g. BARBELL_SIFF_SQUAT. Empty
    -- string, not NULL, when Garmin got only as far as the category -- which is
    -- most of the history. It is part of the primary key, and Postgres will not
    -- key on a nullable column, so the absence has to be spellable.
    sub_category      text NOT NULL DEFAULT '',
    sets              integer,
    reps              integer,
    -- Sum of weight x reps across the exercise's sets. Verified against the
    -- per-set detail on 2026-09-09: it reconciles exactly, so it is stored as
    -- Garmin computes it rather than recomputed from a set table that only goes
    -- back as far as the per-set backfill.
    volume_kg         numeric,
    max_weight_kg     numeric,
    active_duration_s numeric,
    fetched_at        timestamptz DEFAULT now(),
    PRIMARY KEY (activity_id, category, sub_category)
);

CREATE INDEX IF NOT EXISTS idx_activity_exercises_category
    ON garmin_activity_exercises (category, sub_category);

CREATE TABLE IF NOT EXISTS garmin_exercise_sets (
    activity_id     bigint NOT NULL
                    REFERENCES garmin_activities(activity_id) ON DELETE CASCADE,
    -- Position in the session, counting rests. Garmin's own `messageIndex` is
    -- NOT usable here: it is populated on older sessions and null on every
    -- recent one, so keying on it would silently collapse a whole session's
    -- sets onto one row. Position is stable for a given fetch, and the whole
    -- session is rewritten on every re-read, so it never has to survive one.
    set_index       integer NOT NULL,
    -- `ACTIVE` or `REST`. Rest sets are kept rather than filtered at ingest:
    -- rest length is the difference between a heavy triple and a metcon, and it
    -- cannot be recovered later from a table that dropped it.
    set_type        text,
    start_time      timestamptz,
    duration_s      numeric,
    reps            integer,
    weight_kg       numeric,
    category        text,
    exercise_name   text,
    -- Garmin's confidence that it named the right movement, and the single most
    -- important column here for reading the rest. At 100 the exercise is
    -- settled -- either the watch was certain or the athlete named it in Garmin
    -- Connect. Below that the payload carried several candidates and this is
    -- merely the best guess: as of the 2026-09-09 backfill only 139 of 679
    -- active sets are settled, so a progression chart drawn over all of them
    -- would plot the watch's guesswork as if it were a training history. Only
    -- the top candidate is stored; the runner-ups drive no reading of this data.
    probability_pct numeric,
    fetched_at      timestamptz DEFAULT now(),
    PRIMARY KEY (activity_id, set_index)
);

CREATE INDEX IF NOT EXISTS idx_exercise_sets_activity
    ON garmin_exercise_sets (activity_id);
CREATE INDEX IF NOT EXISTS idx_exercise_sets_exercise
    ON garmin_exercise_sets (category, exercise_name);

-- RLS on with no policies, following migration 0008. Both the ingest and the
-- dashboard authenticate with the service role key, which bypasses RLS
-- entirely, so an empty policy set costs the pipeline nothing while denying the
-- anon and authenticated roles outright.
ALTER TABLE garmin_activity_exercises ENABLE ROW LEVEL SECURITY;
ALTER TABLE garmin_exercise_sets ENABLE ROW LEVEL SECURITY;
