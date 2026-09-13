"""Ingestion orchestrator.

Determines the sync window, then runs Garmin ingestion. Safe to
re-run -- all upserts are idempotent.

Garmin is the sole source of activity data. Strava ingestion was
removed on 2026-09-01 after API access was lost; the historical
``strava_activities`` and ``strava_activity_streams`` tables remain
in Supabase as a frozen archive (last row 2026-06-27) and are not
read by this pipeline.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

from ingest import body_composition, exercise_sets, garmin, garmin_activities
from ingest.status import SourceResult, record_source_result, source_is_stale

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
DEFAULT_SYNC_OVERLAP_DAYS = 2
DEFAULT_GARMIN_MAX_STALENESS_HOURS = 36

_GARMIN_WATERMARKS = {
    "wellness": ("garmin_daily_wellness", "date"),
    "hrv": ("garmin_hrv_readings", "date"),
    "heart_rate": ("garmin_heart_rate_readings", "date"),
    "stress": ("garmin_stress_readings", "date"),
    "readiness": ("garmin_training_readiness", "date"),
}


@dataclass(frozen=True)
class IngestionPolicy:
    """Operational thresholds controlling retries and deployment safety.

    Parameters
    ----------
    overlap_days : int
        Days re-read before each source's latest stored record.
    garmin_max_staleness_hours : int
        Maximum age of a successful critical Garmin stage.

    Examples
    --------
    >>> IngestionPolicy(overlap_days=2, garmin_max_staleness_hours=36)
    IngestionPolicy(overlap_days=2, garmin_max_staleness_hours=36)
    """

    overlap_days: int = DEFAULT_SYNC_OVERLAP_DAYS
    garmin_max_staleness_hours: int = DEFAULT_GARMIN_MAX_STALENESS_HOURS

    @classmethod
    def from_environment(cls) -> "IngestionPolicy":
        """Load and validate operational thresholds from environment variables.

        Returns
        -------
        IngestionPolicy
            Validated ingestion policy.

        Examples
        --------
        Load the defaults or environment overrides::

            policy = IngestionPolicy.from_environment()
        """
        overlap_days = int(
            os.environ.get("GARMIN_SYNC_OVERLAP_DAYS", DEFAULT_SYNC_OVERLAP_DAYS)
        )
        max_staleness = int(
            os.environ.get(
                "GARMIN_MAX_STALENESS_HOURS", DEFAULT_GARMIN_MAX_STALENESS_HOURS
            )
        )
        if overlap_days < 0:
            raise ValueError("GARMIN_SYNC_OVERLAP_DAYS cannot be negative.")
        if max_staleness <= 0:
            raise ValueError("GARMIN_MAX_STALENESS_HOURS must be positive.")
        return cls(
            overlap_days=overlap_days,
            garmin_max_staleness_hours=max_staleness,
        )


def get_supabase_client() -> Client:
    """Create an authenticated Supabase client from environment variables.

    Returns
    -------
    supabase.Client
        Authenticated Supabase client using the service role key.

    Examples
    --------
    Create the trusted backend client after loading ``.env``::

        supabase = get_supabase_client()
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_last_synced_date(
    supabase: Client,
    table: str = "garmin_daily_wellness",
    column: str = "date",
    overlap_days: int = DEFAULT_SYNC_OVERLAP_DAYS,
) -> date:
    """Find the source-specific restart date in Supabase.

    Reads the latest source value, rewinds by a safety overlap, and falls back
    to ``DEFAULT_LOOKBACK_DAYS`` if the table is empty or unreachable. Separate
    source watermarks prevent a successful wellness request from advancing a
    failed activity, HRV, heart-rate, stress, or readiness stream.

    Parameters
    ----------
    supabase : supabase.Client
        Authenticated Supabase client.
    table : str, optional
        Source table carrying the watermark.
    column : str, optional
        Date or timestamp column to inspect.
    overlap_days : int, optional
        Days to rewind from the latest stored value.

    Returns
    -------
    date
        The date to start syncing from.

    Examples
    --------
    Resume activities from their own timestamp watermark::

        since = get_last_synced_date(
            supabase, "garmin_activities", "start_time", overlap_days=2
        )
    """
    default_since = date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    try:
        result = (
            supabase.table(table)
            .select(column)
            .order(column, desc=True)
            .limit(1)
            .execute()
        )
        latest = (
            date.fromisoformat(str(result.data[0][column])[:10])
            if result.data
            else None
        )
        since = (
            max(latest - timedelta(days=overlap_days), default_since)
            if latest
            else default_since
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read watermark %s.%s: %s", table, column, exc)
        since = default_since

    logger.info("Syncing %s from %s", table, since)
    return since


def _failed_result(source: str, detail_code: str) -> SourceResult:
    """Build a fixed-code failed result without persisting exception text."""
    return SourceResult(
        source=source,
        status="failed",
        attempted=1,
        detail_code=detail_code,
    )


def main() -> int:
    """Run the full ingestion pipeline and return a deployment-safe exit code.

    Returns
    -------
    int
        Zero when critical Garmin stages are current, otherwise one.

    Examples
    --------
    Propagate the deployment-safe status to the shell::

        raise SystemExit(main())
    """
    logger.info("Starting ingestion pipeline")

    supabase = get_supabase_client()
    policy = IngestionPolicy.from_environment()
    attempted_at = datetime.now(timezone.utc)
    results: list[SourceResult] = []

    logger.info("Running Garmin ingestion")
    try:
        garmin_client = garmin.get_client()
    except Exception as exc:  # noqa: BLE001
        logger.error("Garmin authentication failed: %s", exc, exc_info=True)
        results.append(_failed_result("garmin_auth", "garmin_auth_failed"))
    else:
        results.append(
            SourceResult.from_counts(
                "garmin_auth", attempted=1, succeeded=1, rows_written=0
            )
        )
        watermarks = {
            source: get_last_synced_date(
                supabase,
                table=table,
                column=column,
                overlap_days=policy.overlap_days,
            )
            for source, (table, column) in _GARMIN_WATERMARKS.items()
        }
        try:
            results.append(
                garmin.ingest(supabase, since=watermarks, client=garmin_client)
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Garmin wellness ingestion failed: %s", exc, exc_info=True)
            results.append(
                _failed_result("garmin_wellness", "garmin_wellness_store_failed")
            )

        activities_since = get_last_synced_date(
            supabase,
            table="garmin_activities",
            column="start_time",
            overlap_days=policy.overlap_days,
        )
        try:
            activity_result = garmin_activities.ingest(
                supabase, garmin_client, since=activities_since
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Garmin activity ingestion failed: %s", exc, exc_info=True)
            results.append(
                _failed_result("garmin_activities", "garmin_activity_store_failed")
            )
        else:
            results.append(activity_result.summary)
            if activity_result.summary.status != "failed":
                try:
                    results.append(
                        exercise_sets.ingest(
                            supabase, garmin_client, list(activity_result.activities)
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Garmin exercise-set ingestion failed: %s", exc, exc_info=True
                    )
                    results.append(
                        _failed_result(
                            "garmin_exercise_sets", "garmin_exercise_set_store_failed"
                        )
                    )

    logger.info("Running body-composition ingestion")
    try:
        results.append(body_composition.ingest(supabase))
    except Exception as exc:  # noqa: BLE001
        logger.error("Body-composition ingestion failed: %s", exc, exc_info=True)
        results.append(
            _failed_result("body_composition", "body_composition_store_failed")
        )

    try:
        for result in results:
            record_source_result(supabase, result, attempted_at=attempted_at)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Could not persist ingestion source status: %s", exc, exc_info=True
        )
        return 1

    for result in results:
        logger.info(
            "Source %-22s status=%-8s attempted=%d succeeded=%d rows=%d detail=%s",
            result.source,
            result.status,
            result.attempted,
            result.succeeded,
            result.rows_written,
            result.detail_code or "none",
        )

    critical_sources = {"garmin_auth", "garmin_wellness", "garmin_activities"}
    failed_critical = [
        result.source
        for result in results
        if result.source in critical_sources and result.status == "failed"
    ]
    stale_critical: list[str] = []
    max_age = timedelta(hours=policy.garmin_max_staleness_hours)
    for source in ("garmin_wellness", "garmin_activities"):
        try:
            if source_is_stale(supabase, source, max_age=max_age, now=attempted_at):
                stale_critical.append(source)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not verify freshness for %s: %s", source, exc)
            stale_critical.append(source)

    if failed_critical or stale_critical:
        logger.error(
            "Ingestion failed deployment gate: failed=%s stale=%s",
            failed_critical or "none",
            stale_critical or "none",
        )
        return 1

    logger.info("Ingestion pipeline complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
