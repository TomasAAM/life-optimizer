"""Ingestion orchestrator.

Determines the sync window, then runs Garmin and Strava
ingestion in sequence. Safe to re-run -- all upserts are
idempotent.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

from ingest import garmin, garmin_activities, strava

# Resolve .env relative to this file's project root so it works
# whether called as `python -m ingest.run` or via GitHub Actions.
_PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 90


def get_supabase_client():
    """Create an authenticated Supabase client from environment variables.

    Returns
    -------
    supabase.Client
        Authenticated Supabase client using the service role key.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_last_synced_date(supabase) -> date:
    """Find the most recent date already in Supabase.

    Checks both garmin_daily_wellness and strava_activities
    and returns the earlier of the two latest dates so we
    never miss data from either source.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.

    Returns
    -------
    date
        The date to start syncing from.
    """
    default_since = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    try:
        result = (
            supabase.table("garmin_daily_wellness")
            .select("date")
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        garmin_latest = (
            date.fromisoformat(result.data[0]["date"]) if result.data else default_since
        )
    except Exception:  # noqa: BLE001
        garmin_latest = default_since

    try:
        result = (
            supabase.table("strava_activities")
            .select("start_date")
            .order("start_date", desc=True)
            .limit(1)
            .execute()
        )
        strava_latest = (
            datetime.fromisoformat(result.data[0]["start_date"]).date()
            if result.data
            else default_since
        )
    except Exception:  # noqa: BLE001
        strava_latest = default_since

    since = min(garmin_latest, strava_latest)
    logger.info("Syncing from %s", since)
    return since


def main() -> None:
    """Run the full ingestion pipeline."""
    logger.info("Starting ingestion pipeline")

    supabase = get_supabase_client()
    since = get_last_synced_date(supabase)
    since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)

    logger.info("Running Strava ingestion from %s", since_dt.date())
    try:
        strava.ingest(supabase, since=since_dt)
    except Exception as exc:  # noqa: BLE001
        logger.error("Strava ingestion failed: %s", exc, exc_info=True)

    logger.info("Running Garmin ingestion from %s", since)
    try:
        # Authenticate once and reuse the client for both wellness and
        # activity ingestion to avoid a second SSO login.
        garmin_client = garmin.get_client()
        garmin.ingest(supabase, since=since, client=garmin_client)
        garmin_activities.ingest(supabase, garmin_client, since=since)
    except Exception as exc:  # noqa: BLE001
        logger.error("Garmin ingestion failed: %s", exc, exc_info=True)

    logger.info("Ingestion pipeline complete")


if __name__ == "__main__":
    main()
