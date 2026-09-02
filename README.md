# Life Optimizer

Personal training intelligence dashboard powered by Garmin Connect.

## Architecture

- **Garmin Connect** -- sole data source: daily wellness (HRV, sleep, stress, body battery,
  heart rate, respiration) and the training log (activities, duration, distance, HR,
  native training load)
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

## GitHub Actions

The workflow runs every day at 9am UTC. You can also trigger it manually from the Actions tab.

Required secrets:
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Database schema

| Table | Rows | Description |
|---|---|---|
| `garmin_activities` | 1 per session | Summary + native training load |
| `garmin_daily_wellness` | 1 per day | Daily biometric summary |
| `garmin_hrv_readings` | ~73 per night | 5-min HRV during sleep |
| `garmin_heart_rate_readings` | ~300 per day | 2-min HR all day |
| `garmin_stress_readings` | ~200 per day | 3-min stress all day |
| `garmin_training_readiness` | 2-4 per day | Readiness snapshots |

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
