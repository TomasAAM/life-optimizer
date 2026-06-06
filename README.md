# Life Optimizer

Personal training intelligence dashboard powered by Garmin Connect and Strava.

## Architecture

- **Garmin Connect** -- daily wellness data: HRV, sleep, stress, body battery, heart rate, respiration
- **Strava** -- training log: activities, pace, power, HR streams
- **Supabase** -- raw data storage (7 tables)
- **GitHub Actions** -- weekly ingestion every Sunday at 9am UTC

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

The workflow runs every Sunday at 9am UTC. You can also trigger it manually from the Actions tab.

Required secrets:
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`
- `GARMIN_EMAIL`
- `GARMIN_PASSWORD`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

## Database schema

| Table | Rows | Description |
|---|---|---|
| `strava_activities` | 1 per session | Summary + performance |
| `strava_activity_streams` | 1 per second per session | Raw time-series |
| `garmin_daily_wellness` | 1 per day | Daily biometric summary |
| `garmin_hrv_readings` | ~73 per night | 5-min HRV during sleep |
| `garmin_heart_rate_readings` | ~300 per day | 2-min HR all day |
| `garmin_stress_readings` | ~200 per day | 3-min stress all day |
| `garmin_training_readiness` | 2-4 per day | Readiness snapshots |
