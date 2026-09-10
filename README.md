# Life Optimizer

Personal training intelligence dashboard powered by Garmin Connect.

## Architecture

- **Garmin Connect** -- source of all *training* data: daily wellness (HRV, sleep, stress,
  body battery, heart rate, respiration) and the training log (activities, duration,
  distance, HR, native training load, and the exercises, sets and loads behind
  every strength session)
- **Smart scale** -- bodyweight and body composition, via Android Health Connect
  (see below)
- **Supabase** -- raw data storage + the training plan (zones, plan weeks, sessions)
- **GitHub Actions** -- ingestion every day at 9am UTC
- **Training plan** -- lactate-anchored, generated on demand in multi-week blocks (see below)

## Training plan (on-demand blocks)

The plan is generated in **multi-week blocks** (default 4 weeks) on demand — not on a
schedule. Generation is anchored only to the **measured lactate zones** and the athlete's
**known loads**; it deliberately does **not** consume Garmin recovery data (CTL/ATL/HRV/
readiness) — the athlete self-regulates on the day. Periodization is a pure function of the
race calendar.

Configuration lives in `plan/config.py`:
- `races` — the calendar of target races. For any week the phase is computed against the
  next race on or after it, so one block can flow across a race into the next build.
- `block_weeks`, `pre_race_freshen_days`, `post_race_recovery_days`, weekly availability,
  `base_weekly_km`, and `ATHLETE_LOADS` (the athlete's working weights).

Workflow:

```bash
# 1. Print the generation brief for the upcoming block (phases, zones, loads, guardrails)
python -m plan.context

# 2. Write the block to data/plan_block.json as a PlannedBlock (see plan/models.py).
#    (Done by the Claude Code agent from the brief; review before persisting.)

# 3. Validate against the Pydantic schema and upsert every week to Supabase
python -m plan.persist

# 4. Regenerate the dashboard (shows the current week + a block overview)
python -m dashboard.build
```

Editing one week in `data/plan_block.json` and re-running `plan.persist` re-upserts just that
week (idempotent per `week_start`) — the review-and-tweak loop.

Re-seed zones after a new lactate test with `python -m plan.zones`.

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/TomasAAM/life-optimizer.git
cd life-optimizer
```

### 2. Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Fill in your credentials in .env
```

### 4. Run ingestion locally

```bash
python ingest/run.py
```

### 5. Backfill the strength history (once)

The daily pipeline only looks at its sync window, so the exercise tables start
empty. The per-exercise summary rides along in the activity payload and costs
nothing extra; the per-set detail costs one Garmin call per strength or HIIT
session, so the history is loaded in one pass:

```bash
python -m scripts.backfill_exercise_sets
```

Safe to re-run — every session is rewritten wholesale rather than upserted, so a
movement renamed in Garmin Connect corrects itself on the next pass. Pass a date
to start later, e.g. `python -m scripts.backfill_exercise_sets 2026-07-01`.

## GitHub Actions

The workflow runs every day at 9am UTC. You can also trigger it manually from the Actions tab.

Required secrets:
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional:
- `BODY_SHEET_CSV_URL` -- if unset, body-composition ingestion is skipped and the
  rest of the pipeline runs unchanged.

## Body composition (smart scale)

Weight and body fat come from a Bluetooth scale through **Android Health Connect**.
Health Connect is an *on-device* store: its read API is a Kotlin/Android SDK with no
REST, server-side or CLI access, so nothing running in GitHub Actions can read it
directly. The chain that makes it reachable is:

```
Vitalia scale -> Fitdays app -> Health Connect
  -> on-device exporter (scheduled background read)
  -> Google Sheet, published to the web as CSV
  -> ingest/body_composition.py -> Supabase
```

Publishing the sheet as CSV is what avoids a Google service account -- the URL is the
only credential, so **keep it unguessable and treat it as a secret**. Set it as
`BODY_SHEET_CSV_URL`.

The whole sheet is re-read and upserted on every run, so the ingest is idempotent and
a row corrected in the sheet corrects in Supabase on the next run.

Two things worth knowing about the data:

- **Only weight is measured.** The scale reports body fat, muscle, water, bone,
  visceral fat and metabolic age from a *single* bioimpedance reading pushed through
  the vendor's undisclosed regression, so those are one estimate shown many ways
  rather than independent metrics. The dashboard draws the derived split dashed.
- **Health Connect carries about five of the scale's seventeen metrics** -- weight,
  body fat, lean mass, bone mass, body water. It has no record type for visceral fat,
  metabolic age, physique rating or BMI, so they are dropped in transit. Nothing
  independent is lost, for the reason above.

Timestamps are stored as **local wall clock** (`measured_at_local`), not UTC, because
`BENCHMARKS.md` prescribes weighing fasted in the morning and the dashboard flags
readings taken off that protocol -- normalising to UTC would shift a Santiago 07:12
weigh-in to 10:12 and mislabel it.

## Database schema

| Table | Rows | Description |
|---|---|---|
| `garmin_activities` | 1 per session | Summary + native training load |
| `garmin_activity_exercises` | 1 per exercise per session | What was lifted: sets, reps, tonnage, heaviest load |
| `garmin_exercise_sets` | 1 per set (rests included) | The individual set, with Garmin's confidence that it named the movement |
| `garmin_daily_wellness` | 1 per day | Daily biometric summary |
| `garmin_hrv_readings` | ~73 per night | 5-min HRV during sleep |
| `garmin_heart_rate_readings` | ~300 per day | 2-min HR all day |
| `garmin_stress_readings` | ~200 per day | 3-min stress all day |
| `garmin_training_readiness` | 2-4 per day | Readiness snapshots |
| `body_composition` | 1 per weigh-in | Weight + body-fat estimate from the smart scale |

### Retired: Strava (frozen archive)

Strava was the original activity source. API access was lost and the tables stopped
receiving rows on **2026-06-27**; ingestion was removed on 2026-09-01. The historical
data is **kept in Supabase, read-only, and is not read by any code**:

| Table | Rows | Notes |
|---|---|---|
| `strava_activities` | 172 (2026-03-08 → 2026-06-27) | Superseded by `garmin_activities`, which covers the same window from 2026-03-09 |
| `strava_activity_streams` | ~344k | Per-second HR/pace/power streams. No Garmin equivalent exists -- irreplaceable |

The rows were deliberately **not** migrated into `garmin_activities`: Garmin already
recorded the same sessions, so a migration would have duplicated them and corrupted the
training-load signal the dashboard depends on. Query these tables directly if you ever
need the pre-July history.
